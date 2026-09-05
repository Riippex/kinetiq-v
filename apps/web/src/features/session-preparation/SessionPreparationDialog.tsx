"use client";

import {
  coachingTones,
  prepareSession,
  sessionIntensities,
  sessionModes,
  type CoachingTone,
  type SessionIntensity,
  type SessionMode,
} from "@kinetiq/session-client";
import { useState, type FormEvent } from "react";

const routineId = process.env.NEXT_PUBLIC_KINETIQ_DEMO_ROUTINE_ID;

export function SessionPreparationDialog() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<SessionMode>("NORMAL");
  const [intensity, setIntensity] = useState<SessionIntensity>("PLANNED");
  const [tone, setTone] = useState<CoachingTone>("MOTIVATIONAL");
  const [photo, setPhoto] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!routineId) {
      setMessage("Choose an accepted routine before preparing the session.");
      return;
    }

    setSubmitting(true);
    setMessage(null);
    const result = await prepareSession("/api/graphql", {
      routineId,
      routineVersion: 1,
      mode,
      intensity,
      coachingTone: tone,
      captureDeviceId: "phone-camera",
      displayDeviceId: "browser",
      promptForProgressPhoto: photo,
      idempotencyKey: crypto.randomUUID(),
      dynamic:
        mode === "DYNAMIC"
          ? {
              frequency: "STANDARD",
              allowedChallengeTypes: ["HOLD_POSE", "MIRROR_POSE", "QUICK_REPS", "RECOVERY"],
              scoringEnabled: true,
              narrationEnabled: true,
            }
          : undefined,
    });
    setSubmitting(false);
    setMessage(
      result.session
        ? `Session ready · revision ${result.session.revision}`
        : result.errors[0]?.message ?? "Session preparation failed",
    );
  }

  return (
    <>
      <button
        className="rounded-full bg-[var(--accent)] px-6 py-3 font-semibold text-[#070b14]"
        onClick={() => setOpen(true)}
        type="button"
      >
        Prepare a session
      </button>
      {open && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-5">
          <form
            aria-label="Session preparation"
            className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-white/10 bg-[#111827] p-7 shadow-2xl"
            onSubmit={submit}
          >
            <div className="flex items-start justify-between gap-5">
              <div>
                <p className="text-xs font-semibold tracking-[0.2em] text-[var(--accent)]">SESSION SETUP</p>
                <h2 className="mt-2 text-3xl font-semibold">Full body foundation</h2>
                <p className="mt-2 text-sm text-[var(--muted)]">30 min · phone camera · browser display</p>
              </div>
              <button aria-label="Close" className="text-2xl text-[var(--muted)]" onClick={() => setOpen(false)} type="button">×</button>
            </div>

            <OptionGroup label="Mode" options={sessionModes} value={mode} onChange={value => setMode(value as SessionMode)} />
            <OptionGroup label="Intensity" options={sessionIntensities} value={intensity} onChange={value => setIntensity(value as SessionIntensity)} />
            <OptionGroup label="Coach" options={coachingTones} value={tone} onChange={value => setTone(value as CoachingTone)} />

            <label className="mt-7 flex items-center justify-between rounded-2xl border border-white/10 p-4">
              <span>
                <strong className="block">Progress photo prompt</strong>
                <span className="text-sm text-[var(--muted)]">Ask after the session; capture remains optional.</span>
              </span>
              <input checked={photo} onChange={event => setPhoto(event.target.checked)} type="checkbox" />
            </label>

            {message && <p className="mt-5 rounded-xl bg-white/[0.06] p-3 text-sm">{message}</p>}
            <button className="mt-6 w-full rounded-2xl bg-[var(--accent)] p-4 font-bold text-[#070b14] disabled:opacity-50" disabled={submitting} type="submit">
              {submitting ? "Preparing…" : "Confirm and prepare"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}

function OptionGroup({label, options, value, onChange}: {label: string; options: readonly string[]; value: string; onChange: (value: string) => void}) {
  return (
    <fieldset className="mt-7">
      <legend className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map(option => (
          <button key={option} className={`rounded-full border px-4 py-2 text-sm ${value === option ? "border-[var(--accent)] bg-[var(--accent)] text-[#070b14]" : "border-white/15"}`} onClick={() => onChange(option)} type="button">
            {option.toLowerCase()}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
