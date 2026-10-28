// Types mirror the FastAPI responses (gridwatch/api/main.py, gridwatch/engine.py).

export type Provenance = "public-source" | "illustrative" | "assumption";

export interface Bus {
  id: string;
  label: string;
  vn_kv: number;
  kind: string;
  x: number;
  y: number;
  provenance: Provenance;
  description: string;
  feeder: string | null;
  dt: string | null;
}

export interface Branch {
  id: string;
  kind: "line" | "trafo";
  from_bus: string;
  to_bus: string;
  label: string;
  provenance: Provenance;
  params: Record<string, number>;
  feeder: string | null;
  dt: string | null;
  parallel: number;
}

export interface Meter {
  id: string;
  kind: "feeder_head" | "dt" | "consumer_group";
  label: string;
  location: string;
  accuracy_class: string;
  feeder: string | null;
  dt: string | null;
}

export interface Topology {
  config: { n_feeders: number; dts_per_feeder: number; consumers_per_dt: number };
  buses: Bus[];
  branches: Branch[];
  meters: Meter[];
  feeders: { id: string; label: string; archetype: string; head_branch: string; mv_branches: string[]; dts: string[] }[];
  dts: { id: string; feeder: string; hv_bus: string; lv_bus: string; group_bus: string; trafo_branch: string; lv_branch: string; archetype: string; sn_kva: number }[];
}

export interface Injection {
  type: string;
  feeder: string;
  dt?: string | null;
  n_consumers: number;
  magnitude: number;
  onset_day: number;
  duration_days: number;
}

export interface SimConfig {
  scenario: string;
  seed: number;
  n_feeders: number;
  dts_per_feeder: number;
  consumers_per_dt: number;
  noise_level: number;
  base_missing_rate: number;
  base_delay_rate: number;
  duplicate_rate: number;
  benign_change_rate: number;
  outage_rate: number;
  loss_model_error_sd: number;
  injections: Injection[];
  label?: string | null;
}

export interface SimEvent {
  index: number;
  type: string;
  theft_like: boolean;
  feeder: string;
  dt: string | null;
  consumers: string[];
  magnitude: number;
  phase: "pending" | "active" | "ended";
  start_step: number;
  end_step: number;
  detail: Record<string, unknown>;
}

export interface SimSummary {
  id: string;
  created_at: string;
  config: SimConfig;
  data_hash: string;
  n_consumers: number;
  n_steps: number;
  n_feeders: number;
  n_dts: number;
  start_timestamp: string;
  generation_ms: number;
  events: SimEvent[];
  benign_events: { consumer: string; start_step: number; end_step: number; factor: number; kind: string }[];
  outages: { feeder: string; start_step: number; end_step: number }[];
  ingestion: Record<string, number>;
  pandapower: boolean;
}

export interface BranchFlow {
  p_from_mw: number;
  q_from_mvar: number;
  p_to_mw: number;
  loss_mw: number;
  loading_pct: number;
  i_ka: number;
  in_service: boolean;
}

export interface PowerFlow {
  converged: boolean;
  solver: string;
  solve_ms?: number;
  buses?: Record<string, { vm_pu: number | null; va_degree: number | null; p_mw: number }>;
  branches?: Record<string, BranchFlow>;
  slack_p_mw?: number;
  gen_p_mw?: number;
  other_66kv_load_mw?: number;
  total_loss_mw?: number;
}

export type Status = "normal" | "warning" | "alert" | "unknown";

export interface UnitState {
  id: string;
  score: number;
  threshold: number;
  status: Status;
  balance_24h: {
    input_kwh: number;
    metered_kwh: number;
    imputed_kwh: number;
    loss_est_kwh: number;
    unexplained_kwh: number;
    ratio: number;
    z: number;
    coverage: number;
  };
  meter_kwh_this_hour: number | null;
  consumers: number;
  consumers_flagged: number;
  energised: boolean;
}

export interface GroupState {
  dt: string;
  consumers: number;
  metered_kwh_this_hour: number;
  readings_received: number;
  truth: { true_demand_kw: number; unmetered_kw: number; theft_like_consumers_active: number };
}

export interface NetState {
  run_id: string;
  t: number;
  n_steps: number;
  timestamp: string;
  hour_of_day: number;
  day: number;
  weekday: number;
  scenario: { code: string; label: string | null; status: string; events: SimEvent[] };
  power_flow: PowerFlow;
  hydro_dispatch_mw: number;
  units: { feeder: UnitState[]; dt: UnitState[] };
  groups: GroupState[];
  methods: { consumer: string; unit: string; consumer_threshold: number };
  consumers_flagged: string[];
  timeline_progress: number;
  scores_source: string;
  evaluation_ms: number;
}

export interface FeatureItem {
  feature: string;
  description?: string;
  value: number;
  contribution?: number;
  robust_z?: number;
}

export interface Alert {
  kind: "consumer" | "feeder" | "dt";
  id: string;
  feeder: string;
  dt: string | null;
  category?: string;
  method: string;
  method_name: string;
  score: number;
  threshold: number;
  score_display: string;
  priority: { level: "P1" | "P2" | "P3" | "DQ"; label: string; reasons: string[] };
  text: string;
  evidence: Record<string, number | string[] | number[]>;
  features: { kind: string; base_score?: number; note?: string; items: FeatureItem[] };
  energy_at_stake_kwh_per_day: number;
  priority_index: number;
  truth: Record<string, boolean>;
}

export interface AlertsResponse {
  t: number;
  timestamp: string;
  consumer_method: string;
  unit_method: string;
  alerts: Alert[];
  n_alerts: number;
  compute_ms: number;
  note: string;
  detection_id?: number;
}

export interface MethodInfo {
  name: string;
  family: string;
  signals: string;
  score_kind?: string;
}

export interface ScenarioInfo {
  code: string;
  name: string;
  injection: string | null;
  theft_like: boolean;
  summary: string;
  magnitude: { label: string; unit: string; min: number; max: number; default: number } | null;
}

export interface Meta {
  version: string;
  scenarios: ScenarioInfo[];
  demo_config: SimConfig;
  consumer_methods: Record<string, MethodInfo>;
  unit_methods: Record<string, MethodInfo>;
  default_methods: { consumer: string; unit: string };
  rules_default: Record<string, number>;
  thresholds: Record<string, number>;
  feature_descriptions: Record<string, string>;
  timeline: { step_hours: number; measurement_unit: string; power_flow: string };
  warning: string;
  model_meta: Record<string, unknown>;
}

export interface Balance {
  boundary: { kind: string; id: string; description: string };
  window: { start_hour: number; end_hour: number; start_step: number; end_step: number; as_of_step: number; hours_in_time: number; hours_used: number };
  input_kwh: number;
  metered_kwh: number;
  imputed_kwh: number;
  estimated_loss_kwh: number;
  unexplained_kwh: number;
  unexplained_pct_of_input: number | null;
  sigma_kwh: number;
  z_score: number;
  uncertainty_components_kwh: Record<string, number>;
  data_quality: {
    status: "good" | "fair" | "poor";
    consumer_reading_coverage: number;
    readings_expected: number;
    readings_missing_or_pending: number;
    readings_pending_delayed: number;
    input_meter_gaps_h: number;
    known_outage_hours: number;
    duplicates_removed_run_total: number;
  };
  hourly: Record<"input" | "metered" | "imputed" | "loss_est" | "unexplained", (number | null)[]>;
  formula: string;
  warning: string;
}

export interface UnitSeries {
  kind: string;
  id: string;
  as_of_step: number;
  hourly: Record<"input" | "metered" | "imputed" | "loss_est" | "unexplained", (number | null)[]>;
  rolling_24h: Record<"unexplained" | "ratio" | "z" | "input", (number | null)[]>;
  scores: Record<string, (number | null)[]>;
  thresholds: Record<string, number>;
  truth: { unmetered_kw: (number | null)[]; true_input_kwh: (number | null)[]; theft_like: number[] };
  timeline_progress: number;
}

export interface ConsumerSeries {
  id: string;
  category: string;
  feeder: string;
  dt: string;
  observed_kwh: (number | null)[];
  arrival_step: number[];
  expected_kwh: number[];
  expected_sd: number[];
  truth: { true_kwh: number[]; theft_like: number[]; benign_change: number[]; data_fault: number[] };
  scores: Record<string, (number | null)[]>;
  thresholds: Record<string, number>;
  timeline_progress: number;
}

export interface ConsumerRow {
  id: string;
  feeder: string;
  dt: string;
  category: string;
  ratio_72: number;
  peer_ratio_72: number;
  completeness_72: number;
  score: number;
  flagged: boolean;
}

export interface CompareResponse {
  t: number;
  timestamp: string;
  consumer_methods: {
    method: string;
    name: string;
    family: string;
    signals: string;
    threshold: number;
    flagged: number;
    true_positives: number;
    false_positives: number;
    missed: number;
    flagged_benign_changes: number;
    flagged_data_faults: number;
    flagged_ids: string[];
  }[];
  unit_methods: Record<string, { method: string; name: string; family: string; threshold: number; flagged_ids: string[]; truth_ids: string[]; scores: Record<string, number> }[]>;
  disagreements: { between: string[]; items: { consumer: string; flagged_by: string; truth: Record<string, boolean>; explanation: string }[] };
  note: string;
}

export interface Provenance_ {
  verified_facts: { claim: string; status: string; sources: string[] }[];
  not_verified: string[];
  assumptions: string[];
  synthetic: string[];
  ethics: string[];
}
