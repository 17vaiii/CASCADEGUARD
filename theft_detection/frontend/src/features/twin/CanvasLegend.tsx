import { AlertOctagon, AlertTriangle, ChevronDown, ChevronUp, FlaskConical, Gauge } from "lucide-react";
import { useState } from "react";
import { useApp } from "../../lib/store";

function Swatch({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <svg width="18" height="8" aria-hidden className="shrink-0">
      <line x1="1" y1="4" x2="17" y2="4" stroke={color} strokeWidth="2.5" strokeDasharray={dashed ? "4 3" : undefined} />
    </svg>
  );
}

export function CanvasLegend() {
  const overlay = useApp((s) => s.overlay);
  const setOverlay = useApp((s) => s.setOverlay);
  const showTruth = useApp((s) => s.showTruth);
  const setShowTruth = useApp((s) => s.setShowTruth);
  const pf = useApp((s) => s.state?.power_flow);
  const [open, setOpen] = useState(true);
  const det = overlay === "detection";
  return (
    <div className="absolute bottom-3 left-3 z-10 w-[268px] rounded-md border border-hair bg-panel/95 text-[12px]">
      <div className="flex items-center gap-1 border-b border-hair p-1.5">
        <div role="radiogroup" aria-label="Overlay" className="flex flex-1 rounded border border-hair-strong p-0.5">
          {(["detection", "loading"] as const).map((o) => (
            <button key={o} role="radio" aria-checked={overlay === o} onClick={() => setOverlay(o)}
              className={`flex-1 rounded px-1.5 py-0.5 font-cond text-[12px] ${overlay === o ? "bg-raised text-ink" : "text-ink-3 hover:text-ink-2"}`}>
              {o === "detection" ? "Detection status" : "Electrical loading"}
            </button>
          ))}
        </div>
        <button onClick={() => setOpen(!open)} aria-label={open ? "Hide legend" : "Show legend"} className="rounded p-1 text-ink-3 hover:text-ink">
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>
      {open && (
        <ul className="space-y-1 px-2.5 py-2 text-ink-2">
          <li className="flex items-center gap-2"><Swatch color="var(--color-flow)" />{det ? "Normal (score < 75% of threshold)" : "Below 80% of rating"}</li>
          <li className="flex items-center gap-2"><Swatch color="var(--color-warn)" /><AlertTriangle size={12} color="var(--color-warn)" className="shrink-0" />{det ? "Warning (75–100% of threshold)" : "80–100% of rating"}</li>
          <li className="flex items-center gap-2"><Swatch color="var(--color-alert)" /><AlertOctagon size={12} color="var(--color-alert)" className="shrink-0" />{det ? "Alert: investigate, not proof of theft" : "Above rating"}</li>
          <li className="flex items-center gap-2"><Swatch color="var(--color-ink-3)" dashed />De-energised (supply outage)</li>
          <li className="flex items-center gap-2"><Gauge size={12} color="var(--color-ink-2)" className="ml-[3px] mr-[3px] shrink-0" />Energy meter (feeder head, DT)</li>
          <li className="text-[11px] text-ink-3">Moving dots follow the solved active-power flow: direction, and speed on a log scale.</li>
        </ul>
      )}
      <label className="flex cursor-pointer items-center gap-2 border-t border-hair px-2.5 py-1.5">
        <input type="checkbox" checked={showTruth} onChange={(e) => setShowTruth(e.target.checked)} className="accent-[var(--color-truth)]" />
        <FlaskConical size={13} color="var(--color-truth)" />
        <span>Show simulation ground truth</span>
      </label>
      {open && pf && (
        <div className="border-t border-hair px-2.5 py-1 text-[11px] text-ink-3">
          {pf.converged ? `AC power flow (pandapower) solved in ${pf.solve_ms} ms` : "AC power flow did not converge at this step; flows are not shown"}
        </div>
      )}
    </div>
  );
}
