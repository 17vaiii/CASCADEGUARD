import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AlertOctagon, AlertTriangle, FlaskConical, Gauge, Users } from "lucide-react";
import type { ReactNode } from "react";
import type { Status } from "../../lib/types";

export const STATUS_COLOR: Record<Status, string> = {
  normal: "var(--color-flow)",
  warning: "var(--color-warn)",
  alert: "var(--color-alert)",
  unknown: "var(--color-ink-3)",
};

export function StatusIcon({ status, size = 14 }: { status: Status; size?: number }) {
  if (status === "alert") return <AlertOctagon size={size} color="var(--color-alert)" aria-label="alert" />;
  if (status === "warning") return <AlertTriangle size={size} color="var(--color-warn)" aria-label="warning" />;
  return null;
}

const SIDES: [string, Position][] = [["l", Position.Left], ["r", Position.Right], ["t", Position.Top], ["b", Position.Bottom]];
const hidden = { opacity: 0, width: 4, height: 4, minWidth: 0, minHeight: 0, border: 0 };

function Handles({ extra }: { extra?: ReactNode }) {
  return (
    <>
      {SIDES.map(([id, pos]) => (
        <span key={id}>
          <Handle id={`s-${id}`} type="source" position={pos} style={hidden} isConnectable={false} />
          <Handle id={`t-${id}`} type="target" position={pos} style={hidden} isConnectable={false} />
        </span>
      ))}
      {extra}
    </>
  );
}

export interface BaseData extends Record<string, unknown> {
  label: string;
  sub?: string;
  dim?: boolean;
  selected?: boolean;
  status?: Status;
}

/** Caption placed outside the node box, so handles attach to the symbol itself. */
function Caption({ label, sub, place }: { label: string; sub?: string; place: "above" | "below" | "left" }) {
  const pos =
    place === "above" ? "bottom-full left-1/2 -translate-x-1/2 mb-1.5 text-center"
      : place === "below" ? "top-full left-1/2 -translate-x-1/2 mt-1.5 text-center"
        : "right-full top-1/2 -translate-y-1/2 mr-3 text-right";
  return (
    <div className={`pointer-events-none absolute whitespace-nowrap font-cond leading-tight ${pos}`}>
      <div className="text-[13px] font-semibold text-ink">{label}</div>
      {sub && <div className="text-[11.5px] text-ink-3 tnum">{sub}</div>}
    </div>
  );
}

const wrap = (d: BaseData) => `relative cursor-pointer transition-opacity duration-300 ${d.dim ? "opacity-25" : "opacity-100"}`;

export function SourceNode({ data }: NodeProps) {
  const d = data as BaseData & { variant: "generator" | "grid" };
  return (
    <div className={wrap(d)} style={{ width: 52, height: 52 }}>
      <svg width="52" height="52" viewBox="0 0 52 52" aria-hidden>
        <circle cx="26" cy="26" r="23" fill="var(--color-panel)" stroke={d.selected ? "var(--color-ink)" : "var(--color-flow)"} strokeWidth="2" />
        {d.variant === "generator" ? (
          <>
            <text x="26" y="25" textAnchor="middle" fontSize="15" fontWeight="600" fill="var(--color-ink)" fontFamily="Barlow">G</text>
            <path d="M16 34 q5 -6 10 0 t10 0" fill="none" stroke="var(--color-flow)" strokeWidth="2" />
          </>
        ) : (
          <path d="M13 19 q6.5 -7 13 0 t13 0 M13 27 q6.5 -7 13 0 t13 0 M13 35 q6.5 -7 13 0 t13 0" fill="none" stroke="var(--color-ink-2)" strokeWidth="1.6" />
        )}
      </svg>
      <Caption label={d.label} sub={d.sub} place="below" />
      <Handles />
    </div>
  );
}

export function BusNode({ data }: NodeProps) {
  const d = data as BaseData & { width?: number; kv: number; place?: "above" | "below" };
  const w = d.width ?? 110;
  return (
    <div className={wrap(d)} style={{ width: w, height: 7 }}>
      <div className="h-full w-full rounded-[2px]" style={{ background: d.selected ? "var(--color-ink)" : "var(--color-ink-2)" }} />
      <Caption label={d.label} sub={d.sub} place={d.place ?? "below"} />
      <Handles />
    </div>
  );
}

export function VerticalBusNode({ data }: NodeProps) {
  const d = data as BaseData & { height: number; bays: { id: string; offset: number }[] };
  return (
    <div className={wrap(d)} style={{ width: 7, height: d.height }}>
      <div className="h-full w-full rounded-[2px]" style={{ background: d.selected ? "var(--color-ink)" : "var(--color-ink-2)" }} />
      <div className="pointer-events-none absolute bottom-full left-0 mb-1.5 whitespace-nowrap font-cond leading-tight">
        <div className="text-[13px] font-semibold text-ink">{d.label}</div>
        {d.sub && <div className="text-[11.5px] text-ink-3 tnum">{d.sub}</div>}
      </div>
      <Handles
        extra={d.bays.map((b) => (
          <Handle key={b.id} id={`bay-${b.id}`} type="source" position={Position.Right} isConnectable={false}
            style={{ ...hidden, top: b.offset }} />
        ))}
      />
    </div>
  );
}

export function FeederTagNode({ data }: NodeProps) {
  const d = data as BaseData & { archetype: string; scoreText: string; status: Status };
  const color = { normal: "var(--color-hair-strong)", warning: "var(--color-warn)", alert: "var(--color-alert)", unknown: "var(--color-hair)" }[d.status ?? "normal"];
  return (
    <div
      data-testid={`feeder-tag-${d.label}`} data-selected={d.selected ? "true" : "false"} data-status={d.status} data-dim={d.dim ? "true" : "false"}
      aria-label={`Feeder ${d.label}, status ${d.status}`}
      className={`${wrap(d)} flex items-center gap-2 rounded-md border bg-panel px-2.5 py-1.5`}
      style={{ borderColor: d.selected ? "var(--color-ink)" : color, borderWidth: d.status === "alert" || d.selected ? 2 : 1 }}
    >
      <Gauge size={14} color="var(--color-ink-2)" aria-label="feeder-head meter" />
      <div className="font-cond leading-tight">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
          {d.label}
          <StatusIcon status={d.status} size={13} />
        </div>
        <div className="text-[11px] text-ink-3 tnum">{d.archetype}, {d.scoreText}</div>
      </div>
      <Handles />
    </div>
  );
}

export function JunctionNode({ data }: NodeProps) {
  const d = data as BaseData;
  const color = STATUS_COLOR[d.status ?? "normal"];
  return (
    <div className={wrap(d)} style={{ width: 12, height: 12 }}>
      <svg width="12" height="12" aria-hidden>
        <circle cx="6" cy="6" r="4.5" fill="var(--color-plane)" stroke={color} strokeWidth="2" />
      </svg>
      <Handles />
    </div>
  );
}

export function DtNode({ data }: NodeProps) {
  const d = data as BaseData;
  const border = { normal: "var(--color-hair-strong)", warning: "var(--color-warn)", alert: "var(--color-alert)", unknown: "var(--color-hair)" }[d.status ?? "normal"];
  return (
    <div data-testid={`dt-${d.label}`} data-selected={d.selected ? "true" : "false"} data-status={d.status} data-dim={d.dim ? "true" : "false"}
      aria-label={`DT ${d.label}, status ${d.status}`}
      className={`${wrap(d)} flex items-center gap-1 rounded border bg-panel px-1.5 py-0.5`}
      style={{ borderColor: d.selected ? "var(--color-ink)" : border, borderWidth: d.status === "alert" || d.selected ? 2 : 1 }}>
      <Gauge size={12} color="var(--color-ink-2)" aria-label="DT meter" />
      <span className="font-cond text-[12px] font-semibold text-ink tnum">{d.label}</span>
      <StatusIcon status={d.status ?? "normal"} size={12} />
      {d.sub && <div className="pointer-events-none absolute left-full top-1/2 ml-2 -translate-y-1/2 whitespace-nowrap font-cond text-[11px] leading-tight text-ink-3 tnum">{d.sub}</div>}
      <Handles />
    </div>
  );
}

export function GroupNode({ data }: NodeProps) {
  const d = data as BaseData & { consumers: number; flagged: number; meterText: string; truth?: string | null };
  return (
    <div className={wrap(d)} data-testid={`group-${d.label}`} data-selected={d.selected ? "true" : "false"} data-dim={d.dim ? "true" : "false"}>
      <div className="flex items-center gap-2 rounded-md border bg-raised px-2 py-1.5"
        style={{ borderColor: d.selected ? "var(--color-ink)" : "var(--color-hair-strong)" }}>
        <Users size={14} color="var(--color-ink-2)" aria-hidden />
        <div className="font-cond leading-tight">
          <div className="text-[12px] font-semibold text-ink tnum">{d.consumers} smart meters</div>
          <div className="text-[11px] text-ink-3 tnum">{d.meterText}</div>
        </div>
        {d.flagged > 0 && (
          <span className="ml-1 flex items-center gap-0.5 rounded bg-alert/15 px-1 text-[10.5px] font-semibold text-alert tnum"
            title="consumers flagged by the selected consumer method">
            <AlertOctagon size={11} /> {d.flagged}
          </span>
        )}
      </div>
      {d.truth && (
        <div className="absolute left-0 top-full mt-1 flex items-center gap-1 whitespace-nowrap rounded border border-dashed border-truth bg-plane px-1.5 py-0.5 font-cond text-[10.5px] text-ink">
          <FlaskConical size={11} color="var(--color-truth)" aria-label="simulation ground truth" />
          {d.truth}
        </div>
      )}
      <Handles />
    </div>
  );
}

export function LoadNode({ data }: NodeProps) {
  const d = data as BaseData;
  return (
    <div className={wrap(d)} style={{ width: 22, height: 22 }}>
      <svg width="22" height="22" aria-hidden>
        <path d="M11 1 V14 M4 10 L11 20 L18 10" fill="none" stroke="var(--color-ink-2)" strokeWidth="2" strokeLinejoin="round" />
      </svg>
      <Caption label={d.label} sub={d.sub} place="below" />
      <Handles />
    </div>
  );
}

export const nodeTypes = {
  source: SourceNode,
  bus: BusNode,
  vbus: VerticalBusNode,
  feederTag: FeederTagNode,
  junction: JunctionNode,
  dt: DtNode,
  group: GroupNode,
  load: LoadNode,
};
