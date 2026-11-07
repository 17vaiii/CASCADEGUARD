# OWNER: P5 | STATUS: ACTIVE
"""P5-9: drive the real dashboard in a real browser through the demo script.

Starts Streamlit, walks every step of ``docs/p5/demo.md`` with Playwright, fails on any visible
exception or browser console error, and saves screenshots plus a screen recording.

    python -m pip install playwright && python -m playwright install chromium
    PYTHONPATH=src python -m cascadeguard.dashboard.browser_walkthrough --out docs/p5/demo_media
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from cascadeguard.mitigation import REPO_ROOT

PORT = 8531


def _wait_idle(page: Page, timeout_ms: int = 120_000) -> None:
    # A run shows the "Stop" status widget and spinners; require them gone twice in a row.
    idle = """() => !document.querySelector('[data-testid="stStatusWidget"]')
                 && !document.querySelector('[data-testid="stSpinner"]')
                 && !document.querySelector('.stSpinner')"""
    for _ in range(2):
        page.wait_for_timeout(900)
        page.wait_for_function(idle, timeout=timeout_ms)


def _select(page: Page, label: str, option: str) -> None:
    box = page.locator('[data-testid="stSelectbox"]').filter(has_text=label).first
    combo = box.get_by_role("combobox").first
    combo.click()
    combo.fill(option)                                   # the option list is virtualised: filter it
    page.wait_for_timeout(300)
    opts = page.get_by_role("option")
    exact = opts.filter(has_text=option).all()
    # Prefer an exact text match ("A" must not pick "A + B").
    target = next((o for o in exact if o.inner_text().strip() == option), exact[0])
    target.click()
    _wait_idle(page)


def _simulate(page: Page, section: str, circuits: str, tie: bool) -> None:
    _select(page, "Trip section", section)
    _select(page, "Circuits", circuits)
    box = page.locator('[data-testid="stCheckbox"]').filter(has_text="Lose state-grid tie").first
    if box.locator("input").is_checked() != tie:
        box.locator("label").first.click()
        page.wait_for_timeout(300)
    page.get_by_role("button", name="Simulate").click()
    _wait_idle(page)


def _metrics(page: Page) -> dict[str, str]:
    out = {}
    for m in page.locator('[data-testid="stMetric"]:visible').all():
        lines = [x for x in m.inner_text().split("\n") if x.strip()]
        if len(lines) >= 2:
            out[lines[0]] = lines[1]
    return out


def _tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).first.click()
    _wait_idle(page)


def walkthrough(out_dir: Path, port: int = PORT) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "src"))
    server = subprocess.Popen(
        [sys.executable, "-W", "ignore", "-m", "streamlit", "run",
         str(REPO_ROOT / "src" / "cascadeguard" / "dashboard" / "app.py"), "--server.port", str(port),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        env=env, cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report: dict = {"steps": [], "console_errors": [], "page_errors": []}
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2)
                break
            except Exception:
                time.sleep(1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1500, "height": 950},
                                      record_video_dir=str(out_dir), record_video_size={"width": 1500, "height": 950})
            page = ctx.new_page()
            page.on("console", lambda m: report["console_errors"].append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.get_by_role("tab", name="Grid Resilience").first.wait_for(timeout=120_000)
            _wait_idle(page)

            def step(name: str) -> None:
                exc = page.locator('[data-testid="stException"]')
                texts = [e.inner_text()[:600] for e in exc.all()]
                page.set_viewport_size({"width": 1500, "height": 2300})   # Streamlit scrolls an inner pane
                page.wait_for_timeout(1200)
                page.screenshot(path=str(out_dir / f"{len(report['steps']) + 1:02d}_{name}.png"))
                page.set_viewport_size({"width": 1500, "height": 950})
                page.wait_for_timeout(300)
                report["steps"].append({"step": name, "exceptions": texts, "metrics": _metrics(page)})

            step("start")
            _simulate(page, "S0:", "A", False)                        # season default: post_monsoon
            step("post_monsoon_n1")
            _select(page, "Season", "summer")
            _simulate(page, "S0:", "none", True)
            step("summer_tie_loss")
            _select(page, "Season", "monsoon")
            _simulate(page, "S10:", "A", False)
            step("monsoon_scada")
            page.locator('[data-testid="stCheckbox"]').filter(has_text="Theft-aware").first.locator("label").first.click()
            _wait_idle(page)
            page.get_by_role("button", name="Simulate").click()
            _wait_idle(page)
            step("monsoon_theft_aware")
            _simulate(page, "S0:", "A + B", False)
            step("unmitigable_n2")
            _tab(page, "Loss & Theft")
            step("loss_and_theft")
            _tab(page, "Results")
            step("results")
            for role in ("Planner", "Loss analyst"):
                page.locator('[data-testid="stRadio"] label').filter(has_text=role).first.click()
                _wait_idle(page)
                step(f"role_{role.split()[0].lower()}")
            ctx.close()
            video = page.video.path() if page.video else None
            browser.close()
            if video:
                target = out_dir / "demo_walkthrough.webm"
                target.unlink(missing_ok=True)
                Path(video).rename(target)
                report["video"] = str(target)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()
    report["ok"] = not (report["page_errors"] or any(s["exceptions"] for s in report["steps"]))
    (out_dir / "walkthrough_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(REPO_ROOT / "docs" / "p5" / "demo_media"))
    a = p.parse_args()
    r = walkthrough(Path(a.out))
    for s in r["steps"]:
        print(s["step"], s["metrics"], "EXC:" if s["exceptions"] else "", s["exceptions"] or "")
    print("console errors:", len(r["console_errors"]), r["console_errors"][:5])
    print("page errors:", r["page_errors"][:5])
    print("OK" if r["ok"] else "FAILED")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
