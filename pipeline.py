import os
import sys
import json
import time
import shutil
import pathlib
import pypdf
import docx
import tkinter as tk
from tkinter import simpledialog, messagebox
from google import genai

# Workspace Paths
BASE_DIR = pathlib.Path.cwd()
WORKSPACE_DIR = BASE_DIR / "workspace"
INPUT_DUMP_DIR = WORKSPACE_DIR / "input_dump"
CLIENT_PROFILES_DIR = WORKSPACE_DIR / "client_profiles"
OUTPUT_REPORTS_DIR = WORKSPACE_DIR / "output_reports"
ARCHIVE_DIR = WORKSPACE_DIR / "archive"
REGISTRY_FILE = WORKSPACE_DIR / "client_registry.json"

def init_environment():
    """Initializes the local directory structure and registry file upon first execution."""
    dirs_to_create = [
        WORKSPACE_DIR,
        INPUT_DUMP_DIR,
        CLIENT_PROFILES_DIR,
        OUTPUT_REPORTS_DIR,
        ARCHIVE_DIR
    ]
    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)
    
    if not REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)
        print(f"[INIT] Created new client registry at {REGISTRY_FILE}")
    else:
        print("[INIT] Environment already initialized.")

def load_registry():
    """Reads the stateful registry file."""
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_registry(registry_data):
    """Writes to the stateful registry file."""
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry_data, f, indent=4)

def extract_text_from_file(filepath):
    """Extracts text from PDF or DOCX files."""
    filepath = pathlib.Path(filepath)
    ext = filepath.suffix.lower()
    text = ""
    try:
        if ext == ".pdf":
            reader = pypdf.PdfReader(filepath)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif ext == ".docx":
            doc = docx.Document(filepath)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            print(f"[WARN] Unsupported file extension for text extraction: {ext}")
    except Exception as e:
        print(f"[ERROR] Failed to extract text from {filepath}: {e}")
    return text

def create_new_client_profile(client_id, sample_text):
    """Handles the creation of a new client profile via user prompt."""
    profile_dir = CLIENT_PROFILES_DIR / client_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    instructions_path = profile_dir / "system_instructions.txt"
    template_path = profile_dir / "report_template.docx"
    
    # Create empty files to make it easier for the user
    if not instructions_path.exists():
        instructions_path.write_text("Enter client tone and instructions here...", encoding="utf-8")
    
    # Show GUI Prompt
    root = tk.Tk()
    root.withdraw() # hide main window
    msg = (f"I've created a new folder for this client:\n{profile_dir}\n\n"
           f"Please do the following before clicking OK:\n"
           f"1. Open the 'system_instructions.txt' in that folder and add their specific guidelines.\n"
           f"2. Place their 'report_template.docx' in the same folder.\n\n"
           f"Note: The word template MUST contain {{REPORT_CONTENT}} somewhere inside it so I know where to put the text.\n\n"
           f"Click OK when you are ready to continue processing the file.")
    
    # Bring window to front
    root.attributes("-topmost", True)
    messagebox.showinfo("Action Required: New Client Setup", msg, parent=root)
    root.destroy()
    
    # Simple fingerprint extraction (e.g., longest common words or a direct chunk)
    # For a robust structural marker, we take a 100-character chunk from the first 500 characters
    # that is likely unique to this form structure (skipping empty space).
    clean_text = " ".join(sample_text[:1000].split())
    anchor_text = clean_text[20:120] if len(clean_text) > 120 else clean_text
    
    registry = load_registry()
    registry[client_id] = {
        "anchor_text": anchor_text
    }
    save_registry(registry)
    print(f"[SUCCESS] Registered new client profile: {client_id}")

def match_client_fingerprint(text_sample, registry):
    """Compares current document structural markers against registered client fingerprints."""
    clean_sample = " ".join(text_sample.split())
    for client_id, data in registry.items():
        anchor = data.get("anchor_text", "")
        if anchor and anchor in clean_sample:
            return client_id
    return None

def synthesize_report(raw_text, instructions_text):
    """Commands the Gemini API to perform rigorous thematic cross-referencing."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[ERROR] Failed to initialize Gemini client: {e}")
        return None
    
    # The user requested 'gemini-3.1-pro-high', if unavailable in your tier,
    # you may need to fallback to 'gemini-1.5-pro'
    model_name = "gemini-3.1-pro-high"
    
    system_prompt = (
        "You are a highly skilled psychological report synthesizer.\n"
        "Your task is to map the provided raw intake details into the specific headers dictated by the client guidelines.\n"
        "Enforce blank line tags ([BLANK]) or statistical evaluation markers where empirical diagnostic test scores are required but missing.\n"
        f"CLIENT GUIDELINES:\n{instructions_text}\n"
    )
    
    # Configure low temperature for clinical accuracy
    generation_config = genai.types.GenerateContentConfig(
        temperature=0.1,
        system_instruction=system_prompt,
    )
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=raw_text,
            config=generation_config
        )
        return response.text
    except Exception as e:
        print(f"[ERROR] API Call failed (Ensure {model_name} is available in your tier): {e}")
        print("[INFO] Attempting fallback to gemini-1.5-pro...")
        try:
            response = client.models.generate_content(
                model="gemini-1.5-pro",
                contents=raw_text,
                config=generation_config
            )
            return response.text
        except Exception as e2:
            print(f"[FATAL] API Call failed again: {e2}")
            return None

def inject_into_template(template_path, generated_text, output_path):
    """Injects the generated narrative into the docx template preserving native styles."""
    doc = docx.Document(template_path)
    replaced = False
    
    # Iterate through paragraphs to find the placeholder
    for para in doc.paragraphs:
        if "{{REPORT_CONTENT}}" in para.text:
            para.text = para.text.replace("{{REPORT_CONTENT}}", generated_text)
            replaced = True
    
    # If not found in paragraphs, check tables
    if not replaced:
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        if "{{REPORT_CONTENT}}" in para.text:
                            para.text = para.text.replace("{{REPORT_CONTENT}}", generated_text)
                            replaced = True
    
    if not replaced:
        print(f"[WARN] Placeholder '{{{{REPORT_CONTENT}}}}' not found in {template_path}. Appending to end of document.")
        doc.add_paragraph(generated_text)
        
    doc.save(output_path)
    print(f"[SUCCESS] Saved generated report to {output_path}")

def process_file(filepath):
    """Main pipeline logic for processing an ingested file."""
    print(f"\n[INFO] Processing file: {filepath.name}")
    
    # Step 2: Content Parsing
    raw_text = extract_text_from_file(filepath)
    if not raw_text.strip():
        print(f"[WARN] No text extracted from {filepath.name}. Skipping.")
        return
    
    first_1000_chars = raw_text[:1000]
    
    # Step 3: Classification and State Routing
    registry = load_registry()
    client_id = match_client_fingerprint(first_1000_chars, registry)
    
    if not client_id:
        print("\n[ALERT] Unrecognized intake structure detected. Prompting user...")
        
        # Show GUI Prompt for input
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        
        client_id = simpledialog.askstring(
            "New Intake Form Detected", 
            "I don't recognize the format of this new file.\n\nPlease enter a unique Name or ID for this new client profile:", 
            parent=root
        )
        root.destroy()
        
        if not client_id or not client_id.strip():
            print("[ERROR] Client ID cannot be empty or was cancelled. Aborting process for this file.")
            return
        
        client_id = client_id.strip()
        create_new_client_profile(client_id, first_1000_chars)
        # Reload registry after update
        registry = load_registry()

    print(f"[INFO] Matched profile: {client_id}")
    
    profile_dir = CLIENT_PROFILES_DIR / client_id
    instructions_path = profile_dir / "system_instructions.txt"
    template_path = profile_dir / "report_template.docx"
    
    if not instructions_path.exists() or not template_path.exists():
        print(f"[ERROR] Missing instructions or template for client '{client_id}'.")
        print(f"Expected:\n  - {instructions_path}\n  - {template_path}")
        return

    with open(instructions_path, "r", encoding="utf-8") as f:
        instructions_text = f.read()
    
    # Step 4: Report Synthesis Protocol (API Synchronization)
    print("[INFO] Synthesizing report via Gemini API...")
    generated_narrative = synthesize_report(raw_text, instructions_text)
    
    if not generated_narrative:
        print("[ERROR] Report synthesis failed. Aborting document assembly.")
        return
        
    # Step 5: Document Assembly & Export
    patient_name = filepath.stem.replace(" ", "_")
    output_dir = OUTPUT_REPORTS_DIR / client_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filepath = output_dir / f"{patient_name}_Assessment_Report.docx"
    
    print("[INFO] Assembling final document...")
    inject_into_template(template_path, generated_narrative, output_filepath)
    
    # Move raw file to archive
    archive_dest = ARCHIVE_DIR / filepath.name
    # Handle filename collisions in archive
    if archive_dest.exists():
        archive_dest = ARCHIVE_DIR / f"{filepath.stem}_{int(time.time())}{filepath.suffix}"
    
    shutil.move(str(filepath), str(archive_dest))
    print(f"[INFO] Archived original intake form to {archive_dest}")

def main_loop():
    """Structured polling loop to monitor input directory."""
    print(f"--- Psychological Report Synthesis Pipeline ---")
    print(f"Monitoring '{INPUT_DUMP_DIR}' for new intake forms...")
    print(f"Press Ctrl+C to exit.\n")
    
    try:
        while True:
            # Poll for PDF and DOCX files
            files_to_process = []
            for ext in ('*.pdf', '*.docx', '*.doc'):
                files_to_process.extend(INPUT_DUMP_DIR.glob(ext))
            
            for filepath in files_to_process:
                # Wait briefly to ensure file has finished writing
                time.sleep(1)
                process_file(filepath)
                
            time.sleep(3) # Polling interval
    except KeyboardInterrupt:
        print("\n[INFO] Pipeline stopped by user.")

if __name__ == "__main__":
    init_environment()
    main_loop()
