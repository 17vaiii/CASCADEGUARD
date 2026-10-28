import { create } from "zustand";
import type { AlertsResponse, Meta, NetState, SimSummary, Topology } from "./types";

export type View = "twin" | "energy" | "investigate" | "evaluation" | "sources";
export type Selection =
  | { kind: "bus"; id: string }
  | { kind: "feeder"; id: string }
  | { kind: "dt"; id: string }
  | { kind: "consumer"; id: string }
  | null;

interface AppState {
  meta: Meta | null;
  sim: SimSummary | null;
  topo: Topology | null;
  state: NetState | null;
  t: number;
  playing: boolean;
  speed: number; // steps per second
  view: View;
  selection: Selection;
  consumerMethod: string;
  unitMethod: string;
  overlay: "detection" | "loading";
  showTruth: boolean;
  alerts: AlertsResponse | null;
  busy: string | null;
  error: string | null;
  demoStage: number | null;
  investigateTab: "detail" | "compare";
  labOpen: boolean;
  setLabOpen: (b: boolean) => void;
  setInvestigateTab: (t: "detail" | "compare") => void;
  setMeta: (m: Meta) => void;
  setSim: (s: SimSummary, topo: Topology) => void;
  setState: (s: NetState) => void;
  setT: (t: number) => void;
  step: (dt: number) => void;
  setPlaying: (p: boolean) => void;
  setSpeed: (s: number) => void;
  setView: (v: View) => void;
  select: (s: Selection) => void;
  setMethods: (c?: string, u?: string) => void;
  setOverlay: (o: "detection" | "loading") => void;
  setShowTruth: (b: boolean) => void;
  setAlerts: (a: AlertsResponse | null) => void;
  setBusy: (b: string | null) => void;
  setError: (e: string | null) => void;
  setDemoStage: (s: number | null) => void;
}

export const useApp = create<AppState>((set, get) => ({
  meta: null,
  sim: null,
  topo: null,
  state: null,
  t: 0,
  playing: false,
  speed: 4,
  view: "twin",
  selection: null,
  consumerMethod: "rf_combined",
  unitMethod: "rf_unit_combined",
  overlay: "detection",
  showTruth: false,
  alerts: null,
  busy: null,
  error: null,
  demoStage: null,
  investigateTab: "detail",
  labOpen: typeof window !== "undefined" ? window.innerWidth >= 1800 : true,
  setLabOpen: (labOpen) => set({ labOpen }),
  setInvestigateTab: (investigateTab) => set({ investigateTab }),
  setMeta: (meta) => set({ meta, consumerMethod: meta.default_methods.consumer, unitMethod: meta.default_methods.unit }),
  setSim: (sim, topo) => set({ sim, topo, state: null, alerts: null, playing: false }),
  setState: (state) => set({ state }),
  setT: (t) => {
    const n = get().sim?.n_steps ?? 336;
    set({ t: Math.max(0, Math.min(n - 1, Math.round(t))) });
  },
  step: (d) => {
    const n = get().sim?.n_steps ?? 336;
    const t = Math.max(0, Math.min(n - 1, get().t + d));
    set({ t, playing: t >= n - 1 ? false : get().playing });
  },
  setPlaying: (playing) => set({ playing }),
  setSpeed: (speed) => set({ speed }),
  setView: (view) => set({ view }),
  select: (selection) => set({ selection }),
  setMethods: (c, u) => set({ consumerMethod: c ?? get().consumerMethod, unitMethod: u ?? get().unitMethod }),
  setOverlay: (overlay) => set({ overlay }),
  setShowTruth: (showTruth) => set({ showTruth }),
  setAlerts: (alerts) => set({ alerts }),
  setBusy: (busy) => set({ busy }),
  setError: (error) => set({ error }),
  setDemoStage: (demoStage) => set({ demoStage }),
}));
