import { ChevronRight, FlaskConical, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type ReplayResult } from "../../lib/api";
import { activateSim, runTask } from "../../lib/controller";
import { useApp } from "../../lib/store";

// Steps on the timeline used by the guided demo (demo injection starts on day 5 = step 120).
const BASELINE_T = 100;
const OBSERVE_UNTIL = 228;

interface Stage {
  title: string;
  body: (ctx: { replay: ReplayResult | null }) => React.ReactNode;
  next: string;
  action: () => Promise<void> | void;
}

async function stage1() {
  const s = useApp.getState();
  const demo = s.meta!.demo_config;
  // Normal operation with the demo's seed: identical background data, no injection.
  const sim = await api.createSim({ ...demo, scenario: "A", injections: [], label: `Normal operation (seed ${demo.seed})` });
  await activateSim(sim);
  const st = useApp.getState();
  st.setView("twin");
  st.select(null);
  st.setShowTruth(false);
  st.setAlerts(null);
  st.setT(BASELINE_T);
}

async function stage2() {
  const sim = await api.createDemo(); // the same creation path as Scenario Lab, with a fixed configuration
  await activateSim(sim, true);
  const st = useApp.getState();
  st.setT(BASELINE_T);
  st.setShowTruth(true);
  st.setLabOpen(true);
  st.select({ kind: "feeder", id: "F2" });
}

function stage3() {
  const st = useApp.getState();
  st.setView("twin");
  st.setLabOpen(false);
  st.setSpeed(16);
  st.setPlaying(true);
}

async function stage4() {
  const st = useApp.getState();
  st.setPlaying(false);
  st.setT(OBSERVE_UNTIL);
  const res = await api.detect(st.sim!.id, OBSERVE_UNTIL, "rf_combined", "rf_unit_combined");
  useApp.getState().setMethods("rf_combined", "rf_unit_combined");
  useApp.getState().setAlerts(res);
}

function stage5() {
  const st = useApp.getState();
  const top = st.alerts?.alerts.find((a) => a.kind === "consumer") ?? st.alerts?.alerts[0];
  if (top) st.select(top.kind === "consumer" ? { kind: "consumer", id: top.id } : { kind: top.kind, id: top.id });
  st.setInvestigateTab("detail");
  st.setView("investigate");
}

function stage6() {
  const st = useApp.getState();
  st.setInvestigateTab("compare");
  st.setView("investigate");
}

export function startDemo() {
  const st = useApp.getState();
  if (!st.meta) return;
  st.setDemoStage(0);
  runTask("Preparing normal operation…", stage1);
}

export function DemoGuide() {
  const stage = useApp((s) => s.demoStage);
  const t = useApp((s) => s.t);
  const playing = useApp((s) => s.playing);
  const sim = useApp((s) => s.sim);
  const [replay, setReplay] = useState<ReplayResult | null>(null);

  // Stage 3 plays the timeline and stops at the analysis step.
  useEffect(() => {
    if (stage === 2 && playing && t >= OBSERVE_UNTIL) useApp.getState().setPlaying(false);
  }, [stage, t, playing]);

  if (stage == null) return null;

  const stages: Stage[] = [
    {
      title: "Normal network",
      body: () => (
        <>This is normal operation on day 5 of a synthetic fortnight. Power flows from the interconnected 220 kV network through the receiving
          station to four 11 kV feeders; the moving dots follow the solved AC power flow. Energy is accounted at each feeder head and each DT
          meter against the consumer smart meters behind it. Every feeder&apos;s unexplained energy is near zero.</>
      ),
      next: "Introduce a simulated anomaly",
      action: () => runTask("Injecting the demo scenario…", stage2).then(() => undefined),
    },
    {
      title: "Introduce a simulated anomaly",
      body: () => (
        <>The Scenario Lab configuration is now <strong>Scenario D, persistent consumption anomaly</strong> on feeder F2: four consumers&apos;
          recorded consumption falls by up to 65% in their usual peak hours from day 6, ramping in over 72 hours, while the energy they draw
          is unchanged. The seed is the same, so all other data is identical to the normal run. Orange markers show simulation ground truth,
          which a real utility would not have.</>
      ),
      next: "Play the timeline",
      action: stage3,
    },
    {
      title: "Observe the measurements",
      body: () => (
        <>The timeline is playing to day 10. Watch feeder F2: its feeder-head meter still measures the full energy, the consumer meters
          record less, and the unexplained energy on the F2 details chart rises above the 3% rule line. The feeder and DT colours follow the
          detection score at each step. {playing ? "Playing…" : t >= OBSERVE_UNTIL ? "Reached day 10." : ""}</>
      ),
      next: "Run detection",
      action: () => runTask("Running detectors…", stage4).then(() => undefined),
    },
    {
      title: "Run detection",
      body: () => (
        <>The Random Forest on consumer and grid features and the boundary model ran on the data available at this step. The alert list on
          the right shows their actual outputs, ranked by inspection priority. Click any alert to highlight it on the diagram.</>
      ),
      next: "Investigate the top alert",
      action: stage5,
    },
    {
      title: "Investigate the alert",
      body: () => (
        <>The explanation is generated from this consumer&apos;s readings and its DT&apos;s energy balance; the bars show how each feature moved
          the classifier score. The priority depends on whether the DT balance corroborates the consumer-level deviation.</>
      ),
      next: "Compare methods",
      action: stage6,
    },
    {
      title: "Compare methods",
      body: () => (
        <>Every method was run on the same step. The table counts flags against simulation truth. Look for consumers the threshold rule flags
          but the combined model does not: usually genuine consumption drops that the DT energy balance does not corroborate.</>
      ),
      next: "Reset and verify reproducibility",
      action: () => runTask("Regenerating from the seed…", async () => {
        const st = useApp.getState();
        setReplay(await api.replay(st.sim!.id, OBSERVE_UNTIL));
        st.setView("twin");
        st.setT(0);
        st.select(null);
      }).then(() => undefined),
    },
    {
      title: "Reset and repeat",
      body: ({ replay }) => (
        <>The timeline is back at step 0. The run was regenerated from its configuration and seed:{" "}
          {replay ? (replay.data_identical ? `identical data fingerprint (${replay.replay_hash.slice(0, 12)}) and a maximum detector-score difference of ${replay.max_abs_score_difference === 0 ? "exactly 0" : replay.max_abs_score_difference.toExponential(1)}.`
            : "the regenerated data differed — see the console.") : "checking…"} Start the demo again to replay it.</>
      ),
      next: "Restart the demo",
      action: () => { setReplay(null); startDemo(); },
    },
  ];
  const s = stages[stage];
  const advance = () => {
    const n = stage + 1;
    Promise.resolve(s.action()).then(() => useApp.getState().setDemoStage(n >= stages.length ? 0 : n));
  };
  return (
    <div role="dialog" aria-label="Guided demonstration"
      className="fixed bottom-[100px] right-[396px] z-40 w-[500px] rounded-lg border border-flow/70 bg-panel p-4 shadow-2xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-cond text-[13px] text-ink-2">
          <span className="rounded bg-flow px-1.5 font-semibold text-plane tnum">{stage + 1} / {stages.length}</span>
          Guided demonstration
          <span className="flex items-center gap-1 text-ink-3"><FlaskConical size={12} color="var(--color-truth)" /> simulated data</span>
        </div>
        <button aria-label="Exit demo" onClick={() => { useApp.getState().setDemoStage(null); useApp.getState().setPlaying(false); }} className="text-ink-3 hover:text-ink"><X size={16} /></button>
      </div>
      <h2 className="mt-2 font-cond text-[19px] font-semibold">{s.title}</h2>
      <p className="mt-1 text-[13.5px] leading-relaxed text-ink-2">{s.body({ replay })}</p>
      <div className="mt-3 flex items-center justify-between">
        <span className="text-[12px] text-ink-3 tnum">{sim ? `Run ${sim.id}, seed ${sim.config.seed}` : ""}</span>
        <button onClick={advance} disabled={stage === 2 && playing}
          className="flex items-center gap-1 rounded bg-flow px-3 py-1.5 font-cond text-[14px] font-semibold text-plane hover:brightness-110 disabled:opacity-40">
          {s.next} <ChevronRight size={15} />
        </button>
      </div>
    </div>
  );
}
