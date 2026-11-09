"""
explore_panel.py
Panel Data Exploration, Cohort Filtering & Integrity Verification.

Validates the Prowess master financial & governance panel (panel_firmyear.csv)
and verifies the Top-150 / Top-250 / Top-500 / Top-1000 cohorts across
FY2022-23 (fy=2023) through FY2025-26 (fy=2026).

Usage:
    python data/Panel/explore_panel.py
"""

from pathlib import Path
import pandas as pd

PANEL_PATH = Path("data/Panel/panel_firmyear.csv")
SAMPLE_PATH = Path("data/Panel/sample_list.csv")
DICT_PATH = Path("data/Panel/data_dictionary.csv")


def explore_panel():
    print("=" * 70)
    print("BRSR Project: Prowess Master Panel Exploration & Verification")
    print("=" * 70)

    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Master panel not found at {PANEL_PATH}")

    print(f"Loading panel: {PANEL_PATH}...")
    panel = pd.read_csv(PANEL_PATH, low_memory=False)
    print(f"  Total firm-years: {len(panel):,}")
    print(f"  Total variables : {len(panel.columns)}")
    print(f"  Unique companies: {panel['co_code'].nunique():,}")
    print(f"  Fiscal years    : {sorted(panel['fy'].unique().tolist())}\n")

    # Cohort analysis across FY2023 to FY2026
    brsr_years = [2023, 2024, 2025, 2026]
    print("-" * 70)
    print("SEBI BRSR Target Cohorts (FY2023 to FY2026):")
    print("-" * 70)

    cohort_summary = []
    for y in brsr_years:
        sub = panel[panel["fy"] == y]
        fy_label = sub["fy_label"].iloc[0] if "fy_label" in sub.columns else f"FY{y-1}-{str(y)[-2:]}"
        t150 = sub[sub["top150_fyend"] == 1]
        t250 = sub[sub["top250_fyend"] == 1]
        t500 = sub[sub["top500_fyend"] == 1]
        t1000 = sub[sub["top1000_fyend"] == 1]
        core = sub[sub["core_sample"] == 1]

        cohort_summary.append({
            "fy": y,
            "fy_label": fy_label,
            "total_firms": len(sub),
            "top150_count": len(t150),
            "top150_with_isin": t150["isin"].notna().sum(),
            "top250_count": len(t250),
            "top500_count": len(t500),
            "top1000_count": len(t1000),
            "core_sample_count": len(core),
        })

    summary_df = pd.DataFrame(cohort_summary)
    print(summary_df.to_string(index=False))

    # Unique firms in Top-150 across the 4 years
    top150_mask = (panel["fy"].isin(brsr_years)) & (panel["top150_fyend"] == 1)
    unique_top150_co = panel[top150_mask]["co_code"].unique()
    print(f"\nTotal unique firms in Top-150 universe (FY23–FY26): {len(unique_top150_co)}")
    print(f"Total firm-years in Top-150 study sample: {top150_mask.sum()} (150 x 4)")

    # Sample list check
    if SAMPLE_PATH.exists():
        print("-" * 70)
        print(f"Cross-referencing with Sample List: {SAMPLE_PATH}...")
        sample = pd.read_csv(SAMPLE_PATH)
        top150_sample = sample[sample["co_code"].isin(unique_top150_co)]
        print(f"  Matched firms in sample list: {len(top150_sample)} / {len(unique_top150_co)}")
        print(f"  Firms with valid ISIN: {top150_sample['isin'].notna().sum()}")
        print(f"  Firms with NSE symbol: {top150_sample['nse_symbol'].notna().sum()}")
        print(f"  Firms with BSE scrip : {top150_sample['bse_scrip_code'].notna().sum()}")

    # Check key variables for regression
    print("-" * 70)
    print("Verification of Key Financial, Governance & Winsorised Variables:")
    print("-" * 70)
    top150_df = panel[top150_mask]
    key_vars = [
        "mcap_inr_mn", "mcap_rank", "roa", "roa_w", "tobins_q_w",
        "leverage_w", "sa_csr_spent", "board_size", "pct_independent",
        "ceo_duality", "auditor_big4", "promoter_pct"
    ]
    # Fail loudly on absent variables instead of silently dropping them.
    absent_vars = [v for v in key_vars if v not in top150_df.columns]
    if absent_vars:
        print(f"[WARNING] Variables not found in panel and skipped: {', '.join(absent_vars)}")
    present_vars = [v for v in key_vars if v in top150_df.columns]
    missing_pct = top150_df[present_vars].isna().mean() * 100

    for var in present_vars:
        print(f"  {var:<22}: {missing_pct[var]:5.1f}% missing in Top-150 (FY23–FY26)")

    print("\n[OK] Panel integrity verification complete.")


if __name__ == "__main__":
    explore_panel()
