#!/usr/bin/env python3
# OWNER: P1 | STATUS: ACTIVE
"""Scaffold generator for CascadeGuard-Sharavathi repository.
Generates all directory structures and placeholder files with ownership headers.
Strictly ignores and preserves 'theft_detection/'.
"""

import os
import json
from pathlib import Path

ROOT = Path("/home/sj/git_projects/CASCADEGUARD")

def get_header(path_str: str, owner: str, needs: str = None, is_p1: bool = False) -> str:
    status = "ACTIVE" if is_p1 else "LOCKED (until P1 handoff done)"
    needs_part = f" | NEEDS: {needs}" if needs else ""
    header_comment = f"OWNER: {owner}{needs_part} | STATUS: {status}"

    if path_str.endswith(".py") or path_str.endswith(".yaml") or path_str.endswith(".yml") or \
       path_str.endswith(".toml") or path_str.endswith(".sh") or path_str.endswith(".txt") or \
       path_str.endswith(".env.example") or path_str.endswith("Makefile") or path_str.endswith("CODEOWNERS") or \
       path_str.endswith(".gitignore") or path_str.endswith("Dockerfile.api") or path_str.endswith("Dockerfile.dashboard"):
        return f"# {header_comment}\n"
    elif path_str.endswith(".md"):
        return f"<!-- {header_comment} -->\n# {header_comment}\n"
    elif path_str.endswith(".json") or path_str.endswith(".schema.json"):
        return json.dumps({"$comment": header_comment}, indent=2) + "\n"
    elif path_str.endswith(".csv"):
        return f"# {header_comment}\n"
    elif path_str.endswith(".ipynb"):
        nb = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [f"# {header_comment}\n"]
                }
            ],
            "metadata": {
                "language_info": {"name": "python"}
            },
            "nbformat": 4,
            "nbformat_minor": 2
        }
        return json.dumps(nb, indent=2) + "\n"
    else:
        return f"# {header_comment}\n"

# Files specification: (relative_path, owner, needs, is_p1)
FILES = [
    # Root configs
    ("README.md", "P2", None, False),
    ("pyproject.toml", "P2", None, False),
    ("requirements.txt", "P2", None, False),
    (".gitignore", "P2", None, False),
    (".env.example", "P2", None, False),
    ("Makefile", "P2", None, False),
    ("CODEOWNERS", "P2", None, False),
    ("OWNERSHIP.md", "P1", None, True),
    (".agent/role", "P1", None, True),
    (".agent/rules/ownership.md", "P1", None, True),
    (".github/workflows/ci.yml", "P2", None, False),
    ("scripts/check_ownership.py", "P1", None, True),
    ("scripts/scaffold.sh", "P1", None, True),

    # contracts
    ("contracts/grid_snapshot.schema.json", "P2", "P1", False),
    ("contracts/scenario_record.schema.json", "P2", "P1", False),
    ("contracts/graph_tensor_format.md", "P3", "P2", False),
    ("contracts/meter_data.schema.json", "P2", None, False),
    ("contracts/openapi.yaml", "P2", "P3,P4,P5", False),

    # configs
    ("configs/grids/ieee14.yaml", "P1", None, True),
    ("configs/grids/ieee39.yaml", "P1", None, True),
    ("configs/grids/ieee118.yaml", "P1", None, True),
    ("configs/grids/corridor_v0.yaml", "P1", None, True),
    ("configs/seasons/monsoon.yaml", "P1", None, True),
    ("configs/seasons/post_monsoon.yaml", "P1", None, True),
    ("configs/seasons/summer.yaml", "P1", None, True),
    ("configs/hydro/hydro_limits.yaml", "P1", None, True),
    ("configs/cloud/ray_cluster.yaml", "P2", None, False),
    ("configs/model/gnn.yaml", "P3", "P2", False),
    ("configs/model/baselines.yaml", "P3", "P2", False),
    ("configs/theft/theft_injection.yaml", "P2", None, False),
    ("configs/theft/models.yaml", "P4", "P2", False),
    ("configs/mitigation/optimizer.yaml", "P5", "P1", False),

    # src/cascadeguard
    ("src/cascadeguard/__init__.py", "P1", None, True),
    ("src/cascadeguard/common/__init__.py", "P2", None, False),
    ("src/cascadeguard/common/seed.py", "P2", None, False),
    ("src/cascadeguard/common/logging.py", "P2", None, False),
    ("src/cascadeguard/common/io.py", "P2", None, False),

    # grid (all P1)
    ("src/cascadeguard/grid/__init__.py", "P1", None, True),
    ("src/cascadeguard/grid/loaders.py", "P1", None, True),
    ("src/cascadeguard/grid/corridor_model.py", "P1", None, True),
    ("src/cascadeguard/grid/seasons.py", "P1", None, True),
    ("src/cascadeguard/grid/hydro.py", "P1", None, True),
    ("src/cascadeguard/grid/topology_generator.py", "P1", None, True),

    # sim (all P1)
    ("src/cascadeguard/sim/__init__.py", "P1", None, True),
    ("src/cascadeguard/sim/cascade_engine.py", "P1", None, True),
    ("src/cascadeguard/sim/trip_rules.py", "P1", None, True),
    ("src/cascadeguard/sim/islanding.py", "P1", None, True),
    ("src/cascadeguard/sim/contingency.py", "P1", None, True),
    ("src/cascadeguard/sim/outcomes.py", "P1", None, True),
    ("src/cascadeguard/sim/weak_link.py", "P1", "P3", True),
    ("src/cascadeguard/sim/attack_finder.py", "P1", "P3", True),
    ("src/cascadeguard/sim/overlays.py", "P1", None, True),

    # data
    ("src/cascadeguard/data/__init__.py", "P2", None, False),
    ("src/cascadeguard/data/scenario_generator.py", "P2", "P1", False),
    ("src/cascadeguard/data/meter_generator.py", "P2", "P1", False),
    ("src/cascadeguard/data/writers.py", "P2", None, False),

    # cascade_ml
    ("src/cascadeguard/cascade_ml/__init__.py", "P3", None, False),
    ("src/cascadeguard/cascade_ml/graph_builder.py", "P3", "P2", False),
    ("src/cascadeguard/cascade_ml/baselines.py", "P3", "P2", False),
    ("src/cascadeguard/cascade_ml/gnn.py", "P3", "P2", False),
    ("src/cascadeguard/cascade_ml/train.py", "P3", "P2", False),
    ("src/cascadeguard/cascade_ml/calibration.py", "P3", None, False),
    ("src/cascadeguard/cascade_ml/screening.py", "P3", "P1", False),
    ("src/cascadeguard/cascade_ml/explain.py", "P3", None, False),
    ("src/cascadeguard/cascade_ml/embeddings_export.py", "P3", None, False),

    # theft
    ("src/cascadeguard/theft/__init__.py", "P4", None, False),
    ("src/cascadeguard/theft/technical_loss.py", "P4", "P1", False),
    ("src/cascadeguard/theft/energy_balance.py", "P4", "P2", False),
    ("src/cascadeguard/theft/anomaly.py", "P4", "P2", False),
    ("src/cascadeguard/theft/supervised.py", "P4", "P2", False),
    ("src/cascadeguard/theft/fusion.py", "P4", None, False),
    ("src/cascadeguard/theft/graph_theft.py", "P4", None, False),
    ("src/cascadeguard/theft/reason_codes.py", "P4", None, False),
    ("src/cascadeguard/theft/inspection.py", "P4", None, False),
    ("src/cascadeguard/theft/tamper_signals.py", "P4", None, False),
    ("src/cascadeguard/theft/hidden_load.py", "P4", "P1,P3", False),
    ("src/cascadeguard/theft/fairness.py", "P4", None, False),
    ("src/cascadeguard/theft/ht_tapping.py", "P4", "P1", False),

    # mitigation
    ("src/cascadeguard/mitigation/__init__.py", "P5", None, False),
    ("src/cascadeguard/mitigation/baselines.py", "P5", "P1", False),
    ("src/cascadeguard/mitigation/optimizer.py", "P5", "P1", False),
    ("src/cascadeguard/mitigation/hydro_redispatch.py", "P5", "P1", False),
    ("src/cascadeguard/mitigation/verifier.py", "P5", "P1", False),

    # retrieval
    ("src/cascadeguard/retrieval/__init__.py", "P5", None, False),
    ("src/cascadeguard/retrieval/case_store.py", "P5", "P2,P3", False),
    ("src/cascadeguard/retrieval/warm_start.py", "P5", None, False),

    # copilot
    ("src/cascadeguard/copilot/__init__.py", "P5", None, False),
    ("src/cascadeguard/copilot/brief.py", "P5", None, False),
    ("src/cascadeguard/copilot/citations.py", "P5", None, False),

    # api
    ("src/cascadeguard/api/__init__.py", "P2", None, False),
    ("src/cascadeguard/api/main.py", "P2", "P3,P4,P5", False),
    ("src/cascadeguard/api/routes_resilience.py", "P2", "P3,P4,P5", False),
    ("src/cascadeguard/api/routes_theft.py", "P2", "P3,P4,P5", False),
    ("src/cascadeguard/api/audit.py", "P2", None, False),
    ("src/cascadeguard/api/streaming.py", "P2", None, False),

    # dashboard
    ("src/cascadeguard/dashboard/__init__.py", "P5", None, False),
    ("src/cascadeguard/dashboard/app.py", "P5", "P2", False),
    ("src/cascadeguard/dashboard/views/__init__.py", "P5", None, False),
    ("src/cascadeguard/dashboard/views/resilience.py", "P5", "P3,P4", False),
    ("src/cascadeguard/dashboard/views/theft.py", "P5", "P3,P4", False),

    # tests
    ("tests/__init__.py", "P1", None, True),
    ("tests/grid/__init__.py", "P1", None, True),
    ("tests/sim/__init__.py", "P1", None, True),
    ("tests/data/__init__.py", "P2", None, False),
    ("tests/api/__init__.py", "P2", None, False),
    ("tests/cascade_ml/__init__.py", "P3", None, False),
    ("tests/theft/__init__.py", "P4", None, False),
    ("tests/mitigation/__init__.py", "P5", None, False),
    ("tests/retrieval/__init__.py", "P5", None, False),
    ("tests/dashboard/__init__.py", "P5", None, False),

    # notebooks
    ("notebooks/p1_ieee_powerflow.ipynb", "P1", None, True),

    # experiments & data
    ("experiments/.gitkeep", "P2", None, False),
    ("data/raw/.gitkeep", "P2", None, False),
    ("data/processed/.gitkeep", "P2", None, False),
    ("data/samples/.gitkeep", "P2", None, False),

    # docker
    ("docker/Dockerfile.api", "P2", None, False),
    ("docker/Dockerfile.dashboard", "P5", "P2", False),

    # docs
    ("docs/p1/assumptions_sheet.csv", "P1", None, True),
    ("docs/p1/scenario_output_spec.md", "P1", None, True),
    ("docs/p1/handoff_release1.md", "P1", None, True),
    ("docs/p1/handoff_release2.md", "P1", None, True),
    ("docs/p1/handoff_release3.md", "P1", None, True),
    ("docs/p1/sources/sources_index.csv", "P1", None, True),
    ("docs/p1/sources/.gitkeep", "P1", None, True),
    ("docs/results_table.md", "ALL", None, True),
    ("docs/report/sec_p1.md", "P1", None, True),
    ("docs/report/sec_p2.md", "P2", None, False),
    ("docs/report/sec_p3.md", "P3", None, False),
    ("docs/report/sec_p4.md", "P4", None, False),
    ("docs/report/sec_p5.md", "P5", None, False),
]

def main():
    created = 0
    for rel_path, owner, needs, is_p1 in FILES:
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        content = get_header(rel_path, owner, needs, is_p1)
        
        # Specific contents for specific files:
        if rel_path == ".agent/role":
            content = "P1\n"
        elif rel_path == "docs/p1/sources/sources_index.csv":
            content = "# OWNER: P1 | STATUS: ACTIVE\nsource_id,title,publisher,url,date_published,date_accessed,pages_used,what_it_gives\n"
        elif rel_path == "docs/p1/assumptions_sheet.csv":
            content = "# OWNER: P1 | STATUS: ACTIVE\nparameter_id,parameter_name,value,unit,status,source_id,notes\n"
        elif rel_path == ".gitignore":
            content = "# OWNER: P2 | STATUS: LOCKED (until P1 handoff done)\n.venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n.coverage\n*.egg-info/\ndist/\nbuild/\n.env\ndata/raw/*\n!data/raw/.gitkeep\ndata/processed/*\n!data/processed/.gitkeep\ndata/samples/*\n!data/samples/.gitkeep\n"

        target.write_text(content, encoding="utf-8")
        created += 1

    print(f"Scaffold complete. Created {created} files.")

if __name__ == "__main__":
    main()
