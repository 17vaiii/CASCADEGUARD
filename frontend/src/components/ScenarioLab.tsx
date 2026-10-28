import { Dices, FlaskConical, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type BaselineDiff, type ReplayResult } from "../lib/api";
import { activateSim, createAndActivate, runTask } from "../lib/controller";
import { fmt, INJECTION_LABEL } from "../lib/format";
import { useApp } from "../lib/store";
import type { SimConfig } from "../lib/types";

interface Draft {
  scenario: string;
  feeder: string;
  dt: string;
  n_consumers: number;
  magnitude: number;
  onset_day: number;
  duration_days: number;
  seed: number;
  noise_level: number;
  consumers_per_dt: number;
  benign_change_rate: number;
  base_missing_rate: number;
}

export function ScenarioLab() {
  const meta = useApp((s) => s.meta);
  const sim = useApp((s) => s.sim);
  const topo = useApp((s) => s.topo);
  const t = useApp((s) => s.t);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [diff, setDiff] = useState<BaselineDiff | null>(null);
  const [replay, setReplay] = useState<ReplayResult | null>(null);
  const [rules, setRules] = useState<Record<string, number> | null>(null);
  const [history, setHistory] = useState<Awaited<ReturnType<typeof api.listSims>>>([]);

  useEffect(() => {
    if (meta && !rules) setRules({ ...meta.rules_default });
  }, [meta, rules]);

  useEffect(() => {
    api.listSims().then(setHistory).catch(() => undefined);
  }, [sim]);

  // Start the draft from the active run (same seed and topology), so an injected scenario differs
  // from the current normal-operation run only by the injection.
  useEffect(() => {
    if (!sim || !meta) return;
    const c = sim.config;
    const inj = c.injections[0];
    const sc = meta.scenarios.find((s) => s.code === c.scenario);
    setDraft({
      scenario: c.scenario === "composite" ? "A" : c.scenario,
      feeder: inj?.feeder ?? "F2",
      dt: inj?.dt ?? "",
      n_consumers: inj?.n_consumers ?? 3,
      magnitude: inj?.magnitude ?? sc?.magnitude?.default ?? 50,
      onset_day: inj?.onset_day ?? 4,
      duration_days: inj?.duration_days ?? 8,
      seed: c.seed,
      noise_level: c.noise_level,
      consumers_per_dt: c.consumers_per_dt,
      benign_change_rate: c.benign_change_rate,
      base_missing_rate: c.base_missing_rate,
    });
    setDiff(null);
    setReplay(null);
  }, [sim, meta]);

  if (!meta || !draft || !sim || !topo) return <div className="p-4 text-ink-3">Loading scenario catalogue…</div>;
  const sc = meta.scenarios.find((s) => s.code === draft.scenario)!;
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft({ ...draft, [k]: v });
  const needsConsumers = ["B", "D", "E"].includes(draft.scenario);
  const allowsDt = ["B", "C", "D", "E"].includes(draft.scenario);
  const dts = topo.dts.filter((d) => d.feeder === draft.feeder);

  const configFromDraft = (scenario = draft.scenario): Partial<SimConfig> => {
    const s = meta.scenarios.find((x) => x.code === scenario)!;
    const base: Partial<SimConfig> = {
      scenario, seed: draft.seed, noise_level: draft.noise_level, consumers_per_dt: draft.consumers_per_dt,
      benign_change_rate: draft.benign_change_rate, base_missing_rate: draft.base_missing_rate,
      n_feeders: sim.config.n_feeders, dts_per_feeder: sim.config.dts_per_feeder,
      label: scenario === "A" ? `Normal operation (seed ${draft.seed})` : `${s.name} on ${draft.dt || draft.feeder}`,
      injections: [],
    };
    if (scenario !== "A" && s.injection) {
      base.injections = [{
        type: s.injection, feeder: draft.feeder, dt: allowsDt && draft.dt ? draft.dt : null,
        n_consumers: draft.n_consumers, magnitude: draft.magnitude, onset_day: draft.onset_day,
        duration_days: draft.duration_days,
      }];
    }
    return base;
  };

  const inject = async () => {
    const created = await createAndActivate(configFromDraft(), true, rules ?? undefined);
    if (created) setDiff(null);
  };
  const resetNormal = async () => {
    await createAndActivate(configFromDraft("A"), true, rules ?? undefined);
  };
  const RULE_FIELDS: [string, string, number, number, number][] = [
    ["consumer_shortfall", "Consumer shortfall (72 h, peer-adjusted)", 0.05, 0.95, 0.05],
    ["min_completeness", "Minimum reading completeness", 0, 1, 0.05],
    ["balance_ratio", "Balance rule: unexplained / input", 0, 0.5, 0.005],
    ["balance_z", "Balance rule: minimum z (σ)", 0.5, 10, 0.5],
    ["combined_dt_z", "Combined rule: DT imbalance z (σ)", 0.5, 10, 0.5],
  ];
  const showDiff = () => runTask("Comparing with normal operation…", async () => setDiff(await api.baselineDiff(sim.id, t)));
  const verify = () => runTask("Regenerating from seed…", async () => setReplay(await api.replay(sim.id, t)));

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <section className="border-b border-hair p-4">
        <h2 className="font-cond text-[16px] font-semibold">Scenario Lab</h2>
        <p className="mt-1 text-[12px] text-ink-3">Scenarios change synthetic numbers in a synthetic dataset. They describe no way of tampering with real meters.</p>

        <label className="mt-3 block text-[12px] text-ink-2">Scenario
          <select aria-label="Scenario" value={draft.scenario} onChange={(e) => {
            const s = meta.scenarios.find((x) => x.code === e.target.value)!;
            setDraft({ ...draft, scenario: e.target.value, magnitude: s.magnitude?.default ?? draft.magnitude });
          }} className="mt-1 w-full rounded border border-hair-strong bg-raised px-2 py-1.5 text-[13px] text-ink">
            {meta.scenarios.map((s) => <option key={s.code} value={s.code}>{s.code}. {s.name}</option>)}
          </select>
        </label>
        <p className="mt-1.5 text-[12px] leading-snug text-ink-2">{sc.summary}</p>

        {draft.scenario !== "A" && (
          <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5">
            <Field label="Feeder">
              <select aria-label="Feeder" value={draft.feeder} onChange={(e) => setDraft({ ...draft, feeder: e.target.value, dt: "" })} className={inputCls}>
                {topo.feeders.map((f) => <option key={f.id} value={f.id}>{f.id} ({f.archetype})</option>)}
              </select>
            </Field>
            {allowsDt && (
              <Field label={draft.scenario === "C" ? "DT (random if blank)" : "DT (optional)"}>
                <select aria-label="DT" value={draft.dt} onChange={(e) => set("dt", e.target.value)} className={inputCls}>
                  <option value="">Any DT</option>
                  {dts.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
                </select>
              </Field>
            )}
            {needsConsumers && (
              <Field label="Consumers affected">
                <NumberInput value={draft.n_consumers} min={1} max={20} step={1} onChange={(v) => set("n_consumers", v)} />
              </Field>
            )}
            {sc.magnitude && (
              <Field label={`${sc.magnitude.label} (${sc.magnitude.unit})`} wide>
                <div className="flex items-center gap-2">
                  <input type="range" min={sc.magnitude.min} max={sc.magnitude.max} step={1} value={draft.magnitude}
                    onChange={(e) => set("magnitude", Number(e.target.value))} className="flex-1 accent-[var(--color-flow)]" />
                  <span className="w-12 text-right tnum">{draft.magnitude}{sc.magnitude.unit === "%" ? "%" : "×"}</span>
                </div>
              </Field>
            )}
            <Field label="Onset (day 0–13)">
              <NumberInput value={draft.onset_day} min={0} max={13} step={0.5} onChange={(v) => set("onset_day", v)} />
            </Field>
            <Field label="Duration (days)">
              <NumberInput value={draft.duration_days} min={0.5} max={14} step={0.5} onChange={(v) => set("duration_days", v)} />
            </Field>
          </div>
        )}

        <details className="mt-3 text-[12px]">
          <summary className="cursor-pointer text-ink-2">Dataset and noise settings</summary>
          <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2.5">
            <Field label="Random seed">
              <div className="flex gap-1">
                <NumberInput value={draft.seed} min={0} max={2147483647} step={1} onChange={(v) => set("seed", v)} />
                <button title="Random seed" aria-label="Random seed" onClick={() => set("seed", Math.floor(Math.random() * 100000))}
                  className="rounded border border-hair-strong px-1.5 text-ink-2 hover:text-ink"><Dices size={14} /></button>
              </div>
            </Field>
            <Field label="Meter-noise level (×)"><NumberInput value={draft.noise_level} min={0.25} max={5} step={0.25} onChange={(v) => set("noise_level", v)} /></Field>
            <Field label="Consumers per DT"><NumberInput value={draft.consumers_per_dt} min={5} max={80} step={1} onChange={(v) => set("consumers_per_dt", v)} /></Field>
            <Field label="Genuine-drop rate"><NumberInput value={draft.benign_change_rate} min={0} max={0.2} step={0.01} onChange={(v) => set("benign_change_rate", v)} /></Field>
            <Field label="Base missing-reading rate"><NumberInput value={draft.base_missing_rate} min={0} max={0.2} step={0.005} onChange={(v) => set("base_missing_rate", v)} /></Field>
          </div>
          <p className="mt-2 text-ink-3">Changing seed or size generates a different synthetic population; keep them fixed to compare a scenario with normal operation.</p>
        </details>

        {rules && (
          <details className="mt-2 text-[12px]">
            <summary className="cursor-pointer text-ink-2">Detection rule thresholds</summary>
            <div className="mt-2 space-y-2">
              {RULE_FIELDS.map(([k, label, min, max, step]) => (
                <Field key={k} label={label}>
                  <NumberInput value={rules[k]} min={min} max={max} step={step} onChange={(v) => setRules({ ...rules, [k]: v })} />
                </Field>
              ))}
            </div>
            <p className="mt-2 text-ink-3">Applied when the next run is generated. Machine-learning thresholds are fixed by validation and are not changed here.</p>
          </details>
        )}

        <div className="mt-4 flex gap-2">
          <button onClick={inject} disabled={draft.scenario === "A"}
            className="flex flex-1 items-center justify-center gap-1.5 rounded bg-flow px-3 py-2 font-cond text-[14px] font-semibold text-plane hover:brightness-110 disabled:opacity-40">
            <FlaskConical size={15} /> Inject scenario
          </button>
          <button onClick={resetNormal} title="Same seed, no injection"
            className="flex items-center gap-1.5 rounded border border-hair-strong px-3 py-2 font-cond text-[14px] text-ink hover:bg-raised">
            <RotateCcw size={14} /> Normal operation
          </button>
        </div>
      </section>

      <section className="border-b border-hair p-4 text-[12px]">
        <h3 className="font-cond text-[14px] font-semibold">Active run</h3>
        <dl className="mt-1.5 space-y-0.5">
          <Row k="Label" v={sim.config.label ?? sim.config.scenario} />
          <Row k="Seed" v={String(sim.config.seed)} />
          <Row k="Consumers" v={`${sim.n_consumers} on ${sim.n_feeders} feeders, ${sim.n_dts} DTs`} />
          <Row k="Data fingerprint" v={sim.data_hash.slice(0, 12)} />
          <Row k="Duplicates removed at ingestion" v={String(sim.ingestion.duplicates_removed)} />
        </dl>
        {sim.events.length > 0 && (
          <ul className="mt-2 space-y-1">
            {sim.events.map((e) => (
              <li key={e.index} className="rounded border border-dashed border-truth/70 px-2 py-1">
                <div className="flex items-center gap-1.5 text-ink"><FlaskConical size={12} color="var(--color-truth)" />{INJECTION_LABEL[e.type]}</div>
                <div className="text-ink-3 tnum">{e.dt ?? e.feeder}, steps {e.start_step}–{e.end_step}, magnitude {e.magnitude}{e.consumers.length ? `, ${e.consumers.length} consumers` : ""}</div>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex gap-2">
          <button onClick={showDiff} disabled={sim.config.scenario === "A"} className="flex-1 rounded border border-hair-strong px-2 py-1.5 hover:bg-raised disabled:opacity-40">
            What changed vs normal?
          </button>
          <button onClick={verify} className="flex flex-1 items-center justify-center gap-1 rounded border border-hair-strong px-2 py-1.5 hover:bg-raised">
            <ShieldCheck size={13} /> Verify reproducibility
          </button>
        </div>
        {replay && (
          <div className={`mt-2 rounded border px-2 py-1.5 ${replay.data_identical ? "border-ok/50" : "border-alert/60"}`}>
            <div className="text-ink">{replay.data_identical ? "Regenerated from the seed: identical data" : "Regenerated data differs"}</div>
            <div className="text-ink-3 tnum">fingerprint {replay.replay_hash.slice(0, 12)}, max score difference {replay.max_abs_score_difference.toExponential(1)}, {replay.replay_ms.toFixed(0)} ms</div>
          </div>
        )}
        {history.length > 1 && (
          <details className="mt-3">
            <summary className="cursor-pointer text-ink-2">Run history ({history.length})</summary>
            <ul className="mt-1.5 space-y-1">
              {history.slice(0, 10).map((h) => (
                <li key={h.id}>
                  <button disabled={h.id === sim.id}
                    onClick={() => runTask("Reopening run…", async () => activateSim(await api.sim(h.id)))}
                    className="w-full rounded border border-hair px-2 py-1 text-left hover:bg-raised disabled:border-flow/60 disabled:opacity-100">
                    <div className="truncate text-ink">{h.label ?? h.scenario}</div>
                    <div className="text-ink-3 tnum">seed {h.seed}, {h.created_at.replace("T", " ")}, {h.n_detections} detection run(s)</div>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
        {diff && (
          <div className="mt-2 rounded border border-hair-strong px-2 py-1.5">
            <div className="text-ink">Measurements that differ from normal operation (same seed), up to this step</div>
            {diff.consumers.length === 0 && diff.dt_meters.length === 0 && diff.feeder_meters.length === 0 && diff.loss_estimate_factor_changed.length === 0 && diff.noise_multiplier_changed.length === 0 && (
              <div className="text-ink-3">None yet — the injection has not started at this step.</div>
            )}
            <ul className="mt-1 space-y-0.5 tnum">
              {diff.consumers.slice(0, 8).map((c) => (
                <li key={c.id} className="flex justify-between gap-2"><span>{c.id}</span>
                  <span className="text-ink-2">{c.difference_kwh !== 0 ? fmt.kwh(c.difference_kwh) : ""}{c.extra_missing_readings ? ` +${c.extra_missing_readings} missing` : ""}{c.extra_delayed_readings ? ` +${c.extra_delayed_readings} delayed` : ""}</span></li>
              ))}
              {diff.dt_meters.map((c) => <li key={c.id} className="flex justify-between"><span>DT meter {c.id}</span><span className="text-ink-2">{fmt.kwh(c.difference_kwh)}</span></li>)}
              {diff.feeder_meters.map((c) => <li key={c.id} className="flex justify-between"><span>Feeder meter {c.id}</span><span className="text-ink-2">{fmt.kwh(c.difference_kwh)}</span></li>)}
              {diff.loss_estimate_factor_changed.length > 0 && <li>Loss estimate changed on {diff.loss_estimate_factor_changed.join(", ")}</li>}
              {diff.noise_multiplier_changed.length > 0 && <li>Meter noise changed on {diff.noise_multiplier_changed.join(", ")}</li>}
            </ul>
            <p className="mt-1 text-ink-3">{diff.note}</p>
          </div>
        )}
      </section>
    </div>
  );
}

const inputCls = "mt-1 w-full rounded border border-hair-strong bg-raised px-2 py-1 text-[13px] text-ink";

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return <label className={`block text-[12px] text-ink-2 ${wide ? "col-span-2" : ""}`}>{label}{children}</label>;
}

function NumberInput({ value, min, max, step, onChange }: { value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <input type="number" value={value} min={min} max={max} step={step}
      onChange={(e) => {
        const v = Number(e.target.value);
        if (Number.isFinite(v)) onChange(Math.max(min, Math.min(max, v)));
      }}
      className={inputCls + " tnum"} />
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex justify-between gap-3"><dt className="text-ink-3">{k}</dt><dd className="truncate text-right tnum text-ink">{v}</dd></div>;
}
