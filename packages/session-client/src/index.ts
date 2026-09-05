export const sessionModes = ['NORMAL', 'DYNAMIC'] as const;
export const sessionIntensities = ['LIGHTER', 'PLANNED', 'CHALLENGING'] as const;
export const coachingTones = ['CALM', 'TECHNICAL', 'MOTIVATIONAL', 'EDGY'] as const;
export const dynamicChallengeTypes = ['HOLD_POSE', 'MIRROR_POSE', 'QUICK_REPS', 'RECOVERY'] as const;

export type SessionMode = (typeof sessionModes)[number];
export type SessionIntensity = (typeof sessionIntensities)[number];
export type CoachingTone = (typeof coachingTones)[number];
export type DynamicChallengeType = (typeof dynamicChallengeTypes)[number];

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

interface PrepareSessionResponse {
  data?: {
    prepareSession: {
      session: PreparedSession | null;
      errors: DomainError[];
    };
  };
  errors?: Array<{message: string}>;
}

const prepareSessionMutation = `
  mutation PrepareSession($input: PrepareSessionInput!) {
    prepareSession(input: $input) {
      session { id revision state }
      errors { code message field }
    }
  }
`;

export async function prepareSession(
  endpoint: string,
  input: SessionPreparation,
  authorization?: string,
): Promise<{session: PreparedSession | null; errors: DomainError[]}> {
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'content-type': 'application/json',
        ...(authorization ? {authorization} : {}),
      },
      body: JSON.stringify({query: prepareSessionMutation, variables: {input}}),
    });
    const payload = (await response.json()) as PrepareSessionResponse;
    if (!response.ok || payload.errors?.length) {
      return {
        session: null,
        errors: [{code: 'TRANSPORT_ERROR', message: payload.errors?.[0]?.message ?? `Request failed (${response.status})`}],
      };
    }
    return payload.data?.prepareSession ?? {
      session: null,
      errors: [{code: 'INVALID_RESPONSE', message: 'The backend returned an incomplete response'}],
    };
  } catch {
    return {
      session: null,
      errors: [{code: 'TRANSPORT_ERROR', message: 'The backend could not be reached'}],
    };
  }
}
