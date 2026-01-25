from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import List
from urllib.parse import urljoin

from jobspy.model import (
    Scraper,
    ScraperInput,
    Site,
    JobPost,
    JobResponse,
    Location,
    Country,
    DescriptionFormat,
    Compensation,
    CompensationInterval,
)
from jobspy.scrapers.utils import create_playwright_context, setup_page, parse_proxy_string
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


class JapanDev(Scraper):
    def __init__(
        self,
        proxies: list[str] | str | None = None,
        ca_cert: str | None = None,
        user_agent: str | None = None,
    ):
        site = Site(Site.JAPANDEV)
        super().__init__(site, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        self.base_url = "https://japan-dev.com/japan-jobs-relocation"

    def _parse_salary_to_comp(self, salary_text: str | None) -> Compensation | None:
        if not salary_text:
            return None

        # Examples seen on JapanDev:
        # "10M 14M yr", "8.5M 12M", sometimes includes commas or currency.
        matches = re.findall(r"(\d+(?:\.\d+)?)", salary_text.replace(",", ""))
        if len(matches) < 2:
            return None

        try:
            min_amount = float(matches[0]) * 1_000_000
            max_amount = float(matches[1]) * 1_000_000
            return Compensation(
                interval=CompensationInterval.YEARLY,
                min_amount=min_amount,
                max_amount=max_amount,
                currency="JPY",
            )
        except Exception:
            return None

    def _extract_detail_fields(self, detail_page, scraper_input: ScraperInput) -> dict:
        # Title (job detail page)
        title = None
        title_el = detail_page.locator("h1.job-detail__job-name").first
        if title_el.count() > 0:
            title = title_el.inner_text().strip()

        # Company name (job detail page)
        company_name = None
        company_el = detail_page.locator("a.job-logo__company-name").first
        if company_el.count() > 0:
            company_name = company_el.inner_text().strip()

        # Location (job detail page)
        location_text = None
        loc_el = detail_page.locator("div.job-logo__location").first
        if loc_el.count() > 0:
            location_text = loc_el.inner_text().strip()
        else:
            # Fallback: first item in the summary list (often "Tokyo")
            summary_first = detail_page.locator("ul.job-detail__summary-list li span").first
            if summary_first.count() > 0:
                location_text = summary_first.inner_text().strip()

        # Date posted (job detail page)
        posted = None
        summary_spans = detail_page.locator("ul.job-detail__summary-list li span").all()
        if summary_spans:
            # Usually last span is "January 23, 2026" in your sample
            maybe_date = summary_spans[-1].inner_text().strip()
            try:
                posted = datetime.strptime(maybe_date, "%B %d, %Y").date()
            except Exception:
                posted = None

        # Salary (job detail page): under job-detail-tag-list, find the tag with yen-icon
        salary_text = None
        salary_tag = detail_page.locator(
            "div.job-detail-tag-list__basic-tag:has(img[alt='yen-icon'])"
        ).first
        if salary_tag.count() > 0:
            salary_desc = salary_tag.locator("div.job-detail-tag-list__tag-desc").first
            if salary_desc.count() > 0:
                salary_text = salary_desc.inner_text().strip()

        # Apply link (job detail page): "APPLY NOW" button
        job_url_direct = None
        apply_el = detail_page.locator("a:has-text('APPLY NOW')").first
        if apply_el.count() > 0:
            job_url_direct = apply_el.get_attribute("href")

        # Description (job detail page): main content body container
        description = None
        body_el = detail_page.locator("div.job-detail-main-content div.body").first
        if body_el.count() == 0:
            # Fallback if structure changes slightly
            body_el = detail_page.locator("div.job-detail-main-content").first

        if body_el.count() > 0:
            if scraper_input.description_format == DescriptionFormat.HTML:
                description = body_el.inner_html()
            else:
                description = body_el.inner_text()

        return {
            "title": title,
            "company_name": company_name,
            "location_text": location_text,
            "salary_text": salary_text,
            "job_url_direct": job_url_direct,
            "description": description,
            "date_posted": posted,
        }

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        job_list: List[JobPost] = []

        proxy_str = None
        if self.proxies:
            if isinstance(self.proxies, list) and len(self.proxies) > 0:
                proxy_str = self.proxies[0]
            elif isinstance(self.proxies, str):
                proxy_str = self.proxies
        proxy = parse_proxy_string(proxy_str) if proxy_str else None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = create_playwright_context(
                browser,
                proxy=proxy,
                user_agent=self.user_agent,
                request_timeout=scraper_input.request_timeout,
            )

            page = setup_page(context, block_resources=True)

            # NOTE: leaving your existing entry point; adjust if you scrape a different listing route.
            url = f"{self.base_url}"
            if scraper_input.search_term:
                url += "?query=" + scraper_input.search_term

            logger.info(f"Scraping JapanDev at {url}")

            try:
                page.goto(url)
                # Listing selectors vary; keep original + add a fallback used in related-job items.
                try:
                    page.wait_for_selector(".job-item", timeout=scraper_input.request_timeout * 1000)
                    job_cards = page.locator(".job-item").all()
                except Exception:
                    page.wait_for_selector(".top-jobs__job-item", timeout=scraper_input.request_timeout * 1000)
                    job_cards = page.locator(".top-jobs__job-item").all()
            except Exception as e:
                logger.error(f"Failed to load JapanDev listing page: {e}")
                return JobResponse(jobs=[])

            for card in job_cards:
                try:
                    # Try multiple title link selectors (listing pages can differ)
                    title_el = card.locator(".job-item__title").first
                    if title_el.count() == 0:
                        title_el = card.locator("a.title.link").first
                    if title_el.count() == 0:
                        continue

                    title = title_el.inner_text().strip()
                    job_url_relative = title_el.get_attribute("href")
                    if not job_url_relative:
                        continue
                    job_url = urljoin(self.base_url, job_url_relative)

                    # Company name fallback from listing card (detail page will override if present)
                    company_name = None
                    img_el = card.locator("img.company-logo__inner").first
                    if img_el.count() > 0:
                        company_name = img_el.get_attribute("alt")

                    # Listing location/salary can be unreliable; detail page is source of truth
                    detail_page = setup_page(context, block_resources=True)
                    try:
                        detail_page.goto(job_url)
                        detail = self._extract_detail_fields(detail_page, scraper_input)
                    finally:
                        detail_page.close()

                    final_title = detail["title"] or title
                    final_company = detail["company_name"] or company_name
                    final_location_text = detail["location_text"] or "Japan"
                    comp = self._parse_salary_to_comp(detail["salary_text"])

                    # Keep simple mapping (you can improve city/state parsing later)
                    loc = Location(country=Country.JAPAN, city=final_location_text, state=final_location_text)

                    job_post = JobPost(
                        title=final_title,
                        company_name=final_company,
                        job_url=job_url,
                        job_url_direct=detail["job_url_direct"],
                        location=loc,
                        description=detail["description"],
                        compensation=comp,
                        date_posted=detail["date_posted"] or date.today(),
                    )
                    job_list.append(job_post)

                    if len(job_list) >= scraper_input.results_wanted:
                        break

                except Exception as e:
                    logger.warning(f"Error parsing job card: {e}")
                    continue

            return JobResponse(jobs=job_list)
