export const fmt = {
  kwh: (v: number | null | undefined, nd = 1) => (v == null || !isFinite(v) ? "–" : `${v.toLocaleString("en-IN", { maximumFractionDigits: nd, minimumFractionDigits: nd })} kWh`),
  kw: (v: number | null | undefined, nd = 1) => (v == null || !isFinite(v) ? "–" : `${v.toLocaleString("en-IN", { maximumFractionDigits: nd, minimumFractionDigits: nd })} kW`),
  mw: (v: number | null | undefined, nd = 2) => (v == null || !isFinite(v) ? "–" : `${v.toFixed(nd)} MW`),
  pct: (v: number | null | undefined, nd = 1) => (v == null || !isFinite(v) ? "–" : `${(100 * v).toFixed(nd)}%`),
  num: (v: number | null | undefined, nd = 2) => (v == null || !isFinite(v) ? "–" : v.toFixed(nd)),
  sigma: (v: number | null | undefined) => (v == null || !isFinite(v) ? "–" : `${v.toFixed(1)}σ`),
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function stepLabel(start: string, t: number): string {
  const d = new Date(new Date(start).getTime() + t * 3600_000);
  const day = DAYS[(d.getDay() + 6) % 7];
  return `${day} ${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} ${String(d.getHours()).padStart(2, "0")}:00`;
}

export const INJECTION_LABEL: Record<string, string> = {
  sudden_deviation: "Sudden metered-consumption deviation",
  unmetered_load: "Simulated unmetered load",
  persistent_anomaly: "Persistent consumption anomaly",
  missing_delayed: "Missing / delayed readings",
  noise_stress: "Measurement-noise stress",
  loss_estimate_error: "Technical-loss estimate error",
};

export const PRIORITY_STYLE: Record<string, { text: string; ring: string }> = {
  P1: { text: "text-alert", ring: "border-alert/60" },
  P2: { text: "text-warn", ring: "border-warn/60" },
  P3: { text: "text-ink-2", ring: "border-hair-strong" },
  DQ: { text: "text-series-3", ring: "border-series-3/60" },
};
