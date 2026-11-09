import re
import sys
from dataclasses import dataclass

# ==============================================================================
# Dual-Backend PDF Extraction Engine Setup
# ==============================================================================

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    try:
        import pypdf
        HAS_PYPDF = True
    except ImportError:
        HAS_PYPDF = False


# ==============================================================================
# Regex Patterns for Boundary Detection & Principle Splitting
# ==============================================================================

# Matches opening heading of Section C
SECTION_C_START = re.compile(
    r"^\s*SECTION\s*[-–—:]*\s*C\b[\s:.\-–—]*(?:PRINCIPLE[\s\-–—]*WISE)?",
    re.IGNORECASE | re.MULTILINE
)

# Anchored to line start so inline prose (e.g. "as an annexure to every contract")
# or table footnotes do not prematurely terminate Section C.
SECTION_C_END_HINTS = re.compile(
    r"^\s*(?:INDEPENDENT\s+ASSURANCE\s+STATEMENT|ANNEXURE\s+[I1V\d]+\b|GLOSSARY\b)",
    re.IGNORECASE | re.MULTILINE
)

# Matches actual NGRBC Principle headers (which always start their description
# with "Businesses" in SEBI BRSR filings, or are immediately followed by
# "Essential Indicators"), ignoring table rows that merely list "Principle 1".
PRINCIPLE_HEADER = re.compile(
    r"^\s*PRINCIPLE\s*[-:–—]?\s*([1-9])\b(?:[\s:.\-–—]*Businesses\b|\s*\n\s*Essential\s+Indicators?\b)",
    re.IGNORECASE | re.MULTILINE
)

ESSENTIAL_HEADER = re.compile(r"^\s*ESSENTIAL\s+INDICATORS?\b", re.IGNORECASE | re.MULTILINE)
LEADERSHIP_HEADER = re.compile(r"^\s*LEADERSHIP\s+INDICATORS?\b", re.IGNORECASE | re.MULTILINE)


# ==============================================================================
# Data Structures
# ==============================================================================

@dataclass
class PageText:
    page_number: int  # 1-indexed
    text: str
    num_tables: int = 0


# ==============================================================================
# Table Detection, Filtering & Deterministic Serialization
# ==============================================================================

def is_obj_in_bbox(obj: dict, bbox: tuple[float, float, float, float]) -> bool:
    """
    Checks if the geometric center of a pdfplumber character or word object
    falls inside a table bounding box (x0, top, x1, bottom).
    """
    cx = (obj["x0"] + obj["x1"]) / 2.0
    cy = (obj["top"] + obj["bottom"]) / 2.0
    x0, top, x1, bottom = bbox
    return x0 <= cx <= x1 and top <= cy <= bottom


def detect_tables_on_page(page) -> list:
    """
    Detects discrete, bounded data tables on a pdfplumber page using line-intersection
    geometry. Excludes full-page decorative layout grids (>70% page height) to ensure
    principle headings and narrative prose sections are never erroneously swallowed.
    """
    tables = page.find_tables()
    if not tables:
        return []

    safe_tables = []
    page_height = page.height
    for t in tables:
        bbox = t.bbox
        # Guard: Data tables in BRSR filings are discrete components (<70% of page height).
        # Multi-column layout grids spanning full pages are handled as narrative prose.
        if (bbox[3] - bbox[1]) > (page_height * 0.70):
            continue
        safe_tables.append(t)

    return safe_tables


def serialize_table_rows(table) -> list[str]:
    """
    Deterministically serializes an extracted table into structured key-value sentences:
        "[Header 1: Value 1] | [Header 2: Value 2] | ..."
    Handles single-level and multi-level (compound) headers to ensure zero column scrambling.
    """
    raw_rows = table.extract()
    if not raw_rows or len(raw_rows) < 2:
        return []

    # Clean cell text
    cleaned_rows = [
        [str(c or "").strip().replace("\n", " ") for c in r]
        for r in raw_rows
    ]

    # Detect multi-level header: row 0 has general categories, row 1 has sub-headers
    r0, r1 = cleaned_rows[0], cleaned_rows[1]
    is_multilevel = (
        len(cleaned_rows) > 2
        and any(r0) and any(r1)
        and sum(1 for c in r1 if any(char.isdigit() for char in c)) == 0  # r1 has no numbers
    )

    if is_multilevel:
        headers = []
        last_top = ""
        for a, b in zip(r0, r1):
            if a:
                last_top = a
            compound = f"{last_top} {b}".strip() if last_top != b else b
            headers.append(compound or f"Column_{len(headers)+1}")
        data_rows = cleaned_rows[2:]
    else:
        headers = [h or f"Column_{idx+1}" for idx, h in enumerate(r0)]
        data_rows = cleaned_rows[1:]

    # Serialize each row deterministically
    serialized = []
    for row in data_rows:
        if not any(row):
            continue  # Skip blank rows
        cells = [
            f"[{h}: {val}]"
            for h, val in zip(headers, row)
            if val  # Omit empty cells
        ]
        if cells:
            serialized.append(" | ".join(cells))

    return serialized


def extract_page_texts(pdf_path: str, table_mode: str = "serialized") -> list[PageText]:
    """
    Extracts text from each PDF page with intelligent table separation.

    Parameters:
        pdf_path: Path to the target PDF document.
        table_mode:
            - 'serialized' (default): Isolates pure prose by filtering out table bounding
              boxes, then appends deterministically serialized key-value rows "[Header: Value]".
            - 'prose_only': Filters out all table regions completely for pure narrative analysis.
            - 'raw': Legacy unseparated page.extract_text() without table boundary detection.

    Returns:
        List of PageText objects containing page numbers and extracted text.
    """
    pages = []

    if HAS_PDFPLUMBER:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                if table_mode == "raw":
                    text = page.extract_text() or ""
                    pages.append(PageText(i, text, num_tables=0))
                    continue

                # Detect table boundaries
                tables = detect_tables_on_page(page)
                num_tables = len(tables)

                if not tables:
                    text = page.extract_text() or ""
                    pages.append(PageText(i, text, num_tables=0))
                    continue

                # Filter out table bounding boxes to extract unpolluted prose
                table_bboxes = [t.bbox for t in tables]
                try:
                    prose_page = page.filter(
                        lambda obj: not any(is_obj_in_bbox(obj, b) for b in table_bboxes)
                    )
                    prose_text = (prose_page.extract_text() or "").strip()
                except Exception:
                    # Fallback to standard extraction if filtering encounters font glyph quirks
                    prose_text = (page.extract_text() or "").strip()

                if table_mode == "prose_only":
                    pages.append(PageText(i, prose_text, num_tables=num_tables))
                else:  # 'serialized' mode
                    # Deterministically serialize tables
                    table_lines = []
                    for t in tables:
                        table_lines.extend(serialize_table_rows(t))

                    if table_lines:
                        structured_tables = "\n".join(table_lines)
                        combined_text = (
                            f"{prose_text}\n\n[Structured Table Disclosures]\n{structured_tables}"
                            if prose_text else structured_tables
                        )
                    else:
                        combined_text = prose_text

                    pages.append(PageText(i, combined_text, num_tables=num_tables))

    elif HAS_PYPDF:
        reader = pypdf.PdfReader(pdf_path)
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageText(i, text, num_tables=0))
    else:
        raise RuntimeError(
            "Neither 'pdfplumber' nor 'pypdf' is installed. "
            "Please install one via: pip install pdfplumber or pip install pypdf"
        )

    return pages


def find_section_c_boundaries(pages: list[PageText]) -> tuple[int | None, int | None]:
    start = end = None

    for p in pages:
        if start is None and SECTION_C_START.search(p.text):
            start = p.page_number
        elif start is not None and end is None and SECTION_C_END_HINTS.search(p.text):
            # If the page itself has no Principle headers/indicators, end on previous page
            if not PRINCIPLE_HEADER.search(p.text) and not LEADERSHIP_HEADER.search(p.text):
                end = max(start, p.page_number - 1)
            else:
                end = p.page_number
            break

    if start is not None and end is None and pages:
        end = pages[-1].page_number

    return start, end


def split_by_principle(pages: list[PageText], start_page: int, end_page: int) -> dict:
    relevant = [p for p in pages if start_page <= p.page_number <= end_page]
    full_text = "\n".join(p.text for p in relevant)

    # Deduplicate principle matches so table cells cannot overwrite a principle
    principle_spans = []
    seen_principles = set()
    for m in PRINCIPLE_HEADER.finditer(full_text):
        pnum = int(m.group(1))
        if pnum not in seen_principles:
            seen_principles.add(pnum)
            principle_spans.append((m.start(), pnum))

    result: dict[int, dict[str, str]] = {}

    for idx, (pos, pnum) in enumerate(principle_spans):
        next_pos = principle_spans[idx + 1][0] if idx + 1 < len(principle_spans) else len(full_text)
        block = full_text[pos:next_pos]

        ess_m = ESSENTIAL_HEADER.search(block)
        lead_m = LEADERSHIP_HEADER.search(block)

        if ess_m and lead_m and ess_m.start() < lead_m.start():
            essential_text = block[ess_m.end():lead_m.start()].strip()
            leadership_text = block[lead_m.end():].strip()
        elif ess_m:
            essential_text = block[ess_m.end():].strip()
            leadership_text = ""
        elif lead_m:
            essential_text = block[:lead_m.start()].strip()
            leadership_text = block[lead_m.end():].strip()
        else:
            essential_text = block.strip()
            leadership_text = ""

        result[pnum] = {"Essential": essential_text, "Leadership": leadership_text}

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract Section C from BRSR PDF filings.")
    parser.add_argument("pdf_path", help="Path to the BRSR filing PDF.")
    parser.add_argument(
        "--table-mode",
        choices=["serialized", "prose_only", "raw"],
        default="serialized",
        help="Table handling strategy: 'serialized' (default), 'prose_only', or 'raw'."
    )
    args = parser.parse_args()

    backend = "pdfplumber" if HAS_PDFPLUMBER else ("pypdf" if HAS_PYPDF else "none")
    print(f"Using PDF extraction engine: {backend} | Table Mode: {args.table_mode}")

    pages = extract_page_texts(args.pdf_path, table_mode=args.table_mode)
    start, end = find_section_c_boundaries(pages)
    total_tables = sum(p.num_tables for p in pages)
    print(f"Section C detected: pages {start}-{end} (of {len(pages)} total) | Tables detected: {total_tables}")

    if start is None:
        print("!! Could not locate 'SECTION C' heading -- inspect this PDF by hand.")
        sys.exit(0)

    principles = split_by_principle(pages, start, end)
    for pnum in sorted(principles):
        ess_len = len(principles[pnum]["Essential"])
        lead_len = len(principles[pnum]["Leadership"])
        print(f"  Principle {pnum}: Essential={ess_len} chars, Leadership={lead_len} chars")
        if ess_len == 0 and lead_len == 0:
            print(f"    !! empty -- check page range and heading regex for Principle {pnum}")