"""
schema.py
Canonical Data Schema and Validation for the BRSR Pilot Corpus (Stage 1).

Project Context:
    This module defines the foundational data model for extracting, storing,
    and validating Business Responsibility and Sustainability Reporting (BRSR)
    filings mandated by the Securities and Exchange Board of India (SEBI).

Architectural Invariants & Design Principles:
    1. Granularity:
       Each row corresponds to exactly one combination of:
       (company_id, fiscal_year, principle_number, indicator_type).
       A complete filing will produce up to 18 rows (9 Principles x 2 Indicator Types).

    2. Immutability of Raw Text (`section_text`):
       The `section_text` field stores verbatim, uncleaned text extracted
       directly from the filing (PDF or XBRL). It must NEVER be overwritten or
       destructively altered during downstream cleaning (e.g. stripping punctuation,
       lowercasing, or removing stopwords). Cleaning belongs in a downstream pipeline
       (Stage 3, clean.py) which writes to a separate field (`cleaned_text`).

    3. Fail-Loud Validation:
       Data integrity issues (such as invalid principle numbers, unrecognized indicator
       types, missing corporate identifiers, or empty disclosures) must raise immediate
       exceptions via `SchemaValidationError` rather than silently propagating nulls or
       empty rows into the analytical dataset.

Usage:
    Run as a standalone script to execute a validation smoke test:
        python schema.py
"""

from dataclasses import dataclass, asdict, fields
from pathlib import Path
import csv
import json
import re

# ==============================================================================
# Domain Constants & Allowed Value Sets
# ==============================================================================

# SEBI BRSR divides Principle disclosures into two distinct indicator tiers:
# - "Essential": Mandatory disclosures required for all covered entities.
# - "Leadership": Aspirational / voluntary disclosures for advanced ESG practices.
VALID_INDICATOR_TYPES = {"Essential", "Leadership"}

# Primary source modalities handled by this pipeline:
# - "XBRL": Structured XML instance files submitted to BSE/NSE portals.
# - "PDF": Visual documents (standalone BRSR or integrated Annual Reports).
VALID_SOURCE_TYPES = {"XBRL", "PDF"}

# Provenance tracking: distinguishes fully automated algorithmic extractions
# from rows that have undergone human spot-checking and manual verification against PDFs.
VALID_EXTRACTION_METHODS = {"automated", "manual-checked"}

# National Guidelines on Responsible Business Conduct (NGRBC) defines Principles 1 through 9.
VALID_PRINCIPLES = set(range(1, 10))

# Panel years accepted for the `fy` join key (advisor's panel covers FY2019-20 to FY2025-26).
VALID_FY_RANGE = range(2020, 2027)


# ==============================================================================
# Fiscal-year helpers
# ==============================================================================

# Matches labels such as "FY2024-25". Group 1 = starting calendar year.
_FISCAL_YEAR_RE = re.compile(r"^FY(\d{4})-(\d{2})$")


def fiscal_year_to_fy(fiscal_year: str) -> int:
    """
    Convert a label like "FY2024-25" into the panel's `fy` key (year of the 31-March end).

    Example: "FY2024-25" -> 2025 (year-end 31 Mar 2025).
    Raises ValueError for malformed labels or labels whose two years are not consecutive.
    """
    m = _FISCAL_YEAR_RE.match(fiscal_year.strip())
    if not m:
        raise ValueError(f"fiscal_year={fiscal_year!r} must look like 'FY2024-25'")
    start = int(m.group(1))
    if (start + 1) % 100 != int(m.group(2)):
        raise ValueError(f"fiscal_year={fiscal_year!r}: the two years are not consecutive")
    return start + 1


def fy_to_fiscal_year(fy: int) -> str:
    """
    Convert the panel's `fy` key into a label. Example: 2024 -> "FY2023-24".
    """
    return f"FY{fy - 1}-{str(fy)[-2:]}"


# ==============================================================================
# Custom Exception Class
# ==============================================================================

class SchemaValidationError(ValueError):
    """
    Raised when a BRSRRow instance fails domain validation constraints.

    Inherits from ValueError to maintain standard Python exception ergonomics while
    providing clear error diagnostics identifying the company, year, and principle.
    """
    pass


# ==============================================================================
# Data Model: BRSRRow
# ==============================================================================

@dataclass
class BRSRRow:
    company_id: str
    company_name: str
    sector: str
    fiscal_year: str
    principle_number: int
    indicator_type: str
    section_text: str
    source_type: str
    source_url_or_filepath: str
    extraction_date: str
    extraction_method: str
    prowess_industry: str = ""
    nic_code: str = ""
    # Panel join key: Prowess company code. 0 = not set (legacy pilot rows).
    co_code: int = 0
    # Panel join key: calendar year of the 31-March year-end (FY2023-24 -> 2024). 0 = not set.
    fy: int = 0

    def __post_init__(self):
        """
        Post-initialization validation hook executed automatically upon instance creation.
        Enforces integrity rules and aggregates all validation violations into a single diagnostic error.
        """
        errors = []

        # Rule 1: Principle number must strictly fall within SEBI NGRBC scope (1 to 9)
        if self.principle_number not in VALID_PRINCIPLES:
            errors.append(f"principle_number={self.principle_number} not in 1-9")

        # Rule 2: Indicator type must match one of the two SEBI disclosure tiers
        if self.indicator_type not in VALID_INDICATOR_TYPES:
            errors.append(f"indicator_type={self.indicator_type!r} invalid (must be 'Essential' or 'Leadership')")

        # Rule 3: Source type must be one of the supported extraction inputs
        if self.source_type not in VALID_SOURCE_TYPES:
            errors.append(f"source_type={self.source_type!r} invalid (must be 'XBRL' or 'PDF')")

        # Rule 4: Extraction method must reflect valid pipeline provenance states
        if self.extraction_method not in VALID_EXTRACTION_METHODS:
            errors.append(f"extraction_method={self.extraction_method!r} invalid (must be 'automated' or 'manual-checked')")

        # Rule 5: Extracted text must not be empty or purely whitespace.
        # If a company omitted a principle, the pipeline should log a gap rather than creating a dummy row.
        if not self.section_text or not self.section_text.strip():
            errors.append("section_text is empty -- log a disclosure gap, do not write an empty row")

        # Rule 6: Primary key constraint -- company_id cannot be blank
        if not self.company_id.strip():
            errors.append("company_id is empty -- pipeline cannot proceed without a unique corporate identifier")

        # Rule 7: Panel join keys. Both must be set together, and must agree with fiscal_year.
        # Legacy pilot rows leave both at 0, which is accepted so old CSVs still load.
        if self.co_code or self.fy:
            if self.co_code <= 0:
                errors.append(f"co_code={self.co_code} must be a positive Prowess code when fy is set")
            if self.fy not in VALID_FY_RANGE:
                errors.append(f"fy={self.fy} outside panel range {VALID_FY_RANGE.start}-{VALID_FY_RANGE.stop - 1}")
            else:
                try:
                    expected_fy = fiscal_year_to_fy(self.fiscal_year)
                    if self.fy != expected_fy:
                        errors.append(f"fy={self.fy} does not match fiscal_year={self.fiscal_year!r} (expected {expected_fy})")
                except ValueError as exc:
                    errors.append(str(exc))

        # If any validation errors accumulated, abort by raising SchemaValidationError with detailed context
        if errors:
            raise SchemaValidationError(
                f"[{self.company_id} {self.fiscal_year} Principle {self.principle_number}] "
                + "; ".join(errors)
            )


# Dynamically derive the ordered CSV column names directly from the dataclass fields
CSV_FIELDNAMES = [f.name for f in fields(BRSRRow)]


# ==============================================================================
# I/O Helper Functions
# ==============================================================================

def write_rows_csv(rows: list[BRSRRow], path: str | Path) -> None:
    """
    Serializes a collection of validated BRSRRow objects into a UTF-8 encoded CSV file.

    Parameters:
        rows: List of BRSRRow instances to export.
        path: Filepath where the CSV will be written. Parent directories are created automatically.
    """
    path = Path(path)
    # Ensure the target directory structure exists prior to file creation
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def append_row_jsonl(row: BRSRRow, path: str | Path) -> None:
    """
    Appends a single BRSRRow instance to an append-only JSON Lines archive.

    Why JSONL?
    - Preserves embedded line breaks and raw formatting in `section_text` without CSV quoting risks.
    - Enables incremental, crash-safe data streaming during large extraction batches.
    - Functions as an immutable raw ledger that is never rewritten in place.

    Parameters:
        row: Validated BRSRRow instance to append.
        path: Target .jsonl file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as f:
        # ensure_ascii=False ensures Indian currency symbols, devanagari characters,
        # and special typography are stored cleanly in native UTF-8.
        f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def load_rows_csv(path: str | Path) -> list[BRSRRow]:
    """
    Loads and re-validates BRSRRow instances from a previously saved CSV file.

    Parameters:
        path: Filepath to the CSV file to ingest.

    Returns:
        List of instantiated and validated BRSRRow objects.
    """
    path = Path(path)
    rows = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Type cast principle_number from string back to integer before validation
            r["principle_number"] = int(r["principle_number"])
            # Panel keys: legacy CSVs lack these columns or leave them blank, so default to 0.
            r["co_code"] = int(r.get("co_code") or 0)
            r["fy"] = int(r.get("fy") or 0)
            rows.append(BRSRRow(**r))
    return rows


# ==============================================================================
# Standalone Smoke Test Entry Point
# ==============================================================================

if __name__ == "__main__":
    """
    Smoke test: verifies dataclass instantiation, validation enforcement,
    and CSV serialization by creating a sample validated row.
    """
    print("Executing schema.py smoke test...")
    sample = BRSRRow(
        company_id="INE009A01021",
        company_name="Infosys Limited",
        sector="IT Services & Consulting",
        fiscal_year="FY2023-24",
        principle_number=6,
        indicator_type="Essential",
        section_text="Sample verbatim text from Section C, Principle 6 regarding environmental stewardship...",
        source_type="PDF",
        source_url_or_filepath="data/raw/filings/Infosys-BRSR.pdf",
        extraction_date="2026-09-25",
        extraction_method="automated",
        co_code=100632,   # Infosys, from sample_list.csv
        fy=fiscal_year_to_fy("FY2023-24"),
    )

    # Helper round-trip checks
    assert fiscal_year_to_fy("FY2024-25") == 2025
    assert fy_to_fiscal_year(2024) == "FY2023-24"
    assert fiscal_year_to_fy(fy_to_fiscal_year(2026)) == 2026

    # Mismatched fy must be rejected (fail-loud)
    try:
        BRSRRow(**{**asdict(sample), "fy": 2025})
    except SchemaValidationError:
        pass
    else:
        raise AssertionError("fy/fiscal_year mismatch was not rejected")

    # Write test output to verify directory creation and file serialization
    test_output_file = "data/raw/_smoke_test.csv"
    write_rows_csv([sample], test_output_file)
    print(f"Validation succeeded. Wrote verified smoke test sample to {test_output_file}")
