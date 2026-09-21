import {TVFocusGuideView} from '@amazon-devices/react-native-kepler';
import {
  fetchDisplaySessionState,
  issueDisplayPairingCode,
} from '@kinetiq/session-client';
import React, {useEffect, useState} from 'react';
import {BackHandler, Pressable, StyleSheet, Text, View} from 'react-native';

type SessionMode = 'NORMAL' | 'DYNAMIC';
type SessionIntensity = 'LIGHTER' | 'PLANNED' | 'CHALLENGING';
type Screen = 'PREPARE' | 'READY' | 'PAIRING' | 'LIVE';

const GRAPHQL_ENDPOINT = 'http://localhost:8000/graphql';
const LIVE_REFRESH_INTERVAL_MS = 3000;

const sessionModes: SessionMode[] = ['NORMAL', 'DYNAMIC'];
const sessionIntensities: SessionIntensity[] = [
  'LIGHTER',
  'PLANNED',
  'CHALLENGING',
];

export interface LiveSessionState {
  exerciseName: string | null;
  confirmedReps: number;
  visibilityStatus: 'VISIBLE' | 'PARTIALLY_VISIBLE' | 'NOT_VISIBLE' | string;
  isPaused: boolean;
  pauseReason?: string | null;
}

const NO_PROGRESS_STATE: LiveSessionState = {
  exerciseName: null,
  confirmedReps: 0,
  visibilityStatus: 'VISIBLE',
  isPaused: false,
};

export function App() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [intensity, setIntensity] = useState<SessionIntensity>('PLANNED');
  const [screen, setScreen] = useState<Screen>('PREPARE');
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const [liveState, setLiveState] = useState<LiveSessionState>(NO_PROGRESS_STATE);
  const [isLivePaired, setIsLivePaired] = useState(false);

  useEffect(() => {
    if (screen === 'PREPARE') {
      return;
    }

    const subscription = BackHandler?.addEventListener?.(
      'hardwareBackPress',
      () => {
        setScreen('PREPARE');
        return true;
      },
    );

    return () => subscription?.remove();
  }, [screen]);

  // A real paired session's state (reps, active exercise, visibility,
  // pause reason) changes continuously as Vision observes the workout --
  // reading it once at connect time and never again would leave this
  // display showing an increasingly stale snapshot for the rest of the
  // session. The local-only preview ("Start live movement") never sets
  // `isLivePaired`, so it is never polled.
  useEffect(() => {
    if (screen !== 'LIVE' || !pairingCode || !isLivePaired) {
      return;
    }

    const interval = setInterval(async () => {
      try {
        const res = await fetchDisplaySessionState(GRAPHQL_ENDPOINT, pairingCode);
        if (res.state && res.state.sessionId) {
          setLiveState({
            exerciseName: res.state.activeExercise ?? null,
            confirmedReps: res.state.confirmedReps ?? 0,
            visibilityStatus: res.state.visibilityStatus ?? 'VISIBLE',
            isPaused: res.state.state === 'PAUSED',
            pauseReason: res.state.pauseReason,
          });
          if (res.state.mode) setMode(res.state.mode);
          if (res.state.intensity) setIntensity(res.state.intensity);
        }
      } catch {
        // A transient poll failure must not blank out the last known
        // good live state -- keep showing it and retry on the next tick.
      }
    }, LIVE_REFRESH_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [screen, pairingCode, isLivePaired]);

  const pairDisplay = async () => {
    setPairingError(null);
    try {
      const res = await issueDisplayPairingCode(GRAPHQL_ENDPOINT, 'VEGA_OS');
      if (res.pairing) {
        setPairingCode(res.pairing.code);
        setScreen('PAIRING');
        return;
      }
      setPairingError('Could not generate a pairing code. Check your connection and try again.');
    } catch {
      setPairingError('Could not generate a pairing code. Check your connection and try again.');
    }
    setScreen('PAIRING');
  };

  const connectLiveSession = async () => {
    if (!pairingCode) {
      return;
    }
    setPairingError(null);
    try {
      const res = await fetchDisplaySessionState(GRAPHQL_ENDPOINT, pairingCode);
      if (res.state && res.state.sessionId) {
        setLiveState({
          exerciseName: res.state.activeExercise ?? null,
          confirmedReps: res.state.confirmedReps ?? 0,
          visibilityStatus: res.state.visibilityStatus ?? 'VISIBLE',
          isPaused: res.state.state === 'PAUSED',
          pauseReason: res.state.pauseReason,
        });
        if (res.state.mode) setMode(res.state.mode);
        if (res.state.intensity) setIntensity(res.state.intensity);
        setIsLivePaired(true);
        setScreen('LIVE');
        return;
      }
      // A failed or empty connection must never fall through to the live
      // screen showing stale or fabricated data -- stay on pairing with
      // an honest error instead.
      setPairingError('No paired session yet. Pair this display from your phone first.');
    } catch {
      setPairingError('Could not reach the backend. Check your connection and try again.');
    }
  };

  if (screen === 'LIVE') {
    return (
      <View style={styles.screen} testID="live-screen">
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>KINETIQ V · VEGA OS LIVE</Text>
          <Text style={styles.title}>{liveState.exerciseName ?? 'Waiting for Vision…'}</Text>
          <Text style={styles.description}>
            {mode === 'NORMAL' ? 'Focused training' : 'Dynamic challenge mode'} ·{' '}
            {intensity.toLowerCase()} intensity
          </Text>
        </View>

        <TVFocusGuideView
          autoFocus
          trapFocusLeft
          trapFocusRight
          style={styles.controls}>
          <Text style={styles.label}>LIVE SESSION STATE</Text>
          <Text style={styles.summary} testID="live-metrics-summary">
            {liveState.confirmedReps} REPS CONFIRMED
          </Text>

          <View style={styles.badge} testID="visibility-badge">
            <Text style={styles.badgeText}>
              {liveState.visibilityStatus === 'VISIBLE'
                ? '● TARGET CONFIRMED'
                : '⚠️ VISIBILITY LOW'}
            </Text>
          </View>

          {liveState.isPaused ? (
            <Text style={styles.pauseReason}>PAUSED: {liveState.pauseReason ?? 'USER_REQUEST'}</Text>
          ) : null}

          <TVButton
            label="Back to preparation"
            preferred
            testID="back-to-prep-from-live"
            onPress={() => setScreen('PREPARE')}
          />
        </TVFocusGuideView>
      </View>
    );
  }

  if (screen === 'PAIRING') {
    return (
      <View style={styles.screen} testID="pairing-screen">
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>VEGA OS DISPLAY PAIRING</Text>
          <Text style={styles.title}>Pair with phone</Text>
          <Text style={styles.description}>
            {pairingCode ? (
              <>
                Display pairing code:{' '}
                <Text style={styles.codeHighlight} testID="pairing-code">
                  {pairingCode}
                </Text>
                . Select this device on your mobile app to mirror prepared session activity.
              </>
            ) : (
              'Generating a pairing code…'
            )}
          </Text>
          {pairingError ? (
            <Text style={styles.pairingErrorText} testID="pairing-error">{pairingError}</Text>
          ) : null}
        </View>

        <TVFocusGuideView
          autoFocus
          trapFocusLeft
          trapFocusRight
          style={styles.controls}>
          <TVButton
            label="Connect live session"
            preferred
            testID="connect-live-session"
            onPress={connectLiveSession}
          />
          <TVButton
            label="Back to preparation"
            testID="back-from-pairing"
            onPress={() => setScreen('PREPARE')}
          />
        </TVFocusGuideView>
      </View>
    );
  }

  if (screen === 'READY') {
    return (
      <View style={styles.screen} testID="ready-screen">
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>KINETIQ V · VEGA OS</Text>
          <Text style={styles.title}>Ready to move.</Text>
          <Text style={styles.description}>
            Your {mode === 'NORMAL' ? 'focused' : 'dynamic'} session uses the{' '}
            {intensity.toLowerCase()} intensity.
          </Text>
        </View>

        <TVFocusGuideView
          autoFocus
          trapFocusLeft
          trapFocusRight
          style={styles.controls}>
          <Text style={styles.label}>PREPARED SESSION</Text>
          <Text style={styles.summary} testID="prepared-summary">
            {mode} · {intensity}
          </Text>
          <TVButton
            label="Start live movement"
            preferred
            testID="start-live-movement"
            onPress={() => {
              // Local-only preview (no display pairing involved): starts
              // at zero confirmed reps and no active exercise, since
              // nothing has actually been observed yet.
              setLiveState(NO_PROGRESS_STATE);
              setIsLivePaired(false);
              setScreen('LIVE');
            }}
          />
          <TVButton
            label="Back to preparation"
            testID="back-to-preparation"
            onPress={() => setScreen('PREPARE')}
          />
        </TVFocusGuideView>
      </View>
    );
  }

  return (
    <View style={styles.screen} testID="preparation-screen">
      <View style={styles.copy}>
        <Text style={styles.eyebrow}>KINETIQ V · VEGA OS</Text>
        <Text style={styles.title}>Prepare your session</Text>
        <Text style={styles.description}>
          Use the remote for quick choices. Camera setup and detailed changes
          stay on your phone.
        </Text>
      </View>

      <TVFocusGuideView
        autoFocus
        trapFocusLeft
        trapFocusRight
        style={styles.controls}>
        <Text style={styles.label}>MODE</Text>
        <View style={styles.row}>
          {sessionModes.map((value) => (
            <TVButton
              key={value}
              label={value === 'NORMAL' ? 'Focused' : 'Dynamic'}
              preferred={value === 'NORMAL'}
              selected={mode === value}
              testID={`mode-${value.toLowerCase()}`}
              onPress={() => setMode(value)}
            />
          ))}
        </View>

        <Text style={styles.label}>INTENSITY</Text>
        <View style={styles.row}>
          {sessionIntensities.map((value) => (
            <TVButton
              key={value}
              label={value.toLowerCase()}
              selected={intensity === value}
              testID={`intensity-${value.toLowerCase()}`}
              onPress={() => setIntensity(value)}
            />
          ))}
        </View>

        <View style={styles.row}>
          <TVButton
            label="Start prepared session"
            testID="start-session"
            onPress={() => setScreen('READY')}
          />
          <TVButton
            label="Pair display"
            testID="pair-display"
            onPress={pairDisplay}
          />
        </View>
      </TVFocusGuideView>
    </View>
  );
}

function TVButton({
  label,
  selected = false,
  preferred = false,
  testID,
  onPress,
}: {
  label: string;
  selected?: boolean;
  preferred?: boolean;
  testID: string;
  onPress: () => void;
}) {
  const [focused, setFocused] = useState(false);

  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={{selected}}
      hasTVPreferredFocus={preferred}
      onBlur={() => setFocused(false)}
      onFocus={() => setFocused(true)}
      onPress={onPress}
      testID={testID}
      style={[
        styles.button,
        selected && styles.selected,
        focused && styles.focused,
      ]}>
      <Text
        style={[
          styles.buttonText,
          (selected || focused) && styles.activeButtonText,
        ]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    flexDirection: 'row',
    backgroundColor: '#070B14',
    padding: 72,
    gap: 72,
  },
  copy: {flex: 1, justifyContent: 'center'},
  eyebrow: {
    color: '#A3FF12',
    fontSize: 18,
    fontWeight: '800',
    letterSpacing: 3,
  },
  title: {color: '#F4F7FB', fontSize: 64, fontWeight: '700', marginTop: 20},
  description: {
    color: '#9CA3AF',
    fontSize: 24,
    lineHeight: 34,
    marginTop: 24,
    maxWidth: 720,
  },
  codeHighlight: {
    color: '#A3FF12',
    fontWeight: '800',
  },
  pairingErrorText: {
    color: '#F87171',
    fontSize: 18,
    fontWeight: '600',
    marginTop: 16,
  },
  controls: {width: 650, justifyContent: 'center', gap: 20},
  label: {
    color: '#9CA3AF',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 2,
    marginTop: 12,
  },
  row: {flexDirection: 'row', gap: 16},
  summary: {
    color: '#F4F7FB',
    fontSize: 26,
    fontWeight: '700',
    marginBottom: 12,
  },
  badge: {
    backgroundColor: '#111827',
    borderWidth: 2,
    borderColor: '#A3FF12',
    paddingVertical: 10,
    paddingHorizontal: 18,
    borderRadius: 8,
    alignSelf: 'flex-start',
    marginBottom: 10,
  },
  badgeText: {
    color: '#A3FF12',
    fontSize: 18,
    fontWeight: '700',
  },
  pauseReason: {
    color: '#F87171',
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 10,
  },
  button: {
    minHeight: 64,
    minWidth: 150,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 3,
    borderColor: '#293244',
    borderRadius: 14,
    backgroundColor: '#111827',
    paddingHorizontal: 24,
  },
  selected: {borderColor: '#A3FF12'},
  focused: {
    backgroundColor: '#A3FF12',
    borderColor: '#F4F7FB',
    transform: [{scale: 1.05}],
  },
  buttonText: {
    color: '#D1D5DB',
    fontSize: 19,
    fontWeight: '700',
    textTransform: 'capitalize',
  },
  activeButtonText: {color: '#070B14'},
});

export default App;
