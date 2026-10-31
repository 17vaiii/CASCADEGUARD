"""Team experiment tracking helpers backed by a shared MLflow server."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator


def configure_tracking(experiment_name: str, tracking_uri: str | None = None) -> None:
    """Configure the MLflow client; defaults to the local compose service."""
    try:
        import mlflow
    except ImportError as exc:
        raise RuntimeError("Install mlflow to record experiments") from exc
    mlflow.set_tracking_uri(tracking_uri or os.getenv(
        "MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment(experiment_name)


@contextmanager
def tracked_run(experiment_name: str, run_name: str | None = None,
                params: dict[str, Any] | None = None,
                tags: dict[str, str] | None = None) -> Iterator[Any]:
    """Start a named team run and log its declared params/tags."""
    configure_tracking(experiment_name)
    import mlflow
    with mlflow.start_run(run_name=run_name) as run:
        if params:
            mlflow.log_params(params)
        if tags:
            mlflow.set_tags(tags)
        yield run
