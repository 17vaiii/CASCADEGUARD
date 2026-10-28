import { FlaskConical, Pause, Play, RotateCcw, SkipBack, SkipForward } from "lucide-react";
import { INJECTION_LABEL, stepLabel } from "../lib/format";
import { useApp } from "../lib/store";

const SPEEDS = [1, 2, 4, 8, 16];

export function Timeline() {
  const sim = useApp((s) => s.sim);
  const t = useApp((s) => s.t);
  const st = useApp((s) => s.state);
  const playing = useApp((s) => s.playing);
  const speed = useApp((s) => s.speed);
  const { setT, step, setPlaying, setSpeed } = useApp.getState();
  if (!sim) return <div className="h-[86px] border-t border-hair bg-panel" />;
  const n = sim.n_steps;
  const pct = (s: number) => `${(100 * s) / (n - 1)}%`;
  const active = st?.scenario.events.filter((e) => e.phase === "active") ?? [];
  const shownT = st?.t ?? t;
  return (
    <div className="flex items-center gap-4 border-t border-hair bg-panel px-4 py-2.5">
      <div className="flex items-center gap-1" role="group" aria-label="Playback">
        <IconBtn label="Reset to the first step" onClick={() => { setPlaying(false); setT(0); }}><RotateCcw size={16} /></IconBtn>
        <IconBtn label="Step back one hour" onClick={() => step(-1)}><SkipBack size={16} /></IconBtn>
        <button
          onClick={() => setPlaying(!playing)}
          aria-label={playing ? "Pause" : "Play"}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-flow text-plane hover:brightness-110"
        >
          {playing ? <Pause size={17} /> : <Play size={17} className="ml-0.5" />}
        </button>
        <IconBtn label="Step forward one hour" onClick={() => step(1)}><SkipForward size={16} /></IconBtn>
        <label className="ml-2 flex items-center gap-1.5 text-[12px] text-ink-3">
          Speed
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}
            className="rounded border border-hair-strong bg-raised px-1.5 py-1 text-[12px] text-ink">
            {SPEEDS.map((s) => <option key={s} value={s}>{s} h/s</option>)}
          </select>
        </label>
      </div>

      <div className="min-w-0 flex-1">
        <div className="relative h-7">
          {/* event track: scheduled injections (orange) and outages (grey) */}
          <div className="absolute inset-x-0 top-[11px] h-[6px] rounded-full bg-raised" />
          {sim.events.map((e) => (
            <div key={e.index} title={`${INJECTION_LABEL[e.type]} on ${e.dt ?? e.feeder}: steps ${e.start_step}–${e.end_step}`}
              className="absolute top-[9px] h-[10px] rounded-sm border border-truth bg-truth/35"
              style={{ left: pct(Math.max(0, e.start_step)), width: `calc(${pct(Math.min(n - 1, e.end_step))} - ${pct(Math.max(0, e.start_step))})` }} />
          ))}
          {sim.outages.filter((o) => o.end_step > 0).map((o, i) => (
            <div key={i} title={`Supply outage on ${o.feeder}`} className="absolute top-[9px] h-[10px] w-[3px] rounded-sm bg-ink-3"
              style={{ left: pct(Math.max(0, o.start_step)) }} />
          ))}
          {Array.from({ length: Math.floor(n / 24) + 1 }).map((_, d) => (
            <div key={d} className="absolute top-[21px] h-[6px] w-px bg-hair-strong" style={{ left: pct(Math.min(n - 1, d * 24)) }} />
          ))}
          <input
            type="range" min={0} max={n - 1} value={t} aria-label="Timeline step"
            onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }}
            className="absolute inset-x-0 top-0 h-7 w-full cursor-pointer appearance-none bg-transparent
              [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-[5px] [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-sm [&::-webkit-slider-thumb]:bg-ink
              [&::-moz-range-thumb]:h-5 [&::-moz-range-thumb]:w-[5px] [&::-moz-range-thumb]:rounded-sm [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-ink"
          />
        </div>
        <div className="mt-0.5 flex justify-between font-cond text-[11px] text-ink-3 tnum">
          <span>Day 1</span>
          <span>{n} hourly steps of synthetic data</span>
          <span>Day {Math.ceil(n / 24)}</span>
        </div>
      </div>

      <div className="w-[250px] shrink-0 text-right">
        <div className="font-cond text-[17px] font-semibold tnum">{stepLabel(sim.start_timestamp, shownT)}</div>
        <div className="text-[12px] text-ink-3 tnum">
          Step {shownT} of {n - 1}, day {Math.floor(shownT / 24) + 1}, synthetic calendar
        </div>
        <div className="mt-0.5 flex items-center justify-end gap-1.5 text-[12px]">
          {active.length > 0 ? (
            <><FlaskConical size={12} color="var(--color-truth)" /><span className="text-ink">Simulated event active: {active.map((e) => e.dt ?? e.feeder).join(", ")}</span></>
          ) : (
            <span className="text-ink-3">{st?.scenario.status ?? "loading…"}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function IconBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button aria-label={label} title={label} onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded text-ink-2 hover:bg-raised hover:text-ink">
      {children}
    </button>
  );
}
