import type {TransientSessionUpdate} from '@kinetiq/session-client';

const waitingMessage = 'Camera feed connected. Waiting for a current Vision result.';
const maxResultAgeMs = 10_000;

export function visionTrackingMessage(
  result: Pick<TransientSessionUpdate, 'visibilityStatus' | 'timestamp'> | null,
  now = Date.now(),
): string {
  const timestamp = Date.parse(result?.timestamp ?? '');
  if (!Number.isFinite(timestamp) || Math.abs(now - timestamp) > maxResultAgeMs) {
    return waitingMessage;
  }
  switch (result?.visibilityStatus) {
    case 'VISIBLE':
      return 'Vision can see your full body. Keep it inside the guide.';
    case 'PARTIALLY_VISIBLE':
      return 'Vision can only see part of your body. Adjust the camera to include your feet and head.';
    case 'NOT_VISIBLE':
      return 'Vision cannot currently see your selected target. Step back into the camera view.';
    default:
      return waitingMessage;
  }
}
