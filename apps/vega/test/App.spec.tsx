import 'react-native';
import {act, fireEvent, render, waitFor} from '@testing-library/react-native';
import * as React from 'react';

import {App} from '../src/App';

function jsonResponse(data: unknown) {
  return {
    ok: true,
    json: async () => ({data}),
  };
}

describe('App', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('renders the remote-friendly preparation controls', () => {
    const screen = render(<App />);

    expect(screen.getByTestId('preparation-screen')).toBeTruthy();
    expect(screen.getByTestId('mode-normal').props.hasTVPreferredFocus).toBe(
      true,
    );
    expect(screen.getByTestId('mode-normal').props.accessibilityState).toEqual({
      selected: true,
    });
    expect(
      screen.getByTestId('intensity-planned').props.accessibilityState,
    ).toEqual({selected: true});
  });

  it('updates choices and supports forward and back navigation', () => {
    const screen = render(<App />);

    fireEvent.press(screen.getByTestId('mode-dynamic'));
    fireEvent.press(screen.getByTestId('intensity-challenging'));
    fireEvent.press(screen.getByTestId('start-session'));

    expect(screen.getByTestId('ready-screen')).toBeTruthy();
    expect(screen.getByTestId('prepared-summary')).toHaveTextContent(
      'DYNAMIC · CHALLENGING',
    );

    fireEvent.press(screen.getByTestId('back-to-preparation'));
    expect(screen.getByTestId('preparation-screen')).toBeTruthy();
    expect(screen.getByTestId('mode-dynamic').props.accessibilityState).toEqual(
      {selected: true},
    );
  });

  it('issues a real, non-predictable pairing code and connects to a real paired session', async () => {
    globalThis.fetch = (async (_url: string, init: {body: string}) => {
      const body = JSON.parse(init.body);
      if (body.query.includes('IssueDisplayPairingCode')) {
        return jsonResponse({
          issueDisplayPairingCode: {
            code: 'VEGA-K7Q2X9',
            deviceType: 'VEGA_OS',
            createdAt: new Date().toISOString(),
            expiresAt: new Date(Date.now() + 900000).toISOString(),
            status: 'UNPAIRED',
            pairedSessionId: null,
          },
        });
      }
      if (body.query.includes('DisplaySessionState')) {
        return jsonResponse({
          displaySessionState: {
            sessionId: 'sess-live-01',
            deviceType: 'VEGA_OS',
            status: 'PAIRED',
            mode: 'NORMAL',
            intensity: 'PLANNED',
            state: 'ACTIVE',
            activeExercise: 'bodyweight_squat',
            confirmedReps: 6,
            visibilityStatus: 'VISIBLE',
            pauseReason: null,
          },
        });
      }
      throw new Error(`Unexpected query: ${body.query}`);
    }) as typeof fetch;

    const screen = render(<App />);

    fireEvent.press(screen.getByTestId('pair-display'));
    await waitFor(() => {
      expect(screen.getByTestId('pairing-screen')).toBeTruthy();
    });
    expect(screen.getByTestId('pairing-code')).toHaveTextContent('VEGA-K7Q2X9');
    expect(screen.queryByTestId('pairing-code')).not.toHaveTextContent('VEGA-4404');

    fireEvent.press(screen.getByTestId('connect-live-session'));
    await waitFor(() => {
      expect(screen.getByTestId('live-screen')).toBeTruthy();
    });
    expect(screen.getByTestId('visibility-badge')).toBeTruthy();
    expect(screen.getByTestId('live-metrics-summary')).toHaveTextContent(
      '6 REPS CONFIRMED',
    );

    fireEvent.press(screen.getByTestId('back-to-prep-from-live'));
    await waitFor(() => {
      expect(screen.getByTestId('preparation-screen')).toBeTruthy();
    });
  });

  it('polls displaySessionState while live and reflects a later Vision update', async () => {
    jest.useFakeTimers();
    let displayStateCallCount = 0;

    globalThis.fetch = (async (_url: string, init: {body: string}) => {
      const body = JSON.parse(init.body);
      if (body.query.includes('IssueDisplayPairingCode')) {
        return jsonResponse({
          issueDisplayPairingCode: {
            code: 'VEGA-P0LL01',
            deviceType: 'VEGA_OS',
            createdAt: new Date().toISOString(),
            expiresAt: new Date(Date.now() + 900000).toISOString(),
            status: 'UNPAIRED',
            pairedSessionId: null,
          },
        });
      }
      if (body.query.includes('DisplaySessionState')) {
        displayStateCallCount += 1;
        // The first read (at connect time) sees 6 reps of a squat; every
        // later poll sees a later, real Vision update -- 11 reps of a
        // different exercise. The display must show the newest value, not
        // the snapshot it read when it first connected.
        const isFirstRead = displayStateCallCount === 1;
        return jsonResponse({
          displaySessionState: {
            sessionId: 'sess-live-01',
            deviceType: 'VEGA_OS',
            status: 'PAIRED',
            mode: 'NORMAL',
            intensity: 'PLANNED',
            state: 'ACTIVE',
            activeExercise: isFirstRead ? 'bodyweight_squat' : 'push_up',
            confirmedReps: isFirstRead ? 6 : 11,
            visibilityStatus: 'VISIBLE',
            pauseReason: null,
          },
        });
      }
      throw new Error(`Unexpected query: ${body.query}`);
    }) as typeof fetch;

    const screen = render(<App />);

    fireEvent.press(screen.getByTestId('pair-display'));
    await waitFor(() => {
      expect(screen.getByTestId('pairing-screen')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('connect-live-session'));
    await waitFor(() => {
      expect(screen.getByTestId('live-screen')).toBeTruthy();
    });
    expect(screen.getByTestId('live-metrics-summary')).toHaveTextContent(
      '6 REPS CONFIRMED',
    );

    // No user action, just time passing: a real live display refreshes on
    // its own while the workout continues.
    await act(async () => {
      jest.advanceTimersByTime(3000);
    });

    await waitFor(() => {
      expect(screen.getByTestId('live-metrics-summary')).toHaveTextContent(
        '11 REPS CONFIRMED',
      );
    });
    expect(displayStateCallCount).toBeGreaterThanOrEqual(2);

    jest.useRealTimers();
  });

  it('never shows fabricated live results when the backend connection fails', async () => {
    globalThis.fetch = (async () => {
      throw new Error('network unreachable');
    }) as typeof fetch;

    const screen = render(<App />);

    fireEvent.press(screen.getByTestId('pair-display'));
    await waitFor(() => {
      expect(screen.getByTestId('pairing-screen')).toBeTruthy();
    });
    // No code was ever issued -- must not show a fake/default code.
    expect(screen.queryByTestId('pairing-code')).toBeNull();
    expect(screen.getByTestId('pairing-error')).toBeTruthy();

    fireEvent.press(screen.getByTestId('connect-live-session'));

    // A failed connection attempt (there is no pairing code to connect
    // with) must never transition to the live screen with stale or
    // hardcoded data.
    expect(screen.queryByTestId('live-screen')).toBeNull();
    expect(screen.getByTestId('pairing-screen')).toBeTruthy();
  });

  it('stays on the pairing screen with an error when a paired session cannot be found', async () => {
    globalThis.fetch = (async (_url: string, init: {body: string}) => {
      const body = JSON.parse(init.body);
      if (body.query.includes('IssueDisplayPairingCode')) {
        return jsonResponse({
          issueDisplayPairingCode: {
            code: 'VEGA-A1B2C3',
            deviceType: 'VEGA_OS',
            createdAt: new Date().toISOString(),
            expiresAt: new Date(Date.now() + 900000).toISOString(),
            status: 'UNPAIRED',
            pairedSessionId: null,
          },
        });
      }
      // Unpaired: no session_id yet.
      return jsonResponse({
        displaySessionState: {
          sessionId: null,
          deviceType: 'VEGA_OS',
          status: 'UNPAIRED',
          mode: null,
          intensity: null,
          state: null,
          activeExercise: null,
          confirmedReps: 0,
          visibilityStatus: null,
          pauseReason: null,
        },
      });
    }) as typeof fetch;

    const screen = render(<App />);

    fireEvent.press(screen.getByTestId('pair-display'));
    await waitFor(() => {
      expect(screen.getByTestId('pairing-code')).toHaveTextContent('VEGA-A1B2C3');
    });

    fireEvent.press(screen.getByTestId('connect-live-session'));
    await waitFor(() => {
      expect(screen.getByTestId('pairing-error')).toBeTruthy();
    });
    expect(screen.queryByTestId('live-screen')).toBeNull();
  });
});
