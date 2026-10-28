import {
  Area, Bar, BarChart, Brush, CartesianGrid, Cell, ComposedChart, ErrorBar, LabelList, Line, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmt, stepLabel } from "../lib/format";
import type { Balance, ConsumerSeries, UnitSeries } from "../lib/types";

const GRID = "#1e2d45";
const AXIS = "#2e4262";
const C1 = "#3987e5";
const C2 = "#d95926";
const C3 = "#199e70";
const REF = "#8a9bb4";

const tooltipStyle = {
  contentStyle: { background: "#0f1a2b", border: "1px solid #2e4262", borderRadius: 6, fontSize: 12, color: "#e6edf7" },
  labelStyle: { color: "#a9b8cc", marginBottom: 4 },
  itemStyle: { padding: 0 },
};

function dayTicks(maxStep: number) {
  const ticks = [];
  for (let s = 0; s <= maxStep; s += 24) ticks.push(s);
  return ticks;
}
const dayFmt = (s: number) => `D${Math.floor(s / 24) + 1}`;

export function LegendRow({ items }: { items: { color: string; label: string; kind?: "line" | "band" | "bar" }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-ink-2">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5">
          {i.kind === "band" ? <span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: i.color, opacity: 0.35 }} />
            : i.kind === "bar" ? <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />
              : <span className="inline-block h-[2px] w-4" style={{ background: i.color }} />}
          {i.label}
        </span>
      ))}
    </div>
  );
}

/** Observed vs expected hourly consumption for one consumer, as known at step t. */
export function ConsumerChart({ s, t, start, showTruth, height = 220, brush = false, startTs }: {
  s: ConsumerSeries; t: number; start: number; showTruth: boolean; height?: number; brush?: boolean; startTs: string;
}) {
  const data = [];
  for (let i = start; i <= t; i++) {
    const arrived = s.arrival_step[i] >= 0 && s.arrival_step[i] <= t;
    data.push({
      step: i,
      observed: arrived ? s.observed_kwh[i] : null,
      expected: s.expected_kwh[i],
      band: [Math.max(0, s.expected_kwh[i] - s.expected_sd[i]), s.expected_kwh[i] + s.expected_sd[i]],
      truth: showTruth ? s.truth.true_kwh[i] : undefined,
      theft: s.truth.theft_like[i],
    });
  }
  const theftSpans = showTruth ? spans(s.truth.theft_like, start, t) : [];
  return (
    <div>
      <LegendRow items={[
        { color: C1, label: "Recorded (meter readings received by this step)" },
        { color: REF, label: "Expected profile" },
        { color: REF, label: "±1 SD", kind: "band" },
        ...(showTruth ? [{ color: C2, label: "True demand (simulation)" }] : []),
      ]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          {theftSpans.map(([a, b]) => <ReferenceArea key={a} x1={a} x2={b} fill={C2} fillOpacity={0.08} stroke="none" />)}
          <XAxis dataKey="step" type="number" domain={[start, t]} ticks={dayTicks(t).filter((x) => x >= start)} tickFormatter={dayFmt} stroke={AXIS} />
          <YAxis stroke={AXIS} width={48} tickFormatter={(v) => `${v}`} label={{ value: "kWh/h", angle: -90, position: "insideLeft", offset: 22, fill: "#7487a3", fontSize: 11 }} />
          <Tooltip {...tooltipStyle} labelFormatter={(v) => stepLabel(startTs, Number(v))}
            formatter={(v: unknown, name: string) => (name === "band" ? null : [Array.isArray(v) ? "" : fmt.kwh(v as number, 3), name])} />
          <Area dataKey="band" stroke="none" fill={REF} fillOpacity={0.14} isAnimationActive={false} name="band" />
          <Line dataKey="expected" stroke={REF} strokeWidth={1.5} dot={false} isAnimationActive={false} name="Expected" />
          {showTruth && <Line dataKey="truth" stroke={C2} strokeWidth={1.5} dot={false} isAnimationActive={false} name="True demand" />}
          <Line dataKey="observed" stroke={C1} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} name="Recorded" />
          {brush && <Brush dataKey="step" height={18} stroke={AXIS} fill="#0f1a2b" travellerWidth={8} tickFormatter={dayFmt} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function spans(flags: number[], start: number, end: number): [number, number][] {
  const out: [number, number][] = [];
  let s: number | null = null;
  for (let i = start; i <= end; i++) {
    if (flags[i] && s === null) s = i;
    if ((!flags[i] || i === end) && s !== null) {
      out.push([s, flags[i] ? i : i - 1]);
      s = null;
    }
  }
  return out;
}

/** Rolling 24 h unexplained energy as a share of input, with the rule threshold. */
export function BalanceTrendChart({ s, t, showTruth, ruleRatio = 0.03, height = 200, startTs }: {
  s: UnitSeries; t: number; showTruth: boolean; ruleRatio?: number; height?: number; startTs: string;
}) {
  const data = s.rolling_24h.ratio.slice(0, t + 1).map((r, i) => ({
    step: i,
    ratio: r == null ? null : 100 * r,
    z: s.rolling_24h.z[i],
    unexplained: s.rolling_24h.unexplained[i],
  }));
  const theft = showTruth ? spans(s.truth.theft_like, 0, Math.min(t, s.truth.theft_like.length - 1)) : [];
  return (
    <div>
      <LegendRow items={[
        { color: C1, label: "Unexplained energy, rolling 24 h (% of input)" },
        { color: REF, label: `Rule threshold ${ruleRatio * 100}%` },
        ...(showTruth ? [{ color: C2, label: "Theft-like event active (simulation)", kind: "band" as const }] : []),
      ]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          {theft.map(([a, b]) => <ReferenceArea key={a} x1={a} x2={b} fill={C2} fillOpacity={0.12} stroke="none" />)}
          <XAxis dataKey="step" type="number" domain={[0, Math.max(t, 1)]} ticks={dayTicks(t)} tickFormatter={dayFmt} stroke={AXIS} />
          <YAxis stroke={AXIS} width={48} tickFormatter={(v) => `${v}%`} />
          <ReferenceLine y={ruleRatio * 100} stroke={REF} strokeWidth={1} />
          <ReferenceLine y={0} stroke={AXIS} />
          <Tooltip {...tooltipStyle} labelFormatter={(v) => stepLabel(startTs, Number(v))}
            formatter={(v: unknown, name: string, item: { payload?: { z?: number; unexplained?: number } }) =>
              name === "ratio" ? [`${(v as number).toFixed(2)}% (${fmt.kwh(item.payload?.unexplained)}, ${fmt.sigma(item.payload?.z)})`, "Unexplained, 24 h"] : [String(v), name]} />
          <Line dataKey="ratio" stroke={C1} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Score of one method over time with its decision threshold. */
export function ScoreChart({ scores, threshold, t, height = 150, label, startTs }: {
  scores: (number | null)[]; threshold: number; t: number; height?: number; label: string; startTs: string;
}) {
  const data = scores.slice(0, t + 1).map((v, i) => ({ step: i, score: v }));
  const computed = data.filter((d) => d.score != null).length;
  return (
    <div>
      <LegendRow items={[{ color: C3, label }, { color: REF, label: `Decision threshold ${threshold.toFixed(2)}` }]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="step" type="number" domain={[0, Math.max(t, 1)]} ticks={dayTicks(t)} tickFormatter={dayFmt} stroke={AXIS} />
          <YAxis stroke={AXIS} width={48} />
          <ReferenceLine y={threshold} stroke={REF} strokeWidth={1} />
          <Tooltip {...tooltipStyle} labelFormatter={(v) => stepLabel(startTs, Number(v))} formatter={(v: unknown) => [(v as number)?.toFixed(3), "score"]} />
          <Line dataKey="score" stroke={C3} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
        </ComposedChart>
      </ResponsiveContainer>
      {computed < data.length && <div className="text-[11px] text-ink-3">Score history still being computed in the background ({computed} of {data.length} steps ready).</div>}
    </div>
  );
}

/** Energy-balance waterfall: input minus metered, imputed and estimated losses leaves the unexplained part. */
export function Waterfall({ b, height = 260 }: { b: Balance; height?: number }) {
  const E = b.input_kwh;
  const M = b.metered_kwh;
  const I = b.imputed_kwh;
  const L = b.estimated_loss_kwh;
  const U = b.unexplained_kwh;
  const significant = b.z_score >= 2;
  const rows = [
    { name: "Input", base: 0, value: E, color: C1, label: fmt.kwh(E) },
    { name: "Metered", base: E - M, value: M, color: "#5b7fb0", label: `−${fmt.kwh(M)}` },
    { name: "Imputed", base: E - M - I, value: I, color: C3, label: `−${fmt.kwh(I)}` },
    { name: "Losses (estimated)", base: Math.max(0, U), value: L, color: REF, label: `−${fmt.kwh(L)}` },
    { name: "Unexplained", base: Math.min(0, U), value: Math.abs(U), color: significant ? "#f04848" : "#7487a3", label: fmt.kwh(U), err: 2 * b.sigma_kwh },
  ];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 22, right: 12, bottom: 4, left: 8 }} barCategoryGap="30%">
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="name" stroke={AXIS} interval={0} tick={{ fontSize: 11, fill: "#a9b8cc" }} />
        <YAxis stroke={AXIS} width={64} tickFormatter={(v) => `${Math.round(v).toLocaleString("en-IN")}`} label={{ value: "kWh", angle: -90, position: "insideLeft", offset: 4, fill: "#7487a3", fontSize: 11 }} />
        <Tooltip {...tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.03)" }}
          formatter={(_v: unknown, n: string, item: { payload?: { label?: string } }) => (n === "base" ? null : [item.payload?.label, "Energy"])} />
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="value" stackId="w" maxBarSize={56} radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {rows.map((r) => <Cell key={r.name} fill={r.color} />)}
          <LabelList dataKey="label" position="top" fill="#e6edf7" fontSize={11.5} />
          <ErrorBar dataKey="err" width={10} stroke="#e6edf7" strokeWidth={1.2} direction="y" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Hourly accounting terms (stacked metered + imputed + losses) against the input meter. */
export function HourlyAccountingChart({ b, startTs, height = 220 }: { b: Balance; startTs: string; height?: number }) {
  const n = b.hourly.input.length;
  const data = Array.from({ length: n }).map((_, i) => ({
    step: b.window.start_step + i,
    metered: b.hourly.metered[i],
    imputed: b.hourly.imputed[i],
    loss: b.hourly.loss_est[i],
    input: b.hourly.input[i],
  }));
  return (
    <div>
      <LegendRow items={[
        { color: "#5b7fb0", label: "Metered", kind: "bar" }, { color: C3, label: "Imputed", kind: "bar" },
        { color: REF, label: "Estimated losses", kind: "bar" }, { color: "#e6edf7", label: "Input meter" },
      ]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -6 }} barCategoryGap={1}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="step" stroke={AXIS} tickFormatter={(s) => stepLabel(startTs, s).slice(4, 10)} minTickGap={40} />
          <YAxis stroke={AXIS} width={52} label={{ value: "kWh/h", angle: -90, position: "insideLeft", offset: 14, fill: "#7487a3", fontSize: 11 }} />
          <Tooltip {...tooltipStyle} labelFormatter={(v) => stepLabel(startTs, Number(v))} formatter={(v: unknown, n: string) => [fmt.kwh(v as number, 2), n]} />
          <Bar dataKey="metered" stackId="a" fill="#5b7fb0" isAnimationActive={false} name="Metered" />
          <Bar dataKey="imputed" stackId="a" fill={C3} isAnimationActive={false} name="Imputed" />
          <Bar dataKey="loss" stackId="a" fill={REF} isAnimationActive={false} name="Estimated losses" />
          <Line dataKey="input" stroke="#e6edf7" strokeWidth={2} dot={false} isAnimationActive={false} name="Input meter" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Daily recorded minus expected energy (only readings received by step t). */
export function DailyDifferenceChart({ s, t, height = 150 }: { s: ConsumerSeries; t: number; height?: number }) {
  const days = Math.floor(t / 24) + 1;
  const data = Array.from({ length: days }).map((_, d) => {
    let diff = 0;
    let n = 0;
    for (let i = d * 24; i < Math.min((d + 1) * 24, t + 1); i++) {
      const arrived = s.arrival_step[i] >= 0 && s.arrival_step[i] <= t && s.observed_kwh[i] != null;
      if (arrived) { diff += (s.observed_kwh[i] as number) - s.expected_kwh[i]; n++; }
    }
    return { day: `D${d + 1}`, diff: n ? Number(diff.toFixed(2)) : null, n };
  });
  return (
    <div>
      <LegendRow items={[{ color: C1, label: "Recorded − expected per day (kWh); hours with a received reading only", kind: "bar" }]} />
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="day" stroke={AXIS} />
          <YAxis stroke={AXIS} width={48} />
          <ReferenceLine y={0} stroke={AXIS} />
          <Tooltip {...tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.03)" }}
            formatter={(v: unknown, _n: string, item: { payload?: { n?: number } }) => [`${fmt.kwh(v as number, 2)} (${item.payload?.n} readings)`, "Difference"]} />
          <Bar dataKey="diff" fill={C1} maxBarSize={22} radius={[2, 2, 2, 2]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
