export const sessionModes = ['NORMAL', 'DYNAMIC'] as const;
export const sessionIntensities = ['LIGHTER', 'PLANNED', 'CHALLENGING'] as const;
export const coachingTones = ['CALM', 'TECHNICAL', 'MOTIVATIONAL', 'EDGY'] as const;
export const dynamicChallengeTypes = ['HOLD_POSE', 'MIRROR_POSE', 'QUICK_REPS', 'RECOVERY'] as const;
export const experienceLevels = ['STARTING', 'RETURNING', 'REGULAR'] as const;

export type SessionMode = (typeof sessionModes)[number];
export type SessionIntensity = (typeof sessionIntensities)[number];
export type CoachingTone = (typeof coachingTones)[number];
export type DynamicChallengeType = (typeof dynamicChallengeTypes)[number];
export type ExperienceLevel = (typeof experienceLevels)[number];

export interface Profile {
  id: string;
  displayName: string;
  timezone: string;
  experienceLevel: ExperienceLevel;
  availabilityDaysPerWeek: number;
  targetSessionMinutes: number;
  availableEquipment: string[];
  workoutSpace: string;
  preferences: string[];
  exclusions: string[];
  limitations: string[];
  coachingTone: CoachingTone;
  updatedAt: string;
}

export interface UpdateProfileInput {
  displayName?: string;
  timezone?: string;
  experienceLevel?: ExperienceLevel;
  availabilityDaysPerWeek?: number;
  targetSessionMinutes?: number;
  availableEquipment?: string[];
  workoutSpace?: string;
  preferences?: string[];
  exclusions?: string[];
  limitations?: string[];
  coachingTone?: CoachingTone;
}

export interface Goal {
  id: string;
  revision: number;
  description: string;
  measure?: string | null;
  baseline?: number | null;
  target?: number | null;
  unit?: string | null;
  createdAt: string;
}

export interface SetGoalInput {
  goalId?: string;
  description: string;
  measure?: string;
  baseline?: number;
  target?: number;
  unit?: string;
}

export interface SessionPreparation {
  routineId: string;
  routineVersion: number;
  mode: SessionMode;
  intensity: SessionIntensity;
  coachingTone: CoachingTone;
  captureDeviceId: string;
  displayDeviceId?: string;
  promptForProgressPhoto: boolean;
  idempotencyKey: string;
  dynamic?: {
    frequency: 'LOW' | 'STANDARD' | 'HIGH';
    allowedChallengeTypes: DynamicChallengeType[];
    scoringEnabled: boolean;
    narrationEnabled: boolean;
  };
}

export interface PerformedSet {
  exerciseId: string;
  setOrder: number;
  repetitions?: number | null;
  durationSeconds?: number | null;
}

export interface ObservationCoverage {
  coverageRatio: number;
  trackedSeconds: number;
  totalSeconds: number;
  fullyVisibleRatio: number;
  untrackedReasons: string[];
}

export interface SessionFeedback {
  perceivedEffort?: number | null;
  comments?: string | null;
}

export interface PerformedSetInput {
  exerciseId: string;
  setOrder: number;
  repetitions?: number | null;
  durationSeconds?: number | null;
}

export interface ObservationCoverageInput {
  coverageRatio: number;
  trackedSeconds: number;
  totalSeconds: number;
  fullyVisibleRatio?: number;
  untrackedReasons?: string[];
}

export interface SessionFeedbackInput {
  perceivedEffort?: number | null;
  comments?: string | null;
}

export interface PreparedSession {
  id: string;
  revision: number;
  state: 'READY' | 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'ABANDONED';
  targetPersonId?: string | null;
  confirmedRepetitions?: number;
  performedSets?: PerformedSet[];
  observationCoverage?: ObservationCoverage | null;
  feedback?: SessionFeedback | null;
}

export interface SessionCommand {
  sessionId: string;
  expectedRevision: number;
  idempotencyKey: string;
}

export interface DomainError {
  code: string;
  message: string;
  field?: string | null;
}

export interface SessionResult {
  session: PreparedSession | null;
  errors: DomainError[];
}

export interface TransientSessionUpdateInput {
  sessionId: string;
  activeExerciseId?: string;
  currentRepetitions?: number;
  currentDurationSeconds?: number;
  poseConfidence?: number;
  visibilityStatus?: string;
  timestamp?: string;
}

export interface TransientSessionUpdate {
  sessionId: string;
  activeExerciseId?: string | null;
  currentRepetitions?: number | null;
  currentDurationSeconds?: number | null;
  poseConfidence?: number | null;
  visibilityStatus: string;
  timestamp?: string | null;
}

export interface SessionStateSync {
  session: PreparedSession | null;
  transient: TransientSessionUpdate | null;
  restoredFromCommitted: boolean;
  errors: DomainError[];
}


export interface RoutineExercise {
  id: string;
  name: string;
  version?: number;
  visionSupported?: boolean;
}

export interface CatalogExercise {
  id: string;
  name: string;
  visionSupported: boolean;
}

export interface RoutineItem {
  exercise: RoutineExercise;
  order: number;
  sets: number;
  repetitions?: number | null;
  durationSeconds?: number | null;
}

export interface Routine {
  id: string;
  version: number;
  title: string;
  rationale: string;
  items: RoutineItem[];
  accepted: boolean;
}

export interface RoutineEditItemInput {
  exerciseId: string;
  order: number;
  sets: number;
  repetitions?: number | null;
  durationSeconds?: number | null;
}

export interface EditRoutineInput {
  routineId: string;
  items: RoutineEditItemInput[];
  title?: string;
  baseVersion?: number;
}

const meQuery = `
  query Me {
    me {
      id
      displayName
      timezone
      experienceLevel
      availabilityDaysPerWeek
      targetSessionMinutes
      availableEquipment
      workoutSpace
      preferences
      exclusions
      limitations
      coachingTone
      updatedAt
    }
  }
`;

const updateProfileMutation = `
  mutation UpdateProfile($input: UpdateProfileInput!) {
    updateProfile(input: $input) {
      profile {
        id
        displayName
        timezone
        experienceLevel
        availabilityDaysPerWeek
        targetSessionMinutes
        availableEquipment
        workoutSpace
        preferences
        exclusions
        limitations
        coachingTone
        updatedAt
      }
      errors { code message field }
    }
  }
`;

const exercisesQuery = `
  query Exercises {
    exercises {
      id
      name
      visionSupported
    }
  }
`;

const activeGoalQuery = `
  query ActiveGoal {
    activeGoal {
      id
      revision
      description
      measure
      baseline
      target
      unit
      createdAt
    }
  }
`;

const goalsQuery = `
  query Goals {
    goals {
      id
      revision
      description
      measure
      baseline
      target
      unit
      createdAt
    }
  }
`;

const setGoalMutation = `
  mutation SetGoal($input: SetGoalInput!) {
    setGoal(input: $input) {
      goal {
        id
        revision
        description
        measure
        baseline
        target
        unit
        createdAt
      }
      errors { code message field }
    }
  }
`;

const prepareSessionMutation = `
  mutation PrepareSession($input: PrepareSessionInput!) {
    prepareSession(input: $input) {
      session { id revision state }
      errors { code message field }
    }
  }
`;

const startSessionMutation = `
  mutation StartSession($command: SessionCommand!) {
    startSession(command: $command) {
      session { id revision state }
      errors { code message field }
    }
  }
`;

const pauseSessionMutation = `
  mutation PauseSession($command: SessionCommand!) {
    pauseSession(command: $command) {
      session { id revision state }
      errors { code message field }
    }
  }
`;

const resumeSessionMutation = `
  mutation ResumeSession($command: SessionCommand!) {
    resumeSession(command: $command) {
      session { id revision state }
      errors { code message field }
    }
  }
`;

const confirmSessionTargetMutation = `
  mutation ConfirmSessionTarget($command: SessionCommand!, $targetPersonId: String!) {
    confirmSessionTarget(command: $command, targetPersonId: $targetPersonId) {
      session {
        id
        revision
        state
        targetPersonId
      }
      errors { code message field }
    }
  }
`;

const disableDynamicModeMutation = `
  mutation DisableDynamicMode($command: SessionCommand!) {
    disableDynamicMode(command: $command) {
      session { id revision state }
      errors { code message field }
    }
  }
`;

const finishSessionMutation = `
  mutation FinishSession(
    $command: SessionCommand!
    $performedSets: [PerformedSetInput!]
    $observationCoverage: ObservationCoverageInput
    $feedback: SessionFeedbackInput
  ) {
    finishSession(
      command: $command
      performedSets: $performedSets
      observationCoverage: $observationCoverage
      feedback: $feedback
    ) {
      session {
        id
        revision
        state
        confirmedRepetitions
        performedSets {
          exerciseId
          setOrder
          repetitions
          durationSeconds
        }
        observationCoverage {
          coverageRatio
          trackedSeconds
          totalSeconds
          fullyVisibleRatio
          untrackedReasons
        }
        feedback {
          perceivedEffort
          comments
        }
      }
      errors { code message field }
    }
  }
`;

const recordSessionFeedbackMutation = `
  mutation RecordSessionFeedback(
    $command: SessionCommand!
    $feedback: SessionFeedbackInput!
  ) {
    recordSessionFeedback(
      command: $command
      feedback: $feedback
    ) {
      session {
        id
        revision
        state
        confirmedRepetitions
        performedSets {
          exerciseId
          setOrder
          repetitions
          durationSeconds
        }
        observationCoverage {
          coverageRatio
          trackedSeconds
          totalSeconds
          fullyVisibleRatio
          untrackedReasons
        }
        feedback {
          perceivedEffort
          comments
        }
      }
      errors { code message field }
    }
  }
`;

const abandonSessionMutation = `
  mutation AbandonSession($command: SessionCommand!) {
    abandonSession(command: $command) {
      session { id revision state }
      errors { code message field }
    }
  }
`;

const sessionQuery = `
  query Session($id: ID!) {
    session(id: $id) {
      id
      revision
      state
      targetPersonId
      confirmedRepetitions
      performedSets {
        exerciseId
        setOrder
        repetitions
        durationSeconds
      }
      observationCoverage {
        coverageRatio
        trackedSeconds
        totalSeconds
        fullyVisibleRatio
        untrackedReasons
      }
      feedback {
        perceivedEffort
        comments
      }
    }
  }
`;

const publishTransientSessionUpdateMutation = `
  mutation PublishTransientSessionUpdate($input: TransientSessionUpdateInput!) {
    publishTransientSessionUpdate(input: $input) {
      success
      errors { code message field }
    }
  }
`;

const transientSessionStateQuery = `
  query TransientSessionState($sessionId: ID!) {
    transientSessionState(sessionId: $sessionId) {
      sessionId
      activeExerciseId
      currentRepetitions
      currentDurationSeconds
      poseConfidence
      visibilityStatus
      timestamp
    }
  }
`;


const currentRoutineQuery = `
  query CurrentRoutine {
    currentRoutine {
      id
      version
      title
      rationale
      accepted
      items {
        order
        sets
        repetitions
        durationSeconds
        exercise {
          id
          version
          name
          visionSupported
        }
      }
    }
  }
`;

const routineVersionQuery = `
  query RoutineVersion($id: ID!, $version: Int!) {
    routine(id: $id, version: $version) {
      id
      version
      title
      rationale
      accepted
      items {
        order
        sets
        repetitions
        durationSeconds
        exercise {
          id
          version
          name
          visionSupported
        }
      }
    }
  }
`;

const proposeRoutineMutation = `
  mutation ProposeRoutine {
    proposeRoutine {
      routine {
        id
        version
        title
        rationale
        accepted
        items {
          order
          sets
          repetitions
          durationSeconds
          exercise {
            id
            version
            name
            visionSupported
          }
        }
      }
      errors {
        code
        message
        field
      }
    }
  }
`;

const editRoutineMutation = `
  mutation EditRoutine($input: EditRoutineInput!) {
    editRoutine(input: $input) {
      routine {
        id
        version
        title
        rationale
        accepted
        items {
          order
          sets
          repetitions
          durationSeconds
          exercise {
            id
            version
            name
            visionSupported
          }
        }
      }
      errors {
        code
        message
        field
      }
    }
  }
`;

const acceptRoutineMutation = `
  mutation AcceptRoutine($routineId: ID!, $version: Int!) {
    acceptRoutine(routineId: $routineId, version: $version) {
      routine {
        id
        version
        title
        rationale
        accepted
        items {
          order
          sets
          repetitions
          durationSeconds
          exercise {
            id
            version
            name
            visionSupported
          }
        }
      }
      errors {
        code
        message
        field
      }
    }
  }
`;

/**
 * Toggle a catalog exercise id in a profile's exclusion list.
 * Pure and dedupe-safe: exclusions must be stable catalog exercise IDs.
 */
export function toggleExclusion(current: string[], exerciseId: string): string[] {
  if (current.includes(exerciseId)) {
    return current.filter((id) => id !== exerciseId);
  }
  return [...current, exerciseId];
}

/**
 * Parse a free-text, comma-separated limitations field into a normalized,
 * deduplicated list. Limitations are self-reported strings (e.g. "KNEE_PAIN"),
 * not catalog identifiers, so no catalog validation happens client-side.
 */
export function parseLimitationsInput(raw: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const part of raw.split(',')) {
    const trimmed = part.trim();
    if (trimmed && !seen.has(trimmed)) {
      seen.add(trimmed);
      result.push(trimmed);
    }
  }
  return result;
}

/** Format a limitations list back into the comma-separated text a field displays. */
export function formatLimitationsInput(limitations: string[]): string {
  return limitations.join(', ');
}

/**
 * Identify the structured UNSUPPORTED_LIMITATION domain error so clients can
 * render it distinctly from a generic failure (e.g. explaining that the
 * catalog has no adaptation for the reported limitation yet).
 */
export function isUnsupportedLimitationError(errors: DomainError[]): boolean {
  return errors.some((error) => error.code === 'UNSUPPORTED_LIMITATION');
}

async function executeGraphQL<T>(
  endpoint: string,
  query: string,
  variables: Record<string, unknown> = {},
  authorization?: string,
): Promise<{ data?: T; errors?: DomainError[] }> {
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'content-type': 'application/json',
        ...(authorization ? { authorization } : {}),
      },
      body: JSON.stringify({ query, variables }),
    });
    const payload = (await response.json()) as { data?: T; errors?: Array<{ message: string }> };
    if (!response.ok || payload.errors?.length) {
      return {
        errors: [
          {
            code: 'TRANSPORT_ERROR',
            message: payload.errors?.[0]?.message ?? `Request failed (${response.status})`,
          },
        ],
      };
    }
    return { data: payload.data };
  } catch {
    return {
      errors: [{ code: 'TRANSPORT_ERROR', message: 'The backend could not be reached' }],
    };
  }
}

export async function fetchProfile(
  endpoint: string,
  authorization?: string,
): Promise<{ profile: Profile | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{ me: Profile }>(endpoint, meQuery, {}, authorization);
  if (result.errors) {
    return { profile: null, errors: result.errors };
  }
  return { profile: result.data?.me ?? null, errors: [] };
}

export async function updateProfile(
  endpoint: string,
  input: UpdateProfileInput,
  authorization?: string,
): Promise<{ profile: Profile | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{
    updateProfile: { profile: Profile | null; errors: DomainError[] };
  }>(endpoint, updateProfileMutation, { input }, authorization);
  if (result.errors) {
    return { profile: null, errors: result.errors };
  }
  return result.data?.updateProfile ?? {
    profile: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function fetchExercises(
  endpoint: string,
  authorization?: string,
): Promise<{ exercises: CatalogExercise[]; errors: DomainError[] }> {
  const result = await executeGraphQL<{ exercises: CatalogExercise[] }>(
    endpoint,
    exercisesQuery,
    {},
    authorization,
  );
  if (result.errors) {
    return { exercises: [], errors: result.errors };
  }
  return { exercises: result.data?.exercises ?? [], errors: [] };
}

export async function fetchActiveGoal(
  endpoint: string,
  authorization?: string,
): Promise<{ goal: Goal | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{ activeGoal: Goal | null }>(
    endpoint,
    activeGoalQuery,
    {},
    authorization,
  );
  if (result.errors) {
    return { goal: null, errors: result.errors };
  }
  return { goal: result.data?.activeGoal ?? null, errors: [] };
}

export async function fetchGoals(
  endpoint: string,
  authorization?: string,
): Promise<{ goals: Goal[]; errors: DomainError[] }> {
  const result = await executeGraphQL<{ goals: Goal[] }>(endpoint, goalsQuery, {}, authorization);
  if (result.errors) {
    return { goals: [], errors: result.errors };
  }
  return { goals: result.data?.goals ?? [], errors: [] };
}

export async function setGoal(
  endpoint: string,
  input: SetGoalInput,
  authorization?: string,
): Promise<{ goal: Goal | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{
    setGoal: { goal: Goal | null; errors: DomainError[] };
  }>(endpoint, setGoalMutation, { input }, authorization);
  if (result.errors) {
    return { goal: null, errors: result.errors };
  }
  return result.data?.setGoal ?? {
    goal: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function prepareSession(
  endpoint: string,
  input: SessionPreparation,
  authorization?: string,
): Promise<{ session: PreparedSession | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{
    prepareSession: { session: PreparedSession | null; errors: DomainError[] };
  }>(endpoint, prepareSessionMutation, { input }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.prepareSession ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function fetchCurrentRoutine(
  endpoint: string,
  authorization?: string,
): Promise<{ routine: Routine | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{ currentRoutine: Routine | null }>(
    endpoint,
    currentRoutineQuery,
    {},
    authorization,
  );
  if (result.errors) {
    return { routine: null, errors: result.errors };
  }
  return { routine: result.data?.currentRoutine ?? null, errors: [] };
}

export async function fetchRoutineVersion(
  endpoint: string,
  routineId: string,
  version: number,
  authorization?: string,
): Promise<{ routine: Routine | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{ routine: Routine | null }>(
    endpoint,
    routineVersionQuery,
    { id: routineId, version },
    authorization,
  );
  if (result.errors) {
    return { routine: null, errors: result.errors };
  }
  return { routine: result.data?.routine ?? null, errors: [] };
}

export async function proposeRoutine(
  endpoint: string,
  authorization?: string,
): Promise<{ routine: Routine | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{
    proposeRoutine: { routine: Routine | null; errors: DomainError[] };
  }>(endpoint, proposeRoutineMutation, {}, authorization);
  if (result.errors) {
    return { routine: null, errors: result.errors };
  }
  return result.data?.proposeRoutine ?? {
    routine: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function editRoutine(
  endpoint: string,
  input: EditRoutineInput,
  authorization?: string,
): Promise<{ routine: Routine | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{
    editRoutine: { routine: Routine | null; errors: DomainError[] };
  }>(endpoint, editRoutineMutation, { input }, authorization);
  if (result.errors) {
    return { routine: null, errors: result.errors };
  }
  return result.data?.editRoutine ?? {
    routine: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function acceptRoutine(
  endpoint: string,
  routineId: string,
  version: number,
  authorization?: string,
): Promise<{ routine: Routine | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{
    acceptRoutine: { routine: Routine | null; errors: DomainError[] };
  }>(endpoint, acceptRoutineMutation, { routineId, version }, authorization);
  if (result.errors) {
    return { routine: null, errors: result.errors };
  }
  return result.data?.acceptRoutine ?? {
    routine: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function startSession(
  endpoint: string,
  command: SessionCommand,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{
    startSession: SessionResult;
  }>(endpoint, startSessionMutation, { command }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.startSession ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function pauseSession(
  endpoint: string,
  command: SessionCommand,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{
    pauseSession: SessionResult;
  }>(endpoint, pauseSessionMutation, { command }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.pauseSession ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function resumeSession(
  endpoint: string,
  command: SessionCommand,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{
    resumeSession: SessionResult;
  }>(endpoint, resumeSessionMutation, { command }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.resumeSession ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function confirmSessionTarget(
  endpoint: string,
  command: SessionCommand,
  targetPersonId: string,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{
    confirmSessionTarget: SessionResult;
  }>(endpoint, confirmSessionTargetMutation, { command, targetPersonId }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.confirmSessionTarget ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function disableDynamicMode(
  endpoint: string,
  command: SessionCommand,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{
    disableDynamicMode: SessionResult;
  }>(endpoint, disableDynamicModeMutation, { command }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.disableDynamicMode ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export interface FinishSessionActivityInput {
  performedSets?: PerformedSetInput[];
  observationCoverage?: ObservationCoverageInput;
  feedback?: SessionFeedbackInput;
}

export async function finishSession(
  endpoint: string,
  command: SessionCommand,
  activityOrAuth?: FinishSessionActivityInput | string,
  authorization?: string,
): Promise<SessionResult> {
  let activity: FinishSessionActivityInput | undefined;
  let auth = authorization;
  if (typeof activityOrAuth === 'string') {
    auth = activityOrAuth;
  } else if (activityOrAuth) {
    activity = activityOrAuth;
  }

  const variables: Record<string, unknown> = { command };
  if (activity?.performedSets) {
    variables.performedSets = activity.performedSets;
  }
  if (activity?.observationCoverage) {
    variables.observationCoverage = activity.observationCoverage;
  }
  if (activity?.feedback) {
    variables.feedback = activity.feedback;
  }

  const result = await executeGraphQL<{
    finishSession: SessionResult;
  }>(endpoint, finishSessionMutation, variables, auth);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.finishSession ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function recordSessionFeedback(
  endpoint: string,
  command: SessionCommand,
  feedback: SessionFeedbackInput,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{
    recordSessionFeedback: SessionResult;
  }>(endpoint, recordSessionFeedbackMutation, { command, feedback }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.recordSessionFeedback ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function abandonSession(
  endpoint: string,
  command: SessionCommand,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{
    abandonSession: SessionResult;
  }>(endpoint, abandonSessionMutation, { command }, authorization);
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return result.data?.abandonSession ?? {
    session: null,
    errors: [{ code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response' }],
  };
}

export async function fetchSession(
  endpoint: string,
  sessionId: string,
  authorization?: string,
): Promise<SessionResult> {
  const result = await executeGraphQL<{ session: PreparedSession | null }>(
    endpoint,
    sessionQuery,
    { id: sessionId },
    authorization,
  );
  if (result.errors) {
    return { session: null, errors: result.errors };
  }
  return { session: result.data?.session ?? null, errors: [] };
}

export async function publishTransientSessionUpdate(
  endpoint: string,
  input: TransientSessionUpdateInput,
  authorization?: string,
): Promise<{ success: boolean; errors: DomainError[] }> {
  const result = await executeGraphQL<{
    publishTransientSessionUpdate: { success: boolean; errors: DomainError[] };
  }>(endpoint, publishTransientSessionUpdateMutation, { input }, authorization);
  if (result.errors) {
    return { success: false, errors: result.errors };
  }
  return result.data?.publishTransientSessionUpdate ?? { success: false, errors: [] };
}

export async function fetchTransientSessionState(
  endpoint: string,
  sessionId: string,
  authorization?: string,
): Promise<{ transient: TransientSessionUpdate | null; errors: DomainError[] }> {
  const result = await executeGraphQL<{ transientSessionState: TransientSessionUpdate | null }>(
    endpoint,
    transientSessionStateQuery,
    { sessionId },
    authorization,
  );
  if (result.errors) {
    return { transient: null, errors: result.errors };
  }
  return { transient: result.data?.transientSessionState ?? null, errors: [] };
}

export async function syncSessionState(
  endpoint: string,
  sessionId: string,
  authorization?: string,
): Promise<SessionStateSync> {
  const sessionRes = await fetchSession(endpoint, sessionId, authorization);
  if (sessionRes.errors.length > 0 || !sessionRes.session) {
    return {
      session: null,
      transient: null,
      restoredFromCommitted: false,
      errors: sessionRes.errors,
    };
  }

  const transientRes = await fetchTransientSessionState(endpoint, sessionId, authorization);
  const transient = transientRes.transient;
  return {
    session: sessionRes.session,
    transient,
    restoredFromCommitted: transient === null,
    errors: [],
  };
}


