"""Reproducible pandapower checks on the IEEE 14-, 39-, and 118-bus cases.

These public benchmark networks validate the power-flow toolchain. They are
separate from the assumed Sharavathi corridor model and are not substitutes
for a verified Karnataka single-line diagram.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import pandapower as pp
import pandapower.networks as pn


IEEE_CASES = ("case14", "case39", "case118")


@dataclass(frozen=True)
class BenchmarkResult:
    case: str
    buses: int
    lines: int
    transformers: int
    converged: bool
    generation_mw: float | None = None
    load_mw: float | None = None
    losses_mw: float | None = None
    min_vm_pu: float | None = None
    max_vm_pu: float | None = None
    max_line_loading_pct: float | None = None
    error: str | None = None


def run_ieee_benchmarks(cases: tuple[str, ...] = IEEE_CASES) -> list[BenchmarkResult]:
    """Run AC Newton-Raphson power flow on selected built-in IEEE networks."""
    results: list[BenchmarkResult] = []
    for case in cases:
        if case not in IEEE_CASES:
            raise ValueError(f"Unsupported benchmark {case!r}; choose from {IEEE_CASES}")
        net = getattr(pn, case)()
        common = {
            "case": case,
            "buses": len(net.bus),
            "lines": len(net.line),
            "transformers": len(net.trafo),
        }
        try:
            pp.runpp(net, algorithm="nr", init="dc", max_iteration=100, numba=False)
            gen = float(net.res_ext_grid.p_mw.sum())
            if len(net.res_gen):
                gen += float(net.res_gen.p_mw.sum())
            if len(net.res_sgen):
                gen += float(net.res_sgen.p_mw.sum())
            load = float(net.res_load.p_mw.sum())
            losses = gen - load
            line_load = (float(net.res_line.loading_percent.max())
                         if len(net.res_line) else 0.0)
            trafo_load = (float(net.res_trafo.loading_percent.max())
                          if len(net.res_trafo) else 0.0)
            results.append(BenchmarkResult(
                **common,
                converged=bool(net.converged),
                generation_mw=round(gen, 6),
                load_mw=round(load, 6),
                losses_mw=round(losses, 6),
                min_vm_pu=round(float(net.res_bus.vm_pu.min()), 6),
                max_vm_pu=round(float(net.res_bus.vm_pu.max()), 6),
                max_line_loading_pct=round(max(line_load, trafo_load), 4),
            ))
        except Exception as exc:
            results.append(BenchmarkResult(
                **common, converged=False, error=f"{type(exc).__name__}: {exc}",
            ))
    return results


def export_ieee_benchmarks(out_path: str | Path) -> pd.DataFrame:
    """Run all benchmark cases and export a CSV or Parquet result table."""
    frame = pd.DataFrame(asdict(row) for row in run_ieee_benchmarks())
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description="Run IEEE pandapower benchmarks")
    parser.add_argument("--out", default="data/processed/ieee_benchmarks.csv")
    args = parser.parse_args()
    frame = export_ieee_benchmarks(args.out)
    print(frame.to_string(index=False))
    return 0 if bool(frame.converged.all()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
