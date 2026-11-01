"""Compare single-machine sequential throughput with Ray throughput."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.request import urlopen

from cascadeguard.common.io import write_json
from cascadeguard.data.scenario_generator import generate_scenarios


def benchmark(
    output_dir: str = "data/processed/throughput",
    seasons: list[str] | None = None,
    k_max: int = 1,
    load_scales: list[float] | None = None,
    workers: int = 4,
    ray_address: str | None = None,
    seed: int = 42,
) -> dict:
    """Run identical workloads serially and through Ray, and record scenarios/hour."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    measurements = {}
    for label, backend in (("single_machine", "sequential"), ("ray", "ray")):
        destination = str(root / f"cascade_{label}.parquet")
        start = time.perf_counter()
        frame = generate_scenarios(destination, seasons, k_max, load_scales,
                                   seed, backend, workers, ray_address)
        elapsed = max(time.perf_counter() - start, 1e-9)
        attempted = int(frame.attrs.get("scenarios_attempted", len(frame)))
        measurements[label] = {
            "backend": backend,
            "execution_scope": "cluster" if backend == "ray" and ray_address else "local",
            "scenarios_attempted": attempted,
            "scenarios_written": int(len(frame)),
            "elapsed_seconds": round(elapsed, 3),
            "scenarios_per_hour": round(attempted * 3600 / elapsed, 2),
            "output": destination,
        }
    measurements["ray_speedup_vs_single_machine"] = round(
        measurements["ray"]["scenarios_per_hour"] /
        max(measurements["single_machine"]["scenarios_per_hour"], 1e-9), 3)
    measurements["seed"] = seed
    measurements["settings"] = {"seasons": seasons, "k_max": k_max,
                                 "load_scales": load_scales, "workers": workers,
                                 "ray_address": ray_address}
    measurements["note"] = (
        "Both measurements are local until ray_address targets an external cluster. "
        "The sequential and Ray workloads use identical scenario settings."
    )
    report_path = root / "throughput_benchmark.json"
    write_json(measurements, report_path)
    measurements["tracking"] = _track_benchmark(report_path, measurements)
    write_json(measurements, report_path)
    return measurements


def _track_benchmark(report_path: Path, metrics: dict) -> dict:
    """Log a throughput run when the local/shared MLflow endpoint is available."""
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000").rstrip("/")
    if tracking_uri.startswith(("http://", "https://")):
        try:
            with urlopen(tracking_uri, timeout=1):
                pass
        except Exception:
            return {"status": "skipped", "reason": "tracking server is not reachable"}
    try:
        import mlflow
    except ImportError:
        return {"status": "skipped", "reason": "mlflow is not installed"}
    try:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment("cascadeguard-p2-throughput")
        params = {key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value
                  for key, value in metrics["settings"].items() if value is not None}
        with mlflow.start_run(run_name="cascade-throughput") as run:
            mlflow.log_params(params)
            mlflow.log_metrics({
                "single_machine_scenarios_per_hour": metrics["single_machine"]["scenarios_per_hour"],
                "ray_scenarios_per_hour": metrics["ray"]["scenarios_per_hour"],
                "ray_speedup": metrics["ray_speedup_vs_single_machine"],
            })
            mlflow.log_artifact(str(report_path))
            experiment_id = run.info.experiment_id
            run_id = run.info.run_id
        return {"status": "logged", "run_id": run_id, "experiment_id": experiment_id,
                "url": f"{tracking_uri}/#/experiments/{experiment_id}/runs/{run_id}"}
    except Exception as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="data/processed/throughput")
    parser.add_argument("--seasons", nargs="+", default=None)
    parser.add_argument("--k-max", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--load-scales", nargs="+", type=float, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--ray-address", default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = benchmark(args.output_dir, args.seasons, args.k_max, args.load_scales,
                       args.workers, args.ray_address, args.seed)
    print(result)


if __name__ == "__main__":
    main()
