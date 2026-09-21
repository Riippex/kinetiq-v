import {StatusBar} from 'expo-status-bar';
import {
  fetchDisplaySessionState,
  issueDisplayPairingCode,
  sessionIntensities,
  sessionModes,
  type SessionIntensity,
  type SessionMode,
} from '@kinetiq/session-client';
import {useEffect, useState} from 'react';
import {BackHandler, Pressable, StyleSheet, Text, View} from 'react-native';

type ScreenState = 'PREPARE' | 'PAIRING' | 'LIVE_SESSION';

const GRAPHQL_ENDPOINT = 'http://localhost:8000/graphql';
const LIVE_REFRESH_INTERVAL_MS = 3000;

export interface DisplaySessionData {
  sessionId: string;
  mode: SessionMode;
  intensity: SessionIntensity;
  state: string;
  activeExercise: string | null;
  confirmedReps: number;
  visibilityStatus: 'VISIBLE' | 'PARTIALLY_VISIBLE' | 'NOT_VISIBLE' | string;
  pauseReason?: string | null;
}

export default function App() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [intensity, setIntensity] = useState<SessionIntensity>('PLANNED');
  const [screen, setScreen] = useState<ScreenState>('PREPARE');
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const [session, setSession] = useState<DisplaySessionData | null>(null);

  useEffect(() => {
    if (screen === 'PREPARE') {
      return;
    }

    const backSubscription = BackHandler.addEventListener('hardwareBackPress', () => {
      setScreen('PREPARE');
      return true;
    });

    return () => backSubscription.remove();
  }, [screen]);

  // A real paired session's state (reps, active exercise, visibility,
  // pause reason) changes continuously as Vision observes the workout --
  // reading it once at connect time and never again would leave the TV
  // showing an increasingly stale snapshot for the rest of the session.
  // The local-only preview (`session.sessionId === 'local-preview'`) has
  // no pairing code and nothing real to poll.
  useEffect(() => {
    if (screen !== 'LIVE_SESSION' || !pairingCode || session?.sessionId === 'local-preview') {
      return;
    }

    const interval = setInterval(async () => {
      try {
        const res = await fetchDisplaySessionState(GRAPHQL_ENDPOINT, pairingCode);
        if (res.state && res.state.sessionId) {
          setSession({
            sessionId: res.state.sessionId,
            mode: res.state.mode ?? mode,
            intensity: res.state.intensity ?? intensity,
            state: res.state.state ?? 'ACTIVE',
            activeExercise: res.state.activeExercise ?? null,
            confirmedReps: res.state.confirmedReps ?? 0,
            visibilityStatus: res.state.visibilityStatus ?? 'VISIBLE',
            pauseReason: res.state.pauseReason,
          });
        }
      } catch {
        // A transient poll failure must not blank out the last known
        // good live state -- keep showing it and retry on the next tick.
      }
    }, LIVE_REFRESH_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [screen, pairingCode, session?.sessionId, mode, intensity]);

  const startSession = () => {
    // Local-only preview (no display pairing involved): starts at zero
    // confirmed reps and no active exercise, since nothing has actually
    // been observed yet -- never a fabricated placeholder like a
    // pre-filled rep count.
    setSession({
      sessionId: 'local-preview',
      mode,
      intensity,
      state: 'ACTIVE',
      activeExercise: null,
      confirmedReps: 0,
      visibilityStatus: 'VISIBLE',
    });
    setScreen('LIVE_SESSION');
  };

  const pairDisplay = async () => {
    setPairingError(null);
    try {
      const res = await issueDisplayPairingCode(GRAPHQL_ENDPOINT, 'FIRE_TV');
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

  const connectSession = async () => {
    if (!pairingCode) {
      return;
    }
    setPairingError(null);
    try {
      const res = await fetchDisplaySessionState(GRAPHQL_ENDPOINT, pairingCode);
      if (res.state && res.state.sessionId) {
        setSession({
          sessionId: res.state.sessionId,
          mode: res.state.mode ?? mode,
          intensity: res.state.intensity ?? intensity,
          state: res.state.state ?? 'ACTIVE',
          activeExercise: res.state.activeExercise ?? null,
          confirmedReps: res.state.confirmedReps ?? 0,
          visibilityStatus: res.state.visibilityStatus ?? 'VISIBLE',
          pauseReason: res.state.pauseReason,
        });
        setScreen('LIVE_SESSION');
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

  if (screen === 'LIVE_SESSION' && session) {
    return (
      <View style={styles.screen} testID="live-session-screen">
        <StatusBar hidden />
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>KINETIQ V · FIRE TV LIVE</Text>
          <Text style={styles.title}>{session.activeExercise ?? 'Waiting for Vision…'}</Text>
          <Text style={styles.description}>
            {session.mode === 'NORMAL' ? 'Focused training' : 'Dynamic challenge mode'} ·{' '}
            {session.intensity.toLowerCase()} intensity
          </Text>
        </View>

        <View style={styles.panel}>
          <Text style={styles.label}>SESSION STATE</Text>
          <Text style={styles.metricsSummary}>
            {session.state} · {session.confirmedReps} REPS CONFIRMED
          </Text>

          <Text style={styles.label}>TRACKING STATUS</Text>
          <View style={styles.statusBadge}>
            <Text style={styles.statusText}>
              {session.visibilityStatus === 'VISIBLE' ? '● TARGET VISIBLE' : '⚠️ CHECK VISIBILITY'}
            </Text>
          </View>

          {session.pauseReason ? (
            <Text style={styles.pauseReasonText}>PAUSED: {session.pauseReason}</Text>
          ) : null}

          <FocusableButton
            label="Back to preparation"
            preferred
            testID="back-to-prep-btn"
            onPress={() => setScreen('PREPARE')}
          />
        </View>
      </View>
    );
  }

  if (screen === 'PAIRING') {
    return (
      <View style={styles.screen} testID="pairing-screen">
        <StatusBar hidden />
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>DISPLAY PAIRING</Text>
          <Text style={styles.title}>Pair with phone</Text>
          <Text style={styles.description}>
            {pairingCode ? (
              <>
                Display Code: <Text style={styles.codeText} testID="pairing-code">{pairingCode}</Text>. Select this display on your phone to sync workout status.
              </>
            ) : (
              'Generating a pairing code…'
            )}
          </Text>
          {pairingError ? (
            <Text style={styles.errorText} testID="pairing-error">{pairingError}</Text>
          ) : null}
        </View>

        <View style={styles.panel}>
          <FocusableButton
            label="Connect prepared session"
            preferred
            testID="connect-session-btn"
            onPress={connectSession}
          />
          <FocusableButton
            label="Back"
            testID="back-btn"
            onPress={() => setScreen('PREPARE')}
          />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.screen} testID="preparation-screen">
      <StatusBar hidden />
      <View style={styles.copy}>
        <Text style={styles.eyebrow}>KINETIQ V · FIRE TV</Text>
        <Text style={styles.title}>Prepare your session</Text>
        <Text style={styles.description}>
          Use the remote for quick choices. Camera setup and detailed changes stay on your phone.
        </Text>
      </View>

      <View style={styles.panel}>
        <Text style={styles.label}>MODE</Text>
        <View style={styles.row}>
          {sessionModes.map(value => (
            <Choice
              key={value}
              label={value === 'NORMAL' ? 'Focused' : 'Dynamic'}
              preferred={value === 'NORMAL'}
              selected={mode === value}
              onPress={() => setMode(value)}
            />
          ))}
        </View>

        <Text style={styles.label}>INTENSITY</Text>
        <View style={styles.row}>
          {sessionIntensities.map(value => (
            <Choice
              key={value}
              label={value.toLowerCase()}
              selected={intensity === value}
              onPress={() => setIntensity(value)}
            />
          ))}
        </View>

        <View style={styles.row}>
          <FocusableButton
            label="Start prepared session"
            preferred
            testID="start-prepared-session-btn"
            onPress={startSession}
          />
          <FocusableButton
            label="Pair display"
            testID="pair-display-btn"
            onPress={pairDisplay}
          />
        </View>
      </View>
    </View>
  );
}

function Choice({
  label,
  selected,
  preferred,
  onPress,
}: {
  label: string;
  selected: boolean;
  preferred?: boolean;
  onPress: () => void;
}) {
  return <FocusableButton label={label} preferred={preferred} selected={selected} onPress={onPress} />;
}

function FocusableButton({
  label,
  selected = false,
  preferred = false,
  testID,
  onPress,
}: {
  label: string;
  selected?: boolean;
  preferred?: boolean;
  testID?: string;
  onPress?: () => void;
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
      style={[styles.button, selected && styles.selectedButton, focused && styles.focusedButton]}>
      <Text style={[styles.buttonText, (selected || focused) && styles.activeButtonText]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: {flex: 1, flexDirection: 'row', backgroundColor: '#070B14', padding: 72, gap: 72},
  copy: {flex: 1, justifyContent: 'center'},
  eyebrow: {color: '#A3FF12', fontSize: 18, fontWeight: '800', letterSpacing: 3},
  title: {color: '#F4F7FB', fontSize: 64, fontWeight: '700', marginTop: 20},
  description: {color: '#9CA3AF', fontSize: 24, lineHeight: 34, marginTop: 24, maxWidth: 720},
  codeText: {color: '#A3FF12', fontWeight: '800'},
  errorText: {color: '#F87171', fontSize: 18, fontWeight: '600', marginTop: 16},
  panel: {width: 650, justifyContent: 'center', gap: 20},
  label: {color: '#9CA3AF', fontSize: 16, fontWeight: '700', letterSpacing: 2, marginTop: 12},
  metricsSummary: {color: '#F4F7FB', fontSize: 28, fontWeight: '700'},
  statusBadge: {
    backgroundColor: '#111827',
    borderWidth: 2,
    borderColor: '#A3FF12',
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 10,
    alignSelf: 'flex-start',
  },
  statusText: {color: '#A3FF12', fontSize: 18, fontWeight: '700'},
  pauseReasonText: {color: '#F87171', fontSize: 18, fontWeight: '600'},
  row: {flexDirection: 'row', gap: 16},
  button: {
    minHeight: 64,
    minWidth: 150,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 14,
    borderWidth: 3,
    borderColor: '#293244',
    paddingHorizontal: 24,
    backgroundColor: '#111827',
  },
  selectedButton: {borderColor: '#A3FF12'},
  focusedButton: {backgroundColor: '#A3FF12', borderColor: '#F4F7FB', transform: [{scale: 1.05}]},
  buttonText: {color: '#D1D5DB', fontSize: 19, fontWeight: '700', textTransform: 'capitalize'},
  activeButtonText: {color: '#070B14'},
});
