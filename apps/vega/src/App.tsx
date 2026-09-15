import {TVFocusGuideView} from '@amazon-devices/react-native-kepler';
import React, {useEffect, useState} from 'react';
import {BackHandler, Pressable, StyleSheet, Text, View} from 'react-native';

type SessionMode = 'NORMAL' | 'DYNAMIC';
type SessionIntensity = 'LIGHTER' | 'PLANNED' | 'CHALLENGING';
type Screen = 'PREPARE' | 'READY';

const sessionModes: SessionMode[] = ['NORMAL', 'DYNAMIC'];
const sessionIntensities: SessionIntensity[] = [
  'LIGHTER',
  'PLANNED',
  'CHALLENGING',
];

export function App() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [intensity, setIntensity] = useState<SessionIntensity>('PLANNED');
  const [screen, setScreen] = useState<Screen>('PREPARE');

  useEffect(() => {
    if (screen !== 'READY') {
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
          <Text style={styles.summary}>
            {mode} · {intensity}
          </Text>
          <TVButton
            label="Back to preparation"
            preferred
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

        <TVButton
          label="Start prepared session"
          testID="start-session"
          onPress={() => setScreen('READY')}
        />
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
