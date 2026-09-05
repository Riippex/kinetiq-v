import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export default function HomeScreen() {
  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.header}>
        <Text style={styles.brand}>Kinetiq V</Text>
        <View style={styles.status}>
          <Text style={styles.statusText}>FOUNDATION</Text>
        </View>
      </View>

      <View style={styles.content}>
        <Text style={styles.eyebrow}>MOVE · PLAY · PROGRESS</Text>
        <Text style={styles.title}>Ready when you are.</Text>
        <Text style={styles.description}>
          Your phone coordinates the camera, session settings and progress capture.
        </Text>
      </View>

      <Pressable accessibilityRole="button" style={styles.button}>
        <Text style={styles.buttonText}>Prepare a session</Text>
      </Pressable>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#070B14', paddingHorizontal: 24, paddingVertical: 16 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brand: { color: '#F4F7FB', fontSize: 20, fontWeight: '700' },
  status: { borderColor: '#293244', borderRadius: 999, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 5 },
  statusText: { color: '#9CA3AF', fontSize: 10, fontWeight: '700', letterSpacing: 1.2 },
  content: { flex: 1, justifyContent: 'center' },
  eyebrow: { color: '#A3FF12', fontSize: 12, fontWeight: '800', letterSpacing: 2 },
  title: { color: '#F4F7FB', fontSize: 52, fontWeight: '700', letterSpacing: -2, lineHeight: 54, marginTop: 16 },
  description: { color: '#9CA3AF', fontSize: 17, lineHeight: 26, marginTop: 20 },
  button: { alignItems: 'center', backgroundColor: '#A3FF12', borderRadius: 18, padding: 18 },
  buttonText: { color: '#070B14', fontSize: 16, fontWeight: '800' },
});
