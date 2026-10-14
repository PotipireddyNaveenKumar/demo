import sqlite3
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from triage_engine import normalize_area, compute_priority_score, route_department

DB_PATH = "civic_signal.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            report_text TEXT NOT NULL,
            area_label TEXT NOT NULL,
            area_normalized TEXT NOT NULL,
            category TEXT NOT NULL,
            language TEXT NOT NULL,
            summary TEXT NOT NULL,
            urgency TEXT NOT NULL,
            impact TEXT NOT NULL,
            urgency_evidence TEXT,
            location_hint TEXT,
            ai_status TEXT NOT NULL,
            score INTEGER NOT NULL,
            band TEXT NOT NULL,
            score_reasons TEXT NOT NULL,
            department TEXT NOT NULL,
            duplicate_matches INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'new',
            is_sample INTEGER NOT NULL DEFAULT 0,
            photo_name TEXT
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON reports(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dupe ON reports(category, area_normalized, status);")
    conn.commit()
    conn.close()

def get_matching_duplicates(category: str, area_normalized: str, exclude_id: Optional[str] = None) -> List[sqlite3.Row]:
    """Find open reports with the same category and area within the last 30 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT id, created_at, report_text, score, status 
        FROM reports 
        WHERE category = ? 
          AND area_normalized = ? 
          AND status != 'resolved'
          AND created_at >= ?
    """
    params = [category, area_normalized, cutoff]
    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
        
    query += " ORDER BY created_at ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows

def create_report(
    report_text: str,
    area_label: str,
    category: str,
    urgency: str,
    impact: str,
    summary: str,
    language: str = "en",
    urgency_evidence: Optional[str] = None,
    location_hint: Optional[str] = None,
    ai_status: str = "ai_extracted",
    is_sample: int = 0,
    photo_name: Optional[str] = None,
    custom_created_at: Optional[str] = None
) -> Dict[str, Any]:
    norm_area = normalize_area(area_label)
    now_iso = custom_created_at or datetime.now(timezone.utc).isoformat()
    
    # Check existing matching duplicates
    dupes = get_matching_duplicates(category, norm_area)
    dupe_count = len(dupes)
    
    oldest_hours = 0.0
    if dupes:
        try:
            oldest_dt = datetime.fromisoformat(dupes[0]['created_at'])
            current_dt = datetime.fromisoformat(now_iso)
            oldest_hours = max(0.0, (current_dt - oldest_dt).total_seconds() / 3600.0)
        except Exception:
            oldest_hours = 0.0
            
    score, band, reasons = compute_priority_score(
        urgency=urgency,
        impact=impact,
        matching_duplicate_count=dupe_count,
        oldest_duplicate_hours=oldest_hours
    )
    dept = route_department(category)
    report_id = f"rep_{uuid.uuid4().hex[:8]}"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reports (
            id, created_at, report_text, area_label, area_normalized,
            category, language, summary, urgency, impact,
            urgency_evidence, location_hint, ai_status, score,
            band, score_reasons, department, duplicate_matches,
            status, is_sample, photo_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
    """, (
        report_id, now_iso, report_text, area_label, norm_area,
        category, language, summary, urgency, impact,
        urgency_evidence, location_hint, ai_status, score,
        band, json.dumps(reasons), dept, dupe_count,
        is_sample, photo_name
    ))
    conn.commit()
    conn.close()

    return {
        "id": report_id,
        "created_at": now_iso,
        "score": score,
        "band": band,
        "department": dept,
        "duplicate_matches": dupe_count,
        "ai_status": ai_status,
        "reasons": reasons,
        "is_sample": is_sample
    }

def get_queue(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve queue ranked by score descending."""
    conn = get_connection()
    cursor = conn.cursor()
    if status_filter and status_filter != 'all':
        cursor.execute("SELECT * FROM reports WHERE status = ? ORDER BY score DESC, created_at DESC", (status_filter,))
    else:
        cursor.execute("SELECT * FROM reports WHERE status != 'resolved' ORDER BY score DESC, created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        d = dict(r)
        try:
            d['score_reasons'] = json.loads(d.get('score_reasons') or '[]')
        except Exception:
            d['score_reasons'] = []
        results.append(d)
    return results

def get_report_by_id(report_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d['score_reasons'] = json.loads(d.get('score_reasons') or '[]')
    except Exception:
        d['score_reasons'] = []
    return d

def update_status(report_id: str, new_status: str) -> bool:
    if new_status not in ('new', 'in_progress', 'resolved'):
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE reports SET status = ? WHERE id = ?", (new_status, report_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def update_classification(report_id: str, category: str, urgency: str) -> Optional[Dict[str, Any]]:
    """Update official classification and recalculate score/routing."""
    report = get_report_by_id(report_id)
    if not report:
        return None

    norm_area = report['area_normalized']
    dupes = get_matching_duplicates(category, norm_area, exclude_id=report_id)
    dupe_count = len(dupes)

    score, band, reasons = compute_priority_score(
        urgency=urgency,
        impact=report['impact'],
        matching_duplicate_count=dupe_count,
        oldest_duplicate_hours=0.0
    )
    reasons.append("Recalculated by official classification correction")
    dept = route_department(category)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reports 
        SET category = ?, urgency = ?, score = ?, band = ?, score_reasons = ?, department = ?, duplicate_matches = ?
        WHERE id = ?
    """, (category, urgency, score, band, json.dumps(reasons), dept, dupe_count, report_id))
    conn.commit()
    conn.close()

    return get_report_by_id(report_id)

def seed_sample_data_if_empty():
    """Seeds clear sample data if table is empty, strictly labeled SAMPLE DATA."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM reports;")
    count = cursor.fetchone()[0]
    conn.close()

    if count > 0:
        return

    # Seed 3 verified sample items
    now = datetime.now(timezone.utc)
    one_day_ago = (now - timedelta(hours=28)).isoformat()
    two_hours_ago = (now - timedelta(hours=2)).isoformat()

    # 1. Urgent public safety hazard
    create_report(
        report_text="Live electric wire sparking across Main St sidewalk near the crosswalk, sparking when windy.",
        area_label="Downtown Main St",
        category="public_safety",
        urgency="immediate_hazard",
        impact="multiple_people",
        summary="Live sparking wire down across sidewalk near Main St crosswalk.",
        language="en",
        urgency_evidence="Live electric wire sparking across Main St sidewalk",
        location_hint="Main St crosswalk",
        ai_status="ai_extracted",
        is_sample=1,
        custom_created_at=two_hours_ago
    )

    # 2. Road pothole (first report)
    create_report(
        report_text="Dangerous deep pothole on 5th Ave right in front of Central Elementary entrance.",
        area_label="5th Ave District",
        category="roads",
        urgency="safety_risk",
        impact="multiple_people",
        summary="Deep pothole right in front of elementary school entrance.",
        language="en",
        urgency_evidence="Dangerous deep pothole in front of school",
        location_hint="Central Elementary entrance",
        ai_status="ai_extracted",
        is_sample=1,
        custom_created_at=one_day_ago
    )

    # 3. Duplicate report for same pothole to demonstrate clustering & momentum (+5) + aging SLA (+10)
    create_report(
        report_text="Second notice: big wheel-busting hole on 5th Ave by school gate. Almost caused a collision.",
        area_label="5th Ave District",
        category="roads",
        urgency="safety_risk",
        impact="multiple_people",
        summary="Another report of deep road hole near school gate.",
        language="en",
        urgency_evidence="Wheel-busting hole, almost caused collision",
        location_hint="5th Ave by school gate",
        ai_status="ai_extracted",
        is_sample=1,
        custom_created_at=two_hours_ago
    )

    # 4. Multilingual routine park report
    create_report(
        report_text="Hay un banco roto y un poco de pintura de grafiti en el parque del roble.",
        area_label="Oak Park",
        category="parks",
        urgency="routine",
        impact="single_location",
        summary="Broken bench and graffiti in Oak Park.",
        language="es",
        urgency_evidence="banco roto y un poco de pintura",
        location_hint="Oak Park",
        ai_status="ai_extracted",
        is_sample=1,
        custom_created_at=two_hours_ago
    )
