#!/usr/bin/env python3
# OWNER: P1 | STATUS: ACTIVE
"""Pre-commit check to enforce role-based ownership.
Fails if staged files belong to a role other than the active role in .agent/role.
"""

import sys
import subprocess
import re
from pathlib import Path

def get_active_role(repo_root: Path) -> str:
    role_file = repo_root / ".agent" / "role"
    if role_file.exists():
        return role_file.read_text(encoding="utf-8").strip()
    return "P1"

def get_staged_files(repo_root: Path):
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    res = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    if res.returncode != 0:
        return []
    lines = res.stdout.strip().splitlines()
    return [l.strip() for l in lines if l.strip()]

def determine_file_owner(repo_root: Path, rel_path: str) -> str:
    # Ignore untouched legacy folders
    if rel_path.startswith("theft_detection/"):
        return "IGNORED"

    # Check header comment in file
    target = repo_root / rel_path
    if target.exists() and target.is_file():
        try:
            content = target.read_text(encoding="utf-8", errors="ignore")[:500]
            m = re.search(r"OWNER:\s*([A-Za-z0-9_]+)", content)
            if m:
                owner = m.group(1).upper()
                if owner in ("ALL", "SHARED"):
                    return "ALL"
                return owner
        except Exception:
            pass

    # Path prefix rules
    p = rel_path
    if p.startswith("src/cascadeguard/grid/") or p.startswith("src/cascadeguard/sim/") or \
       p.startswith("configs/grids/") or p.startswith("configs/seasons/") or p.startswith("configs/hydro/") or \
       p.startswith("tests/grid/") or p.startswith("tests/sim/") or p.startswith("notebooks/") or \
       p.startswith("docs/p1/") or p.startswith("scripts/") or p.startswith(".agent/") or \
       p in ("OWNERSHIP.md", "tests/__init__.py", "src/cascadeguard/__init__.py"):
        return "P1"
    elif p.startswith("src/cascadeguard/common/") or p.startswith("src/cascadeguard/data/") or \
         p.startswith("src/cascadeguard/api/") or p.startswith("tests/data/") or p.startswith("tests/api/") or \
         p.startswith("configs/cloud/") or p.startswith("experiments/") or p.startswith("data/") or \
         p.startswith(".github/") or p in ("README.md", "pyproject.toml", "requirements.txt", ".gitignore",
                                         ".env.example", "Makefile", "CODEOWNERS", "docker/Dockerfile.api",
                                         "docs/report/sec_p2.md", "contracts/grid_snapshot.schema.json",
                                         "contracts/scenario_record.schema.json", "contracts/meter_data.schema.json",
                                         "contracts/openapi.yaml", "configs/theft/theft_injection.yaml"):
        return "P2"
    elif p.startswith("src/cascadeguard/cascade_ml/") or p.startswith("tests/cascade_ml/") or \
         p.startswith("configs/model/") or p in ("contracts/graph_tensor_format.md", "docs/report/sec_p3.md"):
        return "P3"
    elif p.startswith("src/cascadeguard/theft/") or p.startswith("tests/theft/") or \
         p in ("configs/theft/models.yaml", "docs/report/sec_p4.md"):
        return "P4"
    elif p.startswith("src/cascadeguard/mitigation/") or p.startswith("src/cascadeguard/retrieval/") or \
         p.startswith("src/cascadeguard/copilot/") or p.startswith("src/cascadeguard/dashboard/") or \
         p.startswith("tests/mitigation/") or p.startswith("tests/retrieval/") or p.startswith("tests/dashboard/") or \
         p in ("configs/mitigation/optimizer.yaml", "docker/Dockerfile.dashboard", "docs/report/sec_p5.md"):
        return "P5"
    elif p in ("docs/results_table.md",):
        return "ALL"

    return "UNKNOWN"

def main():
    import os
    allow_scaffold = "--allow-scaffold" in sys.argv or os.environ.get("ALLOW_SCAFFOLD") == "1"
    repo_root = Path(__file__).resolve().parent.parent
    active_role = get_active_role(repo_root)
    staged = get_staged_files(repo_root)

    if not staged:
        sys.exit(0)

    violations = []
    for f in staged:
        owner = determine_file_owner(repo_root, f)
        if owner in (active_role, "ALL", "IGNORED"):
            continue
        # One-time scaffold exception for pristine placeholder files
        if allow_scaffold:
            target = repo_root / f
            try:
                content = target.read_text(encoding="utf-8", errors="ignore").strip()
                # Placeholder files only contain the header or empty structure
                if "STATUS: LOCKED" in content and len(content.splitlines()) <= 5:
                    continue
            except Exception:
                pass
        violations.append((f, owner))

    if violations:
        print(f"❌ OWNERSHIP VIOLATION: Active role is '{active_role}'.")
        print("The following staged files do not belong to you or are locked:")
        for f, owner in violations:
            print(f"  - {f} (Owner: {owner})")
        print("\nPlease unstage these files or switch role if authorised.")
        sys.exit(1)

    print(f"✅ Ownership check passed for role '{active_role}'.")
    sys.exit(0)

if __name__ == "__main__":
    main()
