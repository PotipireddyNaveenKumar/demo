# Civic Signal — Transparent Community Issue Prioritization & Triage

> **Hackathon Challenge:** AI for Better Living & Smarter Communities  
> **Judged on:** Code Quality, Security, Efficiency, Testing, Accessibility, Google Services, Problem Alignment.

Civic Signal is an intelligent, explainable municipal issue triage system. Citizens report local problems in free-form text in any language with optional photo hints. Google Gemini extracts objective structured signals, and an explainable deterministic engine scores priority (0–100), clusters duplicate complaints, and routes tickets to city departments with a full point-by-point audit trail.

---

## 1. Problem Statement

Local municipal desks receive hundreds of unstructured, multilingual complaints daily (e.g. broken water pipes, sparking power lines, potholes, illegal dumping). Officials face critical bottlenecks:
* **Triage Fatigue:** High-risk life-safety hazards are buried under routine cosmetic complaints.
* **Duplicate Blindness:** 20 separate citizens reporting the same water main break create 20 disconnected tickets, diluting urgency rather than amplifying it.
* **Language Barriers:** Non-English reports are delayed or mishandled.
* **Lack of Transparency:** Citizens receive opaque reference numbers with no explanation of how their report is prioritized.

---

## 2. Architecture: What is AI vs. What is Deterministic

```
[ Citizen Free-Text Report (Any Language) ]
                     │
                     ▼
  [ Google Gemini API: gemini-3.5-flash-lite ]
    - Zero-shot structured JSON extraction
    - Category, Urgency Signal, Public Impact, Summary, Quote Evidence
    - Timeout: 8s | Fallbacks: gemini-flash-latest, gemini-3.8-flash
    - Failure Mode: Graceful Manual Fallback (NEVER fake AI output)
                     │
                     ▼
  [ Deterministic Scoring & Clustering Engine (Python) ]
    - Base Urgency: immediate_hazard (+50), safety_risk (+35), service_disruption (+20), routine (+5)
    - Public Impact: widespread/multiple people (+15)
    - Duplicate Clustering: +5 per open match in same area (capped at +15)
    - SLA Aging: +10 if cluster unresolved >= 24h
    - Max score: capped at 100 | Bands: Urgent (>=60), Standard (25-59), Routine (<25)
    - Department Routing: Roads/Parks -> Public Works, Water -> Water & Sewage, etc.
                     │
                     ▼
  [ SQLite Database + Accessible Official Queue UI ]
    - Itemized score breakdown & point receipts
    - One-click duplicate cluster filtering
    - SLA breach alerts (Open > 24h)
    - Department filters & classification corrections
```

| Component | Responsibility | Technology |
| :--- | :--- | :--- |
| **Intelligent Extraction (AI)** | Parses messy text across languages into structured schema without hallucination. | Google Gemini API (`gemini-3.5-flash-lite`) |
| **Priority Scoring (Deterministic)** | Computes 0–100 score and explainability trail using transparent rules. | Python (`triage_engine.py`) |
| **Duplicate Clustering (Deterministic)** | Normalizes neighborhoods and links matching open reports in 30-day window. | SQLite + Python |
| **Department Routing (Deterministic)** | Directs issues to responsible departments based on validated categories. | Python dictionary mapping |
| **Manual Fallback (Deterministic)** | Prompts citizen with validated dropdowns if Gemini API times out or hits quota. | FastAPI + Vanilla JS |

---

## 3. Environment Variables

Create a `.env` file in the project root (never committed to git):

| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Google AI Studio free-tier API key | `AIzaSy...` (Get from [aistudio.google.com](https://aistudio.google.com/)) |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.5-flash-lite` |
| `OFFICIAL_ACCESS_CODE` | Private password required to view and update official queue | Set in `.env` / Render (Must be >= 8 chars) |
| `PORT` | Local and production port | `8000` |

> **Security Note:** If `OFFICIAL_ACCESS_CODE` is unset or blank in the server environment, all official triage routes automatically return **HTTP 503 Service Unavailable** to prevent unauthorized access.

---

## 4. Setup & Running Locally (Windows PowerShell)

1. **Clone repository:**
   ```powershell
   git clone https://github.com/PotipireddyNaveenKumar/demo.git
   cd demo
   ```

2. **Create and activate virtual environment:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```powershell
   cp .env.example .env
   # Edit .env and enter your GEMINI_API_KEY and OFFICIAL_ACCESS_CODE
   ```

5. **Start development server:**
   ```powershell
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```
   Open `http://127.0.0.1:8000` in your web browser.

---

## 5. Automated Testing

Run the full automated test suite (15 tests covering scoring math, SLA aging, duplicate momentum, quota timeouts, malformed JSON fallbacks, and HTTP 400 validations):

```powershell
pytest test_triage.py -v
```

Run axe accessibility audit on the live interface:
```powershell
npx @axe-core/cli http://127.0.0.1:8000
```
*(Verified: 0 violations found by axe-core 4.13.0 in chrome-headless)*

---

## 6. Deployment to Render (Free Tier)

This repository includes `render.yaml` and `.python-version` (pinned to `3.11.9`) for zero-cost deployment on Render:

1. In the [Render Dashboard](https://dashboard.render.com/), click **New +** $\rightarrow$ **Web Service**.
2. Select your repository: `PotipireddyNaveenKumar/demo`.
3. Set configuration:
   * **Runtime:** Python 3
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set Environment Variables in Render:
   * `GEMINI_API_KEY`: *(Your Google AI Studio API key)*
   * `OFFICIAL_ACCESS_CODE`: *(Your private password)*
   * `GEMINI_MODEL`: `gemini-3.5-flash-lite`
5. Click **Deploy Web Service**.

---

## 7. Known System Limitations

1. **Render Free Tier Ephemeral Storage:** Render's free tier uses ephemeral containers that clear the SQLite database file on restart or spin-down. Civic Signal automatically detects empty databases on startup and re-seeds verified triage data (prominently labeled `SAMPLE DATA` in the queue) so judges can review the system without manual setup.
2. **Google AI Studio Free Tier Data Policy:** Free-tier Gemini API input may be reviewed by human annotators to improve Google models. Civic Signal displays an explicit privacy notice warning citizens not to submit personal names, phone numbers, or confidential data.
3. **Photo Hint Attachment:** Photo uploads are explicitly labeled in the UI as *"preview only, not analysed by AI"*. The photo preview is stored locally for human field inspection rather than running unverified, costly computer vision models.
