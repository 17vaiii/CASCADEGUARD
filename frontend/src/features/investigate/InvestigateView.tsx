import { Activity, FlaskConical, GitCompare } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AlertListItem, ExplanationCard } from "../../components/AlertCard";
import { BalanceTrendChart, ConsumerChart, DailyDifferenceChart, ScoreChart } from "../../components/charts";
import { api } from "../../lib/api";
import { runTask } from "../../lib/controller";
import { fmt, stepLabel } from "../../lib/format";
import { useApp } from "../../lib/store";
import type { CompareResponse, ConsumerSeries, UnitSeries } from "../../lib/types";

export function InvestigateView() {
  const sim = useApp((s) => s.sim)!;
  const t = useApp((s) => s.t);
  const alerts = useApp((s) => s.alerts);
  const sel = useApp((s) => s.selection);
  const cm = useApp((s) => s.consumerMethod);
  const um = useApp((s) => s.unitMethod);
  const { select, setAlerts } = useApp.getState();
  const tab = useApp((s) => s.investigateTab);
  const setTab = useApp((s) => s.setInvestigateTab);
  const [search, setSearch] = useState("");
  const run = () => runTask("Running detectors…", async () => setAlerts(await api.detect(sim.id, t, cm, um)));

  return (
    <div className="grid h-full grid-cols-[300px_minmax(0,1fr)] overflow-hidden">
      <aside className="flex min-h-0 flex-col border-r border-hair bg-panel p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-cond text-[16px] font-semibold">Alerts</h2>
          <button onClick={run} className="flex items-center gap-1 rounded bg-flow px-2.5 py-1 font-cond text-[13px] font-semibold text-plane"><Activity size={13} /> Run at step {t}</button>
        </div>
        {alerts && <p className="mt-1 text-[11.5px] text-ink-3 tnum">{alerts.n_alerts} alerts at step {alerts.t}, ranked by inspection priority.</p>}
        <form className="mt-2" onSubmit={(e) => { e.preventDefault(); const id = search.trim().toUpperCase(); if (id) select({ kind: "consumer", id: id.startsWith("C-") ? id : `C-${id}` }); }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Open consumer, e.g. C-F2-DT1-009"
            className="w-full rounded border border-hair-strong bg-raised px-2 py-1.5 text-[12.5px] text-ink placeholder:text-ink-3" />
        </form>
        <div className="mt-2 min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
          {!alerts && <p className="text-[12px] text-ink-3">No detection run yet for this simulation. Run the detectors at the current step.</p>}
          {alerts?.alerts.map((a) => (
            <AlertListItem key={`${a.kind}-${a.id}`} a={a} active={sel?.id === a.id}
              onClick={() => { select(a.kind === "consumer" ? { kind: "consumer", id: a.id } : { kind: a.kind, id: a.id }); setTab("detail"); }} />
          ))}
        </div>
      </aside>
      <section className="min-w-0 overflow-y-auto p-5">
        <div className="mb-4 flex gap-1 border-b border-hair">
          {([["detail", "Selected alert"], ["compare", "Compare methods at this step"]] as const).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} className={`relative px-3 pb-2 font-cond text-[14px] ${tab === id ? "text-ink" : "text-ink-3"}`}>
              {label}{tab === id && <span className="absolute inset-x-2 bottom-0 h-[2px] bg-flow" />}
            </button>
          ))}
        </div>
        {tab === "compare" ? <Compare /> : !sel || sel.kind === "bus" ? (
          <p className="text-ink-3">Select an alert, a consumer, a feeder or a DT to investigate it.</p>
        ) : sel.kind === "consumer" ? <ConsumerInvestigation id={sel.id} /> : <UnitInvestigation kind={sel.kind} id={sel.id} />}
      </section>
    </div>
  );
}

function ConsumerInvestigation({ id }: { id: string }) {
  const sim = useApp((s) => s.sim)!;
  const meta = useApp((s) => s.meta)!;
  const t = useApp((s) => s.t);
  const showTruth = useApp((s) => s.showTruth);
  const alerts = useApp((s) => s.alerts);
  const cm = useApp((s) => s.consumerMethod);
  const [s, setS] = useState<ConsumerSeries | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [method, setMethod] = useState(cm);
  const bucket = Math.floor(t / 12);
  useEffect(() => {
    let live = true;
    setErr(null);
    api.consumerSeries(sim.id, id).then((x) => live && setS(x)).catch((e) => live && setErr(e.message));
    return () => { live = false; };
    // re-fetch periodically so background-computed score history fills in
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.id, id, bucket]);
  const alert = alerts?.alerts.find((a) => a.kind === "consumer" && a.id === id);
  const stats = useMemo(() => {
    if (!s) return null;
    let o = 0, e = 0, missing = 0, pending = 0;
    for (let i = Math.max(0, t - 167); i <= t; i++) {
      const arrived = s.arrival_step[i] >= 0 && s.arrival_step[i] <= t;
      if (arrived && s.observed_kwh[i] != null) { o += s.observed_kwh[i]!; e += s.expected_kwh[i]; }
      else if (s.arrival_step[i] < 0) missing++;
      else pending++;
    }
    return { o, e, missing, pending };
  }, [s, t]);
  if (err) return <p className="text-alert">{err}</p>;
  if (!s) return <p className="text-ink-3">Loading consumer {id}…</p>;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="font-cond text-[22px] font-semibold">Consumer {id}</h1>
        <span className="text-[13px] text-ink-2">{s.category}, supplied by {s.dt} on feeder {s.feeder}; synthetic identifier</span>
      </div>
      {stats && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Recorded, last 7 days" value={fmt.kwh(stats.o)} />
          <Stat label="Expected for the same hours" value={fmt.kwh(stats.e)} />
          <Stat label="Recorded vs expected" value={stats.e > 0 ? fmt.pct(stats.o / stats.e, 0) : "–"} />
          <Stat label="Readings missing / pending" value={`${stats.missing} / ${stats.pending}`} />
        </div>
      )}
      <div className="rounded-md border border-hair bg-panel p-4">
        <div className="font-cond text-[15px] font-semibold">Hourly consumption as known at {stepLabel(sim.start_timestamp, t)}</div>
        <ConsumerChart s={s} t={t} start={0} showTruth={showTruth} height={260} brush startTs={sim.start_timestamp} />
        <p className="text-[12px] text-ink-3">Drag the handles under the chart to zoom. Gaps are readings that never arrived or had not arrived by this step.</p>
      </div>
      <div className="rounded-md border border-hair bg-panel p-4">
        <div className="font-cond text-[15px] font-semibold">Difference from the expected profile, by day</div>
        <DailyDifferenceChart s={s} t={t} />
      </div>
      <div className="rounded-md border border-hair bg-panel p-4">
        <div className="flex items-center justify-between">
          <div className="font-cond text-[15px] font-semibold">Score history</div>
          <select value={method} onChange={(e) => setMethod(e.target.value)} className="rounded border border-hair-strong bg-raised px-1.5 py-1 text-[12px]">
            {Object.entries(meta.consumer_methods).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
          </select>
        </div>
        <ScoreChart scores={s.scores[method]} threshold={s.thresholds[method]} t={t} label={meta.consumer_methods[method].name} startTs={sim.start_timestamp} />
      </div>
      <div className="rounded-md border border-hair bg-panel p-4">
        <div className="mb-2 font-cond text-[15px] font-semibold">Explanation</div>
        {alert ? <ExplanationCard a={alert} /> : <p className="text-[13px] text-ink-3">This consumer is not in the latest detection run's alerts. Run detection at this step to generate an explanation.</p>}
      </div>
    </div>
  );
}

function UnitInvestigation({ kind, id }: { kind: "feeder" | "dt"; id: string }) {
  const sim = useApp((s) => s.sim)!;
  const meta = useApp((s) => s.meta)!;
  const t = useApp((s) => s.t);
  const showTruth = useApp((s) => s.showTruth);
  const alerts = useApp((s) => s.alerts);
  const um = useApp((s) => s.unitMethod);
  const [s, setS] = useState<UnitSeries | null>(null);
  const [method, setMethod] = useState(um);
  const bucket = Math.floor(t / 6);
  useEffect(() => {
    let live = true;
    api.unitSeries(sim.id, kind, id, t).then((x) => live && setS(x)).catch(() => undefined);
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.id, kind, id, bucket]);
  const alert = alerts?.alerts.find((a) => a.kind === kind && a.id === id);
  const unm = s?.truth.unmetered_kw.reduce<number>((a, v) => a + (v ?? 0), 0) ?? 0;
  return (
    <div className="space-y-5">
      <h1 className="font-cond text-[22px] font-semibold">{kind === "feeder" ? `Feeder ${id}` : `Distribution transformer ${id}`}</h1>
      {s && (
        <div className="rounded-md border border-hair bg-panel p-4">
          <div className="font-cond text-[15px] font-semibold">Energy balance over time</div>
          <BalanceTrendChart s={s} t={t} showTruth={showTruth} height={230} startTs={sim.start_timestamp} />
          {showTruth && unm > 0 && (
            <p className="mt-1 flex items-center gap-1.5 text-[12px] text-ink-2"><FlaskConical size={12} color="var(--color-truth)" />Simulation truth: {fmt.kwh(unm)} of unmetered load inside this boundary so far.</p>
          )}
        </div>
      )}
      {s && (
        <div className="rounded-md border border-hair bg-panel p-4">
          <div className="flex items-center justify-between">
            <div className="font-cond text-[15px] font-semibold">Score history</div>
            <select value={method} onChange={(e) => setMethod(e.target.value)} className="rounded border border-hair-strong bg-raised px-1.5 py-1 text-[12px]">
              {Object.entries(meta.unit_methods).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
            </select>
          </div>
          <ScoreChart scores={s.scores[method]} threshold={s.thresholds[method]} t={t} label={meta.unit_methods[method].name} startTs={sim.start_timestamp} />
        </div>
      )}
      <div className="rounded-md border border-hair bg-panel p-4">
        <div className="mb-2 font-cond text-[15px] font-semibold">Explanation</div>
        {alert ? <ExplanationCard a={alert} /> : <p className="text-[13px] text-ink-3">This boundary is not in the latest detection run's alerts.</p>}
      </div>
    </div>
  );
}

function Compare() {
  const sim = useApp((s) => s.sim)!;
  const t = useApp((s) => s.t);
  const [c, setC] = useState<CompareResponse | null>(null);
  useEffect(() => {
    let live = true;
    runTask("Comparing methods…", async () => { const r = await api.compare(sim.id, t); if (live) setC(r); });
    return () => { live = false; };
  }, [sim.id, t]);
  if (!c) return <p className="text-ink-3">Running every method at step {t}…</p>;
  return (
    <div className="space-y-5">
      <p className="flex items-start gap-1.5 text-[12.5px] text-ink-2"><GitCompare size={14} className="mt-0.5" />All methods were executed on the same data at {stepLabel(sim.start_timestamp, t)}. {c.note}</p>
      <div className="rounded-md border border-hair bg-panel p-4">
        <div className="font-cond text-[15px] font-semibold">Consumer level</div>
        <table className="mt-2 w-full text-[12.5px] tnum">
          <thead className="text-left text-ink-3">
            <tr><th className="py-1 font-normal">Method</th><th className="font-normal">Signals</th><th className="text-right font-normal">Flagged</th><th className="text-right font-normal">Theft-like (TP)</th><th className="text-right font-normal">Clean (FP)</th><th className="text-right font-normal">Missed</th><th className="text-right font-normal">Genuine drops flagged</th><th className="text-right font-normal">Data faults flagged</th></tr>
          </thead>
          <tbody>
            {c.consumer_methods.map((m) => (
              <tr key={m.method} className="border-t border-hair">
                <td className="py-1.5 text-ink">{m.name}</td><td className="text-ink-3">{m.signals}</td>
                <td className="text-right">{m.flagged}</td><td className="text-right">{m.true_positives}</td><td className="text-right">{m.false_positives}</td>
                <td className="text-right">{m.missed}</td><td className="text-right">{m.flagged_benign_changes}</td><td className="text-right">{m.flagged_data_faults}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[12px] text-ink-3">The feeder energy-balance rule gives every consumer on a flagged feeder the same score, so it cannot point to individual meters.</p>
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        {(["feeder", "dt"] as const).map((k) => (
          <div key={k} className="rounded-md border border-hair bg-panel p-4">
            <div className="font-cond text-[15px] font-semibold">{k === "feeder" ? "Feeder level" : "DT level"}</div>
            <div className="mt-1 text-[12px] text-ink-3">Boundaries with a theft-like event in the last 24 h (simulation truth): {c.unit_methods[k][0]?.truth_ids.join(", ") || "none"}</div>
            <table className="mt-2 w-full text-[12.5px]">
              <tbody>
                {c.unit_methods[k].map((m) => (
                  <tr key={m.method} className="border-t border-hair">
                    <td className="py-1.5 text-ink">{m.name}</td>
                    <td className="text-right text-ink-2">{m.flagged_ids.length ? m.flagged_ids.join(", ") : "none flagged"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <div className="rounded-md border border-hair bg-panel p-4">
        <div className="font-cond text-[15px] font-semibold">Where the consumer rule and the combined Random Forest disagree</div>
        {c.disagreements.items.length === 0 && <p className="mt-1 text-[12.5px] text-ink-3">They agree on every consumer at this step.</p>}
        <ul className="mt-2 space-y-2">
          {c.disagreements.items.map((d) => (
            <li key={d.consumer} className="rounded border border-hair px-3 py-2 text-[12.5px]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-cond text-[14px] font-semibold">{d.consumer}</span>
                <span className="text-ink-3">flagged only by {d.flagged_by === "consumer_rule" ? "the consumer rule" : "the combined Random Forest"}</span>
              </div>
              <p className="mt-0.5 text-ink-2">{d.explanation}</p>
              <p className="mt-0.5 flex items-center gap-1 text-ink-3"><FlaskConical size={11} color="var(--color-truth)" /> Truth: {d.truth.theft_like ? "theft-like injection" : d.truth.benign_change ? "genuine consumption drop" : d.truth.data_fault ? "data fault" : "normal consumer"}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-hair bg-panel px-3 py-2">
      <div className="text-[12px] text-ink-3">{label}</div>
      <div className="font-cond text-[19px] font-semibold">{value}</div>
    </div>
  );
}
