"""Run with Docker --init --pids-limit 512 --memory 2g --cpus 1.5 --shm-size 1g.

Uses real Chromium and local HTML, without making requests to job providers.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import api_server
from jobspy.scrapers.utils import managed_playwright_context


class BrowserScraper:
    def scrape(self, request, mode="success"):
        with managed_playwright_context(request_timeout=3) as context:
            page = context.new_page()
            page.set_content("<h1>JobScout browser cleanup acceptance test</h1>")
            assert page.title() == ""
            if mode == "timeout":
                time.sleep(60)
            if mode == "crash":
                os._exit(7)
            if mode in {"leader_exit", "ignores_term"}:
                child = subprocess.Popen([
                    sys.executable, "-c",
                    "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready',flush=True); time.sleep(60)",
                ], stdout=subprocess.PIPE, text=True)
                assert child.stdout.readline().strip() == "ready"
                child.stdout.close()
                if mode == "leader_exit":
                    os._exit(7)
                time.sleep(60)
        return SimpleNamespace(jobs=[])


def process_snapshot():
    snapshots = []
    for entry in Path("/proc").glob("[0-9]*/stat"):
        try:
            raw = entry.read_text()
            fields = raw[raw.rindex(")") + 2:].split()
            snapshots.append((entry.parent.name, fields[0]))
        except (OSError, ValueError, IndexError):
            continue
    return snapshots


def run_case(index, mode):
    api_server._acquire_scrape_slot()
    request = api_server.ScrapeRequest(
        site_type=["tokyodev"], results_wanted=1, request_timeout=6,
        options={"mode": mode},
    )
    started = time.monotonic()
    api_server.run_scraper_task(str(index), request)
    elapsed = time.monotonic() - started
    result = api_server.JOB_STORE[str(index)]
    expected = "completed" if mode == "success" else "failed"
    assert result["status"] == expected, (mode, result)
    assert result.get("error_code") != "cleanup_failed", (mode, result)
    assert elapsed < 11, (mode, elapsed)
    assert api_server.readiness()["ready"]
    return elapsed


def main():
    api_server.SCRAPER_MAPPING[api_server.Site.TOKYODEV] = BrowserScraper
    run_case("warmup", "success")
    baseline = int(Path("/sys/fs/cgroup/pids.current").read_text())
    stop = threading.Event()
    peak = [baseline]

    def sample():
        while not stop.wait(0.1):
            peak[0] = max(peak[0], int(Path("/sys/fs/cgroup/pids.current").read_text()))

    sampler = threading.Thread(target=sample)
    sampler.start()
    try:
        modes = ["success", "timeout", "crash", "leader_exit", "ignores_term"]
        for index in range(int(os.getenv("JOBSPY_STRESS_CYCLES", "50"))):
            mode = modes[index % len(modes)]
            elapsed = run_case(index, mode)
            zombies = [pid for pid, state in process_snapshot() if state == "Z"]
            current = int(Path("/sys/fs/cgroup/pids.current").read_text())
            assert not zombies, (mode, zombies)
            assert current <= baseline + 4, (mode, baseline, current)
            print(json.dumps({"cycle": index + 1, "mode": mode, "seconds": round(elapsed, 2), "pids": current, "zombies": len(zombies)}), flush=True)
        run_case("after-stress", "success")
        assert peak[0] < 512
        print(json.dumps({"result": "passed", "baseline_pids": baseline, "peak_pids": peak[0]}), flush=True)
    finally:
        stop.set()
        sampler.join(timeout=1)


if __name__ == "__main__":
    main()
