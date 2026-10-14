import os
import json
import logging
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("civic_signal.gemini")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "language": {"type": "STRING", "description": "ISO language code, e.g., en, es, hi, or und"},
        "category": {
            "type": "STRING",
            "enum": ["roads", "streetlights", "water_drainage", "waste", "parks", "public_safety", "other"]
        },
        "urgency": {
            "type": "STRING",
            "enum": ["immediate_hazard", "safety_risk", "service_disruption", "routine", "unclear"]
        },
        "impact": {
            "type": "STRING",
            "enum": ["multiple_people", "single_location", "unknown"]
        },
        "summary": {"type": "STRING", "description": "Brief 1-sentence summary of the issue"},
        "location_hint": {"type": "STRING", "description": "Specific landmark, cross-street, or location mentioned, or null"},
        "urgency_evidence": {"type": "STRING", "description": "Exact excerpt from text indicating urgency, or null"}
    },
    "required": ["language", "category", "urgency", "impact", "summary"]
}

PROMPT_SYSTEM = (
    "You are an objective civic issue triage classifier. "
    "Analyze the citizen report and extract structured categorization without hallucinating details. "
    "Do not invent facts not present in the user text. "
    "If safety is at stake (e.g. live wires, gas leaks, open manholes), classify urgency as immediate_hazard or safety_risk."
)

def extract_issue_signals(report_text: str, area_hint: str = "") -> Dict[str, Any]:
    """
    Extracts structured issue classification from free-form text using Google Gemini API.
    
    Failure behavior:
    If GEMINI_API_KEY is unset, or if timeout (4s), rate limit (429), or invalid JSON occurs,
    it returns {'success': False, 'error': ..., 'fallback_required': True}.
    NEVER fakes AI output.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY is not configured. Falling back to manual entry.")
        return {
            "success": False,
            "error": "Gemini API key is not configured.",
            "fallback_required": True
        }

    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
    url = f"{GEMINI_API_URL.format(model=model)}?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"Context Area: {area_hint or 'Unknown'}\nCitizen Report:\n\"\"\"\n{report_text}\n\"\"\""
                    }
                ]
            }
        ],
        "systemInstruction": {
            "parts": [{"text": PROMPT_SYSTEM}]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
            "temperature": 0.1
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=4.0)
        
        if response.status_code == 429:
            logger.warning("Gemini rate limit exceeded (429).")
            return {
                "success": False,
                "error": "Gemini quota/rate limit reached. Manual classification required.",
                "fallback_required": True
            }
            
        if response.status_code != 200:
            logger.warning(f"Gemini API returned status {response.status_code}: {response.text}")
            return {
                "success": False,
                "error": f"Gemini API error (HTTP {response.status_code}). Manual classification required.",
                "fallback_required": True
            }

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return {
                "success": False,
                "error": "Gemini returned empty candidates. Manual classification required.",
                "fallback_required": True
            }

        text_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        extracted = json.loads(text_content)

        # Sanity check extracted fields
        valid_categories = {"roads", "streetlights", "water_drainage", "waste", "parks", "public_safety", "other"}
        valid_urgencies = {"immediate_hazard", "safety_risk", "service_disruption", "routine", "unclear"}
        valid_impacts = {"multiple_people", "single_location", "unknown"}

        category = extracted.get("category") if extracted.get("category") in valid_categories else "other"
        urgency = extracted.get("urgency") if extracted.get("urgency") in valid_urgencies else "unclear"
        impact = extracted.get("impact") if extracted.get("impact") in valid_impacts else "unknown"

        return {
            "success": True,
            "data": {
                "language": extracted.get("language", "und"),
                "category": category,
                "urgency": urgency,
                "impact": impact,
                "summary": extracted.get("summary", report_text[:120]),
                "location_hint": extracted.get("location_hint"),
                "urgency_evidence": extracted.get("urgency_evidence")
            }
        }

    except requests.exceptions.Timeout:
        logger.warning("Gemini request timed out (>4s).")
        return {
            "success": False,
            "error": "Gemini API request timed out (limit: 4s). Manual entry required.",
            "fallback_required": True
        }
    except Exception as exc:
        logger.error(f"Unexpected error communicating with Gemini API: {exc}")
        return {
            "success": False,
            "error": f"AI extraction error: {str(exc)}. Manual entry required.",
            "fallback_required": True
        }
