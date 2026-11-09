# QA Notes and Verification Protocol

## Purpose
Track manual verification of extracted Section C text against original PDF/XBRL filings.

## Common Extraction Failures Modes to Watch For
1. **Table Bleed:** Multi-column tables or numerical tables whose text gets interleaved into paragraph sentences.
2. **Heading Collision:** Page numbers or running headers like "Integrated Annual Report" included inside Principle text.
3. **Boundary Truncation:** Section C ending too early because an inner heading matched an end hint.
4. **Scrambled Columns:** Two-column narratives read horizontally across columns rather than vertically down each column.
5. **Missing Subsections:** Essential or Leadership indicator subheadings omitted or misplaced.

## Verification Checklist
- [ ] Confirm start page and end page of Section C in the source document.
- [ ] Verify each principle (P1 to P9) maps to the correct disclosure content.
- [ ] Check verbatim correspondence on 10–15 sample rows.
- [ ] Tag verified rows as `manual-checked` in `extraction_method`.

