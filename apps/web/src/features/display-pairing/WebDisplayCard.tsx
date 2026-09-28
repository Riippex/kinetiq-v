"use client";

import {
  fetchDisplaySessionState,
  issueDisplayPairingCode,
  type DisplayPairingCode,
  type DisplaySessionState,
} from "@kinetiq/session-client";
import { useEffect, useState } from "react";

const pollIntervalMs = 2_000;

export function WebDisplayCard() {
  const [pairing, setPairing] = useState<DisplayPairingCode | null>(null);
  const [session, setSession] = useState<DisplaySessionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!pairing || session?.status === "PAIRED") return;

    const code = pairing.code;
    let cancelled = false;
    async function poll() {
      const result = await fetchDisplaySessionState("/api/graphql", code);
      if (cancelled) return;
      if (result.errors.length) {
        setMessage(result.errors[0].message);
        return;
      }
      if (result.state?.status === "EXPIRED") {
        setMessage("This pairing code expired. Generate a new one.");
        return;
      }
      if (result.state?.status === "PAIRED" && result.state.sessionId) {
        setSession(result.state);
        setMessage(null);
      }
    }

    void poll();
    const interval = window.setInterval(() => void poll(), pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [pairing, session?.status]);

  useEffect(() => {
    if (!pairing || session?.status !== "PAIRED") return;

    let cancelled = false;
    const interval = window.setInterval(async () => {
      const result = await fetchDisplaySessionState("/api/graphql", pairing.code);
      if (!cancelled && result.state?.status === "PAIRED") setSession(result.state);
    }, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [pairing, session?.status]);

  async function generateCode() {
    setLoading(true);
    setMessage(null);
    setSession(null);
    try {
      const result = await issueDisplayPairingCode("/api/graphql", "WEB");
      if (result.pairing) setPairing(result.pairing);
      else setMessage(result.errors[0]?.message ?? "Could not generate a pairing code.");
    } catch {
      setMessage("Could not reach the backend. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-3xl border border-white/10 bg-white/[0.04] p-6">
      <p className="text-xs font-semibold tracking-[0.2em] text-[var(--accent)]">WEB DISPLAY</p>
      <h2 className="mt-2 text-2xl font-semibold">Pair this browser</h2>
      <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
        Generate a code, enter it on your phone, and this browser becomes the live workout display.
      </p>

      {!pairing ? (
        <button
          className="mt-5 rounded-full bg-[var(--accent)] px-6 py-3 font-semibold text-[#070b14] disabled:opacity-50"
          disabled={loading}
          onClick={() => void generateCode()}
          type="button"
        >
          {loading ? "Generating…" : "Generate pairing code"}
        </button>
      ) : session?.status === "PAIRED" ? (
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <Metric label="Session" value={session.state ?? "READY"} />
          <Metric label="Confirmed reps" value={String(session.confirmedReps)} />
          <Metric label="Exercise" value={session.activeExercise ?? "Waiting for Vision…"} />
          <Metric label="Tracking" value={session.visibilityStatus ?? "Waiting for Vision…"} />
          {session.pauseReason ? <Metric label="Paused" value={session.pauseReason} /> : null}
          <button
            className="rounded-2xl border border-white/15 px-4 py-3 text-sm font-semibold"
            onClick={() => {
              setPairing(null);
              setSession(null);
            }}
            type="button"
          >
            Pair another session
          </button>
        </div>
      ) : (
        <div className="mt-5 rounded-2xl border border-[var(--accent)]/50 bg-[#070b14] p-5">
          <p className="text-sm text-[var(--muted)]">Enter this code on your phone</p>
          <p className="mt-2 text-4xl font-black tracking-[0.16em] text-[var(--accent)]">{pairing.code}</p>
          <p className="mt-3 text-sm text-[var(--muted)]">Waiting for the phone to pair a prepared session…</p>
          <button className="mt-4 text-sm font-semibold underline" onClick={() => void generateCode()} type="button">
            Generate a new code
          </button>
        </div>
      )}

      {message ? <p className="mt-4 rounded-xl bg-red-400/10 p-3 text-sm text-red-200">{message}</p> : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-[#070b14] p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">{label}</p>
      <p className="mt-2 font-semibold">{value}</p>
    </div>
  );
}
