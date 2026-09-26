"""Bounded, authenticated internal API for the custom JobSpy scrapers."""

import hmac
import logging
import multiprocessing
import os
import queue
import signal
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from pydantic import ConfigDict, Field, field_validator, model_validator

from jobspy.model import Country, DescriptionFormat, JobType, ScraperInput, Site
from jobspy.scrapers.japandev import JapanDev
from jobspy.scrapers.tokyodev import TokyoDev


DEFAULT_ALLOWED_SITES = frozenset({"tokyodev", "japandev"})
DEFAULT_MAX_RESULTS = 25
DEFAULT_TASK_TTL_SECONDS = 3600

SCRAPER_MAPPING = {
    Site.TOKYODEV: TokyoDev,
    Site.JAPANDEV: JapanDev,
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_server")
app = FastAPI(title="JobScout JobSpy Scraper API")
JOB_STORE: dict[str, dict[str, Any]] = {}
JOB_STORE_LOCK = threading.Lock()
CLEANUP_FAILED = threading.Event()


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _allowed_sites() -> frozenset[str]:
    configured = {
        value.strip().lower()
        for value in os.getenv("JOBSPY_ALLOWED_SITES", "").split(",")
        if value.strip()
    }
    return frozenset(configured) if configured else DEFAULT_ALLOWED_SITES


TASK_TTL_SECONDS = _positive_int_env("JOBSPY_TASK_TTL_SECONDS", DEFAULT_TASK_TTL_SECONDS)
SCRAPE_SEMAPHORE = threading.BoundedSemaphore(
    _positive_int_env("JOBSPY_MAX_CONCURRENT_JOBS", 1)
)


def _cleanup_expired_tasks() -> None:
    expires_before = time.monotonic() - TASK_TTL_SECONDS
    with JOB_STORE_LOCK:
        expired_task_ids = [
            task_id
            for task_id, task in JOB_STORE.items()
            if float(task.get("_updated_at", 0.0)) < expires_before
        ]
        for task_id in expired_task_ids:
            JOB_STORE.pop(task_id, None)


def _store_task(task_id: str, **values: Any) -> None:
    with JOB_STORE_LOCK:
        JOB_STORE[task_id] = {
            **values,
            "_updated_at": time.monotonic(),
        }


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in task.items() if not key.startswith("_")}


def _require_api_token(
    x_jobspy_token: Optional[str] = Header(default=None),
) -> None:
    expected_token = os.getenv("JOBSPY_API_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JobSpy API token is not configured",
        )
    if not x_jobspy_token or not hmac.compare_digest(x_jobspy_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JobSpy API token",
        )


def _acquire_scrape_slot() -> None:
    if CLEANUP_FAILED.is_set():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JobSpy is unready: browser cleanup failed",
        )
    if not SCRAPE_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A JobSpy scrape is already running",
        )


class ScrapeRequest(ScraperInput):
    """One bounded scrape request for a configured JobScout source."""

    model_config = ConfigDict(extra="forbid")

    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Scraper-specific options",
    )

    @field_validator("site_type", mode="before")
    @classmethod
    def validate_site_type(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value

        sites: list[Site] = []
        for site in value:
            if isinstance(site, Site):
                sites.append(site)
                continue
            if not isinstance(site, str):
                raise ValueError(f"Invalid site: {site}")
            try:
                sites.append(Site[site.upper()])
            except KeyError:
                try:
                    sites.append(Site(site.lower()))
                except ValueError as exc:
                    raise ValueError(f"Invalid site: {site}") from exc
        return sites

    @field_validator("country", mode="before")
    @classmethod
    def parse_country(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return Country.from_string(value)
            except ValueError as exc:
                raise ValueError(f"Invalid country: {value}") from exc
        return value

    @field_validator("job_type", mode="before")
    @classmethod
    def parse_job_type(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        for job_type in JobType:
            if job_type.name.lower() == value.lower() or value.lower() in job_type.value:
                return job_type
        raise ValueError(f"Invalid job_type: {value}")

    @field_validator("description_format", mode="before")
    @classmethod
    def parse_description_format(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return DescriptionFormat(value.lower())
            except ValueError:
                return DescriptionFormat.MARKDOWN
        return value

    @field_validator("results_wanted")
    @classmethod
    def validate_results_wanted(cls, value: int) -> int:
        if value < 1 or value > DEFAULT_MAX_RESULTS:
            raise ValueError(f"results_wanted must be between 1 and {DEFAULT_MAX_RESULTS}")
        return value

    @model_validator(mode="after")
    def validate_allowed_site(self) -> "ScrapeRequest":
        if len(self.site_type) != 1:
            raise ValueError("exactly one site_type is required")
        site = self.site_type[0].value
        if site not in _allowed_sites():
            raise ValueError(f"site '{site}' is not enabled")
        return self


def _run_scraper_worker(
    site: Site,
    request: ScrapeRequest,
    result_queue: Any,
    started: Any,
) -> None:
    """Run the browser in its own process so a hung scraper can be terminated safely."""
    if os.name == "posix":
        os.setsid()
    # Acknowledge ownership before launching any browser. The parent must never
    # signal an inferred process group while the child still shares its group.
    started.send(os.getpgrp() if os.name == "posix" else None)
    started.close()

    try:
        scraper_class = SCRAPER_MAPPING[site]
        scraper = scraper_class()
        results = scraper.scrape(request, **request.options)
        jobs_data = [job.model_dump() for job in results.jobs]
        result_queue.put({"status": "completed", "data": jobs_data})
    except Exception as exc:
        logger.exception("Scrape worker failed for %s", site.value)
        result_queue.put({"status": "failed", "error": str(exc)})


def _process_group_exists(process_group_id: Optional[int]) -> bool:
    if process_group_id is None:
        return False
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def _browser_processes() -> set[tuple[int, str]]:
    """Identify browser descendants which escaped the worker's process group.

    Identity includes start time to avoid confusing recycled PIDs. These are
    verification only: we never kill processes based on their executable name.
    """
    processes = set()
    for entry in Path("/proc").glob("[0-9]*/stat"):
        try:
            raw = entry.read_text()
            name = raw[raw.index("(") + 1:raw.rindex(")")]
            fields = raw[raw.rindex(")") + 2:].split()
            if name in {"headless_shell", "chrome", "chromium", "chrome_crashpad", "node"}:
                processes.add((int(entry.parent.name), fields[19]))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return processes


def _terminate_scraper_worker(
    process: multiprocessing.Process,
    process_group_id: Optional[int] = None,
) -> bool:
    """Collect the worker and stop its group, even after the group leader exits."""
    if process.pid is None:
        return True
    for termination_signal in (signal.SIGTERM, signal.SIGKILL):
        try:
            if process_group_id is not None:
                os.killpg(process_group_id, termination_signal)
            elif process.is_alive():
                if termination_signal == signal.SIGTERM:
                    process.terminate()
                else:
                    process.kill()
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2
        while True:
            process.join(timeout=0)
            if not process.is_alive() and not _process_group_exists(process_group_id):
                return True
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    return False


def _scraper_process_context() -> multiprocessing.context.BaseContext:
    """Use fork on supported hosts so scraper models do not need to be serialized."""
    if "fork" in multiprocessing.get_all_start_methods():
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context()


def _close_scraper_resources(*resources: Any) -> bool:
    """Attempt every close, even when an earlier multiprocessing handle fails."""
    closed = True
    for resource in resources:
        if resource is not None:
            try:
                resource.close()
            except Exception:
                closed = False
                logger.exception("Cannot close scraper resource")
    return closed


def run_scraper_task(task_id: str, request: ScrapeRequest) -> None:
    """Release capacity only after the worker and browser group are gone."""
    site = request.site_type[0]
    timeout_seconds = max(int(request.request_timeout or 1), 1)
    deadline = time.monotonic() + timeout_seconds
    result_queue = started_reader = started_writer = process = None
    try:
        context = _scraper_process_context()
        browser_baseline = _browser_processes()
        result_queue = context.Queue(maxsize=1)
        started_reader, started_writer = context.Pipe(duplex=False)
        process = context.Process(
            target=_run_scraper_worker,
            args=(site, request, result_queue, started_writer),
            daemon=True,
        )
    except Exception:
        CLEANUP_FAILED.set()
        _close_scraper_resources(started_reader, started_writer, result_queue, process)
        _store_task(task_id, status="failed", error="cannot allocate scraper resources", error_code="cleanup_failed")
        logger.exception("Task %s: cannot allocate scraper resources", task_id)
        return
    process_group_id = None
    result = {"status": "failed", "error": "scrape worker exited without returning a result"}
    try:
        logger.info("Task %s: starting scrape for %s", task_id, site.value)
        process.start()
        started_writer.close()
        if not started_reader.poll(max(0, min(5, deadline - time.monotonic()))):
            raise TimeoutError("scrape worker did not establish process ownership")
        process_group_id = started_reader.recv()
        if os.name == "posix" and process_group_id != process.pid:
            process_group_id = None
            raise RuntimeError("scrape worker reported invalid process ownership")
        result = result_queue.get(timeout=max(0, deadline - time.monotonic()))
        # The scraper's context manager has already closed Playwright before it
        # sends a result. Give the queue feeder/worker a bounded chance to exit.
        process.join(timeout=max(0, min(2, deadline - time.monotonic())))
    except queue.Empty:
        result = {"status": "failed", "error": f"scrape exceeded request timeout of {timeout_seconds} seconds", "error_code": "scrape_timeout"}
    except Exception as exc:
        logger.exception("Task %s: scraper process failed", task_id)
        result = {"status": "failed", "error": str(exc), "error_code": "scrape_failed"}
    finally:
        try:
            cleaned = _terminate_scraper_worker(process, process_group_id)
            if process.pid is not None and os.name == "posix" and process_group_id is None:
                # Startup failed before ownership was acknowledged; descendants
                # cannot safely be attributed. Let the watchdog recreate us.
                cleaned = False
            if _browser_processes() - browser_baseline:
                cleaned = False
        except Exception:
            logger.exception("Task %s: cannot verify browser cleanup", task_id)
            cleaned = False
        handles_closed = _close_scraper_resources(started_reader, started_writer, result_queue)
        # The parent never writes to this queue, so it has no feeder to join.
        # Collect the exit code before closing multiprocessing's sentinel. Even
        # failed descendant verification must not leak a finished worker handle.
        exit_code = process.exitcode
        if process.pid is None or exit_code is not None:
            handles_closed = _close_scraper_resources(process) and handles_closed
        cleaned = cleaned and handles_closed
        if not cleaned:
            CLEANUP_FAILED.set()
            result = {"status": "failed", "error": "browser cleanup failed; JobSpy requires recovery", "error_code": "cleanup_failed"}
            logger.error("Task %s: browser cleanup failed; refusing further scrapes", task_id)
        elif result.get("status") == "completed" and exit_code != 0:
            result = {"status": "failed", "error": "worker did not exit cleanly", "error_code": "scrape_failed"}

        if result.get("status") == "completed":
            jobs_data = result.get("data") or []
            _store_task(task_id, status="completed", count=len(jobs_data), data=jobs_data)
        else:
            _store_task(task_id, status="failed", error=str(result.get("error") or "scrape failed"), error_code=result.get("error_code", "scrape_failed"))
        if cleaned:
            SCRAPE_SEMAPHORE.release()


@app.post("/scrape", status_code=status.HTTP_202_ACCEPTED)
async def submit_scrape_job(
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(_require_api_token),
) -> dict[str, str]:
    """Submit one bounded, allowlisted scraping task."""
    _cleanup_expired_tasks()
    _acquire_scrape_slot()
    task_id = str(uuid.uuid4())
    _store_task(task_id, status="processing")
    try:
        background_tasks.add_task(run_scraper_task, task_id, request)
    except Exception:
        SCRAPE_SEMAPHORE.release()
        raise
    return {
        "task_id": task_id,
        "status": "processing",
        "message": "Job submitted.",
    }


@app.get("/status/{task_id}")
async def check_job_status(
    task_id: str,
    _: None = Depends(_require_api_token),
) -> dict[str, Any]:
    """Return a task state, including terminal failures as ordinary task data."""
    _cleanup_expired_tasks()
    with JOB_STORE_LOCK:
        job = JOB_STORE.get(task_id)
        if job is not None:
            job = dict(job)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task ID not found")
    return _public_task(job)


@app.get("/health")
def health() -> dict[str, Any]:
    """Unauthenticated container health endpoint."""
    _cleanup_expired_tasks()
    with JOB_STORE_LOCK:
        task_count = len(JOB_STORE)
    return {
        "status": "ok",
        "jobs_in_memory": task_count,
        "allowed_sites": sorted(_allowed_sites()),
    }


@app.get("/ready")
def readiness() -> dict[str, Any]:
    """Readiness is independent of the HTTP process being alive."""
    if CLEANUP_FAILED.is_set():
        raise HTTPException(status_code=503, detail={"ready": False, "reason": "cleanup_failed"})
    with JOB_STORE_LOCK:
        active = sum(task.get("status") == "processing" for task in JOB_STORE.values())
    return {"ready": True, "active_scrapes": active}
