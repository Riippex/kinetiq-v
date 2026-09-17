// MOCK / DEMO SCREEN -- not wired to a real backend.
//
// There is no pairing-code issuance or session-state API anywhere in
// kinetiq-v yet: `pairDisplay`/`startSession` below only flip local
// component state, they never call GraphQL or any pairing service. The
// "FIRE-7892" pairing code and the initial session data are hardcoded.
// KV-404 reflects this: it is Ready (mock UI only), not Verified, until a
// real pairing/session-state backend exists and this screen calls it.
import {StatusBar} from 'expo-status-bar';
import {
  sessionIntensities,
  sessionModes,
  type SessionIntensity,
  type SessionMode,
} from '@kinetiq/session-client';
import {useEffect, useState} from 'react';
import {BackHandler, Pressable, StyleSheet, Text, View} from 'react-native';

type ScreenState = 'PREPARE' | 'PAIRING' | 'LIVE_SESSION';

export interface DisplaySessionData {
  sessionId: string;
  mode: SessionMode;
  intensity: SessionIntensity;
  state: 'READY' | 'ACTIVE' | 'PAUSED' | 'COMPLETED';
  activeExercise: string;
  confirmedReps: number;
  visibilityStatus: 'VISIBLE' | 'PARTIALLY_VISIBLE' | 'NOT_VISIBLE';
  pauseReason?: string | null;
}

export default function App() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [intensity, setIntensity] = useState<SessionIntensity>('PLANNED');
  const [screen, setScreen] = useState<ScreenState>('PREPARE');
  const [session, setSession] = useState<DisplaySessionData>({
    sessionId: 'display-paired-01',
    mode: 'NORMAL',
    intensity: 'PLANNED',
    state: 'ACTIVE',
    activeExercise: 'Goblet Squat',
    confirmedReps: 8,
    visibilityStatus: 'VISIBLE',
  });

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

  const startSession = () => {
    setSession(prev => ({
      ...prev,
      mode,
      intensity,
      state: 'ACTIVE',
    }));
    setScreen('LIVE_SESSION');
  };

  const pairDisplay = () => {
    setScreen('PAIRING');
  };

  if (screen === 'LIVE_SESSION') {
    return (
      <View style={styles.screen} testID="live-session-screen">
        <StatusBar hidden />
        <View style={styles.copy}>
          <MockBanner />
          <Text style={styles.eyebrow}>KINETIQ V · FIRE TV LIVE</Text>
          <Text style={styles.title}>{session.activeExercise}</Text>
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
          <MockBanner />
          <Text style={styles.eyebrow}>DISPLAY PAIRING</Text>
          <Text style={styles.title}>Pair with phone</Text>
          <Text style={styles.description}>
            Display Code: <Text style={styles.codeText}>FIRE-7892</Text>. Select this display on your phone to sync workout status.
          </Text>
        </View>

        <View style={styles.panel}>
          <FocusableButton
            label="Connect prepared session"
            preferred
            testID="connect-session-btn"
            onPress={() => setScreen('LIVE_SESSION')}
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

function MockBanner() {
  return (
    <View style={styles.mockBanner} testID="mock-banner">
      <Text style={styles.mockBannerText}>DEMO MODE — not connected to a live session</Text>
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
  mockBanner: {
    alignSelf: 'flex-start',
    backgroundColor: '#3B0764',
    borderWidth: 2,
    borderColor: '#C084FC',
    borderRadius: 8,
    paddingVertical: 6,
    paddingHorizontal: 14,
    marginBottom: 16,
  },
  mockBannerText: {color: '#E9D5FF', fontSize: 14, fontWeight: '800', letterSpacing: 1},
  eyebrow: {color: '#A3FF12', fontSize: 18, fontWeight: '800', letterSpacing: 3},
  title: {color: '#F4F7FB', fontSize: 64, fontWeight: '700', marginTop: 20},
  description: {color: '#9CA3AF', fontSize: 24, lineHeight: 34, marginTop: 24, maxWidth: 720},
  codeText: {color: '#A3FF12', fontWeight: '800'},
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
