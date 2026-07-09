"""
PenStrokes AI  --  Simplified FastAPI Backend
No authentication. Session-based in-memory state. Public access.
"""

from dotenv import load_dotenv

load_dotenv()

import os
import time
import asyncio
import tempfile
from typing import List
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Header, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google import genai

from core import extract_text_from_bytes, synthesize_report

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SESSION_TTL_SECONDS = 3600  # 1 hour

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

sessions: dict[str, dict] = {}


def _get_session(session_id: str) -> dict:
    """Return the session dict, creating it if needed."""
    if session_id not in sessions:
        sessions[session_id] = {
            "created_at": time.time(),
            "last_active": time.time(),
            "intake_text": "",
            "sample_text": "",
            "report_text": "",
            "files": [],
        }
    sessions[session_id]["last_active"] = time.time()
    return sessions[session_id]


def _cleanup_expired_sessions() -> int:
    """Remove sessions older than SESSION_TTL_SECONDS. Returns count removed."""
    now = time.time()
    expired = [
        sid for sid, data in sessions.items()
        if now - data["last_active"] > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del sessions[sid]
    return len(expired)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

BANNER = r"""
  ____            ____  _             _               _    ___
 |  _ \ ___ _ __ / ___|| |_ _ __ ___ | | _____  ___  / \  |_ _|
 | |_) / _ \ '_ \\___ \| __| '__/ _ \| |/ / _ \/ __|/ _ \  | |
 |  __/  __/ | | |___) | |_| | | (_) |   <  __/\__ / ___ \ | |
 |_|   \___|_| |_|____/ \__|_|  \___/|_|\_\___||__/_/   \_\___|

 Backend starting up ...
"""

app = FastAPI(title="PenStrokes AI", version="2.0.0")

# CORS — allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Startup / shutdown events
# ---------------------------------------------------------------------------

async def _session_cleanup_loop():
    """Background task that purges expired sessions every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        removed = _cleanup_expired_sessions()
        if removed:
            print(f"[cleanup] Removed {removed} expired session(s). Active: {len(sessions)}")


@app.on_event("startup")
async def on_startup():
    print(BANNER)
    print(f"  Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Key  : {'set' if GEMINI_API_KEY else 'MISSING'}")
    print()
    asyncio.create_task(_session_cleanup_loop())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RefineRequest(BaseModel):
    instructions: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload-intake")
async def upload_intake(
    files: List[UploadFile] = File(...),
    x_session_id: str = Header(..., alias="X-Session-ID"),
):
    session = _get_session(x_session_id)
    results = []
    all_texts: list[str] = []

    for f in files:
        raw = await f.read()
        try:
            text = extract_text_from_bytes(raw, f.filename or "file.txt")
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to extract text from {f.filename}: {exc}")
        all_texts.append(text)
        results.append({"name": f.filename, "chars": len(text)})

    combined = "\n\n---\n\n".join(all_texts)
    session["intake_text"] = combined
    session["files"] = [r["name"] for r in results]

    return {
        "success": True,
        "files": results,
        "total_chars": len(combined),
    }


@app.post("/api/upload-sample")
async def upload_sample(
    file: UploadFile = File(...),
    x_session_id: str = Header(..., alias="X-Session-ID"),
):
    session = _get_session(x_session_id)
    raw = await file.read()
    try:
        text = extract_text_from_bytes(raw, file.filename or "sample.txt")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to extract text from {file.filename}: {exc}")

    session["sample_text"] = text

    return {
        "success": True,
        "filename": file.filename,
        "chars": len(text),
    }


@app.post("/api/generate")
async def generate(
    x_session_id: str = Header(..., alias="X-Session-ID"),
):
    session = _get_session(x_session_id)
    intake_text = session.get("intake_text", "")
    sample_text = session.get("sample_text", "")

    if not intake_text:
        raise HTTPException(status_code=400, detail="No intake documents uploaded yet.")
    if not sample_text:
        raise HTTPException(status_code=400, detail="No sample report uploaded yet.")

    try:
        report = synthesize_report(intake_text, sample_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    session["report_text"] = report

    return {
        "success": True,
        "report_text": report,
    }


@app.post("/api/refine")
async def refine(
    body: RefineRequest,
    x_session_id: str = Header(..., alias="X-Session-ID"),
):
    session = _get_session(x_session_id)
    report_text = session.get("report_text", "")

    if not report_text:
        raise HTTPException(status_code=400, detail="No report generated yet. Generate a report first.")

    system_prompt = (
        "You are a report editor. The clinician wants to modify an existing report. "
        "Apply their instructions precisely. "
        "CRITICAL: Do NOT add any new facts, data, observations, or clinical information "
        "that are not already in the report or in the original intake data provided. "
        "If the clinician asks to add detail on something not in the source data, write [BLANK]. "
        "Do NOT hallucinate or fabricate any content. "
        "Return ONLY the complete modified report, not explanations."
    )

    # Include intake data as reference to keep refinements grounded
    intake_text = session.get("intake_text", "")

    user_message = (
        "=== ORIGINAL INTAKE DATA (source of truth) ===\n\n"
        f"{intake_text}\n\n"
        "=== CURRENT REPORT ===\n\n"
        f"{report_text}\n\n"
        "=== CLINICIAN INSTRUCTIONS ===\n\n"
        f"{body.instructions}\n\n"
        "Apply the instructions. Use ONLY information from the intake data and current report. "
        "Do NOT invent or add any new information. Return the complete modified report."
    )

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

    models_to_try = ["gemini-2.5-pro", "gemini-2.0-flash"]
    refined_text = ""

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[user_message],
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.0,
                ),
            )
            refined_text = response.text
            break
        except Exception as exc:
            if model_name == models_to_try[-1]:
                raise HTTPException(status_code=500, detail=f"Refine failed: {exc}")
            continue

    session["report_text"] = refined_text

    return {
        "success": True,
        "report_text": refined_text,
    }


# ---------------------------------------------------------------------------
# Download endpoints (session passed as query param for direct browser links)
# ---------------------------------------------------------------------------

@app.get("/api/download/docx")
async def download_docx(session: str = Query(..., alias="session")):
    sess = sessions.get(session)
    if not sess or not sess.get("report_text"):
        raise HTTPException(status_code=404, detail="No report found for this session.")

    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    report_text: str = sess["report_text"]
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)

    for line in report_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            doc.add_paragraph("")
            continue

        # Detect headings (ALL CAPS or ends with colon, short lines)
        is_heading = (
            (stripped.isupper() or stripped.endswith(":"))
            and len(stripped) < 80
        )

        if is_heading:
            heading = doc.add_heading(stripped, level=2 if ":" in stripped else 1)
        else:
            doc.add_paragraph(stripped)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    doc.save(tmp.name)
    tmp.close()

    return FileResponse(
        path=tmp.name,
        filename="PenStrokes_Report.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/download/pdf")
async def download_pdf(session: str = Query(..., alias="session")):
    sess = sessions.get(session)
    if not sess or not sess.get("report_text"):
        raise HTTPException(status_code=404, detail="No report found for this session.")

    from fpdf import FPDF

    report_text: str = sess["report_text"]

    pdf = FPDF(format="letter")
    pdf.set_margins(25, 20, 25)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    effective_width = pdf.w - pdf.l_margin - pdf.r_margin

    lines = report_text.split("\n")
    prev_blank = False  # track consecutive blanks

    for line in lines:
        # Encode safely for latin-1
        safe_line = line.encode("latin-1", errors="replace").decode("latin-1")
        stripped = safe_line.strip()

        # --- Blank line handling: collapse consecutive blanks ---
        if not stripped:
            if not prev_blank:
                pdf.ln(3)
            prev_blank = True
            continue
        prev_blank = False

        # --- Heading detection ---
        # A "section heading" is: ALL CAPS (at least 4 chars, no lowercase),
        # or a short line that is all caps with maybe a dash/colon.
        # Field labels like "Name: John" are NOT headings.
        words = stripped.split()
        is_all_caps = (
            len(stripped) >= 4
            and stripped.upper() == stripped
            and any(c.isalpha() for c in stripped)
            and len(stripped) < 100
        )
        # Section header ending with colon: must be short and have no value after it
        # e.g. "Methods Used:" is a heading, but "Name: John Doe" is NOT
        is_section_colon = (
            stripped.endswith(":")
            and len(stripped) < 60
            and ":" not in stripped[:-1]  # only one colon, at the end
        )

        if is_all_caps:
            # Major heading (e.g. "CONFIDENTIAL INFORMATION", "NEUROPSYCHOLOGICAL ASSESSMENT")
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(effective_width, 6, stripped)
            pdf.ln(2)
        elif is_section_colon:
            # Section subheading (e.g. "Methods Used:", "Background:")
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(effective_width, 5.5, stripped)
            pdf.ln(1)
        else:
            # Normal body text
            pdf.set_font("Helvetica", "", 10.5)
            pdf.multi_cell(effective_width, 5, safe_line)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp.name)
    tmp.close()

    return FileResponse(
        path=tmp.name,
        filename="PenStrokes_Report.pdf",
        media_type="application/pdf",
    )


# ---------------------------------------------------------------------------
# Serve frontend static files (AFTER all API routes)
# ---------------------------------------------------------------------------

_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
    print(f"  Frontend served from: {os.path.abspath(_frontend_dist)}")
else:
    print(f"  [warn] Frontend dist not found at {os.path.abspath(_frontend_dist)} -- API-only mode")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )
