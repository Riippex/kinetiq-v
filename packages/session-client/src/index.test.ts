import assert from 'node:assert/strict';
import test from 'node:test';

import {
  fetchExercises,
  fetchProfile,
  formatLimitationsInput,
  isUnsupportedLimitationError,
  parseLimitationsInput,
  toggleExclusion,
  updateProfile,
  type DomainError,
} from './index.ts';

// --- toggleExclusion -------------------------------------------------------

test('toggleExclusion adds a catalog exercise id not yet excluded', () => {
  const result = toggleExclusion(['exercise-push-up-v1'], 'exercise-plank-v1');
  assert.deepEqual(result, ['exercise-push-up-v1', 'exercise-plank-v1']);
});

test('toggleExclusion removes a catalog exercise id already excluded', () => {
  const result = toggleExclusion(['exercise-push-up-v1', 'exercise-plank-v1'], 'exercise-push-up-v1');
  assert.deepEqual(result, ['exercise-plank-v1']);
});

test('toggleExclusion never mutates the input array', () => {
  const original = ['exercise-push-up-v1'];
  const result = toggleExclusion(original, 'exercise-plank-v1');
  assert.deepEqual(original, ['exercise-push-up-v1']);
  assert.notEqual(result, original);
});

// --- parseLimitationsInput / formatLimitationsInput -------------------------

test('parseLimitationsInput splits, trims, and drops empty entries', () => {
  const result = parseLimitationsInput('KNEE_PAIN,  WRIST_PAIN ,, ');
  assert.deepEqual(result, ['KNEE_PAIN', 'WRIST_PAIN']);
});

test('parseLimitationsInput deduplicates repeated entries', () => {
  const result = parseLimitationsInput('KNEE_PAIN, knee_pain, KNEE_PAIN');
  // Case-sensitive: distinct casings are preserved as distinct self-reported strings,
  // only exact duplicates collapse.
  assert.deepEqual(result, ['KNEE_PAIN', 'knee_pain']);
});

test('parseLimitationsInput returns an empty array for blank input', () => {
  assert.deepEqual(parseLimitationsInput(''), []);
  assert.deepEqual(parseLimitationsInput('   '), []);
});

test('formatLimitationsInput joins limitations for display', () => {
  assert.equal(formatLimitationsInput(['KNEE_PAIN', 'WRIST_PAIN']), 'KNEE_PAIN, WRIST_PAIN');
  assert.equal(formatLimitationsInput([]), '');
});

test('parseLimitationsInput and formatLimitationsInput round-trip', () => {
  const original = ['KNEE_PAIN', 'WRIST_PAIN'];
  assert.deepEqual(parseLimitationsInput(formatLimitationsInput(original)), original);
});

// --- isUnsupportedLimitationError -------------------------------------------

test('isUnsupportedLimitationError recognizes the structured error code', () => {
  const errors: DomainError[] = [
    { code: 'UNSUPPORTED_LIMITATION', message: 'No catalog template supports KNEE_PAIN' },
  ];
  assert.equal(isUnsupportedLimitationError(errors), true);
});

test('isUnsupportedLimitationError returns false for unrelated errors', () => {
  const errors: DomainError[] = [{ code: 'INVALID_ROUTINE_EDIT', message: 'Bad request' }];
  assert.equal(isUnsupportedLimitationError(errors), false);
});

test('isUnsupportedLimitationError returns false for an empty error list', () => {
  assert.equal(isUnsupportedLimitationError([]), false);
});

// --- fetchExercises / updateProfile: request shape and transport failure ---

test('fetchExercises submits the exercises query and returns the catalog list', async () => {
  const calls: Array<{ url: string; body: { query: string } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) as { query: string } });
    return {
      ok: true,
      json: async () => ({
        data: {
          exercises: [
            { id: 'exercise-bodyweight-squat-v1', name: 'Bodyweight Squat', visionSupported: true },
          ],
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await fetchExercises('/api/graphql');
    assert.deepEqual(result.errors, []);
    assert.equal(result.exercises.length, 1);
    assert.equal(result.exercises[0].id, 'exercise-bodyweight-squat-v1');
    assert.equal(calls.length, 1);
    assert.match(calls[0].body.query, /query Exercises/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchExercises surfaces a transport error when the request fails', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    throw new Error('network down');
  }) as typeof fetch;

  try {
    const result = await fetchExercises('/api/graphql');
    assert.deepEqual(result.exercises, []);
    assert.equal(result.errors.length, 1);
    assert.equal(result.errors[0].code, 'TRANSPORT_ERROR');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('updateProfile submits exclusions and limitations as plain string arrays', async () => {
  const calls: Array<{ variables: { input: Record<string, unknown> } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (_url: string, init: RequestInit) => {
    const body = JSON.parse(init.body as string) as { variables: { input: Record<string, unknown> } };
    calls.push(body);
    return {
      ok: true,
      json: async () => ({
        data: {
          updateProfile: {
            profile: {
              id: 'athlete-1',
              displayName: 'Athlete',
              timezone: 'UTC',
              experienceLevel: 'RETURNING',
              availabilityDaysPerWeek: 3,
              targetSessionMinutes: 15,
              availableEquipment: ['NONE'],
              workoutSpace: 'LIVING_ROOM',
              preferences: [],
              exclusions: ['exercise-pull-up-v1'],
              limitations: ['KNEE_PAIN'],
              coachingTone: 'CALM',
              updatedAt: '2026-01-01T00:00:00Z',
            },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await updateProfile('/api/graphql', {
      exclusions: ['exercise-pull-up-v1'],
      limitations: ['KNEE_PAIN'],
    });
    assert.deepEqual(result.errors, []);
    assert.deepEqual(result.profile?.exclusions, ['exercise-pull-up-v1']);
    assert.deepEqual(result.profile?.limitations, ['KNEE_PAIN']);
    assert.deepEqual(calls[0].variables.input.exclusions, ['exercise-pull-up-v1']);
    assert.deepEqual(calls[0].variables.input.limitations, ['KNEE_PAIN']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchProfile reloads persisted exclusions and limitations', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    ({
      ok: true,
      json: async () => ({
        data: {
          me: {
            id: 'athlete-1',
            displayName: 'Athlete',
            timezone: 'UTC',
            experienceLevel: 'RETURNING',
            availabilityDaysPerWeek: 3,
            targetSessionMinutes: 15,
            availableEquipment: ['NONE'],
            workoutSpace: 'LIVING_ROOM',
            preferences: [],
            exclusions: ['exercise-pull-up-v1'],
            limitations: ['KNEE_PAIN'],
            coachingTone: 'CALM',
            updatedAt: '2026-01-01T00:00:00Z',
          },
        },
      }),
    }) as Response) as typeof fetch;

  try {
    const result = await fetchProfile('/api/graphql');
    assert.deepEqual(result.profile?.exclusions, ['exercise-pull-up-v1']);
    assert.deepEqual(result.profile?.limitations, ['KNEE_PAIN']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
