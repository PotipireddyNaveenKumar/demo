import os
import sys
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from database import (
    init_db,
    seed_sample_data_if_empty,
    create_report,
    get_queue,
    get_report_by_id,
    update_status,
    update_classification
)
from gemini_client import extract_issue_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("civic_signal")

from fastapi.exceptions import RequestValidationError

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_sample_data_if_empty()
    logger.info("Civic Signal database initialized via lifespan.")
    yield

# Also ensure db is initialized on import
init_db()
seed_sample_data_if_empty()

app = FastAPI(
    title="Civic Signal API",
    description="Transparent Community Issue Prioritization & Routing",
    version="1.0.0",
    lifespan=lifespan
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors(), "message": "Input validation error: text must be 8-1200 characters and area 2-100 characters."}
    )

class ReportSubmitRequest(BaseModel):
    text: str = Field(..., min_length=8, max_length=1200)
    area: str = Field(..., min_length=2, max_length=100)
    manual_category: Optional[str] = None
    manual_urgency: Optional[str] = None
    manual_impact: Optional[str] = None
    manual_summary: Optional[str] = None
    photo_name: Optional[str] = None

class StatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(new|in_progress|resolved)$")

class ClassificationUpdateRequest(BaseModel):
    category: str = Field(..., pattern="^(roads|streetlights|water_drainage|waste|parks|public_safety|other)$")
    urgency: str = Field(..., pattern="^(immediate_hazard|safety_risk|service_disruption|routine|unclear)$")

def verify_official_auth(code: Optional[str]):
    required_code = os.environ.get("OFFICIAL_ACCESS_CODE", "").strip()
    if not required_code:
        raise HTTPException(
            status_code=503,
            detail="Official routes disabled: OFFICIAL_ACCESS_CODE is not configured in server environment."
        )
    if not code or code.strip() != required_code:
        raise HTTPException(status_code=401, detail="Invalid official access code.")

@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    return {
        "status": "healthy",
        "service": "Civic Signal",
        "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        "official_routes_enabled": bool(os.environ.get("OFFICIAL_ACCESS_CODE", "").strip())
    }

@app.post("/api/reports")
def submit_report(req: ReportSubmitRequest):
    # Check if manual classification was submitted
    if req.manual_category and req.manual_urgency:
        result = create_report(
            report_text=req.text,
            area_label=req.area,
            category=req.manual_category,
            urgency=req.manual_urgency,
            impact=req.manual_impact or "single_location",
            summary=req.manual_summary or req.text[:120],
            language="en",
            urgency_evidence="Manual submission entry",
            location_hint=req.area,
            ai_status="manual_fallback",
            is_sample=0,
            photo_name=req.photo_name
        )
        return {
            "ok": True,
            "manual_entry_required": False,
            "report": result
        }

    # Attempt AI structured extraction
    ai_res = extract_issue_signals(req.text, req.area)

    if not ai_res.get("success"):
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "manual_entry_required": True,
                "error_reason": ai_res.get("error", "AI triage temporarily unavailable."),
                "message": "AI extraction was unavailable. Please select category and urgency below to proceed."
            }
        )

    ai_data = ai_res["data"]
    created = create_report(
        report_text=req.text,
        area_label=req.area,
        category=ai_data["category"],
        urgency=ai_data["urgency"],
        impact=ai_data["impact"],
        summary=ai_data["summary"],
        language=ai_data.get("language", "und"),
        urgency_evidence=ai_data.get("urgency_evidence"),
        location_hint=ai_data.get("location_hint") or req.area,
        ai_status="ai_extracted",
        is_sample=0,
        photo_name=req.photo_name
    )

    return {
        "ok": True,
        "manual_entry_required": False,
        "report": created
    }

@app.get("/api/official/queue")
def get_official_queue(
    status: Optional[str] = Query("all"),
    department: Optional[str] = Query("all"),
    x_official_code: Optional[str] = Header(None, alias="X-Official-Code")
):
    verify_official_auth(x_official_code)
    reports = get_queue(status_filter=status, department_filter=department)
    return {
        "ok": True,
        "total": len(reports),
        "department_filter": department,
        "reports": reports
    }

@app.patch("/api/official/reports/{report_id}/status")
def patch_status(
    report_id: str,
    body: StatusUpdateRequest,
    x_official_code: Optional[str] = Header(None, alias="X-Official-Code")
):
    verify_official_auth(x_official_code)
    success = update_status(report_id, body.status)
    if not success:
        raise HTTPException(status_code=404, detail="Report not found or invalid status.")
    return {"ok": True, "id": report_id, "new_status": body.status}

@app.patch("/api/official/reports/{report_id}/classify")
def patch_classification(
    report_id: str,
    body: ClassificationUpdateRequest,
    x_official_code: Optional[str] = Header(None, alias="X-Official-Code")
):
    verify_official_auth(x_official_code)
    updated = update_classification(report_id, body.category, body.urgency)
    if not updated:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"ok": True, "report": updated}

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index_page():
    base_dir = os.path.dirname(__file__)
    for name in ("index.html", "Index.html"):
        p = os.path.join(base_dir, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Civic Signal Backend Active</h1>", status_code=200)
