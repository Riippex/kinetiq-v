import assert from 'node:assert/strict';
import test from 'node:test';

import * as indexModule from './index.ts';
import {
  abandonSession,
  confirmSessionTarget,
  disableDynamicMode,
  fetchDynamicChallenges,
  fetchExercises,
  fetchProfile,
  fetchSession,
  fetchTransientSessionState,
  fetchVisionCandidates,
  finishSession,
  formatLimitationsInput,
  isUnsupportedLimitationError,
  parseLimitationsInput,
  pauseSession,
  recordSessionFeedback,
  resumeSession,
  skipDynamicChallenge,
  startSession,
  startSessionVisionAnalysis,
  subscribeToTransientSessionUpdates,
  syncSessionState,
  toggleExclusion,
  updateProfile,
  type DomainError,
  type SessionCommand,
  type WebSocketLike,
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

// Regression test for the Block 4 finding: publishTransientSessionUpdate
// let any authenticated owner of a session with a confirmed target
// forge arbitrary "live Vision result" values. TransientSessionUpdate is
// now server-produced only (PollVisionObservationsUseCase polling real
// Vision observations), so this client must not expose any operation
// that publishes one -- only fetchTransientSessionState and
// subscribeToTransientSessionUpdates remain, both read-only.
test('does not export a publishTransientSessionUpdate operation', () => {
  assert.equal(
    'publishTransientSessionUpdate' in indexModule,
    false,
    'transient session updates must be server-produced only',
  );
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

// --- startSessionVisionAnalysis / fetchVisionCandidates ---------------------

test('startSessionVisionAnalysis submits mutation with command and returns session', async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; body: { query: string; variables: { command: SessionCommand } } }> = [];
  globalThis.fetch = (async (url: string, options: { body: string }) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return {
      ok: true,
      json: async () => ({
        data: {
          startSessionVisionAnalysis: {
            session: { id: 'sess-001', revision: 2, state: 'READY', targetPersonId: null },
            errors: [],
          },
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await startSessionVisionAnalysis('/api/graphql', testCommand);
    assert.deepEqual(result.errors, []);
    assert.equal(result.session?.id, 'sess-001');
    assert.equal(result.session?.revision, 2);
    assert.match(calls[0].body.query, /mutation StartSessionVisionAnalysis/);
    assert.deepEqual(calls[0].body.variables.command, testCommand);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('startSessionVisionAnalysis surfaces domain error when the lease is contended', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({
      data: {
        startSessionVisionAnalysis: {
          session: null,
          errors: [
            {
              code: 'VISION_OPERATION_IN_PROGRESS',
              message: 'Another Vision operation is already in progress for this session',
            },
          ],
        },
      },
    }),
  }) as Response) as typeof fetch;

  try {
    const result = await startSessionVisionAnalysis('/api/graphql', testCommand);
    assert.equal(result.session, null);
    assert.equal(result.errors[0].code, 'VISION_OPERATION_IN_PROGRESS');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchVisionCandidates returns the detected candidates for a session', async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; body: { query: string; variables: { sessionId: string } } }> = [];
  globalThis.fetch = (async (url: string, options: { body: string }) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return {
      ok: true,
      json: async () => ({
        data: {
          visionCandidates: [
            { candidateId: 'person-alpha', confidence: 0.95 },
            { candidateId: 'person-beta', confidence: 0.88 },
          ],
        },
      }),
    } as Response;
  }) as typeof fetch;

  try {
    const result = await fetchVisionCandidates('/api/graphql', 'sess-001');
    assert.deepEqual(result.errors, []);
    assert.equal(result.candidates.length, 2);
    assert.equal(result.candidates[0].candidateId, 'person-alpha');
    assert.equal(result.candidates[1].confidence, 0.88);
    assert.match(calls[0].body.query, /query VisionCandidates/);
    assert.equal(calls[0].body.variables.sessionId, 'sess-001');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchVisionCandidates returns an empty list before any are detected', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({ data: { visionCandidates: [] } }),
  }) as Response) as typeof fetch;

  try {
    const result = await fetchVisionCandidates('/api/graphql', 'sess-001');
    assert.deepEqual(result.errors, []);
    assert.deepEqual(result.candidates, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchVisionCandidates surfaces a transport error when the request fails', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    throw new Error('network down');
  }) as typeof fetch;

  try {
    const result = await fetchVisionCandidates('/api/graphql', 'sess-001');
    assert.deepEqual(result.candidates, []);
    assert.equal(result.errors[0].code, 'TRANSPORT_ERROR');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

// --- subscribeToTransientSessionUpdates -------------------------------------

class FakeWebSocket implements WebSocketLike {
  readyState = 0;
  sent: string[] = [];
  private listeners: Record<string, Array<(event: any) => void>> = {};

  addEventListener(type: string, listener: (event: any) => void): void {
    (this.listeners[type] ??= []).push(listener);
  }

  removeEventListener(type: string, listener: (event: any) => void): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== listener);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
    this.emit('close', {});
  }

  emit(type: string, event: any): void {
    for (const listener of this.listeners[type] ?? []) listener(event);
  }

  simulateOpen(): void {
    this.readyState = 1;
    this.emit('open', {});
  }

  simulateMessage(message: unknown): void {
    this.emit('message', { data: JSON.stringify(message) });
  }

  lastSent(): any {
    return JSON.parse(this.sent[this.sent.length - 1]);
  }
}

test('subscribeToTransientSessionUpdates sends connection_init on open, then subscribe on ack', () => {
  let created: FakeWebSocket | undefined;
  subscribeToTransientSessionUpdates(
    'wss://api.example.com/graphql',
    'sess-100',
    () => {},
    {
      webSocketFactory: (url, protocol) => {
        assert.equal(url, 'wss://api.example.com/graphql');
        assert.equal(protocol, 'graphql-transport-ws');
        created = new FakeWebSocket();
        return created;
      },
    },
  );

  const socket = created!;
  socket.simulateOpen();
  assert.deepEqual(socket.lastSent(), { type: 'connection_init' });

  socket.simulateMessage({ type: 'connection_ack' });
  const subscribeMessage = socket.lastSent();
  assert.equal(subscribeMessage.type, 'subscribe');
  assert.equal(subscribeMessage.payload.variables.sessionId, 'sess-100');
  assert.match(subscribeMessage.payload.query, /subscription TransientSessionUpdates/);
});

test('subscribeToTransientSessionUpdates delivers next messages to onUpdate', () => {
  let created: FakeWebSocket | undefined;
  const received: unknown[] = [];
  subscribeToTransientSessionUpdates(
    'wss://api.example.com/graphql',
    'sess-101',
    (update) => received.push(update),
    {
      webSocketFactory: () => {
        created = new FakeWebSocket();
        return created;
      },
    },
  );

  const socket = created!;
  socket.simulateOpen();
  socket.simulateMessage({ type: 'connection_ack' });
  const subscribeId = socket.lastSent().id;

  socket.simulateMessage({
    type: 'next',
    id: subscribeId,
    payload: {
      data: {
        transientSessionUpdates: {
          sessionId: 'sess-101',
          currentRepetitions: 5,
          visibilityStatus: 'VISIBLE',
        },
      },
    },
  });

  assert.equal(received.length, 1);
  assert.deepEqual(received[0], {
    sessionId: 'sess-101',
    currentRepetitions: 5,
    visibilityStatus: 'VISIBLE',
  });
});

test('subscribeToTransientSessionUpdates surfaces graphql-transport-ws error messages', () => {
  let created: FakeWebSocket | undefined;
  const errors: DomainError[][] = [];
  subscribeToTransientSessionUpdates(
    'wss://api.example.com/graphql',
    'sess-102',
    () => {},
    {
      onError: (e) => errors.push(e),
      webSocketFactory: () => {
        created = new FakeWebSocket();
        return created;
      },
    },
  );

  const socket = created!;
  socket.simulateOpen();
  socket.simulateMessage({ type: 'connection_ack' });
  const subscribeId = socket.lastSent().id;

  socket.simulateMessage({
    type: 'error',
    id: subscribeId,
    payload: [{ message: 'Workout session not found' }],
  });

  assert.equal(errors.length, 1);
  assert.equal(errors[0][0].code, 'SUBSCRIPTION_ERROR');
  assert.equal(errors[0][0].message, 'Workout session not found');
});

test('subscribeToTransientSessionUpdates unsubscribe sends complete and closes the socket', () => {
  let created: FakeWebSocket | undefined;
  const subscription = subscribeToTransientSessionUpdates(
    'wss://api.example.com/graphql',
    'sess-103',
    () => {},
    {
      webSocketFactory: () => {
        created = new FakeWebSocket();
        return created;
      },
    },
  );

  const socket = created!;
  socket.simulateOpen();
  socket.simulateMessage({ type: 'connection_ack' });
  const subscribeId = socket.lastSent().id;

  subscription.unsubscribe();

  assert.deepEqual(socket.lastSent(), { type: 'complete', id: subscribeId });
  assert.equal(socket.readyState, 3);
});

test('subscribeToTransientSessionUpdates reports a transport error on unexpected close', () => {
  let created: FakeWebSocket | undefined;
  const errors: DomainError[][] = [];
  subscribeToTransientSessionUpdates(
    'wss://api.example.com/graphql',
    'sess-104',
    () => {},
    {
      onError: (e) => errors.push(e),
      webSocketFactory: () => {
        created = new FakeWebSocket();
        return created;
      },
    },
  );

  const socket = created!;
  socket.simulateOpen();
  socket.emit('close', {});

  assert.equal(errors.length, 1);
  assert.equal(errors[0][0].code, 'TRANSPORT_ERROR');
});

test('subscribeToTransientSessionUpdates does not report an error after a clean complete', () => {
  let created: FakeWebSocket | undefined;
  const errors: DomainError[][] = [];
  let completed = false;
  subscribeToTransientSessionUpdates(
    'wss://api.example.com/graphql',
    'sess-105',
    () => {},
    {
      onError: (e) => errors.push(e),
      onComplete: () => {
        completed = true;
      },
      webSocketFactory: () => {
        created = new FakeWebSocket();
        return created;
      },
    },
  );

  const socket = created!;
  socket.simulateOpen();
  socket.simulateMessage({ type: 'connection_ack' });
  const subscribeId = socket.lastSent().id;

  socket.simulateMessage({ type: 'complete', id: subscribeId });
  socket.emit('close', {});

  assert.equal(completed, true);
  assert.equal(errors.length, 0);
});

test('fetchDynamicChallenges queries and returns dynamic challenges for a session', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string);
      assert.equal(body.variables.sessionId, 'sess-dyn-1');
      return {
        ok: true,
        json: async () => ({
          data: {
            sessionDynamicChallenges: [
              {
                id: 'ch-1',
                challengeType: 'HOLD_POSE',
                exerciseId: 'exercise-push-up-v1',
                targetValue: 10,
                description: 'Hold push-up pose for 10 seconds',
                setOrder: 1,
                status: 'PENDING',
              },
            ],
          },
        }),
      } as Response;
    }) as typeof globalThis.fetch;

    const res = await fetchDynamicChallenges('http://localhost/graphql', 'sess-dyn-1');
    assert.equal(res.errors.length, 0);
    assert.equal(res.challenges.length, 1);
    assert.equal(res.challenges[0].id, 'ch-1');
    assert.equal(res.challenges[0].status, 'PENDING');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('skipDynamicChallenge executes mutation and returns updated challenge list', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string);
      assert.equal(body.variables.input.challengeId, 'ch-1');
      return {
        ok: true,
        json: async () => ({
          data: {
            skipDynamicChallenge: {
              challenges: [
                {
                  id: 'ch-1',
                  challengeType: 'HOLD_POSE',
                  exerciseId: 'exercise-push-up-v1',
                  targetValue: 10,
                  description: 'Hold push-up pose for 10 seconds',
                  setOrder: 1,
                  status: 'SKIPPED',
                },
              ],
              errors: [],
            },
          },
        }),
      } as Response;
    }) as typeof globalThis.fetch;

    const res = await skipDynamicChallenge('http://localhost/graphql', {
      sessionId: 'sess-dyn-1',
      expectedRevision: 1,
      challengeId: 'ch-1',
      clientMutationId: 'mut-1',
    });

    assert.equal(res.errors.length, 0);
    assert.equal(res.challenges.length, 1);
    assert.equal(res.challenges[0].status, 'SKIPPED');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('issueDisplayPairingCode issues pairing code for device type', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string);
      assert.equal(body.variables.deviceType, 'FIRE_TV');
      return {
        ok: true,
        json: async () => ({
          data: {
            issueDisplayPairingCode: {
              code: 'FIRE-7892',
              deviceType: 'FIRE_TV',
              createdAt: '2026-09-18T12:00:00Z',
              expiresAt: '2026-09-18T12:15:00Z',
              status: 'UNPAIRED',
            },
          },
        }),
      } as Response;
    }) as typeof globalThis.fetch;

    const res = await indexModule.issueDisplayPairingCode('http://localhost/graphql', 'FIRE_TV');
    assert.equal(res.errors.length, 0);
    assert.equal(res.pairing?.code, 'FIRE-7892');
    assert.equal(res.pairing?.status, 'UNPAIRED');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchDisplaySessionState queries session state by pairing code', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string);
      assert.equal(body.variables.code, 'FIRE-7892');
      return {
        ok: true,
        json: async () => ({
          data: {
            displaySessionState: {
              sessionId: 'sess-123',
              deviceType: 'FIRE_TV',
              status: 'PAIRED',
              mode: 'NORMAL',
              intensity: 'PLANNED',
              state: 'ACTIVE',
              activeExercise: 'Goblet Squat',
              confirmedReps: 8,
              visibilityStatus: 'VISIBLE',
            },
          },
        }),
      } as Response;
    }) as typeof globalThis.fetch;

    const res = await indexModule.fetchDisplaySessionState('http://localhost/graphql', 'FIRE-7892');
    assert.equal(res.errors.length, 0);
    assert.equal(res.state?.sessionId, 'sess-123');
    assert.equal(res.state?.status, 'PAIRED');
    assert.equal(res.state?.confirmedReps, 8);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchProgressSummary queries progress and returns ProgressSummary', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string);
      assert.equal(body.variables.fromDate, '2026-09-01T00:00:00Z');
      assert.equal(body.variables.toDate, '2026-09-08T00:00:00Z');
      return {
        ok: true,
        json: async () => ({
          data: {
            progress: {
              fromDate: '2026-09-01T00:00:00Z',
              toDate: '2026-09-08T00:00:00Z',
              consistency: {
                totalSessions: 3,
                plannedSessions: 3,
                consistencyRatio: 1.0,
                currentStreakDays: 3,
                completedCount: 3,
                abandonedCount: 0,
                skippedCount: 0,
              },
              performanceProjections: [
                {
                  exerciseId: 'ex-squat',
                  exerciseName: 'Squat',
                  measuredVolume: 100,
                  selfReportedVolume: 0,
                  estimated1RM: 95.5,
                  evidenceSource: 'MEASURED',
                  trend: 'IMPROVING',
                },
              ],
              goalProgress: null,
            },
          },
        }),
      } as Response;
    }) as typeof globalThis.fetch;

    const res = await indexModule.fetchProgressSummary(
      'http://localhost/graphql',
      '2026-09-01T00:00:00Z',
      '2026-09-08T00:00:00Z'
    );
    assert.equal(res.errors.length, 0);
    assert.equal(res.summary?.consistency.completedCount, 3);
    assert.equal(res.summary?.performanceProjections[0].exerciseId, 'ex-squat');
    assert.equal(res.summary?.performanceProjections[0].estimated1RM, 95.5);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


