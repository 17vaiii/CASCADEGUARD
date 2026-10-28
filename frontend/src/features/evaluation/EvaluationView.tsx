import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { LegendRow } from "../../components/charts";
import { api, type ExperimentResults } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
const GRID = "#1e2d45";
const AXIS = "#2e4262";
const tip = { contentStyle: { background: "#0f1a2b", border: "1px solid #2e4262", borderRadius: 6, fontSize: 12 }, labelStyle: { color: "#a9b8cc" } };
const f3 = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(3));
const ci = (r: any, k: string) => (r.ci95?.[k] ? `[${f3(r.ci95[k][0])}, ${f3(r.ci95[k][1])}]` : "");

// Emphasis encoding for sweeps: the combined model in the accent, comparators muted.
const SWEEP_SERIES = [
  { key: "rf_combined", label: "Random Forest, consumer + grid", color: "#3987e5", width: 2.5 },
  { key: "rf_consumer", label: "Random Forest, consumer only", color: "#199e70", width: 2 },
  { key: "consumer_rule", label: "Consumer threshold rule", color: "#8a9bb4", width: 2 },
];

export function EvaluationView() {
  const [r, setR] = useState<ExperimentResults | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.results().then(setR).catch((e) => setErr(e.message)); }, []);
  if (err) return <div className="p-6 text-alert">{err}</div>;
  if (!r) return <div className="p-6 text-ink-3">Loading experiment results…</div>;
  if (!r.available) return (
    <div className="p-6">
      <h1 className="font-cond text-[22px] font-semibold">No experiment results yet</h1>
      <p className="mt-2 text-ink-2">{r.message}</p>
    </div>
  );
  const b = r.benchmark;
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1280px] space-y-6 p-6">
        <header>
          <h1 className="font-cond text-[24px] font-semibold">Model evaluation on the synthetic benchmark</h1>
          <p className="mt-1 max-w-4xl text-[13.5px] text-ink-2">
            Computed by <code className="text-ink">python -m gridwatch.experiments.run</code> on {r.generated_at} from saved test predictions.
            These numbers describe performance on this project's documented synthetic benchmark only; they are not real-world theft-detection accuracy.
          </p>
          <p className="mt-2 max-w-4xl text-[12.5px] text-ink-3">
            Train seeds {b.train_seeds[0]}–{b.train_seeds[1]} ({b.train_seeds[2]} runs), validation {b.val_seeds[0]}–{b.val_seeds[1]} ({b.val_seeds[2]}), test {b.test_seeds[0]}–{b.test_seeds[1]} ({b.test_seeds[2]}); splits grouped by run.
            Unit: {b.unit_of_evaluation}. Rules use their configured thresholds; ML thresholds maximise F1 on validation runs. Brackets: 95% cluster-bootstrap CI over test runs.
          </p>
        </header>

        <Panel title="Consumer level: which meters to examine">
          <MetricBars rows={r.main.consumer} />
          <MetricTable rows={r.main.consumer} />
        </Panel>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel title="Feeder level"><MetricTable rows={r.main.feeder} compact /></Panel>
          <Panel title="DT level"><MetricTable rows={r.main.dt} compact /></Panel>
        </div>

        <Panel title="Benign confounders (share of negative consumer windows flagged)">
          <table className="w-full text-[12.5px] tnum">
            <thead className="text-left text-ink-3"><tr><th className="py-1 font-normal">Method</th><th className="text-right font-normal">Genuine consumption drop</th><th className="text-right font-normal">Missing / delayed data</th><th className="text-right font-normal">Other normal consumers</th><th className="text-right font-normal">Recall on theft-like windows</th></tr></thead>
            <tbody>
              {r.confounders.map((c: any) => (
                <tr key={c.method} className="border-t border-hair">
                  <td className="py-1.5">{c.name}</td>
                  <td className="text-right">{f3(c.flag_rate_benign_change)} <span className="text-ink-3">(n={c.n_benign})</span></td>
                  <td className="text-right">{f3(c.flag_rate_data_fault)} <span className="text-ink-3">(n={c.n_fault})</span></td>
                  <td className="text-right">{c.flag_rate_other_negatives == null ? "–" : c.flag_rate_other_negatives.toFixed(4)}</td>
                  <td className="text-right">{f3(c.recall_theft_like)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Robustness sweeps (consumer-level F1)">
          <LegendRow items={SWEEP_SERIES.map((s) => ({ color: s.color, label: s.label }))} />
          <div className="mt-2 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {([["prevalence", "Anomaly prevalence"], ["noise", "Meter-noise multiplier"], ["missing", "Base missing-reading rate"], ["loss_error", "Loss-estimate error (%)"]] as const).map(([k, title]) => (
              <SweepChart key={k} title={title} sweep={r.sweeps[k]} />
            ))}
          </div>
          <SweepFeederTable sweeps={r.sweeps} />
        </Panel>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel title="Localisation (single-feeder theft runs)">
            <p className="text-[12px] text-ink-3">{r.localisation.definition}.</p>
            <table className="mt-2 w-full text-[12.5px] tnum">
              <thead className="text-left text-ink-3"><tr><th className="py-1 font-normal">Method</th><th className="text-right font-normal">Feeder top-1</th><th className="text-right font-normal">DT top-1</th></tr></thead>
              <tbody>
                {Object.keys(r.localisation.results.feeder).map((m) => (
                  <tr key={m} className="border-t border-hair"><td className="py-1.5">{m}</td>
                    <td className="text-right">{f3(r.localisation.results.feeder[m].top1_hit_rate)}</td>
                    <td className="text-right">{f3(r.localisation.results.dt[m].top1_hit_rate)}</td></tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="Detection delay">
            <p className="text-[12px] text-ink-3">{r.delay.definition}</p>
            <table className="mt-2 w-full text-[12.5px] tnum">
              <thead className="text-left text-ink-3"><tr><th className="py-1 font-normal">Level and method</th><th className="text-right font-normal">Events</th><th className="text-right font-normal">Detected</th><th className="text-right font-normal">Median delay</th></tr></thead>
              <tbody>
                {Object.entries(r.delay.results).map(([k, v]: [string, any]) => (
                  <tr key={k} className="border-t border-hair"><td className="py-1.5">{k.replace(/:/g, ", ")}</td><td className="text-right">{v.events}</td>
                    <td className="text-right">{f3(v.detection_rate)}</td><td className="text-right">{v.median_delay_h == null ? "–" : `${v.median_delay_h.toFixed(0)} h`}</td></tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel title="Energy-balance validation">
            <p className="text-[12.5px] text-ink-2">{r.energy_balance_recovery.definition}</p>
            <div className="mt-3 grid grid-cols-3 gap-3">
              {Object.entries(r.energy_balance_recovery.summary).map(([k, v]: [string, any]) => (
                <div key={k} className="rounded border border-hair px-3 py-2">
                  <div className="text-[12px] text-ink-3">{{ dt_recovery_ratio: "DT boundary, recovered / injected", feeder_recovery_ratio: "Feeder boundary, recovered / injected", feeder_recovery_ratio_incl_losses: "Feeder, recovered / (injected + its extra losses)" }[k] ?? k}</div>
                  <div className="font-cond text-[20px] font-semibold">{v.mean.toFixed(3)}</div>
                  <div className="text-[11.5px] text-ink-3 tnum">SD {v.sd.toFixed(3)}, n={r.energy_balance_recovery.runs.length}</div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Runtime as data volume grows">
            <table className="w-full text-[12.5px] tnum">
              <thead className="text-left text-ink-3"><tr><th className="py-1 font-normal">Consumers</th><th className="text-right font-normal">Readings</th><th className="text-right font-normal">Generate + power flow</th><th className="text-right font-normal">Features / step</th><th className="text-right font-normal">Scoring / step</th></tr></thead>
              <tbody>
                {r.runtime.map((x: any) => (
                  <tr key={x.consumers} className="border-t border-hair"><td className="py-1.5">{x.consumers}</td><td className="text-right">{x.readings_generated.toLocaleString()}</td>
                    <td className="text-right">{x.generation_and_power_flow_s.toFixed(2)} s</td><td className="text-right">{x.features_per_step_ms} ms</td><td className="text-right">{x.scoring_per_step_ms} ms</td></tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[12px] text-ink-3">Measured on {r.environment.platform}, Python {r.environment.python}.</p>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-md border border-hair bg-panel p-4"><h2 className="mb-2 font-cond text-[16px] font-semibold">{title}</h2>{children}</section>;
}

function MetricTable({ rows, compact }: { rows: any[]; compact?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="mt-2 w-full text-[12.5px] tnum">
        <thead className="text-left text-ink-3">
          <tr><th className="py-1 font-normal">Method</th>{!compact && <th className="font-normal">Signals</th>}<th className="text-right font-normal">Precision</th><th className="text-right font-normal">Recall</th><th className="text-right font-normal">F1</th><th className="text-right font-normal">FPR</th><th className="text-right font-normal">ROC-AUC</th><th className="text-right font-normal">PR-AUC</th></tr>
        </thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.method} className="border-t border-hair">
              <td className="py-1.5 text-ink">{x.name}</td>{!compact && <td className="text-ink-3">{x.signals}</td>}
              <td className="text-right">{f3(x.precision)}</td><td className="text-right">{f3(x.recall)}</td>
              <td className="text-right">{f3(x.f1)} {!compact && <span className="text-ink-3">{ci(x, "f1")}</span>}</td>
              <td className="text-right">{x.fpr.toFixed(4)}</td><td className="text-right">{f3(x.roc_auc)}</td>
              <td className="text-right">{f3(x.pr_auc)} {!compact && <span className="text-ink-3">{ci(x, "pr_auc")}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[11.5px] text-ink-3">Windows: {rows[0]?.n_pos} positive, {rows[0]?.n_neg} negative.</p>
    </div>
  );
}

function MetricBars({ rows }: { rows: any[] }) {
  const data = rows.map((x) => ({
    name: x.name.replace("Random Forest", "RF").replace("Isolation Forest", "IF"),
    method: x.method,
    f1: x.f1, err: x.ci95?.f1 ? [x.f1 - x.ci95.f1[0], x.ci95.f1[1] - x.f1] : [0, 0], label: x.f1.toFixed(2),
  }));
  return (
    <div>
      <div className="text-[12px] text-ink-2">F1 at the operating threshold, with 95% CI. Highlighted: the combined consumer + grid model; values are in the table below.</div>
      <ResponsiveContainer width="100%" height={36 * data.length + 30}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" domain={[0, 1]} stroke={AXIS} />
          <YAxis type="category" dataKey="name" width={250} stroke={AXIS} tick={{ fontSize: 12, fill: "#a9b8cc" }} />
          <Tooltip {...tip} cursor={{ fill: "rgba(255,255,255,0.03)" }} formatter={(v: any) => [Number(v).toFixed(3), "F1"]} />
          <Bar dataKey="f1" maxBarSize={20} radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.method} fill={d.method === "rf_combined" ? "#3987e5" : "#4a5d7a"} />)}
            <ErrorBar dataKey="err" width={6} stroke="#e6edf7" direction="x" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function SweepChart({ title, sweep }: { title: string; sweep: any }) {
  const data = sweep.levels.map((lv: any, i: number) => {
    const row: any = { level: String(lv) };
    SWEEP_SERIES.forEach((s) => { row[s.key] = sweep.consumer[s.key]?.[i]?.f1 ?? null; });
    return row;
  });
  return (
    <div className="rounded border border-hair p-2">
      <div className="text-[12.5px] text-ink-2">{title}</div>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -20 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="level" stroke={AXIS} />
          <YAxis domain={[0, 1]} stroke={AXIS} />
          <Tooltip {...tip} formatter={(v: any, n: any) => [Number(v).toFixed(3), SWEEP_SERIES.find((s) => s.key === n)?.label ?? n]} />
          {SWEEP_SERIES.map((s) => (
            <Line key={s.key} dataKey={s.key} stroke={s.color} strokeWidth={s.width} dot={{ r: 4, strokeWidth: 2, stroke: "#0f1a2b", fill: s.color }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function SweepFeederTable({ sweeps }: { sweeps: any }) {
  return (
    <details className="mt-3 text-[12.5px]">
      <summary className="cursor-pointer text-ink-2">Every method, every sweep level (consumer F1 and feeder F1 / false-positive rate)</summary>
      {Object.entries(sweeps).map(([k, sw]: [string, any]) => (
        <div key={k} className="mt-3 overflow-x-auto">
          <div className="text-ink">{k}</div>
          <table className="mt-1 w-full tnum">
            <thead className="text-left text-ink-3"><tr><th className="font-normal">Method</th>{sw.levels.map((l: any) => <th key={String(l)} className="text-right font-normal">{String(l)}</th>)}</tr></thead>
            <tbody>
              {Object.entries(sw.consumer).map(([m, rows]: [string, any]) => (
                <tr key={m} className="border-t border-hair"><td className="py-1">consumer: {m}</td>{rows.map((x: any, i: number) => <td key={i} className="text-right">{f3(x.f1)}</td>)}</tr>
              ))}
              {Object.entries(sw.feeder).map(([m, rows]: [string, any]) => (
                <tr key={m} className="border-t border-hair"><td className="py-1">feeder: {m}</td>{rows.map((x: any, i: number) => <td key={i} className="text-right">{f3(x.f1)} <span className="text-ink-3">fpr {x.fpr.toFixed(3)}</span></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </details>
  );
}
