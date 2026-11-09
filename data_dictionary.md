# BRSR Pilot Corpus — Data Dictionary

## Overview
This document defines the schema, field specifications, data validation rules, and constraints for the Business Responsibility and Sustainability Reporting (BRSR) corpus. Every script in the extraction, cleaning, and analysis pipeline must conform strictly to this specification via `schema.py` (`BRSRRow`).

Each record in the dataset represents a single `(company_id, fiscal_year, principle_number, indicator_type)` unit.

---

## Field Specifications (Canonical Schema)

| # | Field Name | Data Type | Nullable | Allowed / Expected Values | Description & Integrity Rules |
|---|------------|-----------|:--------:|---------------------------|-------------------------------|
| 1 | `company_id` | `str` | **No** | 12-char ISIN (e.g., `INE009A01021`) | Primary security/company identifier. ISIN is strongly preferred for unambiguous cross-database joins. |
| 2 | `company_name` | `str` | **No** | Full legal entity name (e.g., `Infosys Limited`) | Official registered company name matching regulatory filings. |
| 3 | `sector` | `str` | **No** | Sector / Industry classification | Broad industry classification aligned with Prowess or National Industrial Classification (NIC). |
| 4 | `fiscal_year` | `str` | **No** | Format: `FY<YYYY>-<YY>` (e.g., `FY2024-25`) | The fiscal reporting period covered by the disclosure, **not** the extraction or publication date. |
| 5 | `principle_number`| `int` | **No** | Integer `1` through `9` | National Guidelines on Responsible Business Conduct (NGRBC) principle index (P1 to P9). |
| 6 | `indicator_type` | `str` | **No** | `"Essential"`, `"Leadership"` | SEBI disclosure tier. Essential indicators are mandatory; Leadership indicators are voluntary/aspirational. |
| 7 | `section_text` | `str` | **No** | Non-empty verbatim text string | Raw, uncleaned narrative extracted directly from the source filing. **Must remain immutable once written.** Cleaning occurs strictly downstream. |
| 8 | `source_type` | `str` | **No** | `"XBRL"`, `"PDF"` | The underlying document format from which this row was extracted. Enables error-rate stratification across formats. |
| 9 | `source_url_or_filepath` | `str` | **No** | Relative path or valid URL | Reproducibility trail: relative file path (e.g. `data/raw/filings/Infosys-BRSR.pdf`) or permanent filing URL. |
| 10 | `extraction_date` | `str` | **No** | ISO 8601 Date: `YYYY-MM-DD` | Date the extraction script executed. Useful for tracking versioning and pipeline iterations. |
| 11 | `extraction_method` | `str` | **No** | `"automated"`, `"manual-checked"` | Extraction provenance. Rows visually verified by an analyst against the source PDF are tagged `manual-checked`. |
| 12 | `prowess_industry` | `str` | Yes | Prowess industry group description | Prowess granular industry name. |
| 13 | `nic_code` | `str` | Yes | 5-digit National Industrial Classification | NIC 2008 code for cross-sector normalization. |
| 14 | `co_code` | `int` | Yes | Positive integer (e.g., `100632`) | Prowess company code. Primary key for joining to `panel_firmyear.csv`. |
| 15 | `fy` | `int` | Yes | Calendar year of 31-March end (`2020`–`2026`) | Financial year key matching `panel_firmyear.csv` (e.g. `2024` = FY2023-24). |

---

## NGRBC Principles Reference (1–9)

Under SEBI's BRSR framework (Section C), disclosures are organized by the nine principles of the National Guidelines on Responsible Business Conduct:
- **P1:** Businesses should conduct and govern themselves with integrity, and in a manner that is Ethical, Transparent, and Accountable.
- **P2:** Businesses should provide goods and services in a manner that is sustainable and safe.
- **P3:** Businesses should respect and promote the well-being of all employees, including those in their value chains.
- **P4:** Businesses should respect the interests of and be responsive to all stakeholders.
- **P5:** Businesses should respect and promote human rights.
- **P6:** Businesses should respect and make efforts to protect and restore the environment.
- **P7:** Businesses, when engaging in influencing public and regulatory policy, should do so in a manner that is responsible and transparent.
- **P8:** Businesses should promote inclusive growth and equitable development.
- **P9:** Businesses should engage with and provide value to their consumers in a responsible manner.

---

## Validation & Invariant Rules

1. **Immutability of `section_text`:**
   - Raw extraction logic must never perform lossy transformations (lowercasing, punctuation stripping, regex replacement) on `section_text`.
   - Downstream normalization and cleaning must write to separate columns or distinct files (e.g., `data/processed/pilot_corpus_clean.csv`).
2. **Fail-Loud Validation:**
   - `schema.BRSRRow.__post_init__` validates all values immediately upon instantiation. Any row with an empty `company_id`, empty `section_text`, out-of-range `principle_number` (not 1–9), or invalid enum raises `SchemaValidationError`.
   - Missing disclosure sections must be logged as gaps/exceptions in QA logs, never written as blank placeholder rows.
3. **Storage Formats:**
   - **Raw Archive:** `data/raw/pilot_corpus.jsonl` — Append-only JSON Lines format (UTF-8) preserving complete raw line breaks and formatting.
   - **Processed Dataset:** `data/processed/pilot_corpus_clean.csv` — Delimited dataset with cleaned text, token counts, and QA flags.

