"""
generate_manifest.py
Automated Manifest Generator for SEBI BRSR Study Cohorts.

Reads Prowess panel_firmyear.csv and sample_list.csv, filters to the target
cohort (Top-150 / Top-250 / Top-500 / Top-1000) for specified fiscal years (FY2023–26),
checks local disk for existing filings (both standardized and legacy pilot names),
and exports the expanded manifest (e.g. manifest_top150.csv) with join keys (co_code, fy).

Usage:
    python generate_manifest.py --cohort top150 --output manifest_top150.csv
    python generate_manifest.py --cohort top250 --output manifest_top250.csv
"""

import argparse
from pathlib import Path
import pandas as pd
from schema import fy_to_fiscal_year

PANEL_PATH = Path("data/Panel/panel_firmyear.csv")
SAMPLE_PATH = Path("data/Panel/sample_list.csv")
FILINGS_DIR = Path("data/raw/filings")

# Known pilot file aliases for FY2024-25 (fy=2025)
PILOT_FILE_ALIASES = {
    ("INE009A01021", 2025): {
        "xbrl": FILINGS_DIR / "Infosys.xml",
        "pdf": FILINGS_DIR / "Infosys-BRSR.pdf",
    },
    ("INE467B01029", 2025): {
        "xbrl": FILINGS_DIR / "TCS.xml",
        "pdf": FILINGS_DIR / "TCS_BRSR.pdf",
    },
    ("INE669C01036", 2025): {
        "xbrl": FILINGS_DIR / "Tech_Mahindra.xml",
        "pdf": FILINGS_DIR / "techMahindra-BRSR.pdf",
    },
    ("INE949L01017", 2025): {
        "xbrl": FILINGS_DIR / "AU_Bank.xml",
        "pdf": FILINGS_DIR / "AU_BANK_BRSR-2025.pdf",
    },
    ("INE073K01018", 2025): {
        "xbrl": FILINGS_DIR / "Sonacoms.xml",
        "pdf": FILINGS_DIR / "Sonacoms.pdf",
    },
}


def build_manifest(
    cohort: str = "top150",
    years: list[int] | None = None,
    output_path: str = "manifest_top150.csv",
) -> pd.DataFrame:
    if years is None:
        years = [2023, 2024, 2025, 2026]

    cohort_col = f"{cohort}_fyend"
    print(f"Generating manifest for cohort='{cohort}' ({cohort_col}) across years={years}...")

    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Master panel not found at {PANEL_PATH}")

    panel = pd.read_csv(PANEL_PATH, low_memory=False)
    sample = pd.read_csv(SAMPLE_PATH) if SAMPLE_PATH.exists() else None

    # Filter to cohort and years
    if cohort_col not in panel.columns:
        raise ValueError(f"Cohort column '{cohort_col}' not found in panel.")

    mask = (panel["fy"].isin(years)) & (panel[cohort_col] == 1)
    cohort_df = panel[mask].copy()

    # Sort deterministically by fy, then mcap_rank
    cohort_df = cohort_df.sort_values(by=["fy", "mcap_rank", "company_name"]).reset_index(drop=True)

    manifest_rows = []
    FILINGS_DIR.mkdir(parents=True, exist_ok=True)

    for _, row in cohort_df.iterrows():
        co_code = int(row["co_code"])
        fy = int(row["fy"])
        fiscal_year = str(row.get("fy_label") or fy_to_fiscal_year(fy))
        isin = str(row["isin"]).strip() if pd.notna(row["isin"]) else ""
        company_name = str(row["company_name"]).strip()
        bse_scrip = str(int(row["bse_scrip_code"])) if pd.notna(row.get("bse_scrip_code")) else ""
        nse_symbol = str(row["nse_symbol"]).strip() if pd.notna(row.get("nse_symbol")) else ""
        sector = str(row["industry_name"]).strip() if pd.notna(row.get("industry_name")) else ""
        nic_raw = pd.to_numeric(row.get("nic_code"), errors="coerce")
        nic_code = str(int(nic_raw)) if pd.notna(nic_raw) else ""
        mcap_rank = row.get("mcap_rank", "")

        # Standard file paths
        std_xbrl = FILINGS_DIR / f"{isin}_{fy}.xml"
        std_pdf = FILINGS_DIR / f"{isin}_{fy}.pdf"

        # Check aliases or standard names on disk
        alias = PILOT_FILE_ALIASES.get((isin, fy), {})
        xbrl_target = alias.get("xbrl") if (alias.get("xbrl") and alias.get("xbrl").exists()) else std_xbrl
        pdf_target = alias.get("pdf") if (alias.get("pdf") and alias.get("pdf").exists()) else std_pdf

        xbrl_found = xbrl_target.exists()
        pdf_found = pdf_target.exists()

        status = "ready" if (xbrl_found or pdf_found) else "pending_download"
        if not (xbrl_found or pdf_found):
            notes = "Filing pending retrieval"
        elif (isin, fy) in PILOT_FILE_ALIASES:
            notes = "Pilot filing locally available"
        else:
            notes = "Downloaded from NSE BRSR portal"

        manifest_rows.append({
            "co_code": co_code,
            "fy": fy,
            "fiscal_year": fiscal_year,
            "company_id": isin,
            "company_name": company_name,
            "sector": sector,
            "prowess_industry": sector,
            "nic_code": nic_code,
            "bse_scrip_code": bse_scrip,
            "nse_symbol": nse_symbol,
            "mcap_rank": mcap_rank,
            "xbrl_url_or_path": str(xbrl_target),
            "xbrl_found": "TRUE" if xbrl_found else "FALSE",
            "pdf_url_or_path": str(pdf_target),
            "pdf_found": "TRUE" if pdf_found else "FALSE",
            "status": status,
            "notes": notes,
        })

    manifest_df = pd.DataFrame(manifest_rows)
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_df.to_csv(out_file, index=False, encoding="utf-8")

    print(f"\n[OK] Successfully wrote {len(manifest_df)} rows to {out_file}")
    print("\n--- Manifest Summary by Fiscal Year ---")
    summary = manifest_df.groupby("fy").agg(
        firms=("co_code", "count"),
        xbrl_present=("xbrl_found", lambda x: (x == "TRUE").sum()),
        pdf_present=("pdf_found", lambda x: (x == "TRUE").sum()),
        ready_for_extraction=("status", lambda s: (s == "ready").sum()),
    ).reset_index()
    print(summary.to_string(index=False))
    print(f"\nUnique companies across all years: {manifest_df['co_code'].nunique()}")

    return manifest_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate BRSR study manifest from Prowess panel.")
    parser.add_argument("--cohort", default="top150", choices=["top150", "top250", "top500", "top1000"],
                        help="Cohort selection flag in panel (default: top150)")
    parser.add_argument("--years", default="2023,2024,2025,2026",
                        help="Comma-separated fiscal years (default: 2023,2024,2025,2026)")
    parser.add_argument("--output", default="manifest_top150.csv",
                        help="Output manifest CSV path (default: manifest_top150.csv)")
    args = parser.parse_args()

    parsed_years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    build_manifest(cohort=args.cohort, years=parsed_years, output_path=args.output)
