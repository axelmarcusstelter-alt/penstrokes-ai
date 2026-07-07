"""
Local file storage — replaces Google Drive.
Stores everything under backend/data/ in organized folders.
Zero setup required.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent / "data"
CLIENTS_DIR = DATA_DIR / "clients"


def init_storage():
    """Ensure the base directory structure exists."""
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)


def list_clients() -> list[dict]:
    """List all client folders."""
    init_storage()
    clients = []
    if not CLIENTS_DIR.exists():
        return clients
    for folder in sorted(CLIENTS_DIR.iterdir()):
        if folder.is_dir() and not folder.name.startswith("."):
            # Count cases
            cases_dir = folder / "cases"
            case_count = len(list(cases_dir.iterdir())) if cases_dir.exists() else 0
            # Check for sample report
            sample = None
            for f in folder.iterdir():
                if f.name.lower().startswith("sample_report") and f.is_file():
                    sample = f.name
                    break
            clients.append({
                "id": folder.name,
                "name": folder.name,
                "case_count": case_count,
                "sample_report": sample,
            })
    return clients


def create_client(name: str) -> dict:
    """Create a new client folder."""
    init_storage()
    client_dir = CLIENTS_DIR / name
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "cases").mkdir(exist_ok=True)
    return {"id": name, "name": name, "case_count": 0, "sample_report": None}


def save_sample_report(client_name: str, filename: str, file_bytes: bytes) -> str:
    """Save (or replace) the sample report for a client."""
    client_dir = CLIENTS_DIR / client_name
    client_dir.mkdir(parents=True, exist_ok=True)

    # Remove old sample reports
    for f in client_dir.iterdir():
        if f.name.lower().startswith("sample_report") and f.is_file():
            f.unlink()

    # Save new
    safe_name = f"sample_report_{filename}"
    dest = client_dir / safe_name
    dest.write_bytes(file_bytes)
    return safe_name


def get_sample_report_path(client_name: str) -> Path | None:
    """Get the path to the client's sample report, if any."""
    client_dir = CLIENTS_DIR / client_name
    if not client_dir.exists():
        return None
    for f in client_dir.iterdir():
        if f.name.lower().startswith("sample_report") and f.is_file():
            return f
    return None


def create_case(client_name: str, case_number: str) -> dict:
    """Create a case folder with intake/ and output/ subfolders."""
    cases_dir = CLIENTS_DIR / client_name / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    case_dir = cases_dir / case_number
    intake_dir = case_dir / "intake"
    output_dir = case_dir / "output"
    intake_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "id": case_number,
        "case_number": case_number,
        "client_name": client_name,
        "case_dir": str(case_dir),
        "intake_dir": str(intake_dir),
        "output_dir": str(output_dir),
    }


def save_intake_file(client_name: str, case_number: str, filename: str, file_bytes: bytes) -> str:
    """Save an intake file to the case's intake folder."""
    intake_dir = CLIENTS_DIR / client_name / "cases" / case_number / "intake"
    intake_dir.mkdir(parents=True, exist_ok=True)
    dest = intake_dir / filename
    dest.write_bytes(file_bytes)
    return str(dest)


def save_report(client_name: str, case_number: str, filename: str, file_bytes: bytes) -> str:
    """Save a generated report to the case's output folder."""
    output_dir = CLIENTS_DIR / client_name / "cases" / case_number / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / filename
    dest.write_bytes(file_bytes)
    return str(dest)


def get_intake_files(client_name: str, case_number: str) -> list[str]:
    """List intake files for a case."""
    intake_dir = CLIENTS_DIR / client_name / "cases" / case_number / "intake"
    if not intake_dir.exists():
        return []
    return [f.name for f in intake_dir.iterdir() if f.is_file()]


def list_cases(client_name: str) -> list[dict]:
    """List all cases for a client."""
    cases_dir = CLIENTS_DIR / client_name / "cases"
    if not cases_dir.exists():
        return []
    cases = []
    for folder in sorted(cases_dir.iterdir(), reverse=True):
        if folder.is_dir():
            intake_count = len(list((folder / "intake").iterdir())) if (folder / "intake").exists() else 0
            has_report = any(f.suffix == ".docx" for f in (folder / "output").iterdir()) if (folder / "output").exists() else False
            cases.append({
                "id": folder.name,
                "case_number": folder.name,
                "intake_count": intake_count,
                "has_report": has_report,
            })
    return cases


def delete_case(client_name: str, case_number: str):
    """Delete a case folder entirely."""
    case_dir = CLIENTS_DIR / client_name / "cases" / case_number
    if case_dir.exists():
        shutil.rmtree(case_dir)
