import assert from 'node:assert/strict';
import test from 'node:test';

import {
  abandonSession,
  confirmSessionTarget,
  disableDynamicMode,
  fetchExercises,
  fetchProfile,
  fetchSession,
  fetchTransientSessionState,
  finishSession,
  formatLimitationsInput,
  isUnsupportedLimitationError,
  parseLimitationsInput,
  pauseSession,
  publishTransientSessionUpdate,
  recordSessionFeedback,
  resumeSession,
  startSession,
  syncSessionState,
  toggleExclusion,
  updateProfile,
  type DomainError,
  type SessionCommand,
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

// --- Session lifecycle mutations --------------------------------------------

const testCommand: SessionCommand = {
  sessionId: 'session-123',
  expectedRevision: 1,
  idempotencyKey: 'cmd-key-1',
};

test('startSession submits mutation with command and returns session', async () => {
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand } } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          startSession: {
            session: { id: 'session-123', revision: 2, state: 'ACTIVE' },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await startSession('/api/graphql', testCommand);
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.state, 'ACTIVE');
    assert.equal(result.session?.revision, 2);
    assert.equal(calls.length, 1);
    assert.match(calls[0].body.query, /mutation StartSession/);
    assert.deepEqual(calls[0].body.variables.command, testCommand);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('pauseSession submits mutation with command and returns session', async () => {
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand } } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          pauseSession: {
            session: { id: 'session-123', revision: 3, state: 'PAUSED' },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await pauseSession('/api/graphql', { ...testCommand, expectedRevision: 2 });
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.state, 'PAUSED');
    assert.equal(result.session?.revision, 3);
    assert.match(calls[0].body.query, /mutation PauseSession/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('resumeSession submits mutation with command and returns session', async () => {
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand } } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          resumeSession: {
            session: { id: 'session-123', revision: 4, state: 'ACTIVE' },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await resumeSession('/api/graphql', { ...testCommand, expectedRevision: 3 });
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.state, 'ACTIVE');
    assert.equal(result.session?.revision, 4);
    assert.match(calls[0].body.query, /mutation ResumeSession/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('disableDynamicMode submits mutation with command and returns session', async () => {
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand } } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          disableDynamicMode: {
            session: { id: 'session-123', revision: 5, state: 'ACTIVE' },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await disableDynamicMode('/api/graphql', { ...testCommand, expectedRevision: 4 });
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.revision, 5);
    assert.match(calls[0].body.query, /mutation DisableDynamicMode/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('finishSession submits mutation with command and returns session', async () => {
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand } } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          finishSession: {
            session: { id: 'session-123', revision: 6, state: 'COMPLETED' },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await finishSession('/api/graphql', { ...testCommand, expectedRevision: 5 });
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.state, 'COMPLETED');
    assert.equal(result.session?.revision, 6);
    assert.match(calls[0].body.query, /mutation FinishSession/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('finishSession submits mutation with activity payload and returns completed session details', async () => {
  const calls: Array<{
    url: string;
    body: {
      query: string;
      variables: {
        command: SessionCommand;
        performedSets?: Array<{ exerciseId: string; setOrder: number; repetitions?: number }>;
        observationCoverage?: { coverageRatio: number; trackedSeconds: number; totalSeconds: number };
        feedback?: { perceivedEffort?: number; comments?: string };
      };
    };
  }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          finishSession: {
            session: {
              id: 'session-123',
              revision: 6,
              state: 'COMPLETED',
              confirmedRepetitions: 25,
              performedSets: [{ exerciseId: 'exercise-push-up-v1', setOrder: 1, repetitions: 25, durationSeconds: null }],
              observationCoverage: {
                coverageRatio: 0.95,
                trackedSeconds: 57,
                totalSeconds: 60,
                fullyVisibleRatio: 1.0,
                untrackedReasons: [],
              },
              feedback: {
                perceivedEffort: 8,
                comments: 'Great workout',
              },
            },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const activity = {
      performedSets: [{ exerciseId: 'exercise-push-up-v1', setOrder: 1, repetitions: 25 }],
      observationCoverage: { coverageRatio: 0.95, trackedSeconds: 57, totalSeconds: 60 },
      feedback: { perceivedEffort: 8, comments: 'Great workout' },
    };
    const result = await finishSession('/api/graphql', { ...testCommand, expectedRevision: 5 }, activity);
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.state, 'COMPLETED');
    assert.equal(result.session?.confirmedRepetitions, 25);
    assert.equal(result.session?.performedSets?.length, 1);
    assert.equal(result.session?.observationCoverage?.coverageRatio, 0.95);
    assert.equal(result.session?.feedback?.perceivedEffort, 8);
    assert.equal(calls[0].body.variables.performedSets?.[0]?.exerciseId, 'exercise-push-up-v1');
    assert.equal(calls[0].body.variables.feedback?.perceivedEffort, 8);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('recordSessionFeedback submits mutation with command and feedback', async () => {
  const calls: Array<{
    url: string;
    body: {
      query: string;
      variables: { command: SessionCommand; feedback: { perceivedEffort?: number; comments?: string } };
    };
  }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          recordSessionFeedback: {
            session: {
              id: 'session-123',
              revision: 7,
              state: 'COMPLETED',
              feedback: { perceivedEffort: 7, comments: 'Follow-up comment' },
            },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await recordSessionFeedback(
      '/api/graphql',
      { ...testCommand, expectedRevision: 6 },
      { perceivedEffort: 7, comments: 'Follow-up comment' },
    );
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.revision, 7);
    assert.equal(result.session?.feedback?.perceivedEffort, 7);
    assert.equal(result.session?.feedback?.comments, 'Follow-up comment');
    assert.match(calls[0].body.query, /mutation RecordSessionFeedback/);
    assert.deepEqual(calls[0].body.variables.feedback, { perceivedEffort: 7, comments: 'Follow-up comment' });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('abandonSession submits mutation with command and returns session', async () => {
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand } } }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(init.body as string) });
    return {
      ok: true,
      json: async () => ({
        data: {
          abandonSession: {
            session: { id: 'session-123', revision: 2, state: 'ABANDONED' },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await abandonSession('/api/graphql', testCommand);
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.state, 'ABANDONED');
    assert.equal(result.session?.revision, 2);
    assert.match(calls[0].body.query, /mutation AbandonSession/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('startSession surfaces domain error when revision conflict occurs', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({
      data: {
        startSession: {
          session: null,
          errors: [{ code: 'REVISION_CONFLICT', message: 'Session revision conflict', field: 'expectedRevision' }],
        },
      },
    }),
  }) as Response) as typeof fetch;

  try {
    const result = await startSession('/api/graphql', testCommand);
    assert.equal(result.session, null);
    assert.equal(result.errors.length, 1);
    assert.equal(result.errors[0].code, 'REVISION_CONFLICT');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('publishTransientSessionUpdate sends mutation and returns status', async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; body: { query: string; variables: unknown } }> = [];
  globalThis.fetch = (async (url: string, options: { body: string }) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return {
      ok: true,
      json: async () => ({
        data: {
          publishTransientSessionUpdate: { success: true, errors: [] },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await publishTransientSessionUpdate('/api/graphql', {
      sessionId: 'sess-001',
      activeExerciseId: 'goblet-squat',
      currentRepetitions: 5,
    });
    assert.equal(result.success, true);
    assert.deepEqual(result.errors, []);
    assert.match(calls[0].body.query, /mutation PublishTransientSessionUpdate/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('syncSessionState restores from committed PostgreSQL when transient state is null (Redis loss)', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (_url: string, options: { body: string }) => {
    const parsed = JSON.parse(options.body);
    if (parsed.query.includes('query Session')) {
      return {
        ok: true,
        json: async () => ({
          data: {
            session: {
              id: 'sess-001',
              revision: 3,
              state: 'COMPLETED',
              confirmedRepetitions: 12,
            },
          },
        }),
      } as Response;
    }
    if (parsed.query.includes('query TransientSessionState')) {
      return {
        ok: true,
        json: async () => ({
          data: { transientSessionState: null },
        }),
      } as Response;
    }
    throw new Error('Unexpected query');
  }) as typeof fetch;

  try {
    const sync = await syncSessionState('/api/graphql', 'sess-001');
    assert.equal(sync.session?.id, 'sess-001');
    assert.equal(sync.session?.state, 'COMPLETED');
    assert.equal(sync.transient, null);
    assert.equal(sync.restoredFromCommitted, true);
    assert.deepEqual(sync.errors, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('confirmSessionTarget sends mutation with targetPersonId and updates session', async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand; targetPersonId: string } } }> = [];
  globalThis.fetch = (async (url: string, options: { body: string }) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return {
      ok: true,
      json: async () => ({
        data: {
          confirmSessionTarget: {
            session: {
              id: 'sess-001',
              revision: 2,
              state: 'READY',
              targetPersonId: 'person-42',
            },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await confirmSessionTarget('/api/graphql', testCommand, 'person-42');
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.id, 'sess-001');
    assert.equal(result.session?.targetPersonId, 'person-42');
    assert.match(calls[0].body.query, /mutation ConfirmSessionTarget/);
    assert.equal(calls[0].body.variables.targetPersonId, 'person-42');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('confirmSessionTarget surfaces domain error when session not found', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({
      data: {
        confirmSessionTarget: {
          session: null,
          errors: [{ code: 'SESSION_NOT_FOUND', message: 'Workout session not found' }],
        },
      },
    }),
  }) as Response) as typeof fetch;

  try {
    const result = await confirmSessionTarget('/api/graphql', testCommand, 'person-42');
    assert.equal(result.session, null);
    assert.equal(result.errors.length, 1);
    assert.equal(result.errors[0].code, 'SESSION_NOT_FOUND');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

