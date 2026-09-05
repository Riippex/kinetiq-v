import { SessionPreparationDialog } from "@/features/session-preparation/SessionPreparationDialog";

const surfaces = [
  ["Phone", "Camera and session control"],
  ["TV", "Guidance, timing and game events"],
  ["Alexa+", "Voice follow-up between sessions"],
] as const;

export default function Home() {
  return (
    <main className="min-h-screen px-6 py-10 sm:px-12 lg:px-20">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-6xl flex-col justify-between rounded-[2rem] border border-white/10 bg-[radial-gradient(circle_at_top_right,_rgba(163,255,18,0.14),_transparent_40%),linear-gradient(145deg,#111827,#090d16)] p-8 shadow-2xl sm:p-12">
        <nav className="flex items-center justify-between">
          <span className="text-lg font-semibold tracking-tight">Kinetiq V</span>
          <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-[var(--muted)]">
            Foundation
          </span>
        </nav>

        <section className="max-w-3xl py-20">
          <p className="mb-5 text-sm font-semibold uppercase tracking-[0.24em] text-[var(--accent)]">
            Move. Play. Progress.
          </p>
          <h1 className="text-5xl font-semibold leading-[1.02] tracking-[-0.05em] sm:text-7xl">
            Your movement coach, connected across the room.
          </h1>
          <p className="mt-7 max-w-2xl text-lg leading-8 text-[var(--muted)]">
            Plan a routine, choose a focused or Dynamic session, and follow your
            progress with live vision feedback and a coach that learns how to
            motivate you.
          </p>
          <div className="mt-8">
            <SessionPreparationDialog />
          </div>
        </section>

        <section className="grid gap-3 md:grid-cols-3">
          {surfaces.map(([title, description]) => (
            <article key={title} className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
              <h2 className="font-semibold">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{description}</p>
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}
