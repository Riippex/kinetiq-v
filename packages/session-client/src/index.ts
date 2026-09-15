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
