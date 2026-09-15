"use client";

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
} from "@kinetiq/session-client";
import { useCallback, useEffect, useState } from "react";

const endpoint = "/api/graphql";

const equipmentOptions = [
  { id: "NONE", label: "No equipment" },
  { id: "MAT", label: "Yoga / floor mat" },
  { id: "RESISTANCE_BANDS", label: "Resistance bands" },
  { id: "PULL_UP_BAR", label: "Pull-up bar" },
];

const spaceOptions = [
  { id: "LIVING_ROOM", label: "Living room" },
  { id: "BEDROOM", label: "Bedroom" },
  { id: "GARAGE", label: "Garage" },
  { id: "HOME_GYM", label: "Home gym" },
];

export function OnboardingCard() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [activeGoal, setActiveGoal] = useState<Goal | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Form fields
  const [goalDescription, setGoalDescription] = useState("Build consistency with home bodyweight movement");
  const [goalTarget, setGoalTarget] = useState(3);
  const [experience, setExperience] = useState<ExperienceLevel>("RETURNING");
  const [daysPerWeek, setDaysPerWeek] = useState(3);
  const [sessionMinutes, setSessionMinutes] = useState(15);
  const [selectedEquipment, setSelectedEquipment] = useState<string[]>(["NONE"]);
  const [selectedSpace, setSelectedSpace] = useState("LIVING_ROOM");
  const [selectedTone, setSelectedTone] = useState<CoachingTone>("CALM");

  const applyData = useCallback((prof: Profile | null, goal: Goal | null) => {
    if (prof) {
      setProfile(prof);
      setExperience(prof.experienceLevel);
      setDaysPerWeek(prof.availabilityDaysPerWeek);
      setSessionMinutes(prof.targetSessionMinutes);
      setSelectedEquipment(prof.availableEquipment.length ? prof.availableEquipment : ["NONE"]);
      setSelectedSpace(prof.workoutSpace || "LIVING_ROOM");
      setSelectedTone(prof.coachingTone || "CALM");
    }
    if (goal) {
      setActiveGoal(goal);
      setGoalDescription(goal.description);
      setGoalTarget(goal.target ?? 3);
    } else {
      setEditing(true);
    }
  }, []);

  const reload = useCallback(() => {
    setLoading(true);
    setErrorMessage(null);
    Promise.all([fetchProfile(endpoint), fetchActiveGoal(endpoint)])
      .then(([profileRes, goalRes]) => {
        if (profileRes.errors.length && profileRes.errors[0].code !== "AUTHENTICATION_REQUIRED") {
          setErrorMessage(profileRes.errors[0].message);
        } else {
          applyData(profileRes.profile, goalRes.goal);
        }
        setLoading(false);
      })
      .catch(() => {
        setErrorMessage("Could not connect to the training service. Check your connection and retry.");
        setLoading(false);
      });
  }, [applyData]);

  useEffect(() => {
    let active = true;
    Promise.all([fetchProfile(endpoint), fetchActiveGoal(endpoint)])
      .then(([profileRes, goalRes]) => {
        if (!active) return;
        if (profileRes.errors.length && profileRes.errors[0].code !== "AUTHENTICATION_REQUIRED") {
          setErrorMessage(profileRes.errors[0].message);
        } else {
          applyData(profileRes.profile, goalRes.goal);
        }
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        setErrorMessage("Could not connect to the training service. Check your connection and retry.");
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [applyData]);

  function toggleEquipment(id: string) {
    if (id === "NONE") {
      setSelectedEquipment(["NONE"]);
      return;
    }
    const filtered = selectedEquipment.filter((item) => item !== "NONE");
    if (filtered.includes(id)) {
      const remaining = filtered.filter((item) => item !== id);
      setSelectedEquipment(remaining.length ? remaining : ["NONE"]);
    } else {
      setSelectedEquipment([...filtered, id]);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErrorMessage(null);

    try {
      // 1. Save profile
      const profRes = await updateProfile(endpoint, {
        experienceLevel: experience,
        availabilityDaysPerWeek: daysPerWeek,
        targetSessionMinutes: sessionMinutes,
        availableEquipment: selectedEquipment,
        workoutSpace: selectedSpace,
        coachingTone: selectedTone,
      });

      if (profRes.errors.length) {
        setErrorMessage(profRes.errors[0].message);
        setSaving(false);
        return;
      }

      // 2. Save goal revision
      const goalRes = await setGoal(endpoint, {
        description: goalDescription,
        measure: "weekly_completed_sessions",
        baseline: 0,
        target: goalTarget,
        unit: "sessions/week",
      });

      if (goalRes.errors.length) {
        setErrorMessage(goalRes.errors[0].message);
        setSaving(false);
        return;
      }

      if (profRes.profile) setProfile(profRes.profile);
      if (goalRes.goal) setActiveGoal(goalRes.goal);
      setEditing(false);
    } catch {
      setErrorMessage("Failed to persist training context. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 shadow-xl backdrop-blur-md animate-pulse">
        <div className="h-4 w-32 rounded bg-white/10" />
        <div className="mt-3 h-8 w-64 rounded bg-white/10" />
        <div className="mt-4 h-16 w-full rounded bg-white/5" />
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-6 shadow-xl backdrop-blur-md">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-[var(--accent)] shadow-[0_0_8px_var(--accent)]" />
          <h2 className="text-xs font-semibold tracking-wider uppercase text-[var(--accent)]">
            Athlete Context & Onboarding
          </h2>
        </div>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/80 transition hover:bg-white/10 hover:text-white"
          >
            Edit Context
          </button>
        )}
      </div>

      {errorMessage && (
        <div className="mt-4 flex items-center justify-between rounded-xl border border-red-500/30 bg-red-950/40 p-3.5 text-xs text-red-200">
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={reload}
            className="ml-3 font-semibold underline hover:text-white"
          >
            Retry
          </button>
        </div>
      )}

      {!editing ? (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-xl font-semibold text-white">
              {activeGoal ? activeGoal.description : "No goal configured"}
            </span>
            {activeGoal?.target && (
              <span className="rounded-full border border-[var(--accent)]/30 bg-[var(--accent)]/10 px-2.5 py-0.5 text-xs font-medium text-[var(--accent)]">
                {activeGoal.target} sessions / week (rev {activeGoal.revision})
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs text-[var(--muted)] sm:grid-cols-4">
            <div className="rounded-xl border border-white/5 bg-black/20 p-3">
              <span className="block text-white/40 uppercase tracking-wider text-[10px]">Experience</span>
              <span className="mt-1 font-medium text-white">{profile?.experienceLevel ?? "RETURNING"}</span>
            </div>
            <div className="rounded-xl border border-white/5 bg-black/20 p-3">
              <span className="block text-white/40 uppercase tracking-wider text-[10px]">Schedule</span>
              <span className="mt-1 font-medium text-white">
                {profile?.availabilityDaysPerWeek ?? 3} days · {profile?.targetSessionMinutes ?? 15}m
              </span>
            </div>
            <div className="rounded-xl border border-white/5 bg-black/20 p-3">
              <span className="block text-white/40 uppercase tracking-wider text-[10px]">Equipment</span>
              <span className="mt-1 font-medium text-white">
                {profile?.availableEquipment?.join(", ") || "None"}
              </span>
            </div>
            <div className="rounded-xl border border-white/5 bg-black/20 p-3">
              <span className="block text-white/40 uppercase tracking-wider text-[10px]">Coach Tone</span>
              <span className="mt-1 font-medium text-white">{profile?.coachingTone ?? "CALM"}</span>
            </div>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSave} className="mt-4 space-y-5 text-sm">
          {/* Goal section */}
          <div>
            <label className="block text-xs font-medium text-white/70">
              Consistency Goal Description
            </label>
            <input
              type="text"
              required
              value={goalDescription}
              onChange={(e) => setGoalDescription(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/40 px-3.5 py-2 text-white placeholder-white/30 focus:border-[var(--accent)] focus:outline-none"
              placeholder="e.g. Build consistency with home bodyweight workouts"
            />
          </div>

          {/* Schedule & targets */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-white/70">
                Target Days / Week: {goalTarget}
              </label>
              <div className="mt-1.5 flex gap-1.5">
                {[2, 3, 4, 5].map((days) => (
                  <button
                    key={days}
                    type="button"
                    onClick={() => {
                      setGoalTarget(days);
                      setDaysPerWeek(days);
                    }}
                    className={`flex-1 rounded-lg border py-1.5 text-xs font-semibold transition ${
                      goalTarget === days
                        ? "border-[var(--accent)] bg-[var(--accent)] text-black"
                        : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10"
                    }`}
                  >
                    {days}d
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-white/70">
                Experience Level
              </label>
              <div className="mt-1.5 flex gap-1.5">
                {experienceLevels.map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    onClick={() => setExperience(lvl)}
                    className={`flex-1 rounded-lg border py-1.5 text-[11px] font-semibold uppercase tracking-wider transition ${
                      experience === lvl
                        ? "border-[var(--accent)] bg-[var(--accent)] text-black"
                        : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10"
                    }`}
                  >
                    {lvl.slice(0, 4)}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-white/70">
                Session Duration
              </label>
              <div className="mt-1.5 flex gap-1.5">
                {[15, 20, 30, 45].map((mins) => (
                  <button
                    key={mins}
                    type="button"
                    onClick={() => setSessionMinutes(mins)}
                    className={`flex-1 rounded-lg border py-1.5 text-xs font-semibold transition ${
                      sessionMinutes === mins
                        ? "border-[var(--accent)] bg-[var(--accent)] text-black"
                        : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10"
                    }`}
                  >
                    {mins}m
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Equipment, Space & Coaching Tone */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-white/70">
                Available Equipment
              </label>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {equipmentOptions.map((eq) => {
                  const active = selectedEquipment.includes(eq.id);
                  return (
                    <button
                      key={eq.id}
                      type="button"
                      onClick={() => toggleEquipment(eq.id)}
                      className={`rounded-lg border px-3 py-1 text-xs transition ${
                        active
                          ? "border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]"
                          : "border-white/10 bg-white/5 text-white/60 hover:bg-white/10"
                      }`}
                    >
                      {eq.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-white/70">
                Workout Space
              </label>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {spaceOptions.map((sp) => (
                  <button
                    key={sp.id}
                    type="button"
                    onClick={() => setSelectedSpace(sp.id)}
                    className={`rounded-lg border px-3 py-1 text-xs transition ${
                      selectedSpace === sp.id
                        ? "border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]"
                        : "border-white/10 bg-white/5 text-white/60 hover:bg-white/10"
                    }`}
                  >
                    {sp.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-white/70">
                Coaching Tone
              </label>
              <div className="mt-1.5 flex gap-1.5">
                {coachingTones.map((tone) => (
                  <button
                    key={tone}
                    type="button"
                    onClick={() => setSelectedTone(tone)}
                    className={`flex-1 rounded-lg border py-1.5 text-[11px] font-medium capitalize transition ${
                      selectedTone === tone
                        ? "border-[var(--accent)] bg-[var(--accent)] text-black font-semibold"
                        : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10"
                    }`}
                  >
                    {tone.toLowerCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-end gap-3 pt-2">
            {profile && activeGoal && (
              <button
                type="button"
                disabled={saving}
                onClick={() => setEditing(false)}
                className="rounded-xl border border-white/10 px-4 py-2 text-xs text-white/70 hover:bg-white/5"
              >
                Cancel
              </button>
            )}
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-[var(--accent)] px-5 py-2 text-xs font-semibold text-black transition hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Persisting Context…" : "Save Athlete Context"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
