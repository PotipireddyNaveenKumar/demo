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
    
    Verified active free-tier models:
    - Primary: gemini-3.5-flash-lite (fastest, high availability)
    - Fallbacks: gemini-flash-latest, gemini-3.8-flash
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY is not configured. Falling back to manual entry.")
        return {
            "success": False,
            "error": "Gemini API key is not configured.",
            "fallback_required": True
        }

    # Use configured model or verified fast model
    configured_model = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"
    candidate_models = [configured_model]
    for m in ("gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-3.8-flash"):
        if m not in candidate_models:
            candidate_models.append(m)

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

    last_error = ""
    for model in candidate_models:
        url = f"{GEMINI_API_URL.format(model=model)}?key={api_key}"
        try:
            response = requests.post(url, json=payload, timeout=6.0)
            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    extracted = json.loads(text_content)
                    
                    valid_categories = {"roads", "streetlights", "water_drainage", "waste", "parks", "public_safety", "other"}
                    valid_urgencies = {"immediate_hazard", "safety_risk", "service_disruption", "routine", "unclear"}
                    valid_impacts = {"multiple_people", "single_location", "unknown"}

                    category = extracted.get("category") if extracted.get("category") in valid_categories else "other"
                    urgency = extracted.get("urgency") if extracted.get("urgency") in valid_urgencies else "unclear"
                    impact = extracted.get("impact") if extracted.get("impact") in valid_impacts else "unknown"

                    return {
                        "success": True,
                        "model_used": model,
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
            elif response.status_code in (404, 503, 429):
                last_error = f"Model {model} returned HTTP {response.status_code}"
                continue
            else:
                last_error = f"Gemini API HTTP {response.status_code}: {response.text[:120]}"
                continue
        except requests.exceptions.Timeout:
            last_error = f"Model {model} timed out (>6s)"
            continue
        except Exception as exc:
            last_error = f"Error with {model}: {str(exc)}"
            continue

    logger.warning(f"All candidate Gemini models failed. Last error: {last_error}")
    return {
        "success": False,
        "error": f"AI extraction unavailable ({last_error}). Manual classification required.",
        "fallback_required": True
    }
