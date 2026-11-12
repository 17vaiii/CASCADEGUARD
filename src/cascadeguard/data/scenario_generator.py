# OWNER: P2 | NEEDS: P1 | STATUS: ACTIVE
"""Generate labelled corridor cascade scenarios using the main package simulator."""

from __future__ import annotations

import argparse

from cascadeguard.data.cascade_sim.simdata.cascade_scenarios import generate_cascade_dataset


def generate_scenarios(
    output: str = "data/processed/cascade_dataset.parquet",
    seasons: list[str] | None = None,
    k_max: int = 2,
    load_scales: list[float] | None = None,
    seed: int = 42,
    backend: str = "ray",
    workers: int = 4,
    ray_address: str | None = None,
):
    """Generate labelled N-k Parquet rows with the repository-local simulator."""
    if backend not in {"sequential", "joblib", "ray"}:
        raise ValueError("backend must be sequential, joblib or ray")
    if workers < 1:
        raise ValueError("workers must be positive")
    return generate_cascade_dataset(
        seasons=seasons,
        k_range=(1, k_max),
        load_scale_points=load_scales,
        seed=seed,
        n_jobs=workers,
        backend=backend,
        output_uri=output,
        ray_address=ray_address,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/processed/cascade_dataset.parquet")
    parser.add_argument("--seasons", nargs="+", default=None)
    parser.add_argument("--k-max", type=int, default=2, choices=(1, 2, 3))
    parser.add_argument("--load-scales", nargs="+", type=float, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--backend", choices=("sequential", "joblib", "ray"), default="ray")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--ray-address", default=None)
    args = parser.parse_args()
    frame = generate_scenarios(args.output, args.seasons, args.k_max, args.load_scales,
                               args.seed, args.backend, args.workers, args.ray_address)
    attempted = int(frame.attrs.get("scenarios_attempted", len(frame)))
    print(f"Simulated {attempted:,} cascade scenarios; wrote {len(frame):,} labelled rows at {args.output}")


if __name__ == "__main__":
    main()