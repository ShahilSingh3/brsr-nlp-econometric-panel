"""
clean.py
Stage 3: Data Cleaning, Normalization & QA for BRSR Disclosures.

Project Context & Objectives:
    Raw textual extractions from corporate filings contain systematic document artifacts:
    - Recurring running headers and footers (e.g. "Integrated Annual Report 2024-25")
    - Isolated standalone page numbering lines
    - Non-breaking space characters (`\\xa0`) and Windows carriage returns (`\\r\\n`)
    - Redundant multi-line breaks and tabs

    PURPOSE OF THIS MODULE:
    This script reads raw extraction records (from CSV or JSONL) and generates
    a cleaned, normalized dataset in `data/processed/pilot_corpus_clean.csv`.

CRITICAL INVARIANT -- IMMUTABILITY OF RAW TEXT:
    The original `section_text` field must NEVER be overwritten, mutated, or truncated.
    Preserving raw verbatim text is required so that:
    1. Any subsequent changes to regex cleaning rules can be re-applied deterministically.
    2. Researchers can audit cleaned output directly against raw ground truth.
    All cleaned output is stored in a dedicated new column: `cleaned_text`.

Usage:
    python clean.py [input_file] [output_file]
    Default behavior:
        python clean.py data/raw/_smoke_test.csv data/processed/pilot_corpus_clean.csv
"""

import re
import sys
from pathlib import Path
import csv
import json
from schema import BRSRRow, CSV_FIELDNAMES

# ==============================================================================
# Regular Expressions for Header, Footer & Pagination Artifact Removal
# ==============================================================================

# Compiled regex patterns targeting recurring boilerplates found in Indian corporate filings.
# Using re.MULTILINE allows '^' and '$' to match at the beginning and end of each line.
HEADER_FOOTER_PATTERNS = [
    # Matches isolated page numbers on their own lines (e.g., "  160  ")
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),

    # Matches standard SEBI BRSR document headers with ampersand
    re.compile(r"^\s*Business Responsibility & Sustainability Report\s*$", re.MULTILINE | re.IGNORECASE),

    # Matches report headers using the word "and" or trailing subtitle phrases
    re.compile(r"^\s*Business Responsibility and Sustainability Report.*$", re.MULTILINE | re.IGNORECASE),

    # Matches integrated annual report running headers (e.g., "Integrated Annual Report 2024-25")
    re.compile(r"^\s*Integrated Annual Report \d{4}-\d{2,4}\s*$", re.MULTILINE | re.IGNORECASE),

    # Matches corporate statutory reports chapter headers
    re.compile(r"^\s*STATUTORY REPORTS\s*$", re.MULTILINE | re.IGNORECASE),
]


# ==============================================================================
# Narrative Cleaning Logic
# ==============================================================================

def clean_narrative(text: str) -> str:
    """
    Normalizes raw extracted text while carefully preserving narrative semantics,
    sentence boundaries, and numerical figures.

    Transformation Steps:
        1. Unicode normalization: Replaces non-breaking spaces ('\\xa0') with standard spaces.
        2. Line break normalization: Converts Windows CRLF ('\\r\\n') and legacy CR ('\\r') to LF ('\\n').
        3. Boilerplate removal: Strips page numbers, headers, and footer lines.
        4. Whitespace collapsing: Reduces excessive vertical whitespace (3+ newlines -> 2 newlines)
           and collapses runs of tabs/horizontal spaces to single spaces.
        5. Strips leading and trailing whitespace.

    Parameters:
        text: Raw verbatim string from `section_text`.

    Returns:
        Cleaned, normalized text string. Returns empty string if input is empty or None.
    """
    if not text:
        return ""

    cleaned = text

    # Step 1 & 2: Normalize Unicode whitespace and newline representations
    cleaned = cleaned.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")

    # Step 3: Remove known recurring header/footer artifacts
    for pat in HEADER_FOOTER_PATTERNS:
        cleaned = pat.sub("", cleaned)

    # Step 4: Normalize paragraph spacing: preserve double newlines for paragraphs
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    # Step 5: Collapse multiple horizontal spaces/tabs into a single space
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    return cleaned.strip()


# ==============================================================================
# Dataset Ingestion & Batch Processing
# ==============================================================================

def process_raw_dataset(input_path: str | Path, output_path: str | Path) -> None:
    """
    Ingests a raw extraction file (either .jsonl or .csv), applies `clean_narrative`
    to each row's `section_text`, computes the cleaned word count, and exports
    the enriched dataset to `output_path`.

    Parameters:
        input_path: Path to the raw input file (.jsonl or .csv).
        output_path: Path where the processed CSV will be written.

    Invariants:
        - `section_text` is left unmodified.
        - `cleaned_text` contains the normalized text.
        - `word_count` provides the token count for quick variance/outlier checks.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    # Ensure destination directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []

    # Ingest depending on file format extension
    if input_path.suffix == ".jsonl":
        # Ingest from append-only JSON Lines ledger
        with input_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    elif input_path.suffix == ".csv":
        # Ingest from standard CSV
        with input_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    else:
        raise ValueError(f"Unsupported format: {input_path.suffix}. Expected .csv or .jsonl")

    # Process rows sequentially
    processed_rows = []
    for r in rows:
        raw_text = r.get("section_text", "")
        # Apply narrative cleaner
        cleaned = clean_narrative(raw_text)
        # Compute word count as a proxy for disclosure length and variance
        words = len(cleaned.split())

        # Create a shallow copy of the row dictionary to avoid in-place mutation
        r_out = dict(r)
        r_out["cleaned_text"] = cleaned
        r_out["word_count"] = words
        processed_rows.append(r_out)

    # Define the output CSV header fields, ensuring new columns are included
    fieldnames = list(rows[0].keys()) if rows else list(CSV_FIELDNAMES)
    if "cleaned_text" not in fieldnames:
        fieldnames.append("cleaned_text")
    if "word_count" not in fieldnames:
        fieldnames.append("word_count")

    # Write output CSV with full UTF-8 encoding
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(processed_rows)

    print(f"Processed {len(processed_rows)} rows. Cleaned dataset written to: {output_path}")


# ==============================================================================
# CLI Entry Point
# ==============================================================================

if __name__ == "__main__":
    """
    Command-line execution handler:
    Accepts optional input and output file arguments; falls back to default paths.
    """
    src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/_smoke_test.csv"
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/processed/pilot_corpus_clean.csv"
    process_raw_dataset(src, dst)
