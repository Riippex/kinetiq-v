"use client";

import {
  acceptRoutine,
  editRoutine,
  fetchCurrentRoutine,
  proposeRoutine,
  type Routine,
  type RoutineEditItemInput,
} from "@kinetiq/session-client";
import { useCallback, useEffect, useState } from "react";

const endpoint = "/api/graphql";

interface RoutinePlanningCardProps {
  onRoutineAccepted?: (routine: Routine | null) => void;
}

export function RoutinePlanningCard({ onRoutineAccepted }: RoutinePlanningCardProps) {
  const [routine, setRoutine] = useState<Routine | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editableItems, setEditableItems] = useState<RoutineEditItemInput[]>([]);
  const [routineTitle, setRoutineTitle] = useState("");

  const applyRoutine = useCallback(
    (r: Routine | null) => {
      setRoutine(r);
      if (r) {
        setRoutineTitle(r.title);
        setEditableItems(
          r.items.map((it) => ({
            exerciseId: it.exercise.id,
            order: it.order,
            sets: it.sets,
            repetitions: it.repetitions,
            durationSeconds: it.durationSeconds,
          })),
        );
        if (r.accepted) {
          onRoutineAccepted?.(r);
        }
      }
    },
    [onRoutineAccepted],
  );

  const loadRoutine = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const res = await fetchCurrentRoutine(endpoint);
      if (res.errors.length && res.errors[0].code !== "AUTHENTICATION_REQUIRED") {
        setErrorMessage(res.errors[0].message);
      } else {
        applyRoutine(res.routine);
      }
    } catch {
      setErrorMessage("Could not connect to routine service.");
    } finally {
      setLoading(false);
    }
  }, [applyRoutine]);

  useEffect(() => {
    let active = true;
    fetchCurrentRoutine(endpoint)
      .then((res) => {
        if (!active) return;
        if (res.errors.length && res.errors[0].code !== "AUTHENTICATION_REQUIRED") {
          setErrorMessage(res.errors[0].message);
        } else {
          applyRoutine(res.routine);
        }
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        setErrorMessage("Could not connect to routine service.");
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [applyRoutine]);

  async function handlePropose() {
    setActionLoading(true);
    setErrorMessage(null);
    try {
      const res = await proposeRoutine(endpoint);
      if (res.errors.length) {
        setErrorMessage(res.errors[0].message);
      } else if (res.routine) {
        setRoutine(res.routine);
        setRoutineTitle(res.routine.title);
        setIsEditing(false);
        setEditableItems(
          res.routine.items.map((it) => ({
            exerciseId: it.exercise.id,
            order: it.order,
            sets: it.sets,
            repetitions: it.repetitions,
            durationSeconds: it.durationSeconds,
          })),
        );
      }
    } catch {
      setErrorMessage("Failed to generate routine proposal.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleAccept() {
    if (!routine) return;
    setActionLoading(true);
    setErrorMessage(null);
    try {
      const res = await acceptRoutine(endpoint, routine.id, routine.version);
      if (res.errors.length) {
        setErrorMessage(res.errors[0].message);
      } else if (res.routine) {
        setRoutine(res.routine);
        onRoutineAccepted?.(res.routine);
      }
    } catch {
      setErrorMessage("Failed to accept routine.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!routine) return;
    setActionLoading(true);
    setErrorMessage(null);
    try {
      const res = await editRoutine(endpoint, {
        routineId: routine.id,
        baseVersion: routine.version,
        title: routineTitle || routine.title,
        items: editableItems,
      });
      if (res.errors.length) {
        setErrorMessage(res.errors[0].message);
      } else if (res.routine) {
        setRoutine(res.routine);
        setIsEditing(false);
        setEditableItems(
          res.routine.items.map((it) => ({
            exerciseId: it.exercise.id,
            order: it.order,
            sets: it.sets,
            repetitions: it.repetitions,
            durationSeconds: it.durationSeconds,
          })),
        );
      }
    } catch {
      setErrorMessage("Failed to save routine changes.");
    } finally {
      setActionLoading(false);
    }
  }

  function updateItemSets(index: number, sets: number) {
    const updated = [...editableItems];
    updated[index] = { ...updated[index], sets: Math.max(1, sets) };
    setEditableItems(updated);
  }

  function updateItemReps(index: number, reps: number) {
    const updated = [...editableItems];
    updated[index] = { ...updated[index], repetitions: Math.max(1, reps) };
    setEditableItems(updated);
  }

  if (loading) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 shadow-xl backdrop-blur-md animate-pulse">
        <div className="h-4 w-28 rounded bg-white/10" />
        <div className="mt-3 h-7 w-48 rounded bg-white/10" />
        <div className="mt-4 h-24 w-full rounded bg-white/5" />
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-6 shadow-xl backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-[var(--accent)] shadow-[0_0_8px_var(--accent)]" />
          <h2 className="text-xs font-semibold tracking-wider uppercase text-[var(--accent)]">
            Prescribed Routine Loop
          </h2>
        </div>
        {routine && (
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider ${
                routine.accepted
                  ? "border border-emerald-500/40 bg-emerald-950/40 text-emerald-300"
                  : "border border-amber-500/40 bg-amber-950/40 text-amber-300"
              }`}
            >
              {routine.accepted ? `Accepted (v${routine.version})` : `Draft v${routine.version} · Pending Acceptance`}
            </span>
          </div>
        )}
      </div>

      {errorMessage && (
        <div className="mt-4 flex items-center justify-between rounded-xl border border-red-500/30 bg-red-950/40 p-3.5 text-xs text-red-200">
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={loadRoutine}
            className="ml-3 font-semibold underline hover:text-white"
          >
            Retry
          </button>
        </div>
      )}

      {!routine ? (
        <div className="mt-5 space-y-4">
          <p className="text-sm text-[var(--muted)]">
            No active routine proposal. Generate an explained routine based on your athlete context and available equipment.
          </p>
          <button
            type="button"
            disabled={actionLoading}
            onClick={handlePropose}
            className="rounded-xl bg-[var(--accent)] px-5 py-2.5 text-xs font-bold text-black transition hover:opacity-90 disabled:opacity-50"
          >
            {actionLoading ? "Generating Proposal…" : "Propose Routine from Context"}
          </button>
        </div>
      ) : (
        <div className="mt-4 space-y-5">
          <div>
            <div className="flex items-baseline justify-between">
              <h3 className="text-2xl font-bold tracking-tight text-white">{routine.title}</h3>
              <span className="text-xs text-[var(--muted)]">Version {routine.version}</span>
            </div>
            <div className="mt-2 rounded-xl border border-white/5 bg-black/30 p-3.5">
              <span className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--accent)]">
                Coach Rationale
              </span>
              <p className="mt-1 text-xs leading-relaxed text-white/80">{routine.rationale}</p>
            </div>
          </div>

          {/* Exercise items list */}
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
                Prescribed Exercises ({routine.items.length})
              </span>
              {!isEditing && (
                <button
                  type="button"
                  onClick={() => setIsEditing(true)}
                  className="text-xs text-[var(--accent)] underline hover:text-white"
                >
                  Adjust Prescription
                </button>
              )}
            </div>

            {!isEditing ? (
              <div className="mt-3 divide-y divide-white/5 rounded-xl border border-white/5 bg-black/20">
                {routine.items.map((item) => (
                  <div key={item.order} className="flex items-center justify-between p-3 text-xs">
                    <div className="flex items-center gap-3">
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/10 text-[10px] font-bold text-white/70">
                        {item.order}
                      </span>
                      <div>
                        <strong className="block text-white font-medium">{item.exercise.name}</strong>
                        {item.exercise.visionSupported && (
                          <span className="text-[10px] text-emerald-400 font-medium">Vision tracked</span>
                        )}
                      </div>
                    </div>
                    <div className="text-right text-white/80">
                      <span className="font-semibold">{item.sets} sets</span>
                      {item.repetitions ? (
                        <span className="text-[var(--muted)]"> × {item.repetitions} reps</span>
                      ) : item.durationSeconds ? (
                        <span className="text-[var(--muted)]"> · {item.durationSeconds}s</span>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <form onSubmit={handleSaveEdit} className="mt-3 space-y-3">
                <div className="divide-y divide-white/5 rounded-xl border border-white/10 bg-black/40 p-3">
                  {routine.items.map((item, index) => (
                    <div key={item.order} className="flex items-center justify-between py-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="text-white/60 font-medium">{item.order}.</span>
                        <span className="text-white font-medium">{item.exercise.name}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <label className="flex items-center gap-1.5 text-white/70">
                          Sets:
                          <input
                            type="number"
                            min={1}
                            max={10}
                            value={editableItems[index]?.sets ?? item.sets}
                            onChange={(e) => updateItemSets(index, parseInt(e.target.value, 10) || 1)}
                            className="w-12 rounded border border-white/20 bg-black/60 px-1.5 py-0.5 text-center text-white"
                          />
                        </label>
                        {item.repetitions !== null && (
                          <label className="flex items-center gap-1.5 text-white/70">
                            Reps:
                            <input
                              type="number"
                              min={1}
                              max={100}
                              value={editableItems[index]?.repetitions ?? item.repetitions ?? 10}
                              onChange={(e) => updateItemReps(index, parseInt(e.target.value, 10) || 1)}
                              className="w-14 rounded border border-white/20 bg-black/60 px-1.5 py-0.5 text-center text-white"
                            />
                          </label>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    disabled={actionLoading}
                    onClick={() => setIsEditing(false)}
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="rounded-lg bg-[var(--accent)] px-4 py-1.5 text-xs font-semibold text-black hover:opacity-90 disabled:opacity-50"
                  >
                    {actionLoading ? "Saving…" : "Save as New Version"}
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* Routine actions */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <button
              type="button"
              disabled={actionLoading}
              onClick={handlePropose}
              className="rounded-xl border border-white/10 px-4 py-2 text-xs font-medium text-white/80 hover:bg-white/5 disabled:opacity-50"
            >
              {actionLoading ? "Processing…" : "Propose New Routine"}
            </button>

            {!routine.accepted ? (
              <button
                type="button"
                disabled={actionLoading}
                onClick={handleAccept}
                className="rounded-xl bg-emerald-400 px-5 py-2.5 text-xs font-bold text-black transition hover:bg-emerald-300 disabled:opacity-50"
              >
                {actionLoading ? "Accepting…" : `Accept Routine (v${routine.version})`}
              </button>
            ) : (
              <div className="flex items-center gap-2 text-xs text-emerald-400">
                <span>✓ Routine accepted for session preparation</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
