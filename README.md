# Civic Signal — AI-Powered Community Issue Triage

> **Challenge:** AI for Better Living & Smarter Communities  
> **Judged on:** Code Quality, Security, Efficiency, Testing, Accessibility, Google Services, Problem Alignment.

Civic Signal is a transparent, explainable triage queue for municipal issues. Citizens submit reports in free-form text in any language with optional photo previews. Google Gemini AI extracts structured signals (category, urgency, impact, location), and a deterministic scoring engine clusters duplicates and routes tickets to city departments with an audit trail.

---

## Architecture & Technology Stack

| Component | Technology | Role |
| :--- | :--- | :--- |
| **Backend API** | Python 3.11 / FastAPI | High-efficiency asynchronous REST API |
| **AI Extraction** | Google Gemini API (`gemini-2.0-flash`) | Zero-shot structured JSON extraction |
| **Scoring Engine** | Python (`triage_engine.py`) | Deterministic, explainable scoring & routing |
| **Database** | SQLite3 (Embedded) | Lightweight zero-latency local storage |
| **Frontend** | Accessible Vanilla HTML5/CSS3/ES6 | Zero build step, full keyboard navigation & ARIA |
| **Testing** | Pytest (`pytest test_triage.py`) | Automated regression & unit test suite |

---

## Explainable Scoring Rules (0–100)

1. **Urgency Points:** `immediate_hazard` (+50), `safety_risk` (+35), `service_disruption` (+20), `routine` (+5), `unclear` (+0).
2. **Public Impact:** `multiple_people` / shared public infrastructure (+15), `single_location` (+0).
3. **Duplicate Momentum:** +5 points for each open matching duplicate report in the same area within 30 days (max +15).
4. **Aging SLA Bonus:** +10 points if the oldest unresolved report in the cluster is $\ge 24$ hours old.
5. **Priority Bands:**
   * **Urgent:** Score $\ge 60$
   * **Standard:** Score $25 - 59$
   * **Routine:** Score $< 25$

---

## Google Gemini API Free Tier & Privacy Notice

* **Primary Model:** `gemini-3.5-flash-lite` (Verified fast free-tier response in AI Studio).
* **Automatic Fallbacks:** `gemini-flash-latest`, `gemini-3.8-flash`.
* **Free Tier Limits:** 15 RPM, 1,000,000 TPM, 1,500 RPD (Google AI Studio).
* **Privacy Disclosure:** In accordance with Google AI Studio free tier terms, data submitted may be reviewed by human annotators to improve Google models. Citizens are warned not to submit sensitive PII.
* **Failure / Quota Behavior:** If Gemini encounters a timeout (>6s), 429 quota exhaustion, or invalid response, the system **never fakes AI output**. It gracefully activates the validated manual entry fallback (`ai_status: "manual_fallback"`).

---

## Local Development & Setup

1. **Clone repository:**
   ```powershell
   git clone https://github.com/PotipireddyNaveenKumar/demo.git
   cd demo
   ```

2. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Configure Environment:**
   Copy `.env.example` to `.env`:
   ```powershell
   cp .env.example .env
   ```
   Set your `GEMINI_API_KEY` and private `OFFICIAL_ACCESS_CODE` (at least 8 characters).

4. **Run Application:**
   ```powershell
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```
   Open `http://127.0.0.1:8000` in your browser.

5. **Run Test Suite:**
   ```powershell
   pytest test_triage.py -v
   ```

---

## Deployment to Render (Free Tier) & Ephemeral Storage

This repository includes `render.yaml` and `.python-version` (pinned to Python 3.11.9) for deployment on Render:

> **Render Free Tier Ephemeral Storage Note:**  
> Render free tier instances use an ephemeral container filesystem where SQLite database files reset on spin-down or reboot. Civic Signal automatically detects when the SQLite database is empty on application startup and re-seeds verified triage data (prominently labeled `SAMPLE DATA` in the queue), guaranteeing uninterrupted hackathon evaluation.

### Render Setup:
1. In the [Render Dashboard](https://dashboard.render.com/), click **New +** $\rightarrow$ **Web Service**.
2. Connect your GitHub repository: `PotipireddyNaveenKumar/demo`.
3. Configure settings:
   * **Runtime:** Python 3
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set Environment Variables in Render:
   * `GEMINI_API_KEY`: *(Your Google AI Studio API key)*
   * `OFFICIAL_ACCESS_CODE`: *(Your secure private code)*
   * `GEMINI_MODEL`: `gemini-3.5-flash-lite`
5. Verify deployment: Navigate to your Render live URL (e.g. `https://your-service.onrender.com/api/health`) and ensure HTTP 200 `healthy`.
