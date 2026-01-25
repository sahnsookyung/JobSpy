import uuid
import logging
from typing import List, Optional, Dict, Any, Union
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

# Import JobSpy core
from jobspy.model import ScraperInput, Site, JobResponse, DescriptionFormat
from jobspy.scrapers.tokyodev import TokyoDev
from jobspy.scrapers.japandev import JapanDev # Assuming you have this too
# Import your Custom Enums
from jobspy.scrapers.tokyodev_enums import (
    JapaneseLevel,
    EnglishLevel,
    ApplicantLocation,
    Seniority,
)

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_server")

app = FastAPI(title="JobSpy Scraper API")

# --- In-Memory Job Store (Replace with Redis in Prod) ---
# Format: { "task_id": { "status": "processing" | "completed" | "failed", "data": ... } }
JOB_STORE: Dict[str, Dict[str, Any]] = {}

# --- Request Models ---

class TokyoDevFilters(BaseModel):
    min_salary: Optional[int] = None
    japanese_requirements: Optional[List[JapaneseLevel]] = None
    english_requirements: Optional[List[EnglishLevel]] = None
    applicant_locations: Optional[List[ApplicantLocation]] = None
    seniorities: Optional[List[Seniority]] = None
    categories: Optional[List[str]] = None

class ScrapeRequest(BaseModel):
    site_name: str = Field(..., description="The site to scrape, e.g., 'tokyodev', 'japandev'")
    search_term: Optional[str] = None
    location: Optional[str] = None
    results_wanted: int = 20
    is_remote: bool = False
    
    # Site-specific filters (Optional)
    tokyodev_filters: Optional[TokyoDevFilters] = None

# --- Background Worker Function ---

def run_scraper_task(task_id: str, request: ScrapeRequest):
    """
    Executes the scraping logic in a background thread/process.
    """
    try:
        logger.info(f"Task {task_id}: Starting scrape for {request.site_name}")
        
        # 1. Map String to Site Enum
        try:
            site_enum = Site[request.site_name.upper()]
        except KeyError:
            raise ValueError(f"Invalid site name: {request.site_name}")

        # 2. Setup Base Input
        scraper_input = ScraperInput(
            site_type=[site_enum],
            search_term=request.search_term,
            location=request.location,
            results_wanted=request.results_wanted,
            is_remote=request.is_remote,
            description_format=DescriptionFormat.MARKDOWN
        )

        scraper = None
        results = None

        # 3. Dispatch to Specific Scraper
        if site_enum == Site.TOKYODEV:
            scraper = TokyoDev()
            # Unpack filters if present
            filters = request.tokyodev_filters.dict() if request.tokyodev_filters else {}
            # Filter out None values to avoid passing nulls to **kwargs
            filters = {k: v for k, v in filters.items() if v is not None}
            
            results = scraper.scrape(scraper_input, **filters)

        elif site_enum == Site.JAPANDEV:
            scraper = JapanDev()
            results = scraper.scrape(scraper_input)
            
        else:
            # Generic/Other Scrapers (Indeed, LinkedIn, etc.)
            # If you want to support them via this API, instantiate them dynamically
            # For now, we raise an error or handle generically
            raise NotImplementedError(f"Scraper for {request.site_name} not configured in API")

        # 4. Save Success Result
        # Convert Pydantic models to dict for JSON serialization
        jobs_data = [job.dict() for job in results.jobs]
        
        JOB_STORE[task_id] = {
            "status": "completed",
            "count": len(jobs_data),
            "data": jobs_data
        }
        logger.info(f"Task {task_id}: Completed with {len(jobs_data)} jobs")

    except Exception as e:
        logger.error(f"Task {task_id}: Failed - {str(e)}")
        JOB_STORE[task_id] = {
            "status": "failed",
            "error": str(e)
        }

# --- Endpoints ---

@app.post("/scrape", status_code=202)
async def submit_scrape_job(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Submits a scraping job. Returns a Task ID immediately.
    """
    task_id = str(uuid.uuid4())
    
    # Initialize status
    JOB_STORE[task_id] = {"status": "processing"}
    
    # Add to background queue
    background_tasks.add_task(run_scraper_task, task_id, request)
    
    return {
        "task_id": task_id,
        "status": "processing",
        "message": "Job submitted successfully. Poll /status/{task_id} for results."
    }

@app.get("/status/{task_id}")
async def check_job_status(task_id: str):
    """
    Check the status of a job. If 'completed', returns the data.
    """
    job = JOB_STORE.get(task_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Task ID not found")
        
    return job

@app.get("/health")
def health():
    return {"status": "ok", "jobs_in_memory": len(JOB_STORE)}
