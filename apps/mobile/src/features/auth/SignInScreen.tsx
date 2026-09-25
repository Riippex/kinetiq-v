import {ActivityIndicator, Image, Pressable, StyleSheet, Text, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import {useAuth} from './AuthProvider';

export function SignInScreen() {
  const {error, signIn, status} = useAuth();
  const loading = status === 'loading';

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.glow} />
      <View style={styles.content}>
        <Image
          accessibilityIgnoresInvertColors
          source={require('../../../assets/images/brand-mark.png')}
          style={styles.logo}
        />
        <Text style={styles.eyebrow}>YOUR MOVEMENT. YOUR MOMENTUM.</Text>
        <Text style={styles.title}>Train with a coach that sees your progress.</Text>
        <Text style={styles.body}>
          Sign in to continue your routines, sessions, Vision tracking, and Alexa follow-ups.
        </Text>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Pressable
          accessibilityRole="button"
          disabled={loading}
          onPress={() => void signIn()}
          style={({pressed}) => [
            styles.button,
            pressed && styles.buttonPressed,
            loading && styles.buttonDisabled,
          ]}
        >
          {loading ? (
            <ActivityIndicator color="#070B14" />
          ) : (
            <Text style={styles.buttonText}>Continue with Kinetiq V</Text>
          )}
        </Pressable>
        <Text style={styles.footnote}>Secure sign-in powered by Amazon Cognito.</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {backgroundColor: '#070B14', flex: 1},
  glow: {
    backgroundColor: '#164E63',
    borderRadius: 220,
    height: 360,
    opacity: 0.28,
    position: 'absolute',
    right: -180,
    top: -120,
    width: 360,
  },
  content: {flex: 1, justifyContent: 'center', paddingHorizontal: 28},
  logo: {height: 112, marginBottom: 28, resizeMode: 'contain', width: 112},
  eyebrow: {color: '#A3FF12', fontSize: 11, fontWeight: '800', letterSpacing: 1.8},
  title: {color: '#F4F7FB', fontSize: 36, fontWeight: '800', lineHeight: 42, marginTop: 12},
  body: {color: '#9CA3AF', fontSize: 16, lineHeight: 24, marginTop: 16},
  error: {color: '#FCA5A5', fontSize: 13, lineHeight: 19, marginTop: 20},
  button: {
    alignItems: 'center',
    backgroundColor: '#A3FF12',
    borderRadius: 16,
    marginTop: 32,
    minHeight: 56,
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  buttonPressed: {backgroundColor: '#B6FF45'},
  buttonDisabled: {opacity: 0.55},
  buttonText: {color: '#070B14', fontSize: 16, fontWeight: '800'},
  footnote: {color: '#64748B', fontSize: 11, marginTop: 14, textAlign: 'center'},
});
