import { FlaskConical } from "lucide-react";
import { PRIORITY_STYLE } from "../lib/format";
import { useApp } from "../lib/store";
import type { Alert } from "../lib/types";

export function PriorityBadge({ level, label }: { level: string; label?: string }) {
  const s = PRIORITY_STYLE[level] ?? PRIORITY_STYLE.P3;
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-[1px] font-cond text-[11.5px] font-semibold ${s.text} ${s.ring}`}>
      {level}{label ? <span className="font-normal text-ink-2">{label}</span> : null}
    </span>
  );
}

export function AlertListItem({ a, active, onClick }: { a: Alert; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`w-full rounded border px-2.5 py-2 text-left transition-colors ${active ? "border-flow bg-raised" : "border-hair hover:border-hair-strong hover:bg-raised/60"}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-cond text-[13.5px] font-semibold">{a.kind === "consumer" ? a.id : `${a.kind === "dt" ? "DT" : "Feeder"} ${a.id}`}</span>
        <PriorityBadge level={a.priority.level} />
      </div>
      <div className="mt-0.5 text-[11.5px] text-ink-3">{a.method_name}, {a.score_display}</div>
    </button>
  );
}

export function ExplanationCard({ a, compact = false }: { a: Alert; compact?: boolean }) {
  const showTruth = useApp((s) => s.showTruth);
  const items = a.features.items ?? [];
  const maxAbs = Math.max(1e-9, ...items.map((i) => Math.abs(i.contribution ?? i.robust_z ?? 0)));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <PriorityBadge level={a.priority.level} label={a.priority.label} />
      </div>
      <p className="text-[13px] leading-relaxed text-ink">{a.text}</p>
      <div className="text-[12px] text-ink-2">
        <span className="text-ink-3">Why this priority: </span>{a.priority.reasons.join("; ")}.
      </div>
      {!compact && items.length > 0 && (
        <div>
          <div className="mb-1 text-[12px] text-ink-2">
            {a.features.kind === "rf_contributions"
              ? `Feature contributions to this classifier score (base ${a.features.base_score?.toFixed(3)} + contributions = ${a.score.toFixed(3)})`
              : a.features.note}
          </div>
          <ul className="space-y-1">
            {items.map((i) => {
              const v = i.contribution ?? i.robust_z ?? 0;
              const w = `${(50 * Math.abs(v)) / maxAbs}%`;
              return (
                <li key={i.feature} className="grid grid-cols-[1fr_120px_52px] items-center gap-2 text-[12px]">
                  <span className="truncate text-ink-2" title={i.description}>{i.description ?? i.feature} <span className="text-ink-3 tnum">= {i.value.toFixed(2)}</span></span>
                  <span className="relative h-2.5 rounded-sm bg-raised">
                    <span className="absolute top-0 h-2.5 rounded-sm" style={{
                      width: w, left: v >= 0 ? "50%" : `calc(50% - ${w})`,
                      background: v >= 0 ? "var(--color-series-1)" : "var(--color-ref)",
                    }} />
                    <span className="absolute left-1/2 top-[-2px] h-[14px] w-px bg-hair-strong" />
                  </span>
                  <span className="text-right tnum text-ink">{v >= 0 ? "+" : ""}{v.toFixed(3)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {showTruth && (
        <div className="flex items-start gap-1.5 rounded border border-dashed border-truth/70 px-2 py-1.5 text-[12px]">
          <FlaskConical size={13} color="var(--color-truth)" className="mt-0.5 shrink-0" />
          <span>
            Simulation ground truth (not available in a real deployment):{" "}
            {Object.entries(a.truth).filter(([, v]) => v).map(([k]) => k.replace(/_/g, " ")).join(", ") || "no injected or benign event active in the last 24 h"}.
          </span>
        </div>
      )}
    </div>
  );
}
