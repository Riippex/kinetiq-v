import React, {useState} from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';

type SessionMode = 'NORMAL' | 'DYNAMIC';

export default function App() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [focused, setFocused] = useState<string | null>('normal');

  return (
    <View style={styles.screen}>
      <View style={styles.copy}>
        <Text style={styles.eyebrow}>KINETIQ V · VEGA OS</Text>
        <Text style={styles.title}>Move with the room.</Text>
        <Text style={styles.description}>
          Review the prepared routine, choose the session style, and start with the remote.
        </Text>
      </View>

      <View style={styles.controls}>
        <Text style={styles.label}>SESSION MODE</Text>
        <View style={styles.row}>
          <Choice label="Focused" value="NORMAL" mode={mode} focused={focused} setMode={setMode} setFocused={setFocused} preferred />
          <Choice label="Dynamic" value="DYNAMIC" mode={mode} focused={focused} setMode={setMode} setFocused={setFocused} />
        </View>
        <TVButton label="Start prepared session" focused={focused === 'start'} onFocus={() => setFocused('start')} />
      </View>
    </View>
  );
}

function Choice({label, value, mode, focused, setMode, setFocused, preferred = false}: {
  label: string;
  value: SessionMode;
  mode: SessionMode;
  focused: string | null;
  setMode: (mode: SessionMode) => void;
  setFocused: (value: string) => void;
  preferred?: boolean;
}) {
  return (
    <TVButton
      label={label}
      selected={mode === value}
      focused={focused === value.toLowerCase()}
      preferred={preferred}
      onFocus={() => setFocused(value.toLowerCase())}
      onPress={() => setMode(value)}
    />
  );
}

function TVButton({label, selected = false, focused, preferred = false, onFocus, onPress}: {
  label: string;
  selected?: boolean;
  focused: boolean;
  preferred?: boolean;
  onFocus: () => void;
  onPress?: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      hasTVPreferredFocus={preferred}
      onFocus={onFocus}
      onPress={onPress}
      style={[styles.button, selected && styles.selected, focused && styles.focused]}>
      <Text style={[styles.buttonText, focused && styles.focusedText]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: {flex: 1, flexDirection: 'row', backgroundColor: '#070B14', padding: 72, gap: 72},
  copy: {flex: 1, justifyContent: 'center'},
  eyebrow: {color: '#A3FF12', fontSize: 18, fontWeight: '800', letterSpacing: 3},
  title: {color: '#F4F7FB', fontSize: 64, fontWeight: '700', marginTop: 20},
  description: {color: '#9CA3AF', fontSize: 24, lineHeight: 34, marginTop: 24, maxWidth: 720},
  controls: {width: 620, justifyContent: 'center', gap: 24},
  label: {color: '#9CA3AF', fontSize: 16, fontWeight: '700', letterSpacing: 2},
  row: {flexDirection: 'row', gap: 16},
  button: {minHeight: 68, minWidth: 180, alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: '#293244', borderRadius: 14, backgroundColor: '#111827', paddingHorizontal: 28},
  selected: {borderColor: '#A3FF12'},
  focused: {backgroundColor: '#A3FF12', borderColor: '#F4F7FB', transform: [{scale: 1.05}]},
  buttonText: {color: '#F4F7FB', fontSize: 20, fontWeight: '700'},
  focusedText: {color: '#070B14'},
});
