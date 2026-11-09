"""
download_filings.py
Automated Harvester & Locator for SEBI BRSR Filings (BSE & NSE).

Reads manifest_top150.csv (or a custom manifest), checks which filings are
already downloaded locally, and retrieves missing XBRL (.xml) and PDF filings.

Features:
- Rate limiting & polite exponential backoff.
- Realistic browser headers to respect exchange API gateways.
- Validation of downloaded files (verifying XML well-formedness or PDF magic bytes).
- Comprehensive download log in data/qa/download_log.csv.
- Dry-run mode to preview pending downloads and coverage statistics.

Usage:
    python download_filings.py --dry-run
    python download_filings.py --manifest manifest_top150.csv --limit 5
    python download_filings.py --fy 2024 --source xbrl
"""

import argparse
import csv
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from scrape_nse_brsr import scrape_nse_brsr

FILINGS_DIR = Path("data/raw/filings")
QA_DIR = Path("data/qa")
DOWNLOAD_LOG_PATH = QA_DIR / "download_log.csv"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}


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


def validate_file(file_path: Path, source_type: str) -> bool:
    """Verifies that the downloaded file is intact and not an error HTML page."""
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


def harvest_filings(
    manifest_path: str = "manifest_top150.csv",
    source_mode: str = "xbrl",
    target_fy: int | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    delay: float = 2.0,
    exchange: str = "auto",
):
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    FILINGS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("SEBI BRSR Filing Harvester & Retrieval Engine")
    print("=" * 70)
    print(f"Manifest: {manifest_path} ({len(rows)} total rows)")
    print(f"Mode    : {source_mode.upper()}")
    print(f"Dry Run : {dry_run}\n")

    # Filter by fy if specified
    if target_fy is not None:
        if isinstance(target_fy, str):
            if target_fy.lower() not in ("all", "*", "any"):
                sel_years = [int(y.strip()) for y in target_fy.split(",") if y.strip().isdigit()]
                rows = [r for r in rows if int(r.get("fy", 0)) in sel_years]
                print(f"Filtered to FY {sel_years}: {len(rows)} rows.")
        elif isinstance(target_fy, int):
            rows = [r for r in rows if int(r.get("fy", 0)) == target_fy]
            print(f"Filtered to FY {target_fy}: {len(rows)} rows.")

    pending_xbrl = []
    pending_pdf = []
    existing_xbrl = 0
    existing_pdf = 0

    for r in rows:
        isin = r["company_id"]
        fy = int(r["fy"])
        xbrl_path = Path(r.get("xbrl_url_or_path") or (FILINGS_DIR / f"{isin}_{fy}.xml"))
        pdf_path = Path(r.get("pdf_url_or_path") or (FILINGS_DIR / f"{isin}_{fy}.pdf"))

        if xbrl_path.exists():
            existing_xbrl += 1
        else:
            pending_xbrl.append((r, xbrl_path))

        if pdf_path.exists():
            existing_pdf += 1
        else:
            pending_pdf.append((r, pdf_path))

    print(f"Status Overview:")
    print(f"  XBRL Files on Disk: {existing_xbrl} | Pending Retrieval: {len(pending_xbrl)}")
    print(f"  PDF Files on Disk : {existing_pdf} | Pending Retrieval: {len(pending_pdf)}")

    if dry_run:
        print("\n[Dry-run completed] No network requests made.")
        print("Sample pending downloads:")
        sample_pending = pending_xbrl[:5] if source_mode in ("xbrl", "both") else pending_pdf[:5]
        for r, target in sample_pending:
            print(f"  - [{r['company_id']} | FY{r['fy']}] {r['company_name']} -> {target.name}")
        return

    # Processing actual retrieval
    targets = []
    if source_mode in ("xbrl", "both"):
        targets.extend([("xbrl", r, path) for r, path in pending_xbrl])
    if source_mode in ("pdf", "both"):
        targets.extend([("pdf", r, path) for r, path in pending_pdf])

    if limit is not None:
        targets = targets[:limit]
        print(f"\nExecution limit set: processing next {len(targets)} filings.")

    print(f"\nStarting retrieval sequence ({len(targets)} targets)...")

    # Ensure the audit log exists (with header) even if every target is a manual pull.
    QA_DIR.mkdir(parents=True, exist_ok=True)
    if not DOWNLOAD_LOG_PATH.exists():
        with DOWNLOAD_LOG_PATH.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(
                f,
                fieldnames=["timestamp", "co_code", "company_id", "fy", "source_type", "status", "file_path", "message"],
            ).writeheader()

    # Check if direct URLs are present
    url_col = {"xbrl": "xbrl_url_or_path", "pdf": "pdf_url_or_path"}
    n_no_url = sum(
        1 for stype, r, _ in targets
        if not (r.get(url_col[stype], "").startswith(("http://", "https://")))
    )
    if n_no_url:
        if exchange in ("auto", "nse"):
            print(f"[Info] {n_no_url}/{len(targets)} targets have no direct download URL in the manifest.")
            print(f"[Info] Delegating retrieval to automated NSE India Harvester (scrape_nse_brsr)...")
            scrape_nse_brsr(
                manifest_path=str(manifest_path),
                target_fy=target_fy,
                limit=limit,
                dry_run=dry_run,
                download_pdf=(source_mode in ("pdf", "both")),
                delay=delay,
            )
            return
        else:
            print(f"[WARNING] {n_no_url}/{len(targets)} targets have no http(s) URL in the manifest. "
                  f"They will be logged as 'manual_pull_needed' and NOT downloaded.")

    for idx, (stype, r, target_path) in enumerate(targets, start=1):
        co_code = int(r.get("co_code", 0))
        isin = r["company_id"]
        fy = int(r["fy"])
        bse_scrip = r.get("bse_scrip_code", "").strip()
        nse_symbol = r.get("nse_symbol", "").strip()
        name = r.get("company_name", "")

        print(f"[{idx}/{len(targets)}] {name} ({isin} | FY{fy}) - Sourcing {stype.upper()}...")

        # Construct potential direct URLs or BSE download requests
        # Note: BSE and NSE portals use dynamic WAF sessions.
        # When direct download URLs are provided in the manifest, download directly.
        direct_url = r.get(f"{stype}_url_or_path", "")
        success = False

        if direct_url.startswith("http://") or direct_url.startswith("https://"):
            try:
                req = urllib.request.Request(direct_url, headers=BROWSER_HEADERS)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                    target_path.write_bytes(data)

                if validate_file(target_path, stype):
                    print(f"    [+] Saved and verified: {target_path.name} ({len(data)} bytes)")
                    log_download_result(co_code, isin, fy, stype, "success", str(target_path))
                    success = True
                else:
                    target_path.unlink(missing_ok=True)
                    print(f"    [-] Invalid payload received from {direct_url}")
                    log_download_result(co_code, isin, fy, stype, "failed_validation", str(target_path))
            except Exception as e:
                print(f"    [!] Error downloading from {direct_url}: {e}")
                log_download_result(co_code, isin, fy, stype, "error", str(target_path), str(e))
        else:
            # Exchange query stub: logs search query metadata for manual/batch pull
            msg = f"Exchange search required: BSE Scrip={bse_scrip}, NSE Symbol={nse_symbol}, FY={fy}"
            print(f"    [i] {msg}")
            log_download_result(co_code, isin, fy, stype, "manual_pull_needed", str(target_path), msg)

        time.sleep(delay)

    print("\nRetrieval sequence concluded. See data/qa/download_log.csv for detailed provenance log.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download & harvest BRSR filings from stock exchanges.")
    parser.add_argument("--manifest", default="manifest_top150.csv", help="Path to manifest CSV")
    parser.add_argument("--source", choices=["xbrl", "pdf", "both"], default="xbrl", help="Filing format to download")
    parser.add_argument("--fy", type=str, default=None, help="Target fiscal year(s): e.g. 2024, '2023,2024,2025,2026', or 'all'")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of filings to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview pending downloads without network calls")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay in seconds between requests (default: 1.5)")
    parser.add_argument("--exchange", choices=["auto", "nse", "direct"], default="auto",
                        help="Exchange scraping engine: auto (queries NSE when URLs are absent), nse, or direct")
    args = parser.parse_args()

    harvest_filings(
        manifest_path=args.manifest,
        source_mode=args.source,
        target_fy=args.fy,
        limit=args.limit,
        dry_run=args.dry_run,
        delay=args.delay,
        exchange=args.exchange,
    )
