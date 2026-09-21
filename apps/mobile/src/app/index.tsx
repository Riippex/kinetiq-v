import {
  acceptRoutine,
  coachingTones,
  fetchActiveGoal,
  fetchCurrentRoutine,
  fetchProfile,
  isUnsupportedLimitationError,
  pairDisplayDevice,
  prepareSession,
  proposeRoutine,
  sessionIntensities,
  sessionModes,
  type CoachingTone,
  type Goal,
  type PreparedSession,
  type Profile,
  type Routine,
  type SessionIntensity,
  type SessionMode,
} from '@kinetiq/session-client';
import {useEffect, useState} from 'react';
import {Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import {OnboardingModal} from '../features/onboarding/OnboardingModal';

const endpoint = process.env.EXPO_PUBLIC_KINETIQ_GRAPHQL_URL ?? '';
const defaultRoutineId = process.env.EXPO_PUBLIC_KINETIQ_DEMO_ROUTINE_ID;

export default function HomeScreen() {
  const [mode, setMode] = useState<SessionMode>('NORMAL');
  const [intensity, setIntensity] = useState<SessionIntensity>('PLANNED');
  const [tone, setTone] = useState<CoachingTone>('MOTIVATIONAL');
  const [photo, setPhoto] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [unsupportedLimitation, setUnsupportedLimitation] = useState(false);

  // Athlete context & onboarding
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [athleteProfile, setAthleteProfile] = useState<Profile | null>(null);
  const [activeGoal, setActiveGoal] = useState<Goal | null>(null);

  // Routine flow
  const [currentRoutine, setCurrentRoutine] = useState<Routine | null>(null);
  const [routineLoading, setRoutineLoading] = useState(false);

  // Display pairing: only possible once a real, owned session exists.
  const [preparedSession, setPreparedSession] = useState<PreparedSession | null>(null);
  const [pairingCodeInput, setPairingCodeInput] = useState('');
  const [pairingMessage, setPairingMessage] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);

  useEffect(() => {
    if (!endpoint) return;
    Promise.all([fetchProfile(endpoint), fetchActiveGoal(endpoint), fetchCurrentRoutine(endpoint)])
      .then(([pRes, gRes, rRes]) => {
        if (pRes.profile) {
          setAthleteProfile(pRes.profile);
          if (pRes.profile.coachingTone) {
            setTone(pRes.profile.coachingTone);
          }
        }
        if (gRes.goal) {
          setActiveGoal(gRes.goal);
        }
        if (rRes.routine) {
          setCurrentRoutine(rRes.routine);
        }
      })
      .catch(() => {});
  }, []);

  async function handleProposeRoutine() {
    if (!endpoint) return;
    setRoutineLoading(true);
    setMessage(null);
    setUnsupportedLimitation(false);
    try {
      const res = await proposeRoutine(endpoint);
      if (res.errors.length) {
        setMessage(res.errors[0].message);
        setUnsupportedLimitation(isUnsupportedLimitationError(res.errors));
      } else if (res.routine) {
        setCurrentRoutine(res.routine);
      }
    } catch {
      setMessage('Failed to propose routine.');
    } finally {
      setRoutineLoading(false);
    }
  }

  async function handleAcceptRoutine() {
    if (!endpoint || !currentRoutine) return;
    setRoutineLoading(true);
    setMessage(null);
    setUnsupportedLimitation(false);
    try {
      const res = await acceptRoutine(endpoint, currentRoutine.id, currentRoutine.version);
      if (res.errors.length) {
        setMessage(res.errors[0].message);
      } else if (res.routine) {
        setCurrentRoutine(res.routine);
      }
    } catch {
      setMessage('Failed to accept routine.');
    } finally {
      setRoutineLoading(false);
    }
  }

  async function submit() {
    const effectiveRoutineId = currentRoutine?.id ?? defaultRoutineId;
    const effectiveRoutineVersion = currentRoutine?.version ?? 1;

    if (!endpoint || !effectiveRoutineId) {
      setMessage('Choose an accepted routine before preparing the session.');
      return;
    }
    if (currentRoutine && !currentRoutine.accepted) {
      setMessage('Routine must be accepted before session preparation.');
      return;
    }

    setSubmitting(true);
    setMessage(null);
    setUnsupportedLimitation(false);
    const result = await prepareSession(endpoint, {
      routineId: effectiveRoutineId,
      routineVersion: effectiveRoutineVersion,
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
    setPreparedSession(result.session ?? null);
    setPairingMessage(null);
  }

  async function handlePairDisplay() {
    if (!endpoint || !preparedSession || !pairingCodeInput.trim()) {
      return;
    }
    setPairing(true);
    setPairingMessage(null);
    try {
      const res = await pairDisplayDevice(
        endpoint,
        pairingCodeInput.trim().toUpperCase(),
        preparedSession.id,
      );
      if (res.errors.length) {
        setPairingMessage(res.errors[0].message);
      } else if (res.state) {
        const displayName = res.state.deviceType === 'FIRE_TV' ? 'Fire TV' : 'Vega';
        setPairingMessage(`Paired with your ${displayName} display.`);
      }
    } catch {
      setPairingMessage('Could not reach the backend. Check your connection and try again.');
    } finally {
      setPairing(false);
    }
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

        {/* Prescribed Routine Section */}
        <View style={styles.routineSection}>
          <View style={styles.athleteHeader}>
            <Text style={styles.athleteEyebrow}>PRESCRIBED ROUTINE</Text>
            {currentRoutine ? (
              <View
                style={[
                  styles.routineBadge,
                  currentRoutine.accepted ? styles.routineBadgeAccepted : styles.routineBadgeDraft,
                ]}
              >
                <Text
                  style={[
                    styles.routineBadgeText,
                    currentRoutine.accepted
                      ? styles.routineBadgeTextAccepted
                      : styles.routineBadgeTextDraft,
                  ]}
                >
                  {currentRoutine.accepted
                    ? `ACCEPTED · V${currentRoutine.version}`
                    : `DRAFT · V${currentRoutine.version}`}
                </Text>
              </View>
            ) : null}
          </View>

          {currentRoutine ? (
            <>
              <Text style={styles.title}>{currentRoutine.title}</Text>
              <View style={styles.rationaleBox}>
                <Text style={styles.rationaleLabel}>COACH RATIONALE</Text>
                <Text style={styles.routineRationale}>{currentRoutine.rationale}</Text>
              </View>

              <View style={styles.exerciseList}>
                {currentRoutine.items.map((item) => (
                  <View key={item.order} style={styles.exerciseRow}>
                    <Text style={styles.exerciseName}>
                      {item.order}. {item.exercise.name}
                    </Text>
                    <Text style={styles.exercisePrescription}>
                      {item.sets} sets
                      {item.repetitions ? ` × ${item.repetitions} reps` : ` · ${item.durationSeconds ?? 30}s`}
                    </Text>
                  </View>
                ))}
              </View>

              {!currentRoutine.accepted ? (
                <Pressable
                  accessibilityRole="button"
                  disabled={routineLoading}
                  onPress={handleAcceptRoutine}
                  style={({ pressed }) => [
                    styles.acceptButton,
                    pressed && styles.buttonPressed,
                    routineLoading && styles.buttonDisabled,
                  ]}
                >
                  <Text style={styles.acceptButtonText}>
                    {routineLoading ? 'Accepting…' : `Accept Routine (v${currentRoutine.version})`}
                  </Text>
                </Pressable>
              ) : null}
            </>
          ) : (
            <View style={styles.emptyRoutineBox}>
              <Text style={styles.emptyRoutineText}>
                No routine proposed yet. Generate an explained routine based on your athlete profile.
              </Text>
              <Pressable
                accessibilityRole="button"
                disabled={routineLoading}
                onPress={handleProposeRoutine}
                style={({ pressed }) => [
                  styles.proposeButton,
                  pressed && styles.buttonPressed,
                  routineLoading && styles.buttonDisabled,
                ]}
              >
                <Text style={styles.proposeButtonText}>
                  {routineLoading ? 'Proposing…' : 'Propose Routine'}
                </Text>
              </Pressable>
            </View>
          )}
        </View>

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

        {message && unsupportedLimitation && (
          <View style={styles.limitationBox}>
            <Text style={styles.limitationLabel}>LIMITATION NOT YET SUPPORTED</Text>
            <Text style={styles.limitationText}>{message}</Text>
          </View>
        )}
        {message && !unsupportedLimitation && <Text style={styles.message}>{message}</Text>}
        {currentRoutine && !currentRoutine.accepted && (
          <Text style={styles.routineWarningText}>
            ⚠️ You must accept the routine above before preparing a workout session.
          </Text>
        )}
        <Pressable
          accessibilityRole="button"
          disabled={submitting || (currentRoutine !== null && !currentRoutine.accepted)}
          onPress={submit}
          style={({pressed}) => [
            styles.button,
            pressed && styles.buttonPressed,
            (submitting || (currentRoutine !== null && !currentRoutine.accepted)) && styles.buttonDisabled,
          ]}
        >
          <Text style={styles.buttonText}>
            {submitting
              ? 'Preparing…'
              : currentRoutine && !currentRoutine.accepted
                ? 'Accept routine first'
                : 'Confirm and prepare'}
          </Text>
        </Pressable>

        {preparedSession ? (
          <View style={styles.pairingSection} testID="pairing-section">
            <Text style={styles.athleteEyebrow}>PAIR A DISPLAY</Text>
            <Text style={styles.optionHelp}>
              Enter the code shown on your Fire TV or Vega display to mirror this session.
            </Text>
            <TextInput
              accessibilityLabel="Display pairing code"
              autoCapitalize="characters"
              autoCorrect={false}
              onChangeText={setPairingCodeInput}
              placeholder="e.g. FIRE-A1B2C3"
              placeholderTextColor="#6B7280"
              style={styles.pairingInput}
              testID="pairing-code-input"
              value={pairingCodeInput}
            />
            <Pressable
              accessibilityRole="button"
              disabled={pairing || !pairingCodeInput.trim()}
              onPress={handlePairDisplay}
              style={({pressed}) => [
                styles.pairButton,
                pressed && styles.buttonPressed,
                (pairing || !pairingCodeInput.trim()) && styles.buttonDisabled,
              ]}
              testID="pair-display-button"
            >
              <Text style={styles.pairButtonText}>{pairing ? 'Pairing…' : 'Pair Display'}</Text>
            </Pressable>
            {pairingMessage ? (
              <Text style={styles.pairingMessage} testID="pairing-message">
                {pairingMessage}
              </Text>
            ) : null}
          </View>
        ) : null}
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
  limitationBox: {
    backgroundColor: 'rgba(245, 158, 11, 0.12)',
    borderColor: 'rgba(245, 158, 11, 0.4)',
    borderWidth: 1,
    borderRadius: 14,
    marginTop: 20,
    padding: 14,
  },
  limitationLabel: {color: '#FBBF24', fontSize: 10, fontWeight: '800', letterSpacing: 1.2},
  limitationText: {color: '#FDE68A', fontSize: 13, lineHeight: 18, marginTop: 6},
  routineSection: {
    backgroundColor: '#111827',
    borderColor: '#293244',
    borderRadius: 18,
    borderWidth: 1,
    padding: 16,
    marginBottom: 28,
  },
  routineBadge: {
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  routineBadgeAccepted: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    borderColor: 'rgba(16, 185, 129, 0.4)',
    borderWidth: 1,
  },
  routineBadgeDraft: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderColor: 'rgba(245, 158, 11, 0.4)',
    borderWidth: 1,
  },
  routineBadgeText: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1.2,
  },
  routineBadgeTextAccepted: {
    color: '#34D399',
  },
  routineBadgeTextDraft: {
    color: '#FBBF24',
  },
  rationaleBox: {
    backgroundColor: 'rgba(0, 0, 0, 0.3)',
    borderColor: '#1E293B',
    borderRadius: 12,
    borderWidth: 1,
    marginTop: 12,
    padding: 12,
  },
  rationaleLabel: {
    color: '#A3FF12',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1.2,
    marginBottom: 4,
  },
  routineRationale: {
    color: '#D1D5DB',
    fontSize: 13,
    lineHeight: 18,
  },
  exerciseList: {
    backgroundColor: 'rgba(0, 0, 0, 0.2)',
    borderColor: '#1E293B',
    borderRadius: 12,
    borderWidth: 1,
    marginTop: 14,
    padding: 8,
  },
  exerciseRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 8,
    paddingVertical: 8,
  },
  exerciseName: {
    color: '#F4F7FB',
    fontSize: 13,
    fontWeight: '600',
  },
  exercisePrescription: {
    color: '#9CA3AF',
    fontSize: 12,
    fontWeight: '500',
  },
  acceptButton: {
    alignItems: 'center',
    backgroundColor: '#34D399',
    borderRadius: 12,
    marginTop: 14,
    padding: 12,
  },
  acceptButtonText: {
    color: '#070B14',
    fontSize: 14,
    fontWeight: '800',
  },
  emptyRoutineBox: {
    alignItems: 'center',
    marginTop: 12,
    padding: 12,
  },
  emptyRoutineText: {
    color: '#9CA3AF',
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 12,
  },
  proposeButton: {
    alignItems: 'center',
    backgroundColor: '#A3FF12',
    borderRadius: 12,
    paddingHorizontal: 18,
    paddingVertical: 10,
  },
  proposeButtonText: {
    color: '#070B14',
    fontSize: 13,
    fontWeight: '800',
  },
  routineWarningText: {
    color: '#FBBF24',
    fontSize: 12,
    marginTop: 12,
    textAlign: 'center',
  },
  button: {alignItems: 'center', backgroundColor: '#A3FF12', borderRadius: 18, marginTop: 24, padding: 18},
  buttonPressed: {opacity: 0.85},
  buttonDisabled: {opacity: 0.55},
  buttonText: {color: '#070B14', fontSize: 16, fontWeight: '800'},
  pairingSection: {
    backgroundColor: '#111827',
    borderColor: '#293244',
    borderRadius: 18,
    borderWidth: 1,
    marginTop: 24,
    padding: 16,
  },
  pairingInput: {
    backgroundColor: '#0B0F1A',
    borderColor: '#293244',
    borderRadius: 12,
    borderWidth: 1,
    color: '#F4F7FB',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 1,
    marginTop: 12,
    padding: 12,
  },
  pairButton: {
    alignItems: 'center',
    backgroundColor: '#A3FF12',
    borderRadius: 12,
    marginTop: 12,
    padding: 12,
  },
  pairButtonText: {color: '#070B14', fontSize: 14, fontWeight: '800'},
  pairingMessage: {color: '#D1D5DB', fontSize: 13, marginTop: 10},
});
