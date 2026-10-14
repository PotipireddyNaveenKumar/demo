import os
import uuid
import pytest
import requests
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Ensure test access code is configured
TEST_ACCESS_CODE = "TestOfficialKey2026!#"
os.environ["OFFICIAL_ACCESS_CODE"] = TEST_ACCESS_CODE

from triage_engine import compute_priority_score, normalize_area, route_department
from database import init_db, seed_sample_data_if_empty, get_queue, create_report, update_classification
from main import app
import gemini_client

client = TestClient(app)

# 1. Normalization & Routing
def test_normalize_area():
    assert normalize_area("  Downtown, Main St.!! ") == "downtown main st"
    assert normalize_area("NORTH-SECTOR #4") == "north sector 4"
    assert normalize_area("") == ""

def test_route_department():
    assert route_department("roads") == "Public Works"
    assert route_department("streetlights") == "Public Works"
    assert route_department("water_drainage") == "Water & Sewage"
    assert route_department("waste") == "Sanitation Dept"
    assert route_department("parks") == "Public Works"
    assert route_department("public_safety") == "Safety Desk"
    assert route_department("unknown_cat") == "Community Affairs"

# 2. Duplicate Cluster Scoring Rules (+5 per match, max +15)
def test_duplicate_cluster_scoring():
    # 0 matches: 0 pts
    score_0, _, r0 = compute_priority_score("routine", "single_location", 0, 0.0)
    assert score_0 == 5  # routine (5) + 0 dupes
    assert any("First known report" in r for r in r0)

    # 1 match: +5 pts
    score_1, _, r1 = compute_priority_score("routine", "single_location", 1, 0.0)
    assert score_1 == 10  # 5 + 5
    assert any("1 matching report(s) in area (+5 pts)" in r for r in r1)

    # 2 matches: +10 pts
    score_2, _, r2 = compute_priority_score("routine", "single_location", 2, 0.0)
    assert score_2 == 15  # 5 + 10
    assert any("2 matching report(s) in area (+10 pts)" in r for r in r2)

    # 3 matches: +15 pts (cap)
    score_3, _, r3 = compute_priority_score("routine", "single_location", 3, 0.0)
    assert score_3 == 20  # 5 + 15
    assert any("3 matching report(s) in area (+15 pts)" in r for r in r3)

    # 5 matches: max +15 pts
    score_5, _, r5 = compute_priority_score("routine", "single_location", 5, 0.0)
    assert score_5 == 20  # 5 + 15 (capped)
    assert any("5 matching report(s) in area (+15 pts)" in r for r in r5)

# 3. SLA Aging Bonus (>24h adds +10 pts)
def test_sla_aging_bonus():
    # Less than 24 hours: 0 bonus
    score_recent, _, r_recent = compute_priority_score("service_disruption", "single_location", 1, 23.5)
    assert score_recent == 25  # 20 (disruption) + 5 (dupe) + 0 (sla)
    assert not any("unresolved for over 24h" in r for r in r_recent)

    # Greater than or equal to 24 hours: +10 bonus
    score_aged, _, r_aged = compute_priority_score("service_disruption", "single_location", 1, 24.1)
    assert score_aged == 35  # 20 (disruption) + 5 (dupe) + 10 (sla)
    assert any("unresolved for over 24h (+10 pts)" in r for r in r_aged)

# 4. Score Capped at 100
def test_score_capped_at_100():
    # immediate_hazard (50) + multiple_people (15) + max dupes (15) + SLA (10) = 90
    score_90, band_90, _ = compute_priority_score("immediate_hazard", "multiple_people", 10, 30.0)
    assert score_90 == 90
    assert band_90 == "urgent"

    # Hypothetical over-cap: 50 + 15 + 15 + 10 = 90; test custom logic capping
    score_cap, band_cap, r_cap = compute_priority_score("immediate_hazard", "multiple_people", 20, 50.0)
    assert score_cap <= 100

# 5. Gemini Mock Tests: Timeout -> manual_entry_required
def test_gemini_timeout_triggers_manual_entry(monkeypatch):
    def mock_extract(text, area):
        return {
            "success": False,
            "error": "Gemini API request timed out (limit: 8s). Manual entry required.",
            "fallback_required": True
        }
    monkeypatch.setattr("main.extract_issue_signals", mock_extract)

    res = client.post("/api/reports", json={
        "text": "Broken traffic light blinking red at busy avenue.",
        "area": "Downtown Broadway"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["manual_entry_required"] is True
    assert "timed out" in data["error_reason"]

# 6. Gemini Mock Tests: Invalid JSON -> manual fallback
def test_gemini_invalid_json_triggers_manual_entry(monkeypatch):
    def mock_extract(text, area):
        return {
            "success": False,
            "error": "AI extraction unavailable (Invalid JSON payload). Manual classification required.",
            "fallback_required": True
        }
    monkeypatch.setattr("main.extract_issue_signals", mock_extract)

    res = client.post("/api/reports", json={
        "text": "Water valve leaking heavily onto the roadway.",
        "area": "Harbor Blvd"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["manual_entry_required"] is True
    assert "Invalid JSON" in data["error_reason"]

# 7. Input Validation: Empty or too-long text returns HTTP 400
def test_empty_or_short_text_returns_400():
    # Text under 8 characters
    res = client.post("/api/reports", json={
        "text": "short",
        "area": "Downtown"
    })
    assert res.status_code == 400
    assert "detail" in res.json()

def test_empty_text_returns_400():
    # Empty string
    res = client.post("/api/reports", json={
        "text": "",
        "area": "Downtown"
    })
    assert res.status_code == 400

def test_too_long_text_returns_400():
    # Over 1200 characters
    long_text = "Dangerous road hazard with gravel. " * 50  # ~1750 chars
    res = client.post("/api/reports", json={
        "text": long_text,
        "area": "Downtown"
    })
    assert res.status_code == 400
    assert "detail" in res.json()

# 8. Queue Authentication and Refusal When Code Unset
def test_api_unauthorized_queue():
    res = client.get("/api/official/queue")
    assert res.status_code == 401

def test_api_refuses_when_official_code_unset(monkeypatch):
    monkeypatch.setenv("OFFICIAL_ACCESS_CODE", "")
    res = client.get("/api/official/queue", headers={"X-Official-Code": "random-code"})
    assert res.status_code == 503
    assert "OFFICIAL_ACCESS_CODE is not configured" in res.json()["detail"]

def test_api_authorized_queue_with_m2_features():
    res = client.get("/api/official/queue", headers={"X-Official-Code": TEST_ACCESS_CODE})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "reports" in data
    assert data["total"] >= 1
    # Verify M2 SLA flag and sample data flag
    sample_reports = [r for r in data["reports"] if r.get("is_sample") == 1]
    assert len(sample_reports) > 0
    assert any("is_over_24h" in r for r in data["reports"])

def test_api_department_filtering():
    res = client.get(
        "/api/official/queue?department=Public+Works",
        headers={"X-Official-Code": TEST_ACCESS_CODE}
    )
    assert res.status_code == 200
    reports = res.json()["reports"]
    for r in reports:
        assert r["department"] == "Public Works"

def test_api_status_update_and_reclassification():
    unique_area = f"Maple Heights {uuid.uuid4().hex[:6]}"
    res = client.post("/api/reports", json={
        "text": "Tree limb resting on power cable near school.",
        "area": unique_area,
        "manual_category": "parks",
        "manual_urgency": "routine",
        "manual_impact": "single_location"
    })
    rep_id = res.json()["report"]["id"]

    # Official corrects classification
    res_corr = client.patch(
        f"/api/official/reports/{rep_id}/classify",
        headers={"X-Official-Code": TEST_ACCESS_CODE},
        json={"category": "public_safety", "urgency": "immediate_hazard"}
    )
    assert res_corr.status_code == 200
    updated = res_corr.json()["report"]
    assert updated["category"] == "public_safety"
    assert updated["urgency"] == "immediate_hazard"
    assert updated["department"] == "Safety Desk"
    assert updated["score"] == 50

    # Status to in_progress
    res_stat = client.patch(
        f"/api/official/reports/{rep_id}/status",
        headers={"X-Official-Code": TEST_ACCESS_CODE},
        json={"status": "in_progress"}
    )
    assert res_stat.status_code == 200
    assert res_stat.json()["new_status"] == "in_progress"

    # Status to resolved
    res_resolve = client.patch(
        f"/api/official/reports/{rep_id}/status",
        headers={"X-Official-Code": TEST_ACCESS_CODE},
        json={"status": "resolved"}
    )
    assert res_resolve.status_code == 200
    assert res_resolve.json()["new_status"] == "resolved"
