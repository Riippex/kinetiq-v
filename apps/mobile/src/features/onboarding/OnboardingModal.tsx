import {
  coachingTones,
  experienceLevels,
  fetchActiveGoal,
  fetchProfile,
  setGoal,
  updateProfile,
  type CoachingTone,
  type ExperienceLevel,
  type Goal,
  type Profile,
} from '@kinetiq/session-client';
import {useCallback, useEffect, useState} from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';

interface OnboardingModalProps {
  visible: boolean;
  endpoint: string;
  onClose: () => void;
  onSaved?: (profile: Profile, goal: Goal) => void;
}

const equipmentList = [
  {id: 'NONE', label: 'No equipment'},
  {id: 'MAT', label: 'Mat'},
  {id: 'RESISTANCE_BANDS', label: 'Bands'},
  {id: 'PULL_UP_BAR', label: 'Pull-up bar'},
];

const spaceList = [
  {id: 'LIVING_ROOM', label: 'Living Room'},
  {id: 'BEDROOM', label: 'Bedroom'},
  {id: 'GARAGE', label: 'Garage'},
  {id: 'HOME_GYM', label: 'Home Gym'},
];

export function OnboardingModal({visible, endpoint, onClose, onSaved}: OnboardingModalProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Profile fields
  const [experience, setExperience] = useState<ExperienceLevel>('RETURNING');
  const [daysPerWeek, setDaysPerWeek] = useState(3);
  const [sessionMinutes, setSessionMinutes] = useState(15);
  const [equipment, setEquipment] = useState<string[]>(['NONE']);
  const [space, setSpace] = useState('LIVING_ROOM');
  const [tone, setTone] = useState<CoachingTone>('CALM');

  // Goal fields
  const [goalDescription, setGoalDescription] = useState('Build consistency with home bodyweight movement');
  const [goalTarget, setGoalTarget] = useState(3);

  const applyData = useCallback((profile: Profile | null, goal: Goal | null) => {
    if (profile) {
      setExperience(profile.experienceLevel);
      setDaysPerWeek(profile.availabilityDaysPerWeek);
      setSessionMinutes(profile.targetSessionMinutes);
      setEquipment(
        profile.availableEquipment.length
          ? profile.availableEquipment
          : ['NONE'],
      );
      setSpace(profile.workoutSpace || 'LIVING_ROOM');
      setTone(profile.coachingTone || 'CALM');
    }
    if (goal) {
      setGoalDescription(goal.description);
      setGoalTarget(goal.target ?? 3);
    }
  }, []);

  const reload = useCallback(() => {
    if (!endpoint) return;
    setLoading(true);
    setErrorMessage(null);
    Promise.all([fetchProfile(endpoint), fetchActiveGoal(endpoint)])
      .then(([profileRes, goalRes]) => {
        if (profileRes.errors.length && profileRes.errors[0].code !== 'AUTHENTICATION_REQUIRED') {
          setErrorMessage(profileRes.errors[0].message);
        } else {
          applyData(profileRes.profile, goalRes.goal);
        }
        setLoading(false);
      })
      .catch(() => {
        setErrorMessage('Could not connect to service. Check network and retry.');
        setLoading(false);
      });
  }, [endpoint, applyData]);

  useEffect(() => {
    if (!visible || !endpoint) return;
    let active = true;

    Promise.all([fetchProfile(endpoint), fetchActiveGoal(endpoint)])
      .then(([profileRes, goalRes]) => {
        if (!active) return;
        if (profileRes.errors.length && profileRes.errors[0].code !== 'AUTHENTICATION_REQUIRED') {
          setErrorMessage(profileRes.errors[0].message);
        } else {
          applyData(profileRes.profile, goalRes.goal);
        }
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        setErrorMessage('Could not connect to service. Check network and retry.');
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [visible, endpoint, applyData]);

  function toggleEquipment(id: string) {
    if (id === 'NONE') {
      setEquipment(['NONE']);
      return;
    }
    const filtered = equipment.filter(item => item !== 'NONE');
    if (filtered.includes(id)) {
      const remaining = filtered.filter(item => item !== id);
      setEquipment(remaining.length ? remaining : ['NONE']);
    } else {
      setEquipment([...filtered, id]);
    }
  }

  async function handleSave() {
    setSaving(true);
    setErrorMessage(null);
    try {
      const profRes = await updateProfile(endpoint, {
        experienceLevel: experience,
        availabilityDaysPerWeek: daysPerWeek,
        targetSessionMinutes: sessionMinutes,
        availableEquipment: equipment,
        workoutSpace: space,
        coachingTone: tone,
      });

      if (profRes.errors.length) {
        setErrorMessage(profRes.errors[0].message);
        setSaving(false);
        return;
      }

      const goalRes = await setGoal(endpoint, {
        description: goalDescription,
        measure: 'weekly_completed_sessions',
        baseline: 0,
        target: goalTarget,
        unit: 'sessions/week',
      });

      if (goalRes.errors.length) {
        setErrorMessage(goalRes.errors[0].message);
        setSaving(false);
        return;
      }

      if (profRes.profile && goalRes.goal) {
        onSaved?.(profRes.profile, goalRes.goal);
      }
      onClose();
    } catch {
      setErrorMessage('Failed to persist training context. Please retry.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <View>
            <Text style={styles.headerEyebrow}>ATHLETE ONBOARDING</Text>
            <Text style={styles.headerTitle}>Training Context</Text>
          </View>
          <Pressable accessibilityRole="button" onPress={onClose} style={styles.closeBtn}>
            <Text style={styles.closeBtnText}>Done</Text>
          </Pressable>
        </View>

        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#A3FF12" />
            <Text style={styles.loadingText}>Loading training context…</Text>
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.scrollContent}>
            {errorMessage && (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>{errorMessage}</Text>
                <Pressable accessibilityRole="button" onPress={reload} style={styles.retryBtn}>
                  <Text style={styles.retryBtnText}>Retry</Text>
                </Pressable>
              </View>
            )}

            {/* Goal Description */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>CONSISTENCY GOAL</Text>
              <TextInput
                style={styles.textInput}
                value={goalDescription}
                onChangeText={setGoalDescription}
                placeholder="e.g. Build consistency with home bodyweight movement"
                placeholderTextColor="#6B7280"
              />
            </View>

            {/* Sessions / Week Target */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>TARGET SESSIONS PER WEEK: {goalTarget}</Text>
              <View style={styles.chipRow}>
                {[1, 2, 3, 4, 5, 6].map(num => (
                  <Pressable
                    accessibilityRole="button"
                    key={num}
                    onPress={() => setGoalTarget(num)}
                    style={[styles.chip, goalTarget === num && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, goalTarget === num && styles.chipTextActive]}>
                      {num} {num === 1 ? 'day' : 'days'}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {/* Experience Level */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>EXPERIENCE LEVEL</Text>
              <View style={styles.chipRow}>
                {experienceLevels.map(lvl => (
                  <Pressable
                    accessibilityRole="button"
                    key={lvl}
                    onPress={() => setExperience(lvl)}
                    style={[styles.chip, experience === lvl && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, experience === lvl && styles.chipTextActive]}>
                      {lvl.toLowerCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {/* Session Duration */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>TARGET SESSION DURATION: {sessionMinutes} MIN</Text>
              <View style={styles.chipRow}>
                {[10, 15, 20, 30, 45].map(mins => (
                  <Pressable
                    accessibilityRole="button"
                    key={mins}
                    onPress={() => setSessionMinutes(mins)}
                    style={[styles.chip, sessionMinutes === mins && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, sessionMinutes === mins && styles.chipTextActive]}>
                      {mins}m
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {/* Available Equipment */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>AVAILABLE EQUIPMENT</Text>
              <View style={styles.chipRow}>
                {equipmentList.map(item => {
                  const selected = equipment.includes(item.id);
                  return (
                    <Pressable
                      accessibilityRole="button"
                      key={item.id}
                      onPress={() => toggleEquipment(item.id)}
                      style={[styles.chip, selected && styles.chipActive]}
                    >
                      <Text style={[styles.chipText, selected && styles.chipTextActive]}>
                        {item.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            {/* Workout Space */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>WORKOUT SPACE</Text>
              <View style={styles.chipRow}>
                {spaceList.map(item => (
                  <Pressable
                    accessibilityRole="button"
                    key={item.id}
                    onPress={() => setSpace(item.id)}
                    style={[styles.chip, space === item.id && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, space === item.id && styles.chipTextActive]}>
                      {item.label}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {/* Coaching Tone */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>COACHING TONE</Text>
              <View style={styles.chipRow}>
                {coachingTones.map(t => (
                  <Pressable
                    accessibilityRole="button"
                    key={t}
                    onPress={() => setTone(t)}
                    style={[styles.chip, tone === t && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, tone === t && styles.chipTextActive]}>
                      {t.toLowerCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            <Pressable
              accessibilityRole="button"
              disabled={saving}
              onPress={handleSave}
              style={({pressed}) => [styles.saveBtn, pressed && styles.saveBtnPressed, saving && styles.saveBtnDisabled]}
            >
              <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save Training Context'}</Text>
            </Pressable>
          </ScrollView>
        )}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#070B14'},
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1F2937',
  },
  headerEyebrow: {color: '#A3FF12', fontSize: 10, fontWeight: '800', letterSpacing: 1.5},
  headerTitle: {color: '#F4F7FB', fontSize: 20, fontWeight: '700', marginTop: 2},
  closeBtn: {padding: 8},
  closeBtnText: {color: '#9CA3AF', fontSize: 15, fontWeight: '600'},
  loadingContainer: {flex: 1, justifyContent: 'center', alignItems: 'center', gap: 12},
  loadingText: {color: '#9CA3AF', fontSize: 14},
  scrollContent: {paddingHorizontal: 20, paddingVertical: 20, paddingBottom: 50},
  errorBox: {
    backgroundColor: '#451A1A',
    borderColor: '#7F1D1D',
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 20,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  errorText: {color: '#FCA5A5', fontSize: 13, flex: 1},
  retryBtn: {paddingLeft: 12},
  retryBtnText: {color: '#FFFFFF', fontWeight: '700', fontSize: 13, textDecorationLine: 'underline'},
  section: {marginBottom: 24},
  sectionLabel: {color: '#9CA3AF', fontSize: 11, fontWeight: '800', letterSpacing: 1.5, marginBottom: 10},
  textInput: {
    backgroundColor: '#111827',
    borderColor: '#293244',
    borderWidth: 1,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: '#F4F7FB',
    fontSize: 15,
  },
  chipRow: {flexDirection: 'row', flexWrap: 'wrap', gap: 8},
  chip: {
    borderColor: '#293244',
    borderRadius: 999,
    borderWidth: 1,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  chipActive: {backgroundColor: '#A3FF12', borderColor: '#A3FF12'},
  chipText: {color: '#D1D5DB', fontSize: 13, fontWeight: '600', textTransform: 'capitalize'},
  chipTextActive: {color: '#070B14'},
  saveBtn: {
    backgroundColor: '#A3FF12',
    borderRadius: 16,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 16,
  },
  saveBtnPressed: {opacity: 0.85},
  saveBtnDisabled: {opacity: 0.55},
  saveBtnText: {color: '#070B14', fontSize: 16, fontWeight: '800'},
});
