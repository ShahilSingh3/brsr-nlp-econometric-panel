"""
xbrl_inspect.py
Stage 0 / Stage 2 Diagnostic Utility: XBRL/XML Filing Inspector.

Project Context & Motivation:
    In SEBI's regulatory regime, companies generate BRSR XBRL files using an
    offline Excel utility provided by the stock exchanges (BSE/NSE). Consequently:
    1. The resulting XML files are not guaranteed to follow a fixed, uniform schema
       across all filing software versions and financial years.
    2. Element tag names and namespaces often vary depending on whether the filing
       was submitted through BSE Listing Centre or NSE Electronic Application Processing.
    3. Narrative disclosures are frequently encapsulated in specialized elements such as
       `...ExplanatoryTextBlock` or nested in contextual scenario dimensions.

    PURPOSE OF THIS SCRIPT:
    Before writing hardcoded XML extraction logic or xpath queries, run this utility on
    real downloaded XBRL instance files. It maps:
    - All declared XML namespaces and prefixes.
    - Total distinct element tag frequencies.
    - Sample text contents for each tag to verify where narrative disclosure actually lives.
    - Heuristic filtering of tags matching Section C and NGRBC principle keywords.

Engine Architecture:
    - Primary engine: `lxml.etree` (fast, full XPath support, standard in production).
    - Automatic fallback: `xml.etree.ElementTree` (standard library, zero external dependencies).

Usage:
    python xbrl_inspect.py path/to/filing.xml
    Example:
        python xbrl_inspect.py data/raw/filings/Infosys.xml
"""

import sys
from collections import Counter

# ==============================================================================
# Dual-Backend XML Engine Initialization
# ==============================================================================

# Attempt to load lxml; if absent, fall back gracefully to standard library ElementTree
# so that researchers can immediately inspect filings without extra environment setup.
try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    import xml.etree.ElementTree as etree
    HAS_LXML = False


# ==============================================================================
# Core Inspection Function
# ==============================================================================

def inspect(path: str, sample_chars: int = 80) -> None:
    """
    Parses an XBRL/XML instance file and outputs a diagnostic summary of its
    internal structure, namespaces, and narrative elements.

    Parameters:
        path: Filepath to the .xml or .xbrl file to inspect.
        sample_chars: Maximum character length for preview snippets printed for each tag.
                      Defaults to 80 characters.
    """
    # Report active XML backend engine
    backend = "lxml" if HAS_LXML else "xml.etree.ElementTree (Python Standard Library)"
    print(f"Using XML parser engine: {backend}")

    # Data structures for accumulating structural statistics
    tag_counts: Counter = Counter()          # Tracks occurrence frequency of each local XML tag
    tag_samples: dict[str, str] = {}         # Captures first non-empty text sample per tag
    ns_map: dict[str, str] = {}              # Maps namespace prefix -> URI

    if HAS_LXML:
        # ----------------------------------------------------------------------
        # Strategy A: lxml-based parsing
        # ----------------------------------------------------------------------
        tree = etree.parse(path)
        root = tree.getroot()
        # lxml directly provides the namespace map on root elements
        ns_map = root.nsmap or {}

        # Iterate over all descendant elements in document order
        for el in root.iter():
            # Extract local tag name, stripping the URI namespace prefix {http://...}
            local_tag = etree.QName(el).localname
            tag_counts[local_tag] += 1

            # Cache the first representative text snippet encountered for this tag
            if local_tag not in tag_samples and el.text and el.text.strip():
                tag_samples[local_tag] = el.text.strip()[:sample_chars]
    else:
        # ----------------------------------------------------------------------
        # Strategy B: xml.etree.ElementTree fallback (standard library)
        # ----------------------------------------------------------------------
        # ElementTree does not expose root.nsmap directly; we capture declared namespaces
        # by streaming events with `start-ns` via iterparse.
        try:
            for event, elem in etree.iterparse(path, events=["start-ns"]):
                prefix, uri = elem
                ns_map[prefix or "(default)"] = uri
        except Exception:
            # Non-fatal: continue even if streaming namespace parsing encounters a quirk
            pass

        tree = etree.parse(path)
        root = tree.getroot()

        for el in root.iter():
            tag_name = el.tag
            # In ElementTree, tags with namespaces are formatted as '{http://...}localname'
            local_tag = tag_name.split("}")[-1] if "}" in tag_name else tag_name
            tag_counts[local_tag] += 1

            # Cache the first representative text snippet
            if local_tag not in tag_samples and el.text and el.text.strip():
                tag_samples[local_tag] = el.text.strip()[:sample_chars]

    # --------------------------------------------------------------------------
    # Output Section 1: Declared Namespaces
    # --------------------------------------------------------------------------
    print(f"--- Namespaces ({len(ns_map)}) ---")
    for prefix, uri in ns_map.items():
        print(f"  {prefix or '(default)'}: {uri}")

    # --------------------------------------------------------------------------
    # Output Section 2: Top Element Tags & Content Samples
    # --------------------------------------------------------------------------
    print(f"\n--- {len(tag_counts)} distinct element tags ---")
    for tag, count in tag_counts.most_common(25):
        sample = tag_samples.get(tag, "")
        print(f"  {tag:<45} x{count:<5} e.g. {sample!r}")
    if len(tag_counts) > 25:
        print(f"  ... and {len(tag_counts) - 25} more tags")

    # --------------------------------------------------------------------------
    # Output Section 3: Keyword Filtering for Section C & Principles
    # --------------------------------------------------------------------------
    # In SEBI taxonomy, narrative disclosures and principle sections typically include
    # one of these indicative substrings in their element name.
    print("\n--- Tags whose name suggests Section C / Principle content ---")
    keywords = ("principle", "essential", "leadership", "sectionc", "ngrbc", "textblock", "explanatory")
    hits = [t for t in tag_counts if any(k in t.lower() for k in keywords)]

    if hits:
        for tag in hits[:20]:
            print(f"  -> {tag} (x{tag_counts[tag]})")
        if len(hits) > 20:
            print(f"  ... and {len(hits) - 20} more matching tags")
    else:
        print("  None found by name -- Section C content may be under generic tags "
              "(e.g. TextBlock elements). Check tag_samples above for narrative text.")


# ==============================================================================
# CLI Entry Point
# ==============================================================================

if __name__ == "__main__":
    """
    Command-line execution handler:
    Ensures a single file path argument is supplied before invoking inspection.
    """
    if len(sys.argv) != 2:
        print("Usage: python xbrl_inspect.py path/to/filing.xml")
        sys.exit(1)

    target_xml_path = sys.argv[1]
    inspect(target_xml_path)