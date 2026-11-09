"""
scrape_nse_brsr.py
Automated Harvester & Scraper for SEBI BRSR Filings from NSE India.

Target Portal:
    https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports
Underlying Endpoint:
    https://www.nseindia.com/api/corporate-bussiness-sustainabilitiy?from_date=DD-MM-YYYY&to_date=DD-MM-YYYY

Features:
    - Session handshake & cookie priming (handles Akamai bot mitigations).
    - Multi-year filing catalog indexing (FY2023, FY2024, FY2025, FY2026).
    - Local JSON catalog caching in data/qa/ to avoid unnecessary exchange queries.
    - Automatic alias resolution for corporate symbols (e.g. TMPV -> TATAMOTORS, LTM -> LTIM).
    - Streaming download of XBRL (.xml) and optional PDF filings into data/raw/filings/.
    - Strict validation: parses XML with xml.etree.ElementTree and validates PDF magic bytes.
    - Automatic manifest synchronization: updates manifest_top150.csv in place.
    - Full audit trail logging in data/qa/download_log.csv.

Usage:
    # Preview pending downloads without network requests:
    python scrape_nse_brsr.py --dry-run --fy 2024

    # Download 5 XBRL filings for FY 2024:
    python scrape_nse_brsr.py --fy 2024 --limit 5

    # Download a single company by NSE symbol:
    python scrape_nse_brsr.py --symbol INFY --fy 2024

    # Download all missing Top-150 XBRL filings for FY 2024:
    python scrape_nse_brsr.py --fy 2024
"""

import argparse
import csv
import json
from pathlib import Path
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Default directories
FILINGS_DIR = Path("data/raw/filings")
QA_DIR = Path("data/qa")
DOWNLOAD_LOG_PATH = QA_DIR / "download_log.csv"
DEFAULT_MANIFEST = Path("manifest_top150.csv")

BASE_URL = "https://www.nseindia.com"
PORTAL_URL = f"{BASE_URL}/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports"
API_URL = f"{BASE_URL}/api/corporate-bussiness-sustainabilitiy"

# Known corporate symbol mapping differences between Prowess and NSE
SYMBOL_ALIASES = {
    "TMPV": "TATAMOTORS",        # Tata Motors Passenger Vehicles -> Tata Motors
    "LTM": "LTIM",               # LTIMindtree
    "ABBOTINDIA": "ABBOTT",      # Abbott India
    "BAJAJ-AUTO": "BAJAJ-AUTO",
    "M&M": "M&M",
}


def get_nse_session() -> requests.Session:
    """Creates a requests Session configured to pass Akamai WAF checks on NSE India."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    session.headers.update(headers)

    print("Initializing NSE session & priming cookies...")
    try:
        resp = session.get(PORTAL_URL, timeout=30)
        if resp.status_code != 200:
            print(f"[!] Warning: Initial portal connection returned HTTP {resp.status_code}")
    except Exception as e:
        print(f"[!] Initial connection warning: {e}. Retrying via root domain...")
        session.get(BASE_URL, timeout=30)

    time.sleep(1.5)

    # Update headers for subsequent AJAX / JSON API requests
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Referer": PORTAL_URL,
        "X-Requested-With": "XMLHttpRequest",
    })

    return session


def fetch_nse_brsr_catalog(session: requests.Session, fy: int, use_cache: bool = True) -> list[dict]:
    """
    Fetches the full BRSR filings catalog for a given fiscal year.
    Caches results in data/qa/nse_catalog_{fy}.json.
    """
    QA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = QA_DIR / f"nse_catalog_{fy}.json"

    if use_cache and cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"[Cache] Loaded {len(data)} filings for FY{fy} from {cache_path}")
                return data
        except Exception:
            pass

    # SEBI BRSR filings for fiscal year T (ending March 31, T) are submitted between
    # April 1, T and March 31, T+1.
    from_date = f"01-04-{fy}"
    to_date = f"31-03-{fy + 1}"
    params = {"from_date": from_date, "to_date": to_date}

    print(f"[API] Querying NSE BRSR feed for FY{fy} (Window: {from_date} to {to_date})...")
    time.sleep(1.5)
    resp = session.get(API_URL, params=params, timeout=35)

    if resp.status_code != 200:
        # Fallback to calendar year if financial year window returned error
        cal_params = {"from_date": f"01-01-{fy}", "to_date": f"31-12-{fy}"}
        time.sleep(1.5)
        resp = session.get(API_URL, params=cal_params, timeout=35)
        if resp.status_code != 200:
            print(f"[!] Failed to fetch NSE catalog for FY{fy}: HTTP {resp.status_code}")
            return []

    try:
        json_data = resp.json()
        filings = json_data.get("data", [])
    except Exception as e:
        print(f"[!] Failed to decode JSON for FY{fy}: {e}")
        return []

    print(f"[API] Retrieved {len(filings)} corporate filings for FY{fy}")
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(filings, f, indent=2)

    return filings


def validate_file(file_path: Path, source_type: str) -> bool:
    """Verifies that the downloaded file is intact, valid XML, or valid PDF."""
    if not file_path.exists() or file_path.stat().st_size < 500:
        return False

    if source_type == "xbrl":
        try:
            ET.parse(file_path)
            return True
        except ET.ParseError:
            return False
    elif source_type == "pdf":
        try:
            with file_path.open("rb") as f:
                header = f.read(5)
                return header.startswith(b"%PDF-")
        except Exception:
            return False
    return True


def log_download_result(
    co_code: int,
    company_id: str,
    fy: int,
    source_type: str,
    status: str,
    file_path: str,
    message: str = "",
):
    QA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = DOWNLOAD_LOG_PATH.exists()

    with DOWNLOAD_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "co_code", "company_id", "fy", "source_type", "status", "file_path", "message"],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "co_code": co_code,
            "company_id": company_id,
            "fy": fy,
            "source_type": source_type,
            "status": status,
            "file_path": file_path,
            "message": message,
        })


def build_catalog_index(filings: list[dict]) -> dict[str, dict]:
    """Indexes NSE filings by uppercase symbol and clean company name."""
    index = {}
    for f in filings:
        sym = f.get("symbol", "").strip().upper()
        if sym:
            # If multiple revisions exist, keep the latest or one with an XBRL file
            if sym not in index or (not index[sym].get("xbrlFile") and f.get("xbrlFile")):
                index[sym] = f

        cname = re.sub(r"[^A-Z0-9]", "", f.get("companyName", "").upper())
        if cname and cname not in index:
            index[cname] = f

    return index


def update_manifest_file(manifest_path: Path, updated_records: dict[tuple[str, int], dict]):
    """Updates manifest CSV in place with newly downloaded filings."""
    if not manifest_path.exists():
        return

    with manifest_path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    updated_count = 0
    for r in rows:
        isin = r.get("company_id", "").strip()
        fy = int(r.get("fy", 0))
        key = (isin, fy)

        if key in updated_records:
            upd = updated_records[key]
            if "xbrl_path" in upd:
                r["xbrl_url_or_path"] = upd["xbrl_path"]
                r["xbrl_found"] = "TRUE"
            if "pdf_path" in upd:
                r["pdf_url_or_path"] = upd["pdf_path"]
                r["pdf_found"] = "TRUE"
            r["status"] = "ready"
            r["notes"] = "Downloaded from NSE BRSR portal"
            updated_count += 1

    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[Manifest] Updated {updated_count} rows in {manifest_path}")


def scrape_nse_brsr(
    manifest_path: str = "manifest_top150.csv",
    target_fy: int | str | list[int] | None = "2024",
    single_symbol: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    download_pdf: bool = False,
    delay: float = 1.0,
    force: bool = False,
):
    FILINGS_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path)

    # Parse target fiscal years
    selected_years = None
    if target_fy is not None:
        if isinstance(target_fy, str):
            if target_fy.lower() in ("all", "*", "any"):
                selected_years = None
            else:
                selected_years = [int(y.strip()) for y in target_fy.split(",") if y.strip().isdigit()]
        elif isinstance(target_fy, int):
            selected_years = [target_fy]
        elif isinstance(target_fy, (list, tuple, set)):
            selected_years = [int(y) for y in target_fy]

    fy_label = "All (FY2023–FY2026)" if selected_years is None else ", ".join(f"FY{y}" for y in selected_years)

    print("=" * 75)
    print("NSE India SEBI BRSR Filing Harvester & Scraper")
    print("=" * 75)
    print(f"Manifest    : {manifest_path}")
    print(f"Target FY   : {fy_label}")
    print(f"Download PDF: {download_pdf}")
    print(f"Dry Run     : {dry_run}\n")

    session = None if dry_run else get_nse_session()

    # Load targets from manifest or single symbol
    targets = []
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as f:
            targets = list(csv.DictReader(f))

    if single_symbol:
        targets = [t for t in targets if t.get("nse_symbol", "").strip().upper() == single_symbol.upper()]
        if not targets:
            # Standalone single symbol target
            def_fy = selected_years[0] if (selected_years and len(selected_years) == 1) else 2024
            targets = [{
                "co_code": 0,
                "company_id": f"NSE_{single_symbol.upper()}",
                "company_name": single_symbol.upper(),
                "nse_symbol": single_symbol.upper(),
                "fy": str(def_fy),
                "fiscal_year": f"FY{def_fy-1}-{str(def_fy)[2:]}",
                "xbrl_url_or_path": str(FILINGS_DIR / f"{single_symbol.upper()}_{def_fy}.xml"),
                "xbrl_found": "FALSE",
            }]

    if selected_years is not None:
        targets = [t for t in targets if int(t.get("fy", 0)) in selected_years]

    print(f"Target count: {len(targets)} firm-year entries")

    # Collect needed fiscal years
    years_needed = sorted(list(set(int(t.get("fy", 0)) for t in targets if t.get("fy"))))
    if not years_needed and target_fy:
        years_needed = [target_fy]

    # Pre-fetch or load catalogs for all needed years
    catalogs = {}
    catalog_indices = {}
    for y in years_needed:
        # In dry run mode, check if cache exists or initialize session if needed
        if dry_run:
            cache_path = QA_DIR / f"nse_catalog_{y}.json"
            if cache_path.exists():
                with cache_path.open("r", encoding="utf-8") as f:
                    catalogs[y] = json.load(f)
            else:
                session = get_nse_session()
                catalogs[y] = fetch_nse_brsr_catalog(session, y)
        else:
            catalogs[y] = fetch_nse_brsr_catalog(session, y)

        catalog_indices[y] = build_catalog_index(catalogs[y])

    # Match and schedule downloads
    matched_downloads = []
    already_present = 0

    for t in targets:
        isin = t.get("company_id", "").strip()
        fy = int(t.get("fy", 0))
        sym = t.get("nse_symbol", "").strip().upper()
        cname = t.get("company_name", "").strip()
        co_code = int(t.get("co_code") or 0)

        # Check standard destinations
        dest_xml = FILINGS_DIR / f"{isin}_{fy}.xml"
        dest_pdf = FILINGS_DIR / f"{isin}_{fy}.pdf"

        if dest_xml.exists() and not force:
            already_present += 1
            continue

        # Symbol resolution
        idx = catalog_indices.get(fy, {})
        filing_info = None

        # 1. Direct symbol match
        if sym in idx:
            filing_info = idx[sym]
        # 2. Known alias match
        elif sym in SYMBOL_ALIASES and SYMBOL_ALIASES[sym] in idx:
            filing_info = idx[SYMBOL_ALIASES[sym]]
        # 3. Clean company name match
        else:
            clean_name = re.sub(r"[^A-Z0-9]", "", cname.upper())
            if clean_name in idx:
                filing_info = idx[clean_name]

        if filing_info:
            matched_downloads.append({
                "target": t,
                "filing": filing_info,
                "dest_xml": dest_xml,
                "dest_pdf": dest_pdf,
            })
        else:
            log_download_result(
                co_code, isin, fy, "xbrl", "not_found_on_nse", str(dest_xml),
                f"No NSE filing found for symbol={sym}, company={cname}"
            )

    print(f"\nSummary:")
    print(f"  Already downloaded locally : {already_present}")
    print(f"  Matched for download on NSE: {len(matched_downloads)}")
    print(f"  Unmatched / missing on NSE : {len(targets) - already_present - len(matched_downloads)}")

    if limit is not None:
        matched_downloads = matched_downloads[:limit]
        print(f"  Execution limit applied   : processing next {len(matched_downloads)} filings")

    if dry_run:
        print("\n[Dry-run completed] Sample matched pending downloads:")
        for item in matched_downloads[:10]:
            t = item["target"]
            f = item["filing"]
            print(f"  - [{t['nse_symbol']} | FY{t['fy']}] {t['company_name']}")
            print(f"      XBRL URL: {f.get('xbrlFile')}")
            if download_pdf:
                print(f"      PDF  URL: {f.get('attachmentFile')}")
        return

    # Execute actual downloads
    print(f"\nStarting download sequence ({len(matched_downloads)} files)...")
    success_count = 0
    updated_records = {}

    for idx, item in enumerate(matched_downloads, start=1):
        t = item["target"]
        f = item["filing"]
        dest_xml = item["dest_xml"]
        dest_pdf = item["dest_pdf"]

        co_code = int(t.get("co_code") or 0)
        isin = t.get("company_id", "").strip()
        fy = int(t.get("fy", 0))
        sym = t.get("nse_symbol", "").strip()
        cname = t.get("company_name", "")

        xbrl_url = f.get("xbrlFile", "").strip()
        pdf_url = f.get("attachmentFile", "").strip()

        print(f"[{idx}/{len(matched_downloads)}] Sourcing {cname} ({sym} | FY{fy})...")

        # 1. Download XBRL
        if xbrl_url:
            try:
                resp = session.get(xbrl_url, timeout=30)
                if resp.status_code == 200 and len(resp.content) > 500:
                    dest_xml.write_bytes(resp.content)
                    if validate_file(dest_xml, "xbrl"):
                        print(f"    [+] Saved XBRL: {dest_xml.name} ({len(resp.content):,} bytes)")
                        log_download_result(co_code, isin, fy, "xbrl", "success", str(dest_xml), xbrl_url)
                        updated_records[(isin, fy)] = {"xbrl_path": str(dest_xml)}
                        success_count += 1
                    else:
                        dest_xml.unlink(missing_ok=True)
                        print(f"    [-] Invalid XML received from {xbrl_url}")
                        log_download_result(co_code, isin, fy, "xbrl", "validation_failed", str(dest_xml))
                else:
                    print(f"    [!] HTTP {resp.status_code} fetching XBRL from {xbrl_url}")
                    log_download_result(co_code, isin, fy, "xbrl", "http_error", str(dest_xml), f"HTTP {resp.status_code}")
            except Exception as e:
                print(f"    [!] Error downloading XBRL: {e}")
                log_download_result(co_code, isin, fy, "xbrl", "download_error", str(dest_xml), str(e))

        # 2. Optionally download PDF
        if download_pdf and pdf_url:
            try:
                resp_pdf = session.get(pdf_url, timeout=40)
                if resp_pdf.status_code == 200 and len(resp_pdf.content) > 500:
                    dest_pdf.write_bytes(resp_pdf.content)
                    if validate_file(dest_pdf, "pdf"):
                        print(f"    [+] Saved PDF : {dest_pdf.name} ({len(resp_pdf.content):,} bytes)")
                        log_download_result(co_code, isin, fy, "pdf", "success", str(dest_pdf), pdf_url)
                        if (isin, fy) in updated_records:
                            updated_records[(isin, fy)]["pdf_path"] = str(dest_pdf)
                    else:
                        dest_pdf.unlink(missing_ok=True)
            except Exception as e:
                print(f"    [!] Error downloading PDF: {e}")

        time.sleep(delay)

    # Synchronize updated manifest
    if updated_records:
        update_manifest_file(manifest_path, updated_records)

    print("\n" + "=" * 75)
    print(f"Scrape completed: {success_count} XBRL filings successfully downloaded & validated.")
    print(f"Provenance logged to: {DOWNLOAD_LOG_PATH}")
    print("=" * 75)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape and harvest SEBI BRSR XBRL reports from NSE India.")
    parser.add_argument("--manifest", default="manifest_top150.csv", help="Path to manifest CSV")
    parser.add_argument("--fy", type=str, default="2024", help="Target fiscal year(s): e.g. 2024, '2023,2024,2025,2026', or 'all'")
    parser.add_argument("--symbol", type=str, default=None, help="Scrape for a specific NSE symbol (e.g. INFY)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of filings to download")
    parser.add_argument("--dry-run", action="store_true", help="Preview matched filings without downloading files")
    parser.add_argument("--download-pdf", action="store_true", help="Also download the matching PDF report")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between requests (default: 1.0)")
    parser.add_argument("--force", action="store_true", help="Re-download even if file exists locally")

    args = parser.parse_args()

    scrape_nse_brsr(
        manifest_path=args.manifest,
        target_fy=args.fy,
        single_symbol=args.symbol,
        limit=args.limit,
        dry_run=args.dry_run,
        download_pdf=args.download_pdf,
        delay=args.delay,
        force=args.force,
    )
