import {
  coachingTones,
  fetchActiveGoal,
  fetchProfile,
  prepareSession,
  sessionIntensities,
  sessionModes,
  type CoachingTone,
  type Goal,
  type Profile,
  type SessionIntensity,
  type SessionMode,
} from '@kinetiq/session-client';
import {useEffect, useState} from 'react';
import {Pressable, ScrollView, StyleSheet, Switch, Text, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import {OnboardingModal} from '../features/onboarding/OnboardingModal';

const endpoint = process.env.EXPO_PUBLIC_KINETIQ_GRAPHQL_URL ?? '';
const routineId = process.env.EXPO_PUBLIC_KINETIQ_DEMO_ROUTINE_ID;

export default function HomeScreen() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [intensity, setIntensity] = useState<SessionIntensity>('PLANNED');
  const [tone, setTone] = useState<CoachingTone>('MOTIVATIONAL');
  const [photo, setPhoto] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // Athlete context & onboarding
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [athleteProfile, setAthleteProfile] = useState<Profile | null>(null);
  const [activeGoal, setActiveGoal] = useState<Goal | null>(null);

  useEffect(() => {
    if (!endpoint) return;
    Promise.all([fetchProfile(endpoint), fetchActiveGoal(endpoint)])
      .then(([pRes, gRes]) => {
        if (pRes.profile) {
          setAthleteProfile(pRes.profile);
          if (pRes.profile.coachingTone) {
            setTone(pRes.profile.coachingTone);
          }
        }
        if (gRes.goal) {
          setActiveGoal(gRes.goal);
        }
      })
      .catch(() => {});
  }, []);

  async function submit() {
    if (!endpoint || !routineId) {
      setMessage('Choose an accepted routine before preparing the session.');
      return;
    }

    setSubmitting(true);
    setMessage(null);
    const result = await prepareSession(endpoint, {
      routineId,
      routineVersion: 1,
      mode,
      intensity,
      coachingTone: tone,
      captureDeviceId: 'phone-camera',
      promptForProgressPhoto: photo,
      idempotencyKey: `phone-${Date.now()}-${Math.random()}`,
      dynamic:
        mode === 'DYNAMIC'
          ? {
              frequency: 'STANDARD',
              allowedChallengeTypes: ['HOLD_POSE', 'MIRROR_POSE', 'QUICK_REPS', 'RECOVERY'],
              scoringEnabled: true,
              narrationEnabled: true,
            }
          : undefined,
    });
    setSubmitting(false);
    setMessage(
      result.session
        ? `Session ready · revision ${result.session.revision}`
        : (result.errors[0]?.message ?? 'Session preparation failed'),
    );
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text style={styles.brand}>Kinetiq V</Text>
          <Text style={styles.status}>SESSION SETUP</Text>
        </View>

        {/* Athlete Context & Onboarding Section */}
        <View style={styles.athleteSection}>
          <View style={styles.athleteHeader}>
            <Text style={styles.athleteEyebrow}>ATHLETE CONTEXT</Text>
            <Pressable
              accessibilityRole="button"
              onPress={() => setShowOnboarding(true)}
              style={styles.athleteEditBtn}
            >
              <Text style={styles.athleteEditBtnText}>
                {activeGoal || athleteProfile ? 'Edit Context' : 'Set Up'}
              </Text>
            </Pressable>
          </View>
          <Text style={styles.athleteGoalText}>
            {activeGoal?.description ?? 'Consistency goal not configured yet'}
          </Text>
          <View style={styles.athleteMetaRow}>
            {activeGoal?.target ? (
              <View style={styles.athleteTag}>
                <Text style={styles.athleteTagText}>{activeGoal.target} sessions/wk</Text>
              </View>
            ) : null}
            {athleteProfile?.experienceLevel ? (
              <View style={styles.athleteTag}>
                <Text style={styles.athleteTagText}>{athleteProfile.experienceLevel.toLowerCase()}</Text>
              </View>
            ) : null}
            {athleteProfile?.coachingTone ? (
              <View style={styles.athleteTag}>
                <Text style={styles.athleteTagText}>coach: {athleteProfile.coachingTone.toLowerCase()}</Text>
              </View>
            ) : null}
            {athleteProfile?.targetSessionMinutes ? (
              <View style={styles.athleteTag}>
                <Text style={styles.athleteTagText}>{athleteProfile.targetSessionMinutes} min</Text>
              </View>
            ) : null}
          </View>
        </View>

        <Text style={styles.eyebrow}>ACCEPTED ROUTINE</Text>
        <Text style={styles.title}>Full body foundation</Text>
        <Text style={styles.description}>30 min · Galaxy camera · choose a display later</Text>

        <OptionGroup label="Mode" options={sessionModes} value={mode} onChange={value => setMode(value as SessionMode)} />
        <OptionGroup label="Intensity" options={sessionIntensities} value={intensity} onChange={value => setIntensity(value as SessionIntensity)} />
        <OptionGroup label="Coach" options={coachingTones} value={tone} onChange={value => setTone(value as CoachingTone)} />

        <View style={styles.toggleRow}>
          <View style={styles.toggleCopy}>
            <Text style={styles.toggleTitle}>Progress photo prompt</Text>
            <Text style={styles.optionHelp}>Ask after the session. Taking the photo remains optional.</Text>
          </View>
          <Switch onValueChange={setPhoto} trackColor={{false: '#293244', true: '#6D9F16'}} thumbColor={photo ? '#A3FF12' : '#D1D5DB'} value={photo} />
        </View>

        {message && <Text style={styles.message}>{message}</Text>}
        <Pressable accessibilityRole="button" disabled={submitting} onPress={submit} style={({pressed}) => [styles.button, pressed && styles.buttonPressed, submitting && styles.buttonDisabled]}>
          <Text style={styles.buttonText}>{submitting ? 'Preparing…' : 'Confirm and prepare'}</Text>
        </Pressable>
      </ScrollView>

      <OnboardingModal
        visible={showOnboarding}
        endpoint={endpoint}
        onClose={() => setShowOnboarding(false)}
        onSaved={(prof, goal) => {
          setAthleteProfile(prof);
          setActiveGoal(goal);
          if (prof.coachingTone) {
            setTone(prof.coachingTone);
          }
        }}
      />
    </SafeAreaView>
  );
}

function OptionGroup({label, options, value, onChange}: {label: string; options: readonly string[]; value: string; onChange: (value: string) => void}) {
  return (
    <View style={styles.optionGroup}>
      <Text style={styles.optionLabel}>{label.toUpperCase()}</Text>
      <View style={styles.optionRow}>
        {options.map(option => (
          <Pressable accessibilityRole="button" key={option} onPress={() => onChange(option)} style={[styles.option, value === option && styles.optionSelected]}>
            <Text style={[styles.optionText, value === option && styles.optionTextSelected]}>{option.toLowerCase()}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {flex: 1, backgroundColor: '#070B14'},
  content: {paddingHorizontal: 24, paddingVertical: 20, paddingBottom: 40},
  header: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24},
  brand: {color: '#F4F7FB', fontSize: 20, fontWeight: '700'},
  status: {color: '#A3FF12', fontSize: 10, fontWeight: '800', letterSpacing: 1.5},
  athleteSection: {
    backgroundColor: '#111827',
    borderColor: '#293244',
    borderRadius: 18,
    borderWidth: 1,
    padding: 16,
    marginBottom: 28,
  },
  athleteHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  athleteEyebrow: {
    color: '#A3FF12',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1.5,
  },
  athleteEditBtn: {
    backgroundColor: '#1E293B',
    borderColor: '#334155',
    borderRadius: 8,
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  athleteEditBtnText: {
    color: '#F4F7FB',
    fontSize: 12,
    fontWeight: '600',
  },
  athleteGoalText: {
    color: '#F4F7FB',
    fontSize: 15,
    fontWeight: '600',
    lineHeight: 20,
  },
  athleteMetaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 10,
  },
  athleteTag: {
    backgroundColor: '#1E293B',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  athleteTagText: {
    color: '#9CA3AF',
    fontSize: 11,
    fontWeight: '600',
  },
  eyebrow: {color: '#A3FF12', fontSize: 11, fontWeight: '800', letterSpacing: 2},
  title: {color: '#F4F7FB', fontSize: 38, fontWeight: '700', letterSpacing: -1.5, marginTop: 12},
  description: {color: '#9CA3AF', fontSize: 16, lineHeight: 24, marginTop: 12},
  optionGroup: {marginTop: 30},
  optionLabel: {color: '#9CA3AF', fontSize: 11, fontWeight: '800', letterSpacing: 1.7, marginBottom: 12},
  optionRow: {flexDirection: 'row', flexWrap: 'wrap', gap: 9},
  option: {borderColor: '#293244', borderRadius: 999, borderWidth: 1, paddingHorizontal: 16, paddingVertical: 11},
  optionSelected: {backgroundColor: '#A3FF12', borderColor: '#A3FF12'},
  optionText: {color: '#D1D5DB', fontSize: 14, fontWeight: '600', textTransform: 'capitalize'},
  optionTextSelected: {color: '#070B14'},
  toggleRow: {alignItems: 'center', borderColor: '#293244', borderRadius: 18, borderWidth: 1, flexDirection: 'row', justifyContent: 'space-between', marginTop: 30, padding: 16},
  toggleCopy: {flex: 1, paddingRight: 16},
  toggleTitle: {color: '#F4F7FB', fontSize: 15, fontWeight: '700'},
  optionHelp: {color: '#9CA3AF', fontSize: 13, lineHeight: 19, marginTop: 4},
  message: {backgroundColor: '#111827', borderRadius: 14, color: '#D1D5DB', marginTop: 20, padding: 14},
  button: {alignItems: 'center', backgroundColor: '#A3FF12', borderRadius: 18, marginTop: 24, padding: 18},
  buttonPressed: {opacity: 0.85},
  buttonDisabled: {opacity: 0.55},
  buttonText: {color: '#070B14', fontSize: 16, fontWeight: '800'},
});
