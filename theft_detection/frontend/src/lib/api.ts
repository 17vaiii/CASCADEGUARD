import type {
  AlertsResponse, Balance, CompareResponse, ConsumerRow, ConsumerSeries, Meta, NetState, Provenance_, SimConfig,
  SimSummary, Topology, UnitSeries,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

const q = (o: Record<string, string | number | undefined | null>) =>
  "?" + Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");

export const api = {
  meta: () => req<Meta>("/meta"),
  provenance: () => req<Provenance_>("/provenance"),
  listSims: () => req<{ id: string; created_at: string; label: string | null; scenario: string; seed: number; data_hash: string; n_detections: number }[]>("/simulations"),
  createSim: (config: Partial<SimConfig>, rules?: Record<string, number>) =>
    req<SimSummary>("/simulations", { method: "POST", body: JSON.stringify({ config, rules }) }),
  createDemo: () => req<SimSummary>("/simulations/demo", { method: "POST" }),
  sim: (id: string) => req<SimSummary>(`/simulations/${id}`),
  topology: (id: string) => req<Topology>(`/simulations/${id}/topology`),
  state: (id: string, t: number, cm: string, um: string) =>
    req<NetState>(`/simulations/${id}/state${q({ t, consumer_method: cm, unit_method: um })}`),
  alerts: (id: string, t: number, cm: string, um: string) =>
    req<AlertsResponse>(`/simulations/${id}/alerts${q({ t, consumer_method: cm, unit_method: um })}`),
  detect: (id: string, t: number, cm: string, um: string) =>
    req<AlertsResponse>(`/simulations/${id}/detect`, { method: "POST", body: JSON.stringify({ t, consumer_method: cm, unit_method: um }) }),
  compare: (id: string, t: number) => req<CompareResponse>(`/simulations/${id}/compare${q({ t })}`),
  balance: (id: string, kind: string, uid: string, t: number, start: number, end: number) =>
    req<Balance>(`/simulations/${id}/energy-balance${q({ kind, id: uid, t, start, end })}`),
  unitSeries: (id: string, kind: "feeder" | "dt", uid: string, t: number) =>
    req<UnitSeries>(`/simulations/${id}/${kind === "feeder" ? "feeders" : "dts"}/${uid}/timeseries${q({ t })}`),
  consumers: (id: string, t: number, opts: { feeder?: string; dt?: string; method?: string }) =>
    req<ConsumerRow[]>(`/simulations/${id}/consumers${q({ t, ...opts })}`),
  consumerSeries: (id: string, cid: string) => req<ConsumerSeries>(`/simulations/${id}/consumers/${cid}/timeseries`),
  baselineDiff: (id: string, t: number) => req<BaselineDiff>(`/simulations/${id}/baseline-diff${q({ t })}`),
  replay: (id: string, t: number) => req<ReplayResult>(`/simulations/${id}/replay${q({ t })}`, { method: "POST" }),
  detections: (simId?: string) => req<DetectionRow[]>(`/detections${q({ sim_id: simId })}`),
  results: () => req<ExperimentResults>("/experiments/results"),
};

export interface BaselineDiff {
  t: number;
  consumers: { id: string; scenario_kwh: number; normal_kwh: number; difference_kwh: number; extra_missing_readings: number; extra_delayed_readings: number }[];
  dt_meters: { id: string; scenario_kwh: number; normal_kwh: number; difference_kwh: number }[];
  feeder_meters: { id: string; scenario_kwh: number; normal_kwh: number; difference_kwh: number }[];
  loss_estimate_factor_changed: string[];
  noise_multiplier_changed: string[];
  unmetered_energy_kwh: Record<string, number>;
  note: string;
}

export interface ReplayResult {
  original_hash: string;
  replay_hash: string;
  data_identical: boolean;
  max_abs_score_difference: number;
  scores_identical_within_1e_12?: boolean;
  replay_ms: number;
}

export interface DetectionRow {
  id: number;
  simulation_id: string;
  created_at: string;
  step: number;
  consumer_method: string;
  unit_method: string;
  n_alerts: number;
  compute_ms: number;
}

// The experiment results are rendered generically; see gridwatch/experiments/run.py for the schema.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ExperimentResults = { available: boolean; message?: string } & Record<string, any>;
