import assert from 'node:assert/strict';
import {test} from 'node:test';
import {redirectSystemPath} from '../src/app/+native-intent.ts';

test('Cognito returns home on cold and warm launch without carrying OAuth parameters', () => {
  for (const initial of [true, false]) {
    for (const path of [
      'kinetiq://callback?code=test-code&state=test-state',
      'kinetiq://callback/?error=access_denied&state=test-state',
      'kinetiq://logout',
    ]) {
      assert.equal(redirectSystemPath({path, initial}), '/');
    }
  }
});

test('other deep links and invalid paths are preserved', () => {
  for (const path of [
    'kinetiq://sessions/session-123',
    '/sessions/session-123',
    'https://callback/?code=test-code',
    'other-app://callback?code=test-code',
    'kinetiq://callback/unrelated-page',
    'not a URL',
  ]) {
    assert.equal(redirectSystemPath({path, initial: false}), path);
  }
});
