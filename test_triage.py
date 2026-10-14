import os
import pytest
from triage_engine import compute_priority_score, normalize_area, route_department
from database import init_db, seed_sample_data_if_empty, get_queue, create_report, update_classification
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_normalize_area():
    assert normalize_area("  Downtown, Main St.!! ") == "downtown main st"
    assert normalize_area("NORTH-SECTOR #4") == "north sector 4"
    assert normalize_area("") == ""

def test_route_department():
    assert route_department("roads") == "Public Works"
    assert route_department("streetlights") == "Public Works"
    assert route_department("water_drainage") == "Water & Sewage"
    assert route_department("waste") == "Sanitation Dept"
    assert route_department("public_safety") == "Safety Desk"
    assert route_department("unknown_cat") == "Community Affairs"

def test_compute_priority_score_rules():
    # Rule 1 & 2: Immediate hazard (+50) + Multiple people (+15) = 65 -> Urgent
    score, band, reasons = compute_priority_score("immediate_hazard", "multiple_people", 0, 0.0)
    assert score == 65
    assert band == "urgent"
    assert any("Immediate hazard" in r for r in reasons)
    assert any("Widespread public impact" in r for r in reasons)

    # Rule 3: Safety risk (+35) + Single location (+0) + 2 duplicates (+10) = 45 -> Standard
    score, band, reasons = compute_priority_score("safety_risk", "single_location", 2, 0.0)
    assert score == 45
    assert band == "standard"
    assert any("2 matching report(s)" in r for r in reasons)

    # Rule 4: Aging SLA bonus: 1 duplicate (+5) + oldest >= 24h (+10) + Service disruption (+20) = 35 -> Standard
    score, band, reasons = compute_priority_score("service_disruption", "single_location", 1, 25.0)
    assert score == 35
    assert band == "standard"
    assert any("unresolved for over 24h" in r for r in reasons)

    # Rule 5: Routine (+5) + 0 dupes = 5 -> Routine
    score, band, reasons = compute_priority_score("routine", "single_location", 0, 0.0)
    assert score == 5
    assert band == "routine"

    # Cap at 100
    score, band, reasons = compute_priority_score("immediate_hazard", "multiple_people", 10, 30.0)
    assert score <= 100

def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["gemini_model"] == "gemini-2.0-flash"

def test_api_manual_fallback_submission():
    import uuid
    unique_area = f"West Bridge {uuid.uuid4().hex[:6]}"
    res = client.post("/api/reports", json={
        "text": "Deep crack on bridge walkway with loose gravel.",
        "area": unique_area,
        "manual_category": "roads",
        "manual_urgency": "safety_risk",
        "manual_impact": "multiple_people"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["manual_entry_required"] is False
    assert data["report"]["ai_status"] == "manual_fallback"
    assert data["report"]["score"] == 50  # 35 (safety_risk) + 15 (multiple_people) + 0 dupes

def test_api_unauthorized_queue():
    res = client.get("/api/official/queue")
    assert res.status_code == 401

def test_api_authorized_queue():
    official_code = os.environ.get("OFFICIAL_ACCESS_CODE", "AdminSecret2026!#")
    res = client.get("/api/official/queue", headers={"X-Official-Code": official_code})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "reports" in data
    assert data["total"] >= 1
    sample_reports = [r for r in data["reports"] if r.get("is_sample") == 1]
    assert len(sample_reports) > 0

def test_api_status_update_and_reclassification():
    official_code = os.environ.get("OFFICIAL_ACCESS_CODE", "AdminSecret2026!#")
    
    # 1. Create a report
    res = client.post("/api/reports", json={
        "text": "Tree limb resting on power cable near school.",
        "area": "Maple Heights",
        "manual_category": "parks",
        "manual_urgency": "routine",
        "manual_impact": "single_location"
    })
    rep_id = res.json()["report"]["id"]

    # 2. Official corrects classification from parks (routine) to public_safety (immediate_hazard)
    res_corr = client.patch(
        f"/api/official/reports/{rep_id}/classify",
        headers={"X-Official-Code": official_code},
        json={"category": "public_safety", "urgency": "immediate_hazard"}
    )
    assert res_corr.status_code == 200
    updated = res_corr.json()["report"]
    assert updated["category"] == "public_safety"
    assert updated["urgency"] == "immediate_hazard"
    assert updated["department"] == "Safety Desk"
    assert updated["score"] == 50  # immediate_hazard (50) + single_location (0)
    assert updated["band"] == "standard"

    # 3. Official updates status to in_progress
    res_stat = client.patch(
        f"/api/official/reports/{rep_id}/status",
        headers={"X-Official-Code": official_code},
        json={"status": "in_progress"}
    )
    assert res_stat.status_code == 200
    assert res_stat.json()["new_status"] == "in_progress"

    # 4. Resolve the report
    res_resolve = client.patch(
        f"/api/official/reports/{rep_id}/status",
        headers={"X-Official-Code": official_code},
        json={"status": "resolved"}
    )
    assert res_resolve.status_code == 200
    assert res_resolve.json()["new_status"] == "resolved"
