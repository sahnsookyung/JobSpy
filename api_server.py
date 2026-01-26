import uuid
import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

# Import JobSpy core
from jobspy.model import ScraperInput, Site, JobType, Country, DescriptionFormat
from jobspy.scrapers.tokyodev import TokyoDev
from jobspy.scrapers.japandev import JapanDev
from jobspy.indeed import Indeed
from jobspy.linkedin import LinkedIn
from jobspy.glassdoor import Glassdoor
from jobspy.ziprecruiter import ZipRecruiter
from jobspy.google import Google
from jobspy.bayt import BaytScraper
from jobspy.naukri import Naukri
from jobspy.bdjobs import BDJobs

SCRAPER_MAPPING = {
    Site.LINKEDIN: LinkedIn,
    Site.INDEED: Indeed,
    Site.ZIP_RECRUITER: ZipRecruiter,
    Site.GLASSDOOR: Glassdoor,
    Site.GOOGLE: Google,
    Site.BAYT: BaytScraper,
    Site.NAUKRI: Naukri,
    Site.BDJOBS: BDJobs,
    Site.TOKYODEV: TokyoDev,
    Site.JAPANDEV: JapanDev,
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_server")
app = FastAPI(title="JobSpy Scraper API")
JOB_STORE: Dict[str, Dict[str, Any]] = {}

# --- Request Model ---
class ScrapeRequest(ScraperInput):
    # We inherit site_type from ScraperInput, but we can add validation or description if needed.
    # ScraperInput defines: site_type: list[Site]
    
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Scraper-specific options")

    # Validator for site_type to handle string inputs (e.g. ["indeed", "linkedin"])
    @field_validator('site_type', mode='before')
    @classmethod
    def validate_site_type(cls, v):
        if isinstance(v, list):
            sites = []
            for site in v:
                if isinstance(site, Site):
                    sites.append(site)
                elif isinstance(site, str):
                    try:
                        # Try mapping by Name (INDEED) or Value ("indeed")
                        try:
                            sites.append(Site[site.upper()])
                        except KeyError:
                            sites.append(Site(site.lower()))
                    except ValueError:
                        raise ValueError(f"Invalid site: {site}")
            return sites
        return v

    @field_validator('country', mode='before')
    @classmethod
    def parse_country(cls, v):
        if isinstance(v, str):
            try:
                return Country.from_string(v)
            except ValueError:
                raise ValueError(f"Invalid country: {v}")
        return v

    @field_validator('job_type', mode='before')
    @classmethod
    def parse_job_type(cls, v):
        if isinstance(v, str):
            for jt in JobType:
                if jt.name.lower() == v.lower():
                    return jt
            for jt in JobType:
                if v.lower() in jt.value:
                    return jt
            raise ValueError(f"Invalid job_type: {v}")
        return v

    @field_validator('description_format', mode='before')
    @classmethod
    def parse_description_format(cls, v):
        if isinstance(v, str):
            try:
                return DescriptionFormat(v.lower())
            except ValueError:
                return DescriptionFormat.MARKDOWN
        return v

# --- Background Worker ---
def run_scraper_task(task_id: str, request: ScrapeRequest):
    try:
        logger.info(f"Task {task_id}: Starting scrape for sites: {[s.name for s in request.site_type]}")
        
        all_jobs = []
        
        # Iterate over all requested sites
        for site_enum in request.site_type:
            scraper_class = SCRAPER_MAPPING.get(site_enum)
            if not scraper_class:
                logger.warning(f"Scraper for {site_enum.name} not configured, skipping.")
                continue
            
            try:
                scraper = scraper_class()
                # We pass the full request object because it IS a ScraperInput
                results = scraper.scrape(request, **(request.options or {}))
                all_jobs.extend(results.jobs)
            except Exception as e:
                logger.error(f"Error scraping {site_enum.name}: {e}")
                # We continue to next site even if one fails
        
        # Save aggregated results
        jobs_data = [job.dict() for job in all_jobs]
        JOB_STORE[task_id] = {
            "status": "completed",
            "count": len(jobs_data),
            "data": jobs_data
        }
        logger.info(f"Task {task_id}: Completed with {len(jobs_data)} jobs")

    except Exception as e:
        logger.error(f"Task {task_id}: Failed - {str(e)}")
        JOB_STORE[task_id] = {"status": "failed", "error": str(e)}

# --- Endpoints ---
@app.post("/scrape", status_code=202)
async def submit_scrape_job(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Submits a scraping job.
    Accepts generic ScraperInput fields + 'options' dictionary.
    """
    if not request.site_type:
         raise HTTPException(status_code=400, detail="site_type list cannot be empty")

    task_id = str(uuid.uuid4())
    JOB_STORE[task_id] = {"status": "processing"}
    background_tasks.add_task(run_scraper_task, task_id, request)
    
    return {
        "task_id": task_id,
        "status": "processing",
        "message": "Job submitted."
    }

@app.get("/status/{task_id}")
async def check_job_status(task_id: str):
    job = JOB_STORE.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Task ID not found")
    
    if job.get("status") == "failed":
        raise HTTPException(status_code=500, detail=job)
        
    return job

@app.get("/health")
def health():
    return {"status": "ok", "jobs_in_memory": len(JOB_STORE)}
