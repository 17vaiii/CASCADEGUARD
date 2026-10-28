import { Activity, ArrowRightLeft, Scale, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { runTask } from "../lib/controller";
import { fmt } from "../lib/format";
import { useApp } from "../lib/store";
import type { ConsumerRow, ConsumerSeries, UnitSeries, UnitState } from "../lib/types";
import { StatusIcon } from "../features/twin/nodes";
import { AlertListItem, ExplanationCard } from "./AlertCard";
import { BalanceTrendChart, ConsumerChart } from "./charts";

export function SidePanel() {
  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto border-b border-hair p-4"><Details /></div>
      <div className="flex max-h-[46%] min-h-[220px] flex-col"><Alerts /></div>
    </div>
  );
}

function Details() {
  const sel = useApp((s) => s.selection);
  if (!sel) return <Overview />;
  if (sel.kind === "bus") return <BusDetails id={sel.id} />;
  if (sel.kind === "consumer") return <ConsumerDetails id={sel.id} />;
  return <UnitDetails kind={sel.kind} id={sel.id} />;
}

function Overview() {
  const st = useApp((s) => s.state);
  const select = useApp((s) => s.select);
  const pf = st?.power_flow;
  const feederMw = st?.units.feeder.reduce((a, u) => a + (pf?.branches?.[`${u.id}-MV1`]?.p_from_mw ?? 0), 0) ?? 0;
  const corridor = Math.abs(pf?.branches?.["L220-TXA-SRS"]?.p_from_mw ?? 0);
  return (
    <div className="space-y-3">
      <h2 className="font-cond text-[16px] font-semibold">Feeders at this step</h2>
      <p className="text-[12px] text-ink-3">Select a feeder, DT or bus on the diagram for its measurements.</p>
      <ul className="space-y-1.5">
        {st?.units.feeder.map((u) => (
          <li key={u.id}>
            <button onClick={() => select({ kind: "feeder", id: u.id })} className="w-full rounded border border-hair px-2.5 py-2 text-left hover:border-hair-strong hover:bg-raised/60">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 font-cond text-[14px] font-semibold">{u.id}<StatusIcon status={u.status} size={13} /></span>
                <span className="text-[12px] text-ink-3 tnum">score {u.score.toFixed(2)} / {u.threshold.toFixed(2)}</span>
              </div>
              <div className="mt-0.5 text-[12px] text-ink-2 tnum">Unexplained 24 h: {fmt.kwh(u.balance_24h.unexplained_kwh)} ({fmt.pct(u.balance_24h.ratio)}, {fmt.sigma(u.balance_24h.z)})</div>
            </button>
          </li>
        ))}
      </ul>
      {pf?.converged && corridor > 0 && (
        <div className="rounded border border-hair p-2.5 text-[12px] text-ink-2">
          <div className="mb-1 flex items-center gap-1.5 text-ink"><ArrowRightLeft size={13} /> Why accounting happens at feeder and DT level</div>
          The four modelled feeders draw {fmt.mw(feederMw, 3)} in total, which is {(100 * feederMw / corridor).toFixed(2)}% of the
          {" "}{fmt.mw(corridor, 0)} flowing on the 220 kV line into the receiving station in this snapshot. A few kilowatts of
          unrecorded consumption cannot be resolved against transmission flows set by generation dispatch, so energy balances are
          computed where metering brackets a small set of consumers.
        </div>
      )}
    </div>
  );
}

function BusDetails({ id }: { id: string }) {
  const topo = useApp((s) => s.topo)!;
  const st = useApp((s) => s.state);
  const bus = topo.buses.find((b) => b.id === id);
  if (!bus) return null;
  const r = st?.power_flow.buses?.[id];
  const conns = topo.branches.filter((b) => b.from_bus === id || b.to_bus === id);
  return (
    <div className="space-y-3 text-[12.5px]">
      <h2 className="font-cond text-[16px] font-semibold">{bus.label}</h2>
      <span className="inline-block rounded border border-hair-strong px-1.5 text-[11px] text-ink-2">
        {bus.provenance === "public-source" ? "Name anchored to public sources" : bus.provenance === "illustrative" ? "Illustrative element" : "Modelling assumption"}
      </span>
      <p className="text-ink-2">{bus.description}</p>
      <dl className="space-y-0.5">
        <KV k="Nominal voltage" v={`${bus.vn_kv} kV`} />
        {r?.vm_pu != null && <KV k="Voltage (AC power flow)" v={`${r.vm_pu.toFixed(4)} pu`} />}
        {r?.va_degree != null && <KV k="Voltage angle" v={`${r.va_degree.toFixed(2)}°`} />}
      </dl>
      <div>
        <div className="mb-1 text-ink-3">Connected branches (power-flow result at this step)</div>
        <ul className="space-y-1">
          {conns.map((b) => {
            const f = st?.power_flow.branches?.[b.id];
            return (
              <li key={b.id} className="rounded border border-hair px-2 py-1">
                <div className="text-ink">{b.label}</div>
                {f && <div className="text-ink-3 tnum">P {fmt.mw(f.p_from_mw, 3)} from {b.from_bus}, loading {f.loading_pct.toFixed(1)}%, losses {fmt.kw(f.loss_mw * 1000, 1)}</div>}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function UnitDetails({ kind, id }: { kind: "feeder" | "dt"; id: string }) {
  const sim = useApp((s) => s.sim)!;
  const st = useApp((s) => s.state);
  const t = useApp((s) => s.t);
  const showTruth = useApp((s) => s.showTruth);
  const cm = useApp((s) => s.consumerMethod);
  const { setView, select } = useApp.getState();
  const u: UnitState | undefined = st?.units[kind].find((x) => x.id === id);
  const [series, setSeries] = useState<UnitSeries | null>(null);
  const [rows, setRows] = useState<ConsumerRow[]>([]);
  const bucket = Math.floor(t / 6);
  useEffect(() => {
    let live = true;
    api.unitSeries(sim.id, kind, id, t).then((s) => live && setSeries(s)).catch(() => undefined);
    api.consumers(sim.id, t, kind === "dt" ? { dt: id, method: cm } : { feeder: id, method: cm }).then((r) => live && setRows(r)).catch(() => undefined);
    return () => { live = false; };
    // refresh every 6 simulated hours while playing; t itself is read when the bucket changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.id, kind, id, bucket, cm]);
  return (
    <div className="space-y-3 text-[12.5px]">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 font-cond text-[16px] font-semibold">{kind === "feeder" ? `Feeder ${id}` : `DT ${id}`}{u && <StatusIcon status={u.status} />}</h2>
        {u && <span className="text-ink-3 tnum">score {u.score.toFixed(2)} (alert at {u.threshold.toFixed(2)})</span>}
      </div>
      {u && (
        <dl className="space-y-0.5 tnum">
          <KV k={kind === "feeder" ? "Feeder-head meter, last 24 h" : "DT meter, last 24 h"} v={fmt.kwh(u.balance_24h.input_kwh)} />
          <KV k="Consumer meters" v={fmt.kwh(u.balance_24h.metered_kwh)} />
          <KV k="Imputed for missing readings" v={fmt.kwh(u.balance_24h.imputed_kwh)} />
          <KV k="Estimated technical losses" v={fmt.kwh(u.balance_24h.loss_est_kwh)} />
          <KV k="Unexplained" v={`${fmt.kwh(u.balance_24h.unexplained_kwh)} (${fmt.pct(u.balance_24h.ratio)}, ${fmt.sigma(u.balance_24h.z)})`} strong />
          <KV k="Reading coverage" v={fmt.pct(u.balance_24h.coverage)} />
          <KV k="Consumers flagged (selected method)" v={`${u.consumers_flagged} of ${u.consumers}`} />
        </dl>
      )}
      <p className="text-[11.5px] text-ink-3">Unexplained energy imbalance is an investigation signal, not proof of electricity theft.</p>
      {series && <BalanceTrendChart s={series} t={t} showTruth={showTruth} height={150} startTs={sim.start_timestamp} />}
      <div className="flex gap-2">
        <button onClick={() => setView("energy")} className="flex flex-1 items-center justify-center gap-1.5 rounded border border-hair-strong py-1.5 hover:bg-raised"><Scale size={13} /> Energy balance</button>
        <button onClick={() => setView("investigate")} className="flex flex-1 items-center justify-center gap-1.5 rounded border border-hair-strong py-1.5 hover:bg-raised"><Search size={13} /> Investigate</button>
      </div>
      <div>
        <div className="mb-1 text-ink-3">Consumers ranked by the selected consumer method</div>
        <table className="w-full text-[12px] tnum">
          <thead className="text-left text-ink-3"><tr><th className="font-normal">Consumer</th><th className="font-normal">72 h vs expected</th><th className="text-right font-normal">Score</th></tr></thead>
          <tbody>
            {rows.slice(0, 8).map((r) => (
              <tr key={r.id} className="cursor-pointer border-t border-hair hover:bg-raised/60" onClick={() => select({ kind: "consumer", id: r.id })}>
                <td className="py-1">{r.id.replace("C-", "")} <span className="text-ink-3">{r.category.slice(0, 3)}</span></td>
                <td>{fmt.pct(r.ratio_72, 0)}</td>
                <td className={`text-right ${r.flagged ? "font-semibold text-alert" : ""}`}>{r.score.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ConsumerDetails({ id }: { id: string }) {
  const sim = useApp((s) => s.sim)!;
  const t = useApp((s) => s.t);
  const showTruth = useApp((s) => s.showTruth);
  const alerts = useApp((s) => s.alerts);
  const setView = useApp((s) => s.setView);
  const [s, setS] = useState<ConsumerSeries | null>(null);
  useEffect(() => {
    let live = true;
    api.consumerSeries(sim.id, id).then((x) => live && setS(x)).catch(() => undefined);
    return () => { live = false; };
  }, [sim.id, id]);
  const alert = alerts?.alerts.find((a) => a.kind === "consumer" && a.id === id);
  return (
    <div className="space-y-3 text-[12.5px]">
      <h2 className="font-cond text-[16px] font-semibold">Consumer {id}</h2>
      <div className="text-ink-3">{s ? `${s.category}, supplied by ${s.dt} on feeder ${s.feeder}. Synthetic identifier.` : "Loading…"}</div>
      {s && <ConsumerChart s={s} t={t} start={Math.max(0, t - 96)} showTruth={showTruth} height={170} startTs={sim.start_timestamp} />}
      {alert ? <ExplanationCard a={alert} compact /> : <div className="text-ink-3">Not flagged in the latest detection run.</div>}
      <button onClick={() => setView("investigate")} className="flex w-full items-center justify-center gap-1.5 rounded border border-hair-strong py-1.5 hover:bg-raised"><Search size={13} /> Open full investigation</button>
    </div>
  );
}

function Alerts() {
  const sim = useApp((s) => s.sim);
  const meta = useApp((s) => s.meta);
  const t = useApp((s) => s.t);
  const cm = useApp((s) => s.consumerMethod);
  const um = useApp((s) => s.unitMethod);
  const alerts = useApp((s) => s.alerts);
  const sel = useApp((s) => s.selection);
  const { setMethods, setAlerts, select } = useApp.getState();
  const run = () => sim && runTask("Running detectors…", async () => setAlerts(await api.detect(sim.id, t, cm, um)));
  const stale = alerts && alerts.t !== t;
  return (
    <div className="flex min-h-0 flex-1 flex-col p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-cond text-[16px] font-semibold">Detection</h2>
        <button onClick={run} className="flex items-center gap-1.5 rounded bg-flow px-3 py-1.5 font-cond text-[13.5px] font-semibold text-plane hover:brightness-110">
          <Activity size={14} /> Run detection at this step
        </button>
      </div>
      {meta && (
        <div className="mt-2 grid grid-cols-2 gap-2 text-[11.5px] text-ink-3">
          <label>Consumer method
            <select value={cm} onChange={(e) => setMethods(e.target.value)} className="mt-0.5 w-full rounded border border-hair-strong bg-raised px-1.5 py-1 text-[12px] text-ink">
              {Object.entries(meta.consumer_methods).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
            </select>
          </label>
          <label>Feeder / DT method
            <select value={um} onChange={(e) => setMethods(undefined, e.target.value)} className="mt-0.5 w-full rounded border border-hair-strong bg-raised px-1.5 py-1 text-[12px] text-ink">
              {Object.entries(meta.unit_methods).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
            </select>
          </label>
        </div>
      )}
      <div className="mt-2 min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
        {!alerts && <p className="text-[12px] text-ink-3">Run detection to execute the selected methods on the data available at this step.</p>}
        {alerts && (
          <p className="text-[11.5px] text-ink-3 tnum">
            {alerts.n_alerts} alerts at step {alerts.t} in {alerts.compute_ms.toFixed(0)} ms{stale ? ". The timeline has moved; run again for the current step." : "."}
          </p>
        )}
        {alerts?.alerts.map((a) => (
          <AlertListItem key={`${a.kind}-${a.id}`} a={a}
            active={!!sel && sel.id === a.id}
            onClick={() => select(a.kind === "consumer" ? { kind: "consumer", id: a.id } : { kind: a.kind, id: a.id })} />
        ))}
      </div>
    </div>
  );
}

function KV({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return <div className="flex justify-between gap-3"><dt className="text-ink-3">{k}</dt><dd className={`text-right ${strong ? "font-semibold text-ink" : "text-ink-2"}`}>{v}</dd></div>;
}
