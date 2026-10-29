"""
grid/attack_finder.py — Corridor weak-link and N-k attack finder.

Identifies the most dangerous line-trip combinations that maximise load
shedding on the Sharavathi corridor using greedy and beam search.

Public API
----------
find_weakest_lines(net, k, method, beam_width, loading_threshold, top_n)
    → list[AttackResult]

greedy_search(net, k, loading_threshold)
    → AttackResult (best greedy k-line combination)

beam_search(net, k, beam_width, loading_threshold, top_n)
    → list[AttackResult] (top-n results from beam search)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional
from collections.abc import Callable

from grid.cascade import (
    CascadeResult,
    simulate_cascade,
)


@dataclass
class AttackResult:
    """Result of a weak-link search."""
    lines_tripped: list[int] = field(default_factory=list)
    line_names: list[str] = field(default_factory=list)
    cascade: Optional[CascadeResult] = None
    score: float = 0.0  # Bengaluru load lost MW (system MW if no target bus exists)
    bengaluru_load_lost_mw: float = 0.0
    predicted_score: float | None = None
    verified: bool = True


def _score_trips(net, trips: list[int], threshold: float) -> AttackResult:
    """Simulate cascade for given trips and return scored result."""
    result = simulate_cascade(
        net, trips, loading_threshold=threshold,
    )
    return AttackResult(
        lines_tripped=trips,
        line_names=result.initial_trip_names,
        cascade=result,
        # Bengaluru's demand is the target of the PRD weak-link experiment.
        # Fall back to system load only for non-corridor topologies without
        # PEENYA/BENGALURU-labelled load buses.
        score=(result.bengaluru_load_lost_mw
               if any("PEENYA" in str(n).upper() or "BENGALURU" in str(n).upper()
                      for n in net.bus["name"])
               else result.load_lost_mw),
        bengaluru_load_lost_mw=result.bengaluru_load_lost_mw,
    )


def greedy_search(
    net,
    k: int = 2,
    loading_threshold: float = 100.0,
) -> AttackResult:
    """
    Greedy N-k attack search: at each step, pick the single additional line
    that maximises load shed when added to the current set of trips.

    Fast: O(k × L) cascade simulations where L = number of lines.
    """
    all_lines = list(net.line.index)
    chosen: list[int] = []

    for step in range(k):
        best_score = -1.0
        best_line = None
        best_result = None

        for li in all_lines:
            if li in chosen:
                continue
            candidate = chosen + [int(li)]
            ar = _score_trips(net, candidate, loading_threshold)
            if ar.score > best_score:
                best_score = ar.score
                best_line = int(li)
                best_result = ar

        if best_line is not None:
            chosen.append(best_line)
        if best_result and best_result.cascade and best_result.cascade.blackout:
            break  # total blackout — no point continuing

    return _score_trips(net, chosen, loading_threshold)


def beam_search(
    net,
    k: int = 2,
    beam_width: int = 10,
    loading_threshold: float = 100.0,
    top_n: int = 10,
) -> list[AttackResult]:
    """
    Beam search N-k attack finder: maintains top beam_width candidates at each
    depth level and extends each by one more line trip.

    Returns top_n combinations ranked by Bengaluru load lost (or total system
    load lost for generic networks without a Bengaluru endpoint).
    """
    all_lines = [int(li) for li in net.line.index]

    # Initialise beam with single-line results
    beam: list[AttackResult] = []
    for li in all_lines:
        ar = _score_trips(net, [li], loading_threshold)
        beam.append(ar)

    beam.sort(key=lambda a: a.score, reverse=True)
    beam = beam[:beam_width]

    # Extend beam up to k lines
    for depth in range(2, k + 1):
        candidates: list[AttackResult] = []
        seen: set[tuple[int, ...]] = set()

        for parent in beam:
            for li in all_lines:
                if li in parent.lines_tripped:
                    continue
                new_trips = sorted(parent.lines_tripped + [li])
                key = tuple(new_trips)
                if key in seen:
                    continue
                seen.add(key)
                ar = _score_trips(net, new_trips, loading_threshold)
                candidates.append(ar)

        candidates.sort(key=lambda a: a.score, reverse=True)
        beam = candidates[:beam_width]

        # Early exit if top result is total blackout
        if beam and beam[0].cascade and beam[0].cascade.blackout:
            break

    # Collect unique results
    seen_final: set[tuple[int, ...]] = set()
    results: list[AttackResult] = []
    for ar in beam:
        key = tuple(sorted(ar.lines_tripped))
        if key not in seen_final:
            seen_final.add(key)
            results.append(ar)

    results.sort(key=lambda a: a.score, reverse=True)
    return results[:top_n]


def find_weakest_lines(
    net,
    k: int = 2,
    method: str = "beam",
    beam_width: int = 10,
    loading_threshold: float = 100.0,
    top_n: int = 10,
) -> list[AttackResult]:
    """
    Find the most damaging k-line trip combinations.

    Parameters
    ----------
    net : pp.pandapowerNet
        Cascade network from build_cascade_net().
    k : int
        Number of simultaneous line trips (N-k).
    method : str
        "greedy" for fast single-best, "beam" for broader search.
    beam_width : int
        Number of candidates kept at each depth (beam search only).
    loading_threshold : float
        Overload threshold in % (default 100).
    top_n : int
        Number of results to return.

    Returns
    -------
    list[AttackResult]
    Sorted by Bengaluru load lost (worst first).
    """
    if method == "greedy":
        result = greedy_search(net, k, loading_threshold)
        return [result]
    elif method == "beam":
        return beam_search(net, k, beam_width, loading_threshold, top_n)
    else:
        raise ValueError(f"Unknown method: {method!r}. Use 'greedy' or 'beam'.")


def gnn_guided_search(
    net, scorer: Callable[[object, list[int]], float], *, k: int = 2,
    beam_width: int = 20, verify_top_n: int = 10,
    loading_threshold: float = 100.0,
) -> list[AttackResult]:
    """Use a Person 2 scorer to guide search, then verify finalists in AC PF.

    The scorer contract is ``scorer(net, sorted_trip_ids) -> risk score``.
    Scores guide pruning only; returned ``score`` and cascade labels always
    come from the Person 1 simulator.
    """
    if k < 1 or beam_width < 1 or verify_top_n < 1:
        raise ValueError("k, beam_width and verify_top_n must be positive")
    lines = [int(i) for i in net.line.index]
    beam: list[tuple[list[int], float]] = [([], 0.0)]
    for _depth in range(k):
        candidates: dict[tuple[int, ...], float] = {}
        for trips, _ in beam:
            for line in lines:
                if line in trips:
                    continue
                next_trips = sorted([*trips, line])
                key = tuple(next_trips)
                if key not in candidates:
                    candidates[key] = float(scorer(net, next_trips))
        beam = [(list(key), value) for key, value in
                sorted(candidates.items(), key=lambda pair: pair[1], reverse=True)[:beam_width]]
        if not beam:
            break
    verified = []
    for trips, prediction in beam[:verify_top_n]:
        item = _score_trips(net, trips, loading_threshold)
        item.predicted_score = prediction
        item.verified = True
        verified.append(item)
    return sorted(verified, key=lambda item: item.score, reverse=True)


def minimum_k_attack_search(
    net, *, max_k: int = 3, target_load_lost_mw: float | None = None,
    target_shed_fraction: float = 1.0, method: str = "beam", beam_width: int = 20,
    loading_threshold: float = 100.0,
) -> AttackResult | None:
    """Find the smallest simulated trip set meeting a load-loss target.

    By default, target is complete loss of the Bengaluru endpoint load (or
    system load for generic networks). Returns None if no candidate through
    ``max_k`` reaches the target.
    """
    if max_k < 1 or not 0 < target_shed_fraction <= 1:
        raise ValueError("max_k must be positive and target_shed_fraction in (0, 1]")
    target_base = (float(net.get("bengaluru_load_mw", 0.0))
                   if float(net.get("bengaluru_load_mw", 0.0)) > 0
                   else float(net.get("total_load_mw", sum(net.load.p_mw))))
    target = target_load_lost_mw if target_load_lost_mw is not None else target_base * target_shed_fraction
    for k in range(1, max_k + 1):
        results = (beam_search(net, k, beam_width, loading_threshold, beam_width)
                   if method == "beam" else [greedy_search(net, k, loading_threshold)]
                   if method == "greedy" else None)
        if results is None:
            raise ValueError("method must be 'beam' or 'greedy'")
        qualifying = [r for r in results if r.score >= target]
        if qualifying:
            return min(qualifying, key=lambda r: (len(r.lines_tripped), -r.score))
    return None


def seasonal_weak_link_report(
    topology=None,
    seasons: Optional[list[str]] = None,
    *,
    load_scale: float = 1.0,
    loading_threshold: float = 100.0,
    top_n: int = 20,
) -> list[dict]:
    """Rank single-line weak links per season by Bengaluru load lost (H4).

    Returns records suitable for CSV/Parquet export, with season, line identity,
    cascade depth, total loss and Bengaluru-specific loss labels.
    """
    from grid.cascade import build_cascade_net
    from grid.config import load_topology
    from grid.hydro import apply_season, get_all_seasons

    topo = topology or load_topology()
    available = get_all_seasons()
    selected = seasons or list(available)
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise ValueError(f"Unknown season(s): {unknown}")

    records: list[dict] = []
    for season_name in selected:
        net = build_cascade_net(topo, load_scale=load_scale)
        apply_season(net, available[season_name])
        candidates = [_score_trips(net, [int(li)], loading_threshold)
                      for li in net.line.index]
        candidates.sort(key=lambda item: item.score, reverse=True)
        for rank, item in enumerate(candidates[:top_n], start=1):
            result = item.cascade
            records.append({
                "season": season_name,
                "rank": rank,
                "line_idx": item.lines_tripped[0],
                "line_name": item.line_names[0] if item.line_names else "",
                "bengaluru_load_lost_mw": result.bengaluru_load_lost_mw,
                "system_load_lost_mw": result.load_lost_mw,
                "cascade_depth": result.cascade_depth,
                "failed_lines": result.failed_lines,
                "blackout": result.blackout,
            })
    return records


def export_seasonal_weak_link_report(
    out_path=None,
    topology=None,
    seasons: Optional[list[str]] = None,
    *,
    load_scale: float = 1.0,
    loading_threshold: float = 100.0,
    top_n: int = 20,
):
    """Generate and save the H4 weak-link table as Parquet or CSV."""
    from pathlib import Path
    import pandas as pd

    path = Path(out_path or "data/processed/weak_link_report.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(seasonal_weak_link_report(
        topology, seasons, load_scale=load_scale,
        loading_threshold=loading_threshold, top_n=top_n,
    ))
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
    return frame


def export_dataset_attack_report(
    dataset_path="data/processed/cascade_dataset.parquet",
    out_path="data/processed/attack_report.parquet",
    *,
    top_n: int = 20,
):
    """Rank simulated N-k contingencies by Bengaluru loss, per season and k."""
    from pathlib import Path
    import pandas as pd

    source = pd.read_parquet(dataset_path)
    required = {"season", "contingency_k", "bengaluru_load_lost_mw", "load_lost_mw"}
    missing = required - set(source.columns)
    if missing:
        raise ValueError(f"Cascade dataset lacks attack-ranking columns: {sorted(missing)}")
    ranked = source.sort_values(
        ["bengaluru_load_lost_mw", "load_lost_mw", "cascade_depth"],
        ascending=[False, False, False], kind="stable",
    )
    report = ranked.groupby(["season", "contingency_k"], sort=False).head(top_n).copy()
    report["rank"] = report.groupby(["season", "contingency_k"], sort=False).cumcount() + 1
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        report.to_csv(path, index=False)
    else:
        report.to_parquet(path, index=False)
    return report


if __name__ == "__main__":
    import argparse
    import logging

    parser = argparse.ArgumentParser(description="Build seasonal corridor weak-link report")
    parser.add_argument("--out", default="data/processed/weak_link_report.parquet")
    parser.add_argument("--seasons", nargs="+", default=None)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--load-scale", type=float, default=1.0)
    parser.add_argument("--attack-dataset", default=None)
    parser.add_argument("--attack-out", default="data/processed/attack_report.parquet")
    parser.add_argument("--attack-top-n", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    frame = export_seasonal_weak_link_report(
        args.out, seasons=args.seasons, top_n=args.top_n,
        load_scale=args.load_scale,
    )
    print(f"Saved {len(frame)} rows to {args.out}")
    if args.attack_dataset:
        attacks = export_dataset_attack_report(
            args.attack_dataset, args.attack_out, top_n=args.attack_top_n,
        )
        print(f"Saved {len(attacks)} attack rows to {args.attack_out}")

