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

export interface PreparedSession {
  id: string;
  revision: number;
  state: 'READY' | 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'ABANDONED';
}

export interface DomainError {
  code: string;
  message: string;
  field?: string | null;
}

export interface RoutineExercise {
  id: string;
  name: string;
  version?: number;
  visionSupported?: boolean;
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
