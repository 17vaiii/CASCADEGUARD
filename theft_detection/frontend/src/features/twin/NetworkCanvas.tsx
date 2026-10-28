import { Background, BackgroundVariant, ConnectionMode, Controls, ReactFlow, useReactFlow, type Edge, type Node, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { fmt } from "../../lib/format";
import { useApp, type Selection } from "../../lib/store";
import type { NetState, Status, Topology } from "../../lib/types";
import { edgeTypes, type FlowEdgeData } from "./FlowEdge";
import { nodeTypes, STATUS_COLOR } from "./nodes";
import { CanvasLegend } from "./CanvasLegend";

// Upstream positions (left part of the diagram). Feeder rows are laid out programmatically.
const UP: Record<string, { x: number; y: number; w?: number }> = {
  GRID220: { x: 0, y: 90 },
  HYD220: { x: 0, y: 330 },
  TXA220: { x: 150, y: 220, w: 100 },
  SRS220: { x: 330, y: 220, w: 100 },
  SRS66: { x: 510, y: 220, w: 90 },
  DSS66: { x: 680, y: 220, w: 90 },
  OTHER66: { x: 544, y: 380 },
};
const ROW_GAP = 205;
const CENTER_Y = 223;
const DSS11_X = 860;
const TAG_X = 885;
const J_X0 = 1110;
const J_DX = 205;

const SHORT: Record<string, string> = {
  GRID220: "Interconnected grid",
  HYD220: "Hydro source",
  TXA220: "220 kV node",
  SRS220: "Receiving stn 220 kV",
  SRS66: "Receiving stn 66 kV",
  DSS66: "Substation 66 kV",
  DSS11: "Substation 11 kV",
  OTHER66: "Other 66 kV load",
};

function rowY(fi: number, n: number) {
  return CENTER_Y + (fi - (n - 1) / 2) * ROW_GAP;
}

function handlesFor(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? ["s-r", "t-l"] : ["s-l", "t-r"];
  return dy > 0 ? ["s-b", "t-t"] : ["s-t", "t-b"];
}

const SPECIAL_HANDLES: Record<string, [string, string]> = {
  "L220-GRID-TXA": ["s-r", "t-l"],
  "L220-GRID-SRS": ["s-t", "t-t"],
  "L220-HYD-TXA": ["s-r", "t-l"],
  "L66-OTHER": ["s-b", "t-t"],
  "T66-11": ["s-r", "t-l"],
};
// Buses with a branch leaving downward keep their caption above the bar.
const CAPTION_ABOVE = new Set(["SRS66"]);

function inSelection(sel: Selection, feeder: string | null, dt: string | null, topo: Topology): boolean | null {
  if (!sel || sel.kind === "bus") return null; // null = no focus, nothing dimmed
  if (feeder == null) return true; // upstream path always shown
  if (sel.kind === "feeder") return feeder === sel.id;
  const selDt = sel.kind === "dt" ? sel.id : sel.id.replace(/^C-/, "").replace(/-\d{3}$/, "");
  const fd = topo.dts.find((d) => d.id === selDt);
  if (!fd || feeder !== fd.feeder) return false;
  if (dt == null) return true;
  return dt === selDt;
}

function buildGraph(topo: Topology, st: NetState | null, sel: Selection, overlay: string, showTruth: boolean) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const n = topo.feeders.length;
  const pos: Record<string, { x: number; y: number }> = {};
  const pf = st?.power_flow;
  const fStatus: Record<string, Status> = {};
  const dStatus: Record<string, Status> = {};
  st?.units.feeder.forEach((u) => (fStatus[u.id] = u.status));
  st?.units.dt.forEach((u) => (dStatus[u.id] = u.status));
  const busById = Object.fromEntries(topo.buses.map((b) => [b.id, b]));
  const rows = topo.feeders.map((_, i) => rowY(i, n));
  const vTop = Math.min(...rows) - 50;
  const vH = Math.max(...rows) - Math.min(...rows) + 100;

  const vmText = (id: string) => {
    const v = pf?.buses?.[id]?.vm_pu;
    return v == null ? undefined : `${v.toFixed(3)} pu`;
  };

  for (const b of topo.buses) {
    const focus = inSelection(sel, b.feeder, b.dt, topo);
    const dim = focus === false;
    const selected = sel?.kind === "bus" && sel.id === b.id;
    if (UP[b.id]) {
      const p = UP[b.id];
      pos[b.id] = { x: p.x, y: p.y };
      if (b.kind === "generator" || b.kind === "grid") {
        const sub = b.kind === "generator"
          ? `${fmt.mw(pf?.gen_p_mw ?? st?.hydro_dispatch_mw, 0)} illustrative dispatch`
          : `slack ${fmt.mw(pf?.slack_p_mw, 0)}`;
        nodes.push({ id: b.id, type: "source", position: p, data: { label: SHORT[b.id], sub, variant: b.kind, dim, selected } });
      } else if (b.kind === "aggregate_load") {
        nodes.push({ id: b.id, type: "load", position: p, data: { label: SHORT[b.id], sub: fmt.mw(pf?.other_66kv_load_mw, 1), dim, selected } });
      } else {
        nodes.push({ id: b.id, type: "bus", position: p, data: { label: SHORT[b.id], sub: `${b.vn_kv} kV${vmText(b.id) ? ", " + vmText(b.id) : ""}`, kv: b.vn_kv, width: p.w, dim, selected, place: CAPTION_ABOVE.has(b.id) ? "above" : "below" } });
      }
    } else if (b.id === "DSS11") {
      pos[b.id] = { x: DSS11_X, y: vTop };
      nodes.push({
        id: b.id, type: "vbus", position: pos[b.id],
        data: { label: SHORT[b.id], sub: `11 kV${vmText(b.id) ? ", " + vmText(b.id) : ""}`, height: vH, dim: false, selected,
          bays: topo.feeders.map((f, i) => ({ id: f.id, offset: rows[i] - vTop })) },
      });
    }
  }

  topo.feeders.forEach((f, fi) => {
    const y = rows[fi];
    const fFocus = inSelection(sel, f.id, null, topo);
    const state = st?.units.feeder.find((u) => u.id === f.id);
    nodes.push({
      id: `tag-${f.id}`, type: "feederTag", position: { x: TAG_X, y: y - 58 },
      data: {
        label: f.id, archetype: f.archetype, status: fStatus[f.id] ?? "unknown",
        scoreText: state ? `score ${state.score.toFixed(2)}` : "score –",
        dim: fFocus === false, selected: sel?.kind === "feeder" && sel.id === f.id,
      },
    });
    f.dts.forEach((dtId, k) => {
      const dt = topo.dts.find((d) => d.id === dtId)!;
      const jx = J_X0 + k * J_DX;
      const focus = inSelection(sel, f.id, dtId, topo);
      const dim = focus === false;
      pos[dt.hv_bus] = { x: jx, y: y - 6 };
      pos[dt.lv_bus] = { x: jx - 42, y: y + 50 };
      pos[dt.group_bus] = { x: jx - 62, y: y + 104 };
      nodes.push({ id: dt.hv_bus, type: "junction", position: pos[dt.hv_bus], data: { label: busById[dt.hv_bus].label, status: fStatus[f.id] ?? "normal", dim: inSelection(sel, f.id, null, topo) === false } });
      const du = st?.units.dt.find((u) => u.id === dtId);
      nodes.push({
        id: dt.lv_bus, type: "dt", position: pos[dt.lv_bus],
        data: { label: dtId, sub: `${dt.sn_kva} kVA, ${du?.meter_kwh_this_hour == null ? "no reading" : fmt.kwh(du.meter_kwh_this_hour)}`,
          status: dStatus[dtId] ?? "unknown", dim, selected: (sel?.kind === "dt" && sel.id === dtId) },
      });
      const g = st?.groups.find((x) => x.dt === dtId);
      let truth: string | null = null;
      if (showTruth && st) {
        const parts: string[] = [];
        if (g && g.truth.unmetered_kw > 0) parts.push(`unmetered load ${g.truth.unmetered_kw.toFixed(1)} kW`);
        if (g && g.truth.theft_like_consumers_active > 0) parts.push(`${g.truth.theft_like_consumers_active} under-recording`);
        st.scenario.events.filter((e) => e.phase === "active" && e.type === "missing_delayed" && e.consumers.some((c) => c.includes(dtId)))
          .forEach((e) => parts.push(`${e.consumers.filter((c) => c.includes(dtId)).length} with data faults`));
        truth = parts.length ? `Injected: ${parts.join(", ")}` : null;
      }
      nodes.push({
        id: dt.group_bus, type: "group", position: pos[dt.group_bus],
        data: { label: dtId, consumers: g?.consumers ?? 0, flagged: du?.consumers_flagged ?? 0,
          meterText: g ? `${fmt.kwh(g.metered_kwh_this_hour)} this hour` : "–", truth, dim,
          selected: sel?.kind === "consumer" && sel.id.startsWith(`C-${dtId}-`) },
      });
    });
  });

  for (const br of topo.branches) {
    const a = pos[br.from_bus];
    const b = pos[br.to_bus];
    if (!a || !b) continue;
    let [sh, th] = SPECIAL_HANDLES[br.id] ?? handlesFor(a, b);
    if (br.from_bus === "DSS11") {
      sh = `bay-${br.feeder}`;
      th = "t-l";
    }
    if (br.dt) [sh, th] = ["s-b", "t-t"];
    const res = pf?.branches?.[br.id];
    const kv = busById[br.to_bus].vn_kv;
    let color = "var(--color-flow)";
    if (overlay === "loading") {
      const l = res?.loading_pct ?? 0;
      color = l > 100 ? "var(--color-alert)" : l > 80 ? "var(--color-warn)" : "var(--color-flow)";
    } else if (br.dt) {
      color = STATUS_COLOR[dStatus[br.dt] ?? "normal"];
    } else if (br.feeder) {
      color = STATUS_COLOR[fStatus[br.feeder] ?? "normal"];
    }
    const focus = inSelection(sel, br.feeder, br.dt, topo);
    const data: FlowEdgeData = {
      kind: br.kind, kv, pMw: res ? res.p_from_mw : null, loading: res?.loading_pct ?? null,
      inService: res ? res.in_service : true, color, dim: focus === false, highlight: focus === true && sel != null,
      step: true,
    };
    edges.push({ id: br.id, source: br.from_bus, target: br.to_bus, sourceHandle: sh, targetHandle: th, type: "flow", data, selectable: true });
  }
  return { nodes, edges };
}

function selectionFor(nodeId: string, topo: Topology): Selection {
  if (nodeId.startsWith("tag-")) return { kind: "feeder", id: nodeId.slice(4) };
  const bus = topo.buses.find((b) => b.id === nodeId);
  if (!bus) return null;
  if (bus.kind === "mv_junction") return { kind: "feeder", id: bus.feeder! };
  if (bus.kind === "dt_lv" || bus.kind === "consumer_group") return { kind: "dt", id: bus.dt! };
  return { kind: "bus", id: nodeId };
}

function HoverCard({ nodeId, x, y }: { nodeId: string; x: number; y: number }) {
  const topo = useApp((s) => s.topo)!;
  const st = useApp((s) => s.state);
  const sel = selectionFor(nodeId, topo);
  let title = "";
  const lines: [string, string][] = [];
  let note = "";
  if (sel?.kind === "feeder" || sel?.kind === "dt") {
    const u = st?.units[sel.kind].find((v) => v.id === sel.id);
    title = sel.kind === "feeder" ? `Feeder ${sel.id}` : `Distribution transformer ${sel.id}`;
    if (u) {
      lines.push(["Input, last 24 h", fmt.kwh(u.balance_24h.input_kwh)]);
      lines.push(["Unexplained, last 24 h", `${fmt.kwh(u.balance_24h.unexplained_kwh)} (${fmt.sigma(u.balance_24h.z)})`]);
      lines.push(["Detection score", `${u.score.toFixed(2)} (threshold ${u.threshold.toFixed(2)})`]);
      lines.push(["Consumers flagged", `${u.consumers_flagged} of ${u.consumers}`]);
    }
    note = "Click to open details";
  } else if (sel?.kind === "bus") {
    const b = topo.buses.find((v) => v.id === nodeId)!;
    title = b.label;
    const r = st?.power_flow.buses?.[nodeId];
    if (r?.vm_pu != null) lines.push(["Voltage (power flow)", `${r.vm_pu.toFixed(4)} pu`]);
    lines.push(["Nominal voltage", `${b.vn_kv} kV`]);
    note = b.provenance === "public-source" ? "Name anchored to public sources; parameters illustrative" : b.provenance === "illustrative" ? "Illustrative element" : "Modelling assumption";
  }
  return (
    <div className="pointer-events-none absolute z-20 w-72 rounded-md border border-hair-strong bg-panel/95 p-3 shadow-xl" style={{ left: x + 14, top: y + 14 }}>
      <div className="font-cond text-[13px] font-semibold">{title}</div>
      <dl className="mt-1.5 space-y-0.5 text-[12px]">
        {lines.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3"><dt className="text-ink-3">{k}</dt><dd className="tnum text-ink">{v}</dd></div>
        ))}
      </dl>
      {note && <div className="mt-1.5 text-[11px] text-ink-3">{note}</div>}
    </div>
  );
}

function Canvas() {
  const topo = useApp((s) => s.topo);
  const st = useApp((s) => s.state);
  const sel = useApp((s) => s.selection);
  const overlay = useApp((s) => s.overlay);
  const showTruth = useApp((s) => s.showTruth);
  const select = useApp((s) => s.select);
  const { fitView } = useReactFlow();
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const graph = useMemo(() => (topo ? buildGraph(topo, st, sel, overlay, showTruth) : { nodes: [], edges: [] }), [topo, st, sel, overlay, showTruth]);

  useEffect(() => {
    const id = window.setTimeout(() => fitView({ padding: 0.05, duration: 300 }), 60);
    return () => window.clearTimeout(id);
  }, [topo, fitView]);

  if (!topo) return null;
  return (
    <div ref={box} className="relative h-full w-full" onMouseLeave={() => setHover(null)}>
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        connectionMode={ConnectionMode.Loose}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.25}
        maxZoom={2.5}
        proOptions={{ hideAttribution: false }}
        onNodeClick={(_, n) => select(selectionFor(n.id, topo))}
        onEdgeClick={(_, e) => {
          const br = topo.branches.find((b) => b.id === e.id);
          if (br?.dt) select({ kind: "dt", id: br.dt });
          else if (br?.feeder) select({ kind: "feeder", id: br.feeder });
        }}
        onPaneClick={() => select(null)}
        onNodeMouseEnter={(ev, n) => {
          const r = box.current?.getBoundingClientRect();
          if (r && (n.type !== "junction")) setHover({ id: n.id, x: ev.clientX - r.left, y: ev.clientY - r.top });
        }}
        onNodeMouseLeave={() => setHover(null)}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#1b2a42" />
        <Controls showInteractive={false} position="top-right" />
      </ReactFlow>
      <div className="absolute left-3 top-3 z-10 flex rounded border border-hair-strong bg-panel/95 p-0.5 font-cond text-[12.5px]" role="group" aria-label="Zoom presets">
        <button onClick={() => fitView({ padding: 0.05, duration: 400 })} className="rounded px-2 py-1 text-ink-2 hover:bg-raised hover:text-ink">Whole chain</button>
        <button onClick={() => fitView({ padding: 0.06, duration: 400, nodes: graph.nodes.filter((n) => n.type !== "source" && n.type !== "bus" && n.type !== "load").map((n) => ({ id: n.id })) })}
          className="rounded px-2 py-1 text-ink-2 hover:bg-raised hover:text-ink">Feeders</button>
      </div>
      {hover && <HoverCard nodeId={hover.id} x={hover.x} y={hover.y} />}
      <CanvasLegend />
    </div>
  );
}

export function NetworkCanvas() {
  return (
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  );
}
