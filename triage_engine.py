import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple

CATEGORIES: Dict[str, str] = {
    'roads': 'Roads / Infrastructure',
    'streetlights': 'Streetlights',
    'water_drainage': 'Water / Drainage',
    'waste': 'Waste',
    'parks': 'Parks',
    'public_safety': 'Public Safety',
    'other': 'Other'
}

URGENCY_POINTS: Dict[str, int] = {
    'immediate_hazard': 50,
    'safety_risk': 35,
    'service_disruption': 20,
    'routine': 5,
    'unclear': 0
}

IMPACT_POINTS: Dict[str, int] = {
    'multiple_people': 15,
    'single_location': 0,
    'unknown': 0
}

DEPARTMENTS: Dict[str, str] = {
    'roads': 'Public Works',
    'streetlights': 'Public Works',
    'water_drainage': 'Water & Sewage',
    'waste': 'Sanitation Dept',
    'parks': 'Public Works',
    'public_safety': 'Safety Desk',
    'other': 'Community Affairs'
}

def normalize_area(area: str) -> str:
    """Normalize area string for deterministic duplicate matching."""
    if not area:
        return ""
    cleaned = re.sub(r'[^\w\s]', ' ', area.lower())
    return " ".join(cleaned.split())

def route_department(category: str) -> str:
    """Deterministic routing from category to department."""
    return DEPARTMENTS.get(category, 'Community Affairs')

def compute_priority_score(
    urgency: str,
    impact: str,
    matching_duplicate_count: int = 0,
    oldest_duplicate_hours: float = 0.0
) -> Tuple[int, str, List[str]]:
    """
    Computes an explainable priority score (0-100), band, and reasons trail.
    
    Rules:
    1. Base urgency points: immediate_hazard (+50), safety_risk (+35), service_disruption (+20), routine (+5), unclear (+0).
    2. Public impact: multiple_people / shared public space (+15).
    3. Duplicate momentum: +5 per matching unresolved report in same area within 30 days (max +15).
    4. Aging SLA bonus: +10 if oldest matching duplicate has been open >= 24 hours.
    5. Max score capped at 100.
    6. Bands: >= 60 Urgent, 25-59 Standard, < 25 Routine.
    """
    score = 0
    reasons: List[str] = []

    # 1. Urgency
    u_pts = URGENCY_POINTS.get(urgency, 0)
    score += u_pts
    u_label = urgency.replace('_', ' ').capitalize()
    reasons.append(f"{u_label} urgency (+{u_pts} pts)")

    # 2. Impact
    i_pts = IMPACT_POINTS.get(impact, 0)
    score += i_pts
    if i_pts > 0:
        reasons.append(f"Widespread public impact (+{i_pts} pts)")
    else:
        reasons.append("Single location or limited impact (+0 pts)")

    # 3. Duplicate momentum (capped at +15)
    dupe_pts = min(matching_duplicate_count * 5, 15)
    score += dupe_pts
    if dupe_pts > 0:
        reasons.append(f"{matching_duplicate_count} matching report(s) in area (+{dupe_pts} pts)")
    else:
        reasons.append("First known report in this category & area (+0 pts)")

    # 4. Aging SLA bonus
    if oldest_duplicate_hours >= 24.0:
        score += 10
        reasons.append(f"Cluster unresolved for over 24h (+10 pts)")

    # 5. Cap at 100
    final_score = min(score, 100)
    if score > 100:
        reasons.append(f"Score capped at maximum 100")

    # 6. Priority band
    if final_score >= 60:
        band = "urgent"
    elif final_score >= 25:
        band = "standard"
    else:
        band = "routine"

    return final_score, band, reasons
