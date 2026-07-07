"""
Core business logic — text extraction, Gemini AI calls, case-number generation.
"""

import io
import os
import re
import time
from datetime import datetime, timezone

from pypdf import PdfReader
from docx import Document
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Minimum character threshold — if local extraction returns less than this,
# the document is likely scanned/handwritten and we use Gemini Vision instead.
_MIN_TEXT_THRESHOLD = 50

# Image extensions that go directly to Gemini Vision
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp", ".heic"}

# MIME type lookup for Gemini Vision
_MIME_MAP = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# ---------------------------------------------------------------------------
# Gemini Vision OCR — reads handwritten, scanned, and printed documents
# ---------------------------------------------------------------------------

_VISION_PROMPT = """\
You are an expert document reader specializing in clinical and psychological intake forms.

Extract ALL text from this document with extreme care and precision. This includes:
- Handwritten text (even messy or difficult handwriting)
- Printed/typed text
- Form field labels AND their filled-in values
- Checkboxes (mark as [✓] checked or [  ] unchecked)
- Any annotations, notes, or marginalia
- Tables and their contents

RULES:
1. Preserve the document's structure (headers, sections, paragraphs, lists).
2. For handwritten text you cannot fully decipher, provide your best interpretation and mark uncertain words with [?].
3. Do NOT add commentary, explanations, or summaries. Return ONLY the extracted text.
4. If the document contains multiple pages, separate them with "--- Page N ---" markers.
5. Be thorough — every piece of clinical information matters.
"""


def _vision_extract(file_bytes: bytes, mime_type: str) -> str:
    """Use Gemini Vision to extract text from any document or image."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Build the multimodal content
    contents = [
        genai.types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
        _VISION_PROMPT,
    ]

    models_to_try = ["gemini-2.5-pro", "gemini-2.0-flash"]
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=genai.types.GenerateContentConfig(temperature=0.0),
            )
            return response.text
        except Exception as exc:
            if model_name == models_to_try[-1]:
                raise RuntimeError(f"Gemini Vision extraction failed: {exc}") from exc
            continue

    return ""


# ---------------------------------------------------------------------------
# Text extraction — smart pipeline (local first, Gemini Vision fallback)
# ---------------------------------------------------------------------------

def extract_text(filepath: str) -> str:
    """Extract text from a local file. Uses Gemini Vision for scanned/handwritten docs."""
    ext = os.path.splitext(filepath)[1].lower()

    # Images → straight to Gemini Vision
    if ext in _IMAGE_EXTENSIONS:
        with open(filepath, "rb") as f:
            data = f.read()
        mime = _MIME_MAP.get(ext, "application/octet-stream")
        return _vision_extract(data, mime)

    # Try fast local extraction first
    local_text = ""
    if ext == ".pdf":
        local_text = _extract_pdf(filepath)
    elif ext == ".docx":
        local_text = _extract_docx(filepath)
    elif ext == ".doc":
        local_text = _extract_doc_fallback(filepath)
    else:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    # If local extraction got enough text, use it
    if len(local_text.strip()) >= _MIN_TEXT_THRESHOLD:
        return local_text

    # Otherwise, the document is likely scanned/handwritten → Gemini Vision
    print(f"[Vision OCR] Local extraction returned only {len(local_text.strip())} chars for {filepath}, using Gemini Vision...")
    with open(filepath, "rb") as f:
        data = f.read()
    mime = _MIME_MAP.get(ext, "application/octet-stream")
    return _vision_extract(data, mime)


def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Extract text from raw bytes. Uses Gemini Vision for scanned/handwritten docs and images."""
    ext = os.path.splitext(filename)[1].lower()

    # Images → straight to Gemini Vision
    if ext in _IMAGE_EXTENSIONS:
        mime = _MIME_MAP.get(ext, "application/octet-stream")
        return _vision_extract(file_bytes, mime)

    # Try fast local extraction first
    local_text = ""
    if ext == ".pdf":
        local_text = _extract_pdf_bytes(file_bytes)
    elif ext == ".docx":
        local_text = _extract_docx_bytes(file_bytes)
    elif ext == ".doc":
        local_text = _extract_doc_bytes_fallback(file_bytes)
    else:
        return file_bytes.decode("utf-8", errors="ignore")

    # If local extraction got enough text, use it
    if len(local_text.strip()) >= _MIN_TEXT_THRESHOLD:
        return local_text

    # Otherwise → Gemini Vision
    print(f"[Vision OCR] Local extraction returned only {len(local_text.strip())} chars for {filename}, using Gemini Vision...")
    mime = _MIME_MAP.get(ext, "application/octet-stream")
    return _vision_extract(file_bytes, mime)


# --- PDF (fast local) ---

def _extract_pdf(filepath: str) -> str:
    reader = PdfReader(filepath)
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extract_pdf_bytes(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


# --- DOCX (fast local) ---

def _extract_docx(filepath: str) -> str:
    doc = Document(filepath)
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_docx_bytes(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


# --- DOC fallback (binary) ---

def _extract_doc_fallback(filepath: str) -> str:
    with open(filepath, "rb") as f:
        raw = f.read()
    return _ascii_from_binary(raw)


def _extract_doc_bytes_fallback(data: bytes) -> str:
    return _ascii_from_binary(data)


def _ascii_from_binary(data: bytes) -> str:
    """Best-effort extraction of readable ASCII runs from binary data."""
    text_chars = []
    for byte in data:
        if 32 <= byte < 127 or byte in (9, 10, 13):
            text_chars.append(chr(byte))
        else:
            text_chars.append(" ")
    raw = "".join(text_chars)
    raw = re.sub(r"[ \t]{3,}", "  ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


# ---------------------------------------------------------------------------
# Gemini AI — report synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_SYNTHESIZE = """\
You are a highly skilled psychological report writer with decades of clinical experience.

Your task is to produce a polished, professional psychological report based on raw intake data provided by the clinician.

CRITICAL INSTRUCTIONS:
1. **REPLICATE THE EXACT FORMAT**: You are given a SAMPLE REPORT. You MUST reproduce its EXACT:
   - Section headers (use the same header names, in the same order)
   - Document structure (same number and type of sections)
   - Formatting patterns (how paragraphs are structured, bullet vs prose, etc.)
   - Writing style, tone, and vocabulary level
   - Paragraph length and detail level
   - Header capitalization style
   The output should look like it was written by the same author as the sample.

2. **Map the data**: Take every piece of relevant information from the RAW INTAKE DATA and place it in the appropriate section of the report, following the structure of the sample.

3. **Missing information**: Where data is clearly needed for a section but was NOT provided in the intake, insert the placeholder tag [BLANK] so the clinician can fill it in later. Never fabricate clinical data.

4. **Clinical language**: Use professional, clinical language consistent with the sample. Maintain the same level of detail, paragraph length, and vocabulary.

5. **Completeness**: Include ALL sections present in the sample report. Do not omit any section.

6. **Output format**: Return ONLY the report text. Do not include meta-commentary, explanations, or notes to the user. Do not use markdown formatting (no **, ##, etc.) — use plain text with clear section headers.
"""

SYSTEM_PROMPT_CHAT = """\
You are a helpful clinical assistant. The user is a psychologist reviewing intake documents for a client.
You have access to the text extracted from the intake documents. Answer the user's questions accurately based on that context.
If the information is not present in the documents, say so clearly.
Be concise but thorough. Use clinical language when appropriate.
"""


def _get_genai_client() -> genai.Client:
    """Return a configured Gemini client."""
    return genai.Client(api_key=GEMINI_API_KEY)


def synthesize_report(raw_text: str, sample_report_text: str) -> str:
    """
    Generate a psychological report from raw intake text,
    matching the style of the provided sample report.
    """
    client = _get_genai_client()

    user_message = (
        "=== SAMPLE REPORT (match this style) ===\n\n"
        f"{sample_report_text}\n\n"
        "=== RAW INTAKE DATA ===\n\n"
        f"{raw_text}\n\n"
        "Now write the complete psychological report."
    )

    # Try premium model first, then fall back
    models_to_try = ["gemini-2.5-pro", "gemini-2.0-flash"]

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[user_message],
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_SYNTHESIZE,
                    temperature=0.1,
                ),
            )
            return response.text
        except Exception as exc:
            # If this was the last model, re-raise
            if model_name == models_to_try[-1]:
                raise RuntimeError(f"All Gemini models failed. Last error: {exc}") from exc
            # Otherwise try the next model
            continue

    return ""  # unreachable but keeps linters happy


def chat_with_doc(context_text: str, messages: list[dict]) -> str:
    """
    Chat about intake documents.
    `messages` is a list of {"role": "user"|"assistant", "content": "..."}.
    """
    client = _get_genai_client()

    # Build the conversation contents for Gemini
    # First message provides the document context
    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        "Here are the intake documents for reference:\n\n"
                        f"{context_text}\n\n"
                        "I may now ask you questions about these documents."
                    )
                }
            ],
        },
        {
            "role": "model",
            "parts": [
                {
                    "text": (
                        "I've reviewed the intake documents. "
                        "Feel free to ask me anything about them."
                    )
                }
            ],
        },
    ]

    # Append conversation history
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}],
        })

    models_to_try = ["gemini-2.5-pro", "gemini-2.0-flash"]
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_CHAT,
                    temperature=0.7,
                ),
            )
            return response.text
        except Exception as exc:
            if model_name == models_to_try[-1]:
                raise RuntimeError(f"All Gemini models failed. Last error: {exc}") from exc
            continue

    return ""


# ---------------------------------------------------------------------------
# Case-number generation
# ---------------------------------------------------------------------------

_case_counter: int = 0


def generate_case_number(client_name: str) -> str:
    """Generate a unique case number like PS-2026-0001."""
    global _case_counter
    _case_counter += 1
    year = datetime.now(timezone.utc).year
    return f"PS-{year}-{_case_counter:04d}"
