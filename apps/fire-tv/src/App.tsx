import {StatusBar} from 'expo-status-bar';
import {
  sessionIntensities,
  sessionModes,
  type SessionIntensity,
  type SessionMode,
} from '@kinetiq/session-client';
import {useState} from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';

export default function App() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [intensity, setIntensity] = useState<SessionIntensity>('PLANNED');

  return (
    <View style={styles.screen}>
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

        <FocusableButton label="Start prepared session" preferred />
      </View>
    </View>
  );
}

function Choice({label, selected, onPress}: {label: string; selected: boolean; onPress: () => void}) {
  return <FocusableButton label={label} selected={selected} onPress={onPress} />;
}

function FocusableButton({
  label,
  selected = false,
  preferred = false,
  onPress,
}: {
  label: string;
  selected?: boolean;
  preferred?: boolean;
  onPress?: () => void;
}) {
  const [focused, setFocused] = useState(false);

  return (
    <Pressable
      accessibilityRole="button"
      hasTVPreferredFocus={preferred}
      onBlur={() => setFocused(false)}
      onFocus={() => setFocused(true)}
      onPress={onPress}
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
  panel: {width: 650, justifyContent: 'center', gap: 20},
  label: {color: '#9CA3AF', fontSize: 16, fontWeight: '700', letterSpacing: 2, marginTop: 12},
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
