# BRSR project – Prowess panel: QC report
Source: Prowessdx, **Sep-2026 vintage**, 12 extractions (file ids 131464_1_{5,10,15,25,35,45,75,125,150,155,205,275}, downloaded 05-Nov-2026).
Panel: **70,343 firm-years** (10,049 firms x FY2020–FY2026), 137 variables. Key (`co_code`,`fy`) unique. FY = year of the 31-March year-end (fy=2024 -> FY2023-24).

## Checks passed
- No duplicate keys in any source table or in the panel.
- Balance-sheet identity (equity + non-current liab. + current liab. = total assets) holds in **13,407 of 13,407** firm-years.
- Independent spot-check of 6 random firm-years (42 field comparisons: board size, independents, PAT, assets, promoter %, auditor, meeting count) recomputed from raw files: **0 mismatches**.
- Spec 275 total income agrees with spec 75 within 1% for 96% of overlapping firm-years (median difference 0).
- Promoter % within 0–100; independent % within 0–100; ISINs unique where present.

## Data gaps (what the downloads do NOT contain) – action needed
1. **No market capitalisation / share price.** The "BSE & NSE Stocks Trading Data" table was not extracted. Consequences: the top-150/250/500/1000 BRSR cohorts **cannot be rebuilt**; Tobin's Q / market-to-book not computable. `rank_total_income_in_data` is only a rough stand-in and is NOT a cohort.
2. **No standalone financials.** Only consolidated tables were extracted. In FY2025, financials exist for 2,766 of 6,022 currently listed firms; **3,256 listed firms (mainly standalone-only reporters, e.g. financial services, trading) have no financials**. Pull Standalone Annual FS (non-Ind AS and Ind AS) with the same indicators.
3. **Thin financial indicator set.** No borrowings, cash, PBDITA or capex. `leverage` is (non-current + current liabilities)/assets, not debt/equity. Note Prowess' "Total liabilities" = total equity + liabilities.
4. **IGAAP and financial-sector (FS_INDAS) firms** have total income only (spec 75), no line items.
5. **Ownership: promoter % only.** No FPI/FII, mutual-fund/DII or public split (Equity Ownership Pattern was extracted with the promoter fields only).
6. **No director gender** in the Board table. A name-based "(MRS.)" proxy was tested and **dropped**: it falls from 7.5% to 2.5% over FY2021–26 purely because the honorific convention fades, so it is invalid.
7. **No audit fees, no delisting dates, no CSR table beyond the Ind AS fields.** CSR fields are 68–99% missing (spent: 68%, required: 87%).
8. **Beta** only for windows ending Mar-2025 and Mar-2026 (FY2025–26).

## Coverage by fiscal year (currently-listed firms, n=6,022)
| FY | Financials (any) | Detailed Ind AS | Board | Promoter % | Meetings | Auditor |
|---|---|---|---|---|---|---|
| 2020 | 2,171 | 1,723 | 4,788 | 4,167 | – | 5,449 |
| 2021 | 2,257 | 1,826 | 4,818 | 4,198 | – | 5,537 |
| 2022 | 2,386 | 1,931 | 4,905 | 4,324 | 4,345 | 5,564 |
| 2023 | 2,512 | 2,048 | 5,098 | 4,446 | 4,392 | 5,614 |
| 2024 | 2,722 | 2,187 | 5,331 | 4,740 | 4,776 | 5,653 |
| 2025 | 2,766 | 2,210 | 5,529 | 5,058 | 5,110 | 5,631 |
| 2026* | 1,447 | 1,248 | 3,127 | 5,407 | 5,500 | 3,298 |

*FY2026 is partial: filings still arriving, and the early filers skew large (e.g. Big-4 share jumps to 30% vs ~17% earlier in the core sample). Treat FY2026 as provisional.
Board-meeting counts start FY2022: the extract begins Jul-2020, so FY2021 is incomplete and was set to missing.

## Core sample (`core_sample`=1)
Consolidated financials + listed by FY-end + FY2021 onward: **3,080 firms, 13,155 firm-years** (2,061 in FY2021 rising to 2,670 in FY2025). 98% have board data; 83% have detailed Ind AS items. **Selection warning:** this is biased toward consolidated reporters (groups with subsidiaries), so it is not a random draw of the top 1,000.

## Judgement calls to be aware of
- Year-end tables (board, ownership, auditor, RPT, energy) use 31-March observations only; event tables (meetings, dividends, capital changes) are assigned to the Apr–Mar FY of the event date. Dividends: a final dividend for year t is usually announced in year t+1.
- Related-party table: aggregate rows ("All Party Types", "All excl Key Pers & Rel") excluded to avoid double counting.
- `auditor_big4` is a name-matching heuristic (Deloitte, BSR/KPMG, SRBC/SR Batliboi/EY, Price Waterhouse/PwC). Walker Chandiok (Grant Thornton) and MSKA (BDO) are not counted.
- `ceo_duality` is inferred from designation text (Chairperson combined with MD/CEO).
- Winsorised columns (`*_w`) clip at the 1st/99th percentile of the full panel. Raw values are retained. Extreme raw values exist (e.g. ROA min -1,389; current ratio max 30,497).
- 896 firm-years have non-positive equity (ROE set missing); 46 have reporting periods other than 12 months.
- BSE placeholder listing dates before 1950 set to missing.

## Recommended next Prowess pulls (same Sep-2026 vintage and company set)
1. BSE & NSE Stocks Trading Data: market cap, close price, shares, volume (year-end and 31-Dec/31-Mar).
2. Standalone Annual FS (non-Ind AS and Ind AS) with the same indicators plus borrowings, cash, PBDITA, capex.
3. Equity Ownership Pattern: FPI/FII, mutual funds/DII, public shareholding.
4. Auditor fees if available; delisting dates (Identity).

---
## Update (6 Nov 2026): second Prowessdx pull — standalone financials, full ownership split, market data

**Source files:** spec 131516 (Identity, Equity Ownership Pattern, Standalone FS table 70, Standalone FS Ind AS table 270), specs 131517–131524 (BSE & NSE Stocks Trading Data, windows 24–31 Mar 2020–2026 and 24–30 Sep 2026), spec 131525 (consolidated FS). **131525 duplicated the consolidated tables already in the panel (same row counts: 17,271 and 13,836), so it adds nothing.**
Build: `python3 -I build_panel.py <raw_dir> <out_dir> <raw2_dir>`.

**Panel is now 70,343 rows x 209 columns.** Key checks:
- No duplicate (co_code, fy) keys.
- Ownership: promoter + institutions + non-institutions sums to 99.9–100.0% everywhere. Promoter % is missing for firms with no promoter group (e.g. HDFC Bank, ICICI Bank), so it is NOT the same as zero.
- Market cap: last trading date on/before 31 Mar, NSE preferred, BSE fallback. Never more than 7 days stale. Largest firm FY2025 = Reliance (Rs 17.26 trn). Firms with no trade in the 24–31 Mar window have no mcap. 68 rows have mcap = 0.
- Market-to-book agrees with Prowess's own NSE P/B within 10% for 84% of standalone rows (median ratio 1.00).
- Cohorts: top-150/250/500/1000 are exactly N in every year, under two reference-date readings (`*_fyend`, `*_prev_fyend`). Confirm which reading SEBI's circular uses before final cohort definitions. Of top-1000 firm-years FY2023–26, 95% are in the core sample and ~3% (FY2023–25) have no financials at all (FY2026 is partial: 11.5%).

**Method choices to be aware of**
- `fin_basis`: consolidated (Ind AS table) if present, else standalone, else "consolidated_thin" (non-Ind AS consolidated: income and assets only). `fin_basis_switch` flags changes. Top-1000 FY2023–26 split is ~75% consolidated / ~22% standalone.
- Consolidated pull has no borrowings. Debt is standalone only (`sa_total_debt`, `sa_debt_to_assets`).
- Tobin's Q = (mcap + total assets − net worth) / total assets, a book-liabilities approximation. Use the `_w` columns.
- CSR variables: prefer `sa_csr_*` (standalone), since CSR is a standalone obligation.
- `core_sample` widened to consolidated OR standalone: 13,155 → 28,921 firm-years (6,452 firms). The earlier consolidated-only sample was biased towards large groups.
- `rank_total_income_in_data` is still not a market-cap rank; use `mcap_rank`.

**Still open:** no director gender in Prowess (needs the annual-report corpus); FY2026 partial; delisting dates not pulled; Prowess licence terms for scripted extraction not confirmed.
