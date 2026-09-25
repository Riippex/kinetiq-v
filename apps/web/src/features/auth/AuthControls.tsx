"use client";

import { useEffect, useState } from "react";

type Session = { authenticated: boolean; email?: string | null };

export function AuthControls() {
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    fetch("/api/auth/session", { cache: "no-store" })
      .then((response) => response.json())
      .then((value: Session) => setSession(value))
      .catch(() => setSession({ authenticated: false }));
  }, []);

  if (session?.authenticated) {
    return (
      <div className="flex items-center gap-3 text-xs">
        {session.email ? <span className="text-[var(--muted)]">{session.email}</span> : null}
        <a className="rounded-full border border-white/15 px-3 py-1.5" href="/api/auth/logout">
          Sign out
        </a>
      </div>
    );
  }

  return (
    <a className="rounded-full bg-[var(--accent)] px-4 py-2 text-xs font-semibold text-black" href="/api/auth/login">
      Sign in
    </a>
  );
}
