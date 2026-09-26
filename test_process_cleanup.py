"""Regression tests for process ownership and readiness after cleanup failure."""

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

import api_server


class CleanupReadinessTests(unittest.TestCase):
    def test_allocation_and_close_failure_remain_unready(self) -> None:
        api_server.CLEANUP_FAILED.clear()
        self.addCleanup(api_server.CLEANUP_FAILED.clear)
        api_server.SCRAPE_SEMAPHORE = threading.BoundedSemaphore(1)
        api_server._acquire_scrape_slot()
        storage = Mock()
        storage.enter_context.return_value = "/unused"
        storage.close.side_effect = OSError("close failed")
        context = Mock()
        context.Pipe.side_effect = OSError("PID resources exhausted")
        request = api_server.ScrapeRequest(site_type=["tokyodev"], results_wanted=1)
        with patch.object(api_server, "_scraper_process_context", return_value=context), \
             patch.object(api_server, "ExitStack", return_value=storage):
            api_server.run_scraper_task("allocation-failure", request)
        storage.close.assert_called_once()
        self.assertEqual(api_server.JOB_STORE["allocation-failure"]["error_code"], "cleanup_failed")
        self.assertFalse(api_server.SCRAPE_SEMAPHORE.acquire(blocking=False))
        with self.assertRaises(HTTPException):
            api_server.readiness()

    def test_closes_remaining_handles_after_one_fails(self) -> None:
        broken, remaining = Mock(), Mock()
        broken.close.side_effect = OSError("close failed")
        self.assertFalse(api_server._close_scraper_resources(broken, remaining))
        remaining.close.assert_called_once()

    def test_partial_result_write_cannot_hold_parent_past_deadline(self) -> None:
        def partial_worker(site, request, result_path, started):
            os.setsid()
            started.send(os.getpgrp())
            started.close()
            with open(result_path, "w") as handle:
                handle.write('{"status":"completed","data":[')
                handle.flush()
                time.sleep(60)

        api_server.CLEANUP_FAILED.clear()
        self.addCleanup(api_server.CLEANUP_FAILED.clear)
        api_server.SCRAPE_SEMAPHORE = threading.BoundedSemaphore(1)
        api_server._acquire_scrape_slot()
        request = api_server.ScrapeRequest(site_type=["tokyodev"], results_wanted=1, request_timeout=1)
        began = time.monotonic()
        with patch.object(api_server, "_run_scraper_worker", partial_worker):
            api_server.run_scraper_task("partial-result", request)
        self.assertLess(time.monotonic() - began, 5)
        self.assertEqual(api_server.JOB_STORE["partial-result"]["error_code"], "scrape_timeout")
        self.assertTrue(api_server.readiness()["ready"])
        self.assertTrue(api_server.SCRAPE_SEMAPHORE.acquire(blocking=False))

    def test_failed_cleanup_blocks_capacity_and_success(self) -> None:
        class EmptyScraper:
            def scrape(self, request, **options):
                return SimpleNamespace(jobs=[])

        original = api_server._terminate_scraper_worker

        def failed_verification(process, group):
            original(process, group)
            return False

        api_server.CLEANUP_FAILED.clear()
        self.addCleanup(api_server.CLEANUP_FAILED.clear)
        api_server.SCRAPE_SEMAPHORE = threading.BoundedSemaphore(1)
        api_server._acquire_scrape_slot()
        request = api_server.ScrapeRequest(site_type=["tokyodev"], results_wanted=1)
        with patch.dict(api_server.SCRAPER_MAPPING, {api_server.Site.TOKYODEV: EmptyScraper}), \
             patch.object(api_server, "_terminate_scraper_worker", side_effect=failed_verification):
            api_server.run_scraper_task("cleanup-failure", request)

        self.assertEqual(api_server.JOB_STORE["cleanup-failure"]["error_code"], "cleanup_failed")
        self.assertFalse(api_server.SCRAPE_SEMAPHORE.acquire(blocking=False))
        with self.assertRaises(HTTPException) as rejected:
            api_server._acquire_scrape_slot()
        self.assertEqual(rejected.exception.status_code, 503)
        self.assertEqual(api_server.health()["status"], "ok")
        with self.assertRaises(HTTPException):
            api_server.readiness()
