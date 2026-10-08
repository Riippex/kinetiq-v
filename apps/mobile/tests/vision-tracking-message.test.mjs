import assert from 'node:assert/strict';
import {test} from 'node:test';
import {visionTrackingMessage} from '../src/features/session/visionTrackingMessage.ts';

const now = Date.parse('2026-10-08T20:00:00Z');
const fresh = timestamp => ({timestamp, visibilityStatus: 'VISIBLE'});

test('connected camera alone and expired or invalid observations never imply tracking', () => {
  for (const result of [null, fresh(null), fresh('invalid'),
    fresh('2026-10-08T19:59:49Z'), fresh('2026-10-08T20:00:11Z')]) {
    assert.match(visionTrackingMessage(result, now), /Waiting for a current Vision result/);
  }
});

test('current observations distinguish full, partial, missing and unknown visibility', () => {
  const timestamp = new Date(now).toISOString();
  assert.match(visionTrackingMessage({timestamp, visibilityStatus: 'VISIBLE'}, now), /full body/);
  assert.match(visionTrackingMessage({timestamp, visibilityStatus: 'PARTIALLY_VISIBLE'}, now), /only see part/);
  assert.match(visionTrackingMessage({timestamp, visibilityStatus: 'NOT_VISIBLE'}, now), /cannot currently see/);
  assert.match(visionTrackingMessage({timestamp, visibilityStatus: 'UNKNOWN'}, now), /Waiting/);
});
