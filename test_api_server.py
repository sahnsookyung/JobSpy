"""Unit tests for JobScout's bounded JobSpy API wrapper."""

import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import api_server


class ApiServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "JOBSPY_API_TOKEN": "test-token",
                "JOBSPY_ALLOWED_SITES": "tokyodev,japandev",
            },
            clear=False,
        )
        self.environment.start()
        with api_server.JOB_STORE_LOCK:
            api_server.JOB_STORE.clear()
        api_server.SCRAPE_SEMAPHORE = threading.BoundedSemaphore(1)

    def tearDown(self) -> None:
        self.environment.stop()

    def test_request_rejects_non_allowlisted_site(self) -> None:
        with self.assertRaises(ValidationError):
            api_server.ScrapeRequest(site_type=["linkedin"], results_wanted=1)

    def test_request_rejects_multiple_sites_and_excessive_results(self) -> None:
        with self.assertRaises(ValidationError):
            api_server.ScrapeRequest(site_type=["tokyodev", "japandev"], results_wanted=1)
        with self.assertRaises(ValidationError):
            api_server.ScrapeRequest(site_type=["tokyodev"], results_wanted=26)

    def test_request_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            api_server.ScrapeRequest(
                site_type=["tokyodev"],
                results_wanted=1,
                display_name="UI-only source metadata",
            )

    def test_authentication_requires_matching_token(self) -> None:
        with self.assertRaises(HTTPException) as missing:
            api_server._require_api_token(None)
        self.assertEqual(missing.exception.status_code, 401)

        with self.assertRaises(HTTPException) as invalid:
            api_server._require_api_token("wrong-token")
        self.assertEqual(invalid.exception.status_code, 401)
        self.assertIsNone(api_server._require_api_token("test-token"))

    def test_concurrency_slot_rejects_second_scrape(self) -> None:
        api_server._acquire_scrape_slot()
        with self.assertRaises(HTTPException) as rejected:
            api_server._acquire_scrape_slot()
        self.assertEqual(rejected.exception.status_code, 429)
        api_server.SCRAPE_SEMAPHORE.release()

    def test_scraper_task_records_success_and_releases_slot(self) -> None:
        class FakeJob:
            def model_dump(self):
                return {"id": "td-1", "title": "Engineer"}

        class FakeScraper:
            def scrape(self, _request, **_options):
                return SimpleNamespace(jobs=[FakeJob()])

        request = api_server.ScrapeRequest(site_type=["tokyodev"], results_wanted=1)
        api_server.SCRAPE_SEMAPHORE.acquire()
        with patch.dict(api_server.SCRAPER_MAPPING, {api_server.Site.TOKYODEV: FakeScraper}):
            api_server.run_scraper_task("task-success", request)

        self.assertEqual(api_server.JOB_STORE["task-success"]["status"], "completed")
        self.assertEqual(api_server.JOB_STORE["task-success"]["count"], 1)
        self.assertTrue(api_server.SCRAPE_SEMAPHORE.acquire(blocking=False))
        api_server.SCRAPE_SEMAPHORE.release()

    def test_scraper_task_records_terminal_failure(self) -> None:
        class FailingScraper:
            def scrape(self, _request, **_options):
                raise RuntimeError("site unavailable")

        request = api_server.ScrapeRequest(site_type=["japandev"], results_wanted=1)
        api_server.SCRAPE_SEMAPHORE.acquire()
        with patch.dict(api_server.SCRAPER_MAPPING, {api_server.Site.JAPANDEV: FailingScraper}):
            api_server.run_scraper_task("task-failure", request)

        task = api_server._public_task(api_server.JOB_STORE["task-failure"])
        self.assertEqual(task["status"], "failed")
        self.assertIn("site unavailable", task["error"])
        self.assertNotIn("_updated_at", task)

    def test_expired_tasks_are_removed(self) -> None:
        previous_ttl = api_server.TASK_TTL_SECONDS
        api_server.TASK_TTL_SECONDS = 1
        try:
            api_server._store_task("expired", status="completed", count=0, data=[])
            with api_server.JOB_STORE_LOCK:
                api_server.JOB_STORE["expired"]["_updated_at"] = 0
            api_server._cleanup_expired_tasks()
            self.assertNotIn("expired", api_server.JOB_STORE)
        finally:
            api_server.TASK_TTL_SECONDS = previous_ttl


if __name__ == "__main__":
    unittest.main()
