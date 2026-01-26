## SRS overview
This SRS defines two Playwright-based scrapers—**TokyoDev** and **JapanDev**—that both implement `Scraper.scrape(ScraperInput) -> JobResponse` and emit `JobPost` objects using only the relevant fields in your model.  

The document structure and requirement style follows common SRS/requirements-engineering guidance from ISO/IEC/IEEE 29148 (clear, verifiable “shall” statements, traceability, and acceptance criteria). [drkasbokar](https://drkasbokar.com/wp-content/uploads/2024/09/29148-2018-ISOIECIEEE.pdf)

## Shared platform requirements
**Architecture (shared for both sites)**  
- SP-FR-1: The system shall provide a shared Playwright “runner” that creates a browser context, sets a consistent User-Agent, supports proxy configuration, and enforces `ScraperInput.request_timeout` for navigation and selector waits.  
- SP-FR-2: The system shall implement a two-phase scrape: (1) Listing discovery to collect job URLs + minimal fields, (2) Detail extraction per job URL only when required to populate missing fields (e.g., `description`, `job_url_direct`).  
- SP-FR-3: The system shall de-duplicate jobs within a run by canonical `job_url`, and across runs by stable `job_url` (plus optional site-specific IDs if discovered).  
- SP-FR-4: The system shall implement resource blocking (images/fonts/stylesheets) as a performance mode using Playwright request routing (abort unnecessary resources, continue others). [pixeljets](https://pixeljets.com/blog/blocking-images-in-playwright/)
- SP-FR-5: The system shall provide structured error reporting per page (failed URL, reason category, HTML snapshot path, screenshot path, and which selector/token failed).  

**Compliance / constraints**  
- SP-C-1: The system shall support an optional “robots policy” mode that checks the site’s `/robots.txt` and applies the organization’s crawling rules (rate limits, disallowed paths) before scraping. [developers.google](https://developers.google.com/search/docs/crawling-indexing/robots/intro)
- SP-C-2: The system shall include configurable throttling (min delay between page actions, max concurrency) to reduce block risk and to align with operational constraints.

**Output mapping (shared)**  
- SP-DM-1: Each scraped job shall map to `JobPost` with: `title`, `job_url`, `company_name` (when available), `location` (when available), and optionally `description`, `job_type`, `compensation`, `emails`, `is_remote`, `date_posted`.  
- SP-DM-2: `JobPost.location.country` shall be set when it is unambiguous (e.g., Japan boards → `Country.JAPAN`), otherwise store a string in `Location.country`.  
- SP-DM-3: When the site provides “remote” markers, the system shall set `JobPost.is_remote`; if unknown, leave it as `None` (do not guess).  

## TokyoDev scraper requirements
**Scope**: Scrape job listings from `https://www.tokyodev.com/jobs` and/or relevant filtered URLs, returning `JobResponse(jobs=[...])`.

**Functional requirements**  
- TD-FR-1 (Listing crawl): The scraper shall extract from the listing page at minimum: `JobPost.title`, `JobPost.company_name` (if present), and `JobPost.job_url` for every visible job card.  
- TD-FR-2 (Pagination): The scraper shall support iterating pages (next-page links or parameterized URLs) until `ScraperInput.results_wanted + ScraperInput.offset` is satisfied or no more results exist.  
- TD-FR-3 (Filter application): The scraper shall apply filters using the site’s UI controls or URL parameters, driven by `ScraperInput.is_remote`, `ScraperInput.search_term`, and `ScraperInput.location` (if the site supports it); when a filter is not supported by the site, it shall be ignored and logged as “not applicable.”  
- TD-FR-4 (Details crawl): For each `job_url`, the scraper shall visit the detail page and attempt to populate:  
- `JobPost.description` (as Markdown/plain based on `ScraperInput.description_format`)  
- `JobPost.company_url` (if available)  
- `JobPost.job_url_direct` (the “apply” URL if it exists)  
- TD-FR-5 (Job type mapping): If the detail page contains job type text (e.g., full-time/contract), the scraper shall map it to your `JobType` enum values and set `JobPost.job_type` accordingly; if not present, leave `None`.  
- TD-FR-6 (Location mapping): If the page provides a location string, the scraper shall populate `JobPost.location.city/state` only when parseable; otherwise store it in a single human-readable field (e.g., `Location.city` with the full text) to avoid incorrect parsing.

**Non-functional requirements**  
- TD-NFR-1: With resource blocking enabled, TokyoDev listing pages shall load without images/fonts/stylesheets to improve throughput while still allowing DOM extraction. [scrapeops](https://scrapeops.io/playwright-web-scraping-playbook/nodejs-playwright-blocking-images-resources/)
- TD-NFR-2: The scraper shall remain functional when minor HTML structure changes occur by relying on stable attributes (links, headings) rather than brittle deep CSS paths where possible.

## JapanDev scraper requirements
**Scope**: Scrape job listings from `https://japan-dev.com/japan-jobs-relocation` including filters such as visa sponsorship, remote conditions, and Japanese level (as supported by the UI).

**Functional requirements**  
- JD-FR-1 (Listing discovery): The scraper shall load the page, wait for job cards to render, and extract for each card: `title`, `company_name` (if present), `job_url`, and any visible tags relevant to `is_remote` or seniority.  
- JD-FR-2 (Next.js fallback): If DOM selectors fail or are unstable, the scraper shall attempt to extract job data from Next.js hydration JSON (commonly provided via a `__NEXT_DATA__` script tag), and then derive job URLs and fields from that JSON. [github](https://github.com/vercel/next.js/discussions/15117)
- JD-FR-3 (Filters): The scraper shall support applying UI-driven filters for (at minimum) remote/visa/japanese level if they exist on the page; it shall record which filters were successfully applied vs. unavailable.  
- JD-FR-4 (Infinite scroll / pagination): The scraper shall scroll and/or paginate until no new jobs appear after N consecutive scroll attempts or until the requested result count is reached.  
- JD-FR-5 (Details extraction): For each `job_url`, the scraper shall fetch the detail page and populate: `description`, `job_url_direct` (apply link), `compensation` (if range is visible), and `location` (default `Country.JAPAN` unless explicitly worldwide/remote).  
- JD-FR-6 (Compensation mapping): If a salary range is present (e.g., “¥8M ~ ¥12M”), the scraper shall map it to `Compensation(min_amount, max_amount, currency="JPY")` and set `interval` when the period is known; if period is unknown, `interval` shall remain `None` (do not infer).  

**Non-functional requirements**  
- JD-NFR-1: The scraper shall use Playwright routing to reduce bandwidth (block images/fonts/stylesheets) while keeping scripts enabled for Next.js rendering. [pixeljets](https://pixeljets.com/blog/blocking-images-in-playwright/)
- JD-NFR-2: The scraper shall include anti-flakiness waits (wait for selector, wait for network idle where appropriate) aligned with Playwright best-practice guidance to reduce intermittent failures on JS-heavy pages. [playwright](https://playwright.dev/docs/best-practices)

## Acceptance criteria and deliverables
**Acceptance tests (run in CI on a schedule)**  
- AT-1: For each site, a “smoke run” shall return at least 5 `JobPost` objects with non-empty `title` and valid `job_url` (HTTP/HTTPS).  
- AT-2: When `results_wanted=25`, the scraper shall return 25 jobs unless the site genuinely has fewer results; if fewer, it shall report “exhausted results” rather than failing.  
- AT-3: For JapanDev, if the DOM path fails but `__NEXT_DATA__` is present, the run shall still extract jobs via the JSON fallback. [trickster](https://www.trickster.dev/post/scraping-nextjs-web-sites-in-2025/)
- AT-4: With resource blocking enabled, median per-page processing time shall improve versus baseline in your environment (you define the baseline and target), validating the request routing optimization. [scrapeops](https://scrapeops.io/playwright-web-scraping-playbook/nodejs-playwright-blocking-images-resources/)

**Deliverables**  
- D-1: `jobspy/scrapers/tokyodev.py` implementing `Scraper`.  
- D-2: `jobspy/scrapers/japandev.py` implementing `Scraper`.  
- D-3: Shared Playwright runner utilities (context creation, routing rules, throttling, retries, artifact capture).  
- D-4: A field-mapping doc (one page) showing exactly how each site populates `JobPost` fields and when fields are left `None`.

Two clarifying questions so I can lock this SRS to your exact needs:
1) Do you want `description_format=MARKDOWN` to be true Markdown conversion (HTML→MD), or is “plain text with line breaks” acceptable?  
2) What storage/output is the target for `JobResponse` results (JSONL file, SQLite, Postgres)?