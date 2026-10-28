import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, getStraightPath, type EdgeProps } from "@xyflow/react";

export interface FlowEdgeData extends Record<string, unknown> {
  kind: "line" | "trafo";
  kv: number;
  pMw: number | null; // signed active power at the from-end (pandapower result); null = no solution
  loading: number | null;
  inService: boolean;
  color: string;
  dim: boolean;
  highlight: boolean;
  step: boolean;
}

/**
 * Animated branch. Particle speed encodes |P| (log scale) and direction encodes the sign of
 * the solved active-power flow; nothing moves unless the power-flow snapshot says power flows.
 */
export function FlowEdge(props: EdgeProps) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition } = props;
  const d = props.data as FlowEdgeData;
  const [path, lx, ly] = d.step
    ? getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 10 })
    : getStraightPath({ sourceX, sourceY, targetX, targetY });
  const width = d.kv >= 200 ? 3 : d.kv >= 60 ? 2.5 : d.kv >= 10 ? 2 : 1.5;
  const kw = d.pMw == null ? 0 : Math.abs(d.pMw) * 1000;
  const flowing = d.inService && d.pMw != null && kw > 0.05;
  // 0.1 kW -> slow, 500 MW -> fast. Duration in seconds for one particle to traverse the edge.
  const dur = Math.max(0.7, Math.min(7, 7 / (0.6 + Math.log10(1 + kw) * 0.55)));
  const reverse = (d.pMw ?? 0) < 0;
  const nParticles = 3;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke: d.inService ? d.color : "var(--color-ink-3)",
          strokeWidth: d.highlight ? width + 1.5 : width,
          strokeDasharray: d.inService ? undefined : "6 5",
          opacity: d.dim ? 0.22 : 1,
          transition: "stroke 300ms, opacity 300ms",
        }}
      />
      {flowing && !d.dim &&
        Array.from({ length: nParticles }).map((_, i) => (
          <circle key={i} r={d.kv >= 60 ? 3.2 : 2.6} fill="var(--color-ink)" className="flow-particle" opacity={0.85}>
            <animateMotion
              dur={`${dur}s`}
              repeatCount="indefinite"
              begin={`${(-i * dur) / nParticles}s`}
              path={path}
              keyPoints={reverse ? "1;0" : "0;1"}
              keyTimes="0;1"
              calcMode="linear"
            />
          </circle>
        ))}
      {d.kind === "trafo" && (
        <EdgeLabelRenderer>
          <div
            className="pointer-events-none absolute"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, opacity: d.dim ? 0.3 : 1 }}
          >
            <svg width="30" height="20" aria-hidden>
              <circle cx="11" cy="10" r="7.5" fill="var(--color-plane)" stroke={d.color} strokeWidth="1.8" />
              <circle cx="19" cy="10" r="7.5" fill="none" stroke={d.color} strokeWidth="1.8" />
            </svg>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const edgeTypes = { flow: FlowEdge };
