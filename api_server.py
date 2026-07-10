"""Bounded, authenticated internal API for the custom JobSpy scrapers."""

import hmac
import logging
import os
import threading
import time
import uuid
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


def run_scraper_task(task_id: str, request: ScrapeRequest) -> None:
    """Run one scraper and always release the slot reserved by the API route."""
    site = request.site_type[0]
    try:
        logger.info("Task %s: starting scrape for %s", task_id, site.value)
        scraper_class = SCRAPER_MAPPING[site]
        scraper = scraper_class()
        results = scraper.scrape(request, **request.options)
        jobs_data = [job.model_dump() for job in results.jobs]
        _store_task(
            task_id,
            status="completed",
            count=len(jobs_data),
            data=jobs_data,
        )
        logger.info("Task %s: completed with %s jobs", task_id, len(jobs_data))
    except Exception as exc:
        logger.exception("Task %s: scrape failed", task_id)
        _store_task(task_id, status="failed", error=str(exc))
    finally:
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
