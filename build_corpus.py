"""
build_corpus.py
Batch Extractor: Ingests filings from manifest (manifest_top150.csv or pilot_manifest.csv),
runs Section C extraction across PDF and/or XBRL modalities,
attaches panel primary keys (co_code, fy),
validates each row with BRSRRow schema, and writes to both:
- data/raw/corpus.jsonl (immutable append-only raw ledger)
- data/raw/corpus.csv   (standard raw tabular dataset)

Supports:
    --manifest [path] : Path to manifest CSV (default: manifest_top150.csv if exists, else pilot_manifest.csv)
    --source [pdf|xbrl|dual] : Extract from PDF (with table separation), XBRL, or both (default: dual).
    --table-mode [serialized|prose_only|raw] : PDF table handling strategy (default: serialized).
    --output-csv [path] : Path for output CSV.
    --output-jsonl [path] : Path for output JSONL.
"""

import argparse
import csv
from datetime import date
from pathlib import Path

from schema import BRSRRow, write_rows_csv, append_row_jsonl, fiscal_year_to_fy
from pdf_section_extractor import (
    extract_page_texts,
    find_section_c_boundaries,
    split_by_principle,
)
from xbrl_section_c_extractor import BRSRXBRLExtractor


def run_batch_extraction(
    manifest_path: str | Path,
    source_modality: str = "dual",
    table_mode: str = "serialized",
    output_csv: str | Path = "data/raw/pilot_corpus.csv",
    output_jsonl: str | Path = "data/raw/pilot_corpus.jsonl",
):
    manifest_path = Path(manifest_path)
    output_csv = Path(output_csv)
    output_jsonl = Path(output_jsonl)

    if not manifest_path.exists():
        print(f"[!] Manifest '{manifest_path}' not found.")
        return

    # Clear previous run files if re-running
    if output_jsonl.exists():
        output_jsonl.unlink()

    with manifest_path.open(encoding="utf-8") as f:
        manifest_rows = list(csv.DictReader(f))

    all_validated_rows: list[BRSRRow] = []
    today_iso = date.today().isoformat()

    print("=" * 70)
    print("BRSR Batch Corpus Extraction Engine")
    print("=" * 70)
    print(f"Manifest     : {manifest_path} ({len(manifest_rows)} manifest entries)")
    print(f"Modality     : {source_modality.upper()}")
    print(f"Table Mode   : {table_mode}")
    print(f"Output CSV   : {output_csv}")
    print(f"Output JSONL : {output_jsonl}\n")

    processed_firms = 0
    skipped_firms = 0

    for m in manifest_rows:
        company_id = m.get("company_id", "").strip()
        company_name = m.get("company_name", "").strip()
        sector = m.get("sector", "").strip()
        fiscal_year = m.get("fiscal_year", "").strip()
        nic_code = m.get("nic_code", "").strip()
        prowess_industry = m.get("prowess_industry", sector).strip()

        # Parse panel keys
        try:
            co_code = int(m.get("co_code") or 0)
        except (ValueError, TypeError):
            co_code = 0

        try:
            fy = int(m.get("fy") or (fiscal_year_to_fy(fiscal_year) if fiscal_year else 0))
        except (ValueError, TypeError):
            fy = 0

        pdf_path = m.get("pdf_url_or_path", "").strip()
        xbrl_path = m.get("xbrl_url_or_path", "").strip()

        pdf_exists = bool(pdf_path and Path(pdf_path).exists())
        xbrl_exists = bool(xbrl_path and Path(xbrl_path).exists())

        if not (pdf_exists or xbrl_exists):
            # Filing not downloaded yet; skip silently or log
            skipped_firms += 1
            continue

        processed_firms += 1
        firm_label = f"[{company_id} | co_code={co_code} | {fiscal_year}] {company_name}"
        print(f"--> Processing: {firm_label}")

        # ----------------------------------------------------------------------
        # Modality A: PDF Extraction (with Table Separation & Serialization)
        # ----------------------------------------------------------------------
        if source_modality in ("pdf", "dual"):
            if not pdf_exists:
                print(f"    [PDF] File '{pdf_path}' not found locally. Skipping PDF.")
            else:
                try:
                    pages = extract_page_texts(pdf_path, table_mode=table_mode)
                    start_p, end_p = find_section_c_boundaries(pages)

                    if start_p is None:
                        print(f"    [!] Section C not located in PDF for {company_name}.")
                    else:
                        total_tables = sum(p.num_tables for p in pages)
                        print(f"    [PDF] Section C: pages {start_p}-{end_p} (Total {len(pages)} pages | {total_tables} bounded tables)")
                        principles = split_by_principle(pages, start_p, end_p)

                        pdf_count = 0
                        for pnum, ind_dict in sorted(principles.items()):
                            for ind_type in ("Essential", "Leadership"):
                                text = ind_dict.get(ind_type, "").strip()
                                if not text:
                                    continue

                                try:
                                    row = BRSRRow(
                                        company_id=company_id,
                                        company_name=company_name,
                                        sector=sector,
                                        fiscal_year=fiscal_year,
                                        principle_number=pnum,
                                        indicator_type=ind_type,
                                        section_text=text,
                                        source_type="PDF",
                                        source_url_or_filepath=pdf_path,
                                        extraction_date=today_iso,
                                        extraction_method="automated",
                                        co_code=co_code,
                                        fy=fy,
                                        nic_code=nic_code,
                                        prowess_industry=prowess_industry,
                                    )
                                    append_row_jsonl(row, output_jsonl)
                                    all_validated_rows.append(row)
                                    pdf_count += 1
                                except Exception as e:
                                    print(f"    [!] PDF Row validation error (P{pnum} {ind_type}): {e}")

                        print(f"    [PDF] Extracted & validated {pdf_count} rows.")
                except Exception as e:
                    print(f"    [!] PDF Extraction failure for {company_name}: {e}")

        # ----------------------------------------------------------------------
        # Modality B: XBRL Extraction (Native Structured Tags & Zero Table Bleed)
        # ----------------------------------------------------------------------
        if source_modality in ("xbrl", "dual"):
            if not xbrl_exists:
                print(f"    [XBRL] File '{xbrl_path}' not found locally. Skipping XBRL.")
            else:
                try:
                    extractor = BRSRXBRLExtractor(xbrl_path)
                    xbrl_rows = extractor.to_brsr_rows(
                        company_id=company_id,
                        company_name=company_name,
                        sector=sector,
                        fiscal_year=fiscal_year,
                        extraction_date=today_iso,
                        co_code=co_code,
                        fy=fy,
                        nic_code=nic_code,
                        prowess_industry=prowess_industry,
                    )
                    for row in xbrl_rows:
                        append_row_jsonl(row, output_jsonl)
                        all_validated_rows.append(row)
                    print(f"    [XBRL] Extracted & validated {len(xbrl_rows)} structured rows (Contexts: {len(extractor.contexts)}).")
                except Exception as e:
                    print(f"    [!] XBRL Extraction error for {company_name}: {e}")

    # Write out combined CSV dataset
    if all_validated_rows:
        write_rows_csv(all_validated_rows, output_csv)
        print("\n" + "=" * 70)
        print(f"Corpus Generation Succeeded!")
        print(f"  Processed filings : {processed_firms}")
        print(f"  Pending filings   : {skipped_firms}")
        print(f"  Total valid rows  : {len(all_validated_rows)}")
        print(f"  CSV Output        : {output_csv}")
        print(f"  JSONL Ledger      : {output_jsonl}")
        print("=" * 70)
    else:
        print("[!] No rows were extracted. Ensure filings exist in data/raw/filings/.")


if __name__ == "__main__":
    default_manifest = "manifest_top150.csv" if Path("manifest_top150.csv").exists() else "pilot_manifest.csv"

    parser = argparse.ArgumentParser(description="Batch Extractor for BRSR Filings (PDF & XBRL).")
    parser.add_argument(
        "--manifest",
        default=default_manifest,
        help=f"Path to manifest CSV file (default: {default_manifest})"
    )
    parser.add_argument(
        "--source",
        choices=["pdf", "xbrl", "dual"],
        default="dual",
        help="Source modality: 'pdf', 'xbrl', or 'dual' (default: dual)."
    )
    parser.add_argument(
        "--table-mode",
        choices=["serialized", "prose_only", "raw"],
        default="serialized",
        help="PDF table handling: 'serialized' (default), 'prose_only', or 'raw'."
    )
    parser.add_argument(
        "--output-csv",
        default="data/raw/pilot_corpus.csv",
        help="Path for output CSV dataset (default: data/raw/pilot_corpus.csv)"
    )
    parser.add_argument(
        "--output-jsonl",
        default="data/raw/pilot_corpus.jsonl",
        help="Path for output JSONL ledger (default: data/raw/pilot_corpus.jsonl)"
    )
    args = parser.parse_args()

    run_batch_extraction(
        manifest_path=args.manifest,
        source_modality=args.source,
        table_mode=args.table_mode,
        output_csv=args.output_csv,
        output_jsonl=args.output_jsonl,
    )
