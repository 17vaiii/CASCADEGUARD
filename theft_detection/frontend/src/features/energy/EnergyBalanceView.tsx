import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { HourlyAccountingChart, Waterfall } from "../../components/charts";
import { api } from "../../lib/api";
import { fmt, stepLabel } from "../../lib/format";
import { useApp } from "../../lib/store";
import type { Balance } from "../../lib/types";

const PRESETS = [
  { id: "24", label: "Last 24 h", hours: 24 },
  { id: "72", label: "Last 72 h", hours: 72 },
  { id: "168", label: "Last 7 days", hours: 168 },
  { id: "all", label: "Since day 1", hours: 10000 },
] as const;

export function EnergyBalanceView() {
  const sim = useApp((s) => s.sim)!;
  const topo = useApp((s) => s.topo)!;
  const t = useApp((s) => s.t);
  const playing = useApp((s) => s.playing);
  const sel = useApp((s) => s.selection);
  const [boundary, setBoundary] = useState<{ kind: "feeder" | "dt"; id: string }>(() =>
    sel?.kind === "feeder" || sel?.kind === "dt" ? { kind: sel.kind, id: sel.id } : { kind: "feeder", id: topo.feeders[0].id });
  const [preset, setPreset] = useState<string>("24");
  const [custom, setCustom] = useState<{ start: number; end: number }>({ start: 0, end: 24 });
  const [b, setB] = useState<Balance | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const end = preset === "custom" ? Math.min(custom.end, t + 1) : t + 1;
  const start = preset === "custom" ? Math.min(custom.start, end - 1) : Math.max(0, end - (PRESETS.find((p) => p.id === preset)?.hours ?? 24));
  const bucket = playing ? Math.floor(t / 3) : t;

  useEffect(() => {
    let live = true;
    setErr(null);
    api.balance(sim.id, boundary.kind, boundary.id, t, start, Math.max(start + 1, end))
      .then((r) => live && setB(r))
      .catch((e) => live && setErr(String(e.message ?? e)));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.id, boundary.kind, boundary.id, bucket, start, end]);

  return (
    <div className="grid h-full grid-cols-[260px_minmax(0,1fr)] overflow-hidden">
      <aside className="overflow-y-auto border-r border-hair bg-panel p-4">
        <h2 className="font-cond text-[16px] font-semibold">Monitoring boundary</h2>
        <ul className="mt-2 space-y-2 text-[13px]">
          {topo.feeders.map((f) => (
            <li key={f.id}>
              <button onClick={() => setBoundary({ kind: "feeder", id: f.id })}
                className={`w-full rounded px-2 py-1 text-left ${boundary.id === f.id ? "bg-raised text-ink" : "text-ink-2 hover:bg-raised/60"}`}>
                Feeder {f.id} <span className="text-ink-3">({f.archetype})</span>
              </button>
              <ul className="ml-3 mt-0.5 border-l border-hair pl-2">
                {f.dts.map((d) => (
                  <li key={d}>
                    <button onClick={() => setBoundary({ kind: "dt", id: d })}
                      className={`w-full rounded px-2 py-0.5 text-left text-[12.5px] ${boundary.id === d ? "bg-raised text-ink" : "text-ink-3 hover:bg-raised/60"}`}>
                      {d}
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
        <h2 className="mt-5 font-cond text-[16px] font-semibold">Interval</h2>
        <div className="mt-2 grid grid-cols-2 gap-1.5">
          {PRESETS.map((p) => (
            <button key={p.id} onClick={() => setPreset(p.id)}
              className={`rounded border px-2 py-1 text-[12.5px] ${preset === p.id ? "border-flow text-ink" : "border-hair-strong text-ink-2 hover:bg-raised"}`}>{p.label}</button>
          ))}
          <button onClick={() => { setPreset("custom"); setCustom({ start, end }); }}
            className={`col-span-2 rounded border px-2 py-1 text-[12.5px] ${preset === "custom" ? "border-flow text-ink" : "border-hair-strong text-ink-2 hover:bg-raised"}`}>Custom range</button>
        </div>
        {preset === "custom" && (
          <div className="mt-2 grid grid-cols-2 gap-2 text-[12px] text-ink-2">
            <label>From step<input type="number" min={0} max={t} value={custom.start} onChange={(e) => setCustom({ ...custom, start: Math.max(0, Number(e.target.value)) })}
              className="mt-0.5 w-full rounded border border-hair-strong bg-raised px-1.5 py-1 text-ink tnum" /></label>
            <label>To step (excl.)<input type="number" min={1} max={sim.n_steps} value={custom.end} onChange={(e) => setCustom({ ...custom, end: Math.max(1, Number(e.target.value)) })}
              className="mt-0.5 w-full rounded border border-hair-strong bg-raised px-1.5 py-1 text-ink tnum" /></label>
          </div>
        )}
        <p className="mt-3 text-[12px] text-ink-3">
          Computed with the readings that had arrived by step {t} ({stepLabel(sim.start_timestamp, t)}). Readings still in transit are imputed and flagged as pending.
        </p>
      </aside>

      <section className="min-w-0 overflow-y-auto p-5">
        <div className="flex items-start gap-2 rounded-md border border-warn/60 bg-warn/10 px-3 py-2.5 text-[13.5px] text-ink">
          <AlertTriangle size={17} color="var(--color-warn)" className="mt-0.5 shrink-0" />
          <span><strong className="font-semibold">Unexplained energy imbalance is an investigation signal, not proof of electricity theft.</strong> It also contains
            technical-loss estimation error, meter error, missing or delayed data and timing effects.</span>
        </div>
        {err && <div className="mt-3 text-alert">{err}</div>}
        {b && (
          <>
            <div className="mt-4 flex flex-wrap items-baseline justify-between gap-3">
              <h1 className="font-cond text-[22px] font-semibold">{boundary.kind === "feeder" ? `Feeder ${boundary.id}` : `Distribution transformer ${boundary.id}`}</h1>
              <span className="text-[13px] text-ink-2 tnum">{stepLabel(sim.start_timestamp, b.window.start_step)} to {stepLabel(sim.start_timestamp, b.window.end_step - 1)} ({b.window.hours_used} h used of {b.window.hours_in_time})</span>
            </div>
            <p className="mt-1 max-w-3xl text-[13px] text-ink-2">{b.boundary.description}</p>

            <div className="mt-4 grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
              <div className="rounded-md border border-hair bg-panel p-4">
                <div className="font-cond text-[15px] font-semibold">Energy balance over the interval</div>
                <Waterfall b={b} />
                <p className="text-[12px] text-ink-3">Whisker on the unexplained bar: ±2σ propagated uncertainty. Red when the unexplained energy is at least 2σ.</p>
              </div>
              <div className="space-y-4">
                <div className="rounded-md border border-hair bg-panel p-4">
                  <div className="font-cond text-[15px] font-semibold">Calculation</div>
                  <div className="mt-2 rounded bg-plane px-3 py-2 text-[13px] leading-relaxed tnum">
                    <div className="text-ink-2">U = E<sub>in</sub> − E<sub>metered</sub> − E<sub>imputed</sub> − L<sub>est</sub></div>
                    <div className="text-ink">
                      U = {fmt.kwh(b.input_kwh)} − {fmt.kwh(b.metered_kwh)} − {fmt.kwh(b.imputed_kwh)} − {fmt.kwh(b.estimated_loss_kwh)}
                    </div>
                    <div className="font-semibold text-ink">
                      U = {fmt.kwh(b.unexplained_kwh)} ({b.unexplained_pct_of_input == null ? "–" : `${b.unexplained_pct_of_input.toFixed(2)}%`} of input), σ = {fmt.kwh(b.sigma_kwh)}, z = {b.z_score.toFixed(2)}
                    </div>
                  </div>
                  <ul className="mt-2 space-y-0.5 text-[12px] text-ink-2">
                    <li>All terms are energy in kWh summed over the same hourly intervals; hours without an input-meter reading are dropped from both sides.</li>
                    <li>E<sub>imputed</sub>: expected-profile values for consumer readings missing or still delayed at this step; zero during known outages.</li>
                    <li>L<sub>est</sub>: one-pass analytic I²R and DT no-load loss estimate from metered and imputed demand (±15% assumed uncertainty).</li>
                  </ul>
                </div>
                <div className="rounded-md border border-hair bg-panel p-4">
                  <div className="font-cond text-[15px] font-semibold">Uncertainty budget (1σ)</div>
                  <table className="mt-2 w-full text-[12.5px] tnum">
                    <tbody>
                      {Object.entries(b.uncertainty_components_kwh).map(([k, v]) => (
                        <tr key={k} className="border-t border-hair"><td className="py-1 text-ink-2">{{ input_meter: "Input meter (bias + random)", consumer_meters: "Consumer meters", loss_model: "Technical-loss estimate", imputation: "Imputation of missing readings" }[k] ?? k}</td><td className="text-right">{fmt.kwh(v, 2)}</td></tr>
                      ))}
                      <tr className="border-t border-hair-strong font-semibold"><td className="py-1">Combined σ</td><td className="text-right">{fmt.kwh(b.sigma_kwh, 2)}</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
              <div className="rounded-md border border-hair bg-panel p-4">
                <div className="font-cond text-[15px] font-semibold">Hourly accounting terms</div>
                <HourlyAccountingChart b={b} startTs={sim.start_timestamp} />
              </div>
              <div className="rounded-md border border-hair bg-panel p-4">
                <div className="flex items-center gap-2 font-cond text-[15px] font-semibold">
                  Measurement quality
                  {b.data_quality.status === "good" ? <span className="flex items-center gap-1 text-[12.5px] font-normal text-ok"><CheckCircle2 size={14} /> good</span>
                    : <span className="flex items-center gap-1 text-[12.5px] font-normal text-warn"><AlertTriangle size={14} /> {b.data_quality.status}</span>}
                </div>
                <table className="mt-2 w-full text-[12.5px] tnum">
                  <tbody>
                    <Q k="Consumer-reading coverage" v={fmt.pct(b.data_quality.consumer_reading_coverage)} />
                    <Q k="Readings expected" v={b.data_quality.readings_expected.toLocaleString()} />
                    <Q k="Missing or pending (imputed)" v={b.data_quality.readings_missing_or_pending.toLocaleString()} />
                    <Q k="…of which delayed, will arrive later" v={b.data_quality.readings_pending_delayed.toLocaleString()} />
                    <Q k="Input-meter gaps (hours dropped)" v={String(b.data_quality.input_meter_gaps_h)} />
                    <Q k="Known outage hours (zero both sides)" v={String(b.data_quality.known_outage_hours)} />
                    <Q k="Duplicate records removed at ingestion (run)" v={String(b.data_quality.duplicates_removed_run_total)} />
                  </tbody>
                </table>
                <p className="mt-2 flex items-start gap-1.5 text-[12px] text-ink-3"><Info size={13} className="mt-0.5 shrink-0" />Quality is “good” at ≥98% coverage with no input gaps, “fair” at ≥90% with ≤2 gaps, otherwise “poor”.</p>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function Q({ k, v }: { k: string; v: string }) {
  return <tr className="border-t border-hair"><td className="py-1 text-ink-2">{k}</td><td className="text-right text-ink">{v}</td></tr>;
}
