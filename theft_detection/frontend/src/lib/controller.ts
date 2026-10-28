import { useEffect, useRef } from "react";
import { api } from "./api";
import { useApp } from "./store";
import type { SimConfig, SimSummary } from "./types";

const LAST_SIM_KEY = "gridwatch:last-sim";

export async function activateSim(sim: SimSummary, keepT = false) {
  const topo = await api.topology(sim.id);
  const { t } = useApp.getState();
  useApp.getState().setSim(sim, topo);
  useApp.getState().setT(keepT ? t : 0);
  try {
    localStorage.setItem(LAST_SIM_KEY, sim.id);
  } catch {
    /* storage unavailable: nothing to remember */
  }
}

export async function runTask<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
  const s = useApp.getState();
  s.setBusy(label);
  s.setError(null);
  try {
    return await fn();
  } catch (e) {
    s.setError(e instanceof Error ? e.message : String(e));
    return undefined;
  } finally {
    useApp.getState().setBusy(null);
  }
}

export async function createAndActivate(config: Partial<SimConfig>, keepT = false, rules?: Record<string, number>) {
  return runTask("Generating simulation…", async () => {
    const sim = await api.createSim(config, rules);
    await activateSim(sim, keepT);
    return sim;
  });
}

/** First load: reopen the last simulation, or start a normal-operation run. */
export function useBootstrap() {
  const setMeta = useApp((s) => s.setMeta);
  useEffect(() => {
    let cancelled = false;
    runTask("Connecting to the simulation backend…", async () => {
      const meta = await api.meta();
      if (cancelled) return;
      setMeta(meta);
      let last: string | null = null;
      try {
        last = localStorage.getItem(LAST_SIM_KEY);
      } catch {
        last = null;
      }
      if (last) {
        try {
          const sim = await api.sim(last);
          await activateSim(sim);
          return;
        } catch {
          /* fall through to a fresh run */
        }
      }
      const sim = await api.createSim({ scenario: "A", seed: 42, label: "Normal operation (seed 42)" });
      await activateSim(sim);
    });
    return () => {
      cancelled = true;
    };
  }, [setMeta]);
}

/** Keeps `state` in sync with (sim, t, methods); drives playback strictly from received states. */
export function useStateSync() {
  const sim = useApp((s) => s.sim);
  const t = useApp((s) => s.t);
  const cm = useApp((s) => s.consumerMethod);
  const um = useApp((s) => s.unitMethod);
  const playing = useApp((s) => s.playing);
  const speed = useApp((s) => s.speed);
  const reqId = useRef(0);

  useEffect(() => {
    if (!sim) return;
    const id = ++reqId.current;
    const started = performance.now();
    api.state(sim.id, t, cm, um)
      .then((st) => {
        if (id !== reqId.current) return;
        useApp.getState().setState(st);
        const s = useApp.getState();
        if (s.playing) {
          const wait = Math.max(0, 1000 / s.speed - (performance.now() - started));
          window.setTimeout(() => {
            const now = useApp.getState();
            if (now.playing && now.t === t && now.sim?.id === sim.id) now.step(1);
          }, wait);
        }
      })
      .catch((e) => {
        if (id === reqId.current) useApp.getState().setError(e instanceof Error ? e.message : String(e));
        useApp.getState().setPlaying(false);
      });
  }, [sim, t, cm, um, playing, speed]);
}
