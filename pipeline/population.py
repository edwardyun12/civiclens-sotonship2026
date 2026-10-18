"""Bring the simulator's residents up to date: ONS mid-2024 small area population estimates.

    python run.py population [--sape-file sapelsoasyoa20222024.xlsx]   refresh data/processed/oa.csv only

Census 2021 gives how each LSOA's residents split across its Output Areas; ONS gives the LSOA's mid-2024 total.
city_data.main() calls apply_sape() too, so a full rebuild also ends up on mid-2024.
"""
from __future__ import annotations

import json
import sys

import pandas as pd
import requests

from pipeline.city_data import LAD_CODE, SOURCES, note
from simulator.paths import PROC, RAW

SAPE_URL = ("https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/populationandmigration/populationestimates/"
            "datasets/lowersuperoutputareamidyearpopulationestimates/mid2022revisednov2025tomid2024/sapelsoasyoa20222024.xlsx")
SAPE_YEAR = 2024
# Age groups for the People map and ward profiles: column -> (first age, last age). 90 = "90 and over" in the file.
AGE_BANDS = {"pop_5_15": (5, 15), "pop_16_24": (16, 24), "pop_25_44": (25, 44), "pop_45_64": (45, 64), "pop_65_plus": (65, 90)}


def fetch_sape(sape_file: str | None = None) -> pd.DataFrame:
    """ONS mid-2024 small area population estimates (released 7 Nov 2025), Southampton's 2021 LSOAs.
    Returns lsoa, pop_est (all ages), pop_0_4_est. The 83 MB workbook is read once; the city's rows are kept in
    data/raw/ons_sape_mid2024_lsoa.csv so later runs (and --update-pop without a file) don't download it again."""
    out_f = RAW / "ons_sape_mid2024_lsoa.csv"
    print(f"[6b] ONS mid-{SAPE_YEAR} LSOA population estimates")
    cached = pd.read_csv(out_f) if out_f.exists() else None
    if sape_file is None and cached is not None and all(f"{b}_est" in cached for b in AGE_BANDS):
        df = cached
    else:
        import openpyxl
        from io import BytesIO
        if sape_file:
            src = sape_file
        else:
            r = requests.get(SAPE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=600)
            r.raise_for_status()
            src = BytesIO(r.content)
        ws = openpyxl.load_workbook(src, read_only=True)[f"Mid-{SAPE_YEAR} LSOA 2021"]
        rows = ws.iter_rows(values_only=True)
        head = next(r for r in rows if r and r[0] == "LAD 2023 Code")
        ix = {h: i for i, h in enumerate(head)}
        young = [f"{s}{a}" for s in "FM" for a in range(5)]
        bands = {b: [f"{s}{a}" for s in "FM" for a in range(lo, hi + 1)] for b, (lo, hi) in AGE_BANDS.items()}
        recs = [{"lsoa": r[ix["LSOA 2021 Code"]], "pop_est": r[ix["Total"]],
                 "pop_0_4_est": sum(r[ix[c]] for c in young),
                 **{f"{b}_est": sum(r[ix[c]] for c in cols) for b, cols in bands.items()}}
                for r in rows if r and r[0] == LAD_CODE]
        df = pd.DataFrame(recs)
        df.to_csv(out_f, index=False)
    note("sape", f"ONS small area population estimates, mid-{SAPE_YEAR}, LSOA 2021 (released 7 Nov 2025)",
         SAPE_URL, "OGL v3.0 (Source: Office for National Statistics)", len(df))
    print(f"   mid-{SAPE_YEAR}: {int(df.pop_est.sum()):,} residents, {int(df.pop_0_4_est.sum()):,} aged 0-4")
    return df


def apply_sape(oa: pd.DataFrame, sape: pd.DataFrame) -> pd.DataFrame:
    """Bring OA populations up to mid-2024. Census 2021 gives how each LSOA's people split across its OAs; the ONS
    estimate gives the LSOA total. Each OA is scaled by its LSOA's growth (all ages and 0-4 separately), so the LSOA
    sums match ONS exactly. The Census counts stay in pop_2021 / pop_0_4_2021 (the 17 Oct baseline uses them)."""
    oa = oa.copy()
    if "pop_2021" not in oa:  # first run: the current pop columns are the Census counts
        oa["pop_2021"], oa["pop_0_4_2021"] = oa["pop"], oa["pop_0_4"]
    s = sape.set_index("lsoa")
    base = oa.groupby("lsoa")[["pop_2021", "pop_0_4_2021"]].transform("sum")
    tot, young = oa["lsoa"].map(s["pop_est"]), oa["lsoa"].map(s["pop_0_4_est"])
    if tot.isna().any():
        raise RuntimeError(f"No mid-{SAPE_YEAR} estimate for LSOAs: {sorted(oa.loc[tot.isna(), 'lsoa'].unique())}")
    oa["pop"] = (oa["pop_2021"] * tot / base["pop_2021"]).round(1)
    # an LSOA with no Census 0-4s (none in Southampton) would divide by zero: spread by total population instead
    w04 = (oa["pop_0_4_2021"] / base["pop_0_4_2021"]).where(base["pop_0_4_2021"] > 0, oa["pop_2021"] / base["pop_2021"])
    oa["pop_0_4"] = (w04 * young).round(1)
    # older age groups: Census OAs only give 0-4, so each OA takes its LSOA's age mix
    for b in AGE_BANDS:
        if f"{b}_est" in s:
            oa[b] = (oa["pop"] * oa["lsoa"].map(s[f"{b}_est"]) / tot).round(1)
    oa["pop_year"] = SAPE_YEAR
    return oa


def update_population(sape_file: str | None = None) -> None:
    """--update-pop: refresh oa.csv to the latest ONS estimates without re-downloading everything else."""
    oa = apply_sape(pd.read_csv(PROC / "oa.csv"), fetch_sape(sape_file))
    oa.to_csv(PROC / "oa.csv", index=False)
    print(f"OA rows: {len(oa)}, population {int(oa.pop_2021.sum()):,} (Census 2021) -> {int(oa['pop'].sum()):,} "
          f"(mid-{SAPE_YEAR}); aged 0-4 {int(oa.pop_0_4_2021.sum()):,} -> {int(oa.pop_0_4.sum()):,}")
    old = json.loads((RAW / "SOURCES.json").read_text()) if (RAW / "SOURCES.json").exists() else {}
    old.update(SOURCES)
    (RAW / "SOURCES.json").write_text(json.dumps(old, indent=2))


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv):
        sys.exit(__doc__)
    update_population(sys.argv[sys.argv.index("--sape-file") + 1] if "--sape-file" in sys.argv else None)
