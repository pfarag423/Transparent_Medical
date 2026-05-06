#!/usr/bin/env python3
"""
parse_mrf.py
Streams the provider MRF CSV, extracts priority CPT codes,
computes the self-pay discount rate, enumerates payers.
Writes cache/{fqdn}/procedures.json and updates provider.json.

Usage:
    python scripts/parse_mrf.py valleymed.org
    python scripts/parse_mrf.py valleymed.org --force-refresh
"""

import sys
import json
import os
import csv
import re
import io
import argparse
from urllib.request import urlopen, Request
from collections import defaultdict

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(SKILL_DIR, "cache")
DATA_DIR = os.path.join(SKILL_DIR, "data")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; InsuranceCalcSkill/1.0)"}
CHUNK_SIZE = 64 * 1024  # 64KB chunks


def load_priority_cpts():
    path = os.path.join(DATA_DIR, "priority_cpts.json")
    with open(path) as f:
        data = json.load(f)
    # Build lookup: cpt_code -> procedure metadata
    return {p["cpt"]: p for p in data["procedures"]}


def load_provider(fqdn):
    path = os.path.join(CACHE_DIR, fqdn, "provider.json")
    if not os.path.exists(path):
        print(f"ERROR: No provider.json for {fqdn}. Run discover_mrf.py first.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def update_provider(fqdn, updates):
    path = os.path.join(CACHE_DIR, fqdn, "provider.json")
    with open(path) as f:
        provider = json.load(f)
    provider.update(updates)
    with open(path, "w") as f:
        json.dump(provider, f, indent=2)


def write_procedures(fqdn, procedures):
    path = os.path.join(CACHE_DIR, fqdn, "procedures.json")
    with open(path, "w") as f:
        json.dump(procedures, f, indent=2)
    print(f"  Procedures cached: {path}")


def detect_schema(header_row):
    """
    Detect CMS schema version from column headers.
    Returns: 'v2', 'v1_wide', or 'unknown'
    """
    cols = [c.lower().strip() for c in header_row]
    if "standard_charge|gross" in cols or "standard_charge|discounted_cash" in cols:
        return "v2"
    if any("gross charge" in c or "gross_charge" in c for c in cols):
        return "v1_wide"
    return "unknown"


def build_col_map_v2(header_row):
    """Map column names to indices for CMS v2 tall format."""
    cols = [c.strip() for c in header_row]
    col_map = {}
    for i, col in enumerate(cols):
        col_lower = col.lower()
        col_map[col_lower] = i
    return col_map


def safe_float(val):
    if val is None:
        return None
    val = str(val).strip().replace("$", "").replace(",", "")
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def extract_codes(row, col_map):
    """Extract all billing codes from a row."""
    codes = []
    for i in range(1, 5):
        code_key = f"code|{i}"
        type_key = f"code|{i}|type"
        if code_key in col_map:
            code = row[col_map[code_key]].strip() if col_map[code_key] < len(row) else ""
            code_type = row[col_map[type_key]].strip() if type_key in col_map and col_map[type_key] < len(row) else ""
            if code:
                codes.append({"code": code, "type": code_type})
    return codes


def get_val(row, col_map, key, default=None):
    idx = col_map.get(key.lower())
    if idx is None or idx >= len(row):
        return default
    return row[idx].strip() or default


def stream_parse_v2(mrf_url, priority_cpts, chunk_size=CHUNK_SIZE):
    """
    Stream-parse a CMS v2 tall CSV MRF.
    Returns: (procedures_by_cpt, payers_seen, discount_samples, hospital_meta)
    """
    procedures_by_cpt = defaultdict(lambda: {
        "gross_charges": [],
        "discounted_cash": [],
        "negotiated_rates": [],
        "payer_entries": [],
    })
    payers_seen = set()
    discount_samples = []
    hospital_meta = {}
    col_map = None
    header_done = False
    row_count = 0
    meta_rows_remaining = 2  # CMS v2/v3 has 2 metadata rows before header

    print(f"  Streaming MRF from: {mrf_url}")
    req = Request(mrf_url, headers=HEADERS)

    buffer = ""
    try:
        with urlopen(req, timeout=60) as resp:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                lines = buffer.split("\n")
                buffer = lines[-1]  # keep incomplete last line

                for line in lines[:-1]:
                    if not line.strip():
                        continue

                    # Parse as CSV
                    try:
                        row = next(csv.reader([line]))
                    except Exception:
                        continue

                    # CMS v2: first few rows are metadata, not data
                    if not header_done:
                        if meta_rows_remaining > 0:
                            # Extract hospital name and address from metadata rows
                            joined = " ".join(row)
                            if not hospital_meta.get("hospital_name"):
                                for cell in row:
                                    if "medical center" in cell.lower() or "hospital" in cell.lower():
                                        if len(cell) > 5 and len(cell) < 100:
                                            hospital_meta["hospital_name"] = cell.strip()
                                            break
                            meta_rows_remaining -= 1
                            continue

                        # This is the header row
                        schema = detect_schema(row)
                        if schema != "v2":
                            print(f"  WARNING: Schema detected as '{schema}', expected v2. Attempting best-effort parse.")
                        col_map = build_col_map_v2(row)
                        header_done = True
                        continue

                    # Data rows
                    if col_map is None:
                        continue

                    row_count += 1
                    if row_count % 100000 == 0:
                        print(f"  Processed {row_count:,} rows...")

                    # Extract codes and check against priority list
                    codes = extract_codes(row, col_map)
                    matched_cpt = None
                    for code_entry in codes:
                        cpt = code_entry["code"].strip()
                        if cpt in priority_cpts:
                            matched_cpt = cpt
                            break

                    gross = safe_float(get_val(row, col_map, "standard_charge|gross"))
                    cash = safe_float(get_val(row, col_map, "standard_charge|discounted_cash"))
                    payer = get_val(row, col_map, "payer_name")
                    plan = get_val(row, col_map, "plan_name")
                    negotiated = safe_float(get_val(row, col_map, "standard_charge|negotiated_dollar"))
                    min_rate = safe_float(get_val(row, col_map, "standard_charge|min"))
                    max_rate = safe_float(get_val(row, col_map, "standard_charge|max"))
                    median = safe_float(get_val(row, col_map, "median_allowed_amount"))
                    methodology = get_val(row, col_map, "standard_charge|methodology")
                    description = get_val(row, col_map, "description", "")
                    setting = get_val(row, col_map, "setting", "outpatient")

                    # Collect discount samples (any row with both gross and cash)
                    if gross and cash and gross > 0 and cash > 0 and len(discount_samples) < 500:
                        discount_samples.append(1 - (cash / gross))

                    # Track payers
                    if payer:
                        payers_seen.add(payer)

                    # Store if priority CPT match
                    if matched_cpt:
                        entry = procedures_by_cpt[matched_cpt]
                        if gross:
                            entry["gross_charges"].append(gross)
                        if cash:
                            entry["discounted_cash"].append(cash)
                        if negotiated and payer:
                            entry["payer_entries"].append({
                                "payer": payer,
                                "plan": plan,
                                "negotiated": negotiated,
                                "min": min_rate,
                                "max": max_rate,
                                "median": median,
                                "methodology": methodology,
                                "setting": setting,
                            })
                        if not entry.get("description") and description:
                            entry["description"] = description
                        if min_rate:
                            entry["negotiated_rates"].append(min_rate)
                        if max_rate:
                            entry["negotiated_rates"].append(max_rate)

    except Exception as e:
        print(f"  Stream error: {e}")

    return procedures_by_cpt, payers_seen, discount_samples, hospital_meta


def compute_self_pay_discount(samples):
    if not samples:
        return None
    # Remove outliers (keep middle 80%)
    samples_sorted = sorted(samples)
    n = len(samples_sorted)
    trimmed = samples_sorted[int(n * 0.1):int(n * 0.9)]
    if not trimmed:
        return None
    avg = sum(trimmed) / len(trimmed)
    return round(avg, 4)


def summarize_procedures(procedures_by_cpt, priority_cpts):
    summary = {}
    for cpt, data in procedures_by_cpt.items():
        gross_list = data["gross_charges"]
        cash_list = data["discounted_cash"]
        neg_list = data["negotiated_rates"]
        payer_entries = data["payer_entries"]

        def median(lst):
            if not lst:
                return None
            s = sorted(lst)
            n = len(s)
            return s[n // 2]

        meta = priority_cpts.get(cpt, {})

        summary[cpt] = {
            "cpt": cpt,
            "description": data.get("description") or meta.get("description", ""),
            "category": meta.get("category", ""),
            "tier": meta.get("tier", ""),
            "pre_auth": meta.get("pre_auth", {}),
            "gross_charge_median": median(gross_list),
            "discounted_cash_median": median(cash_list),
            "negotiated_min": min(neg_list) if neg_list else None,
            "negotiated_max": max(neg_list) if neg_list else None,
            "negotiated_median": median(neg_list),
            "payer_rates": payer_entries[:20],  # cap stored payer entries at 20
            "sample_count": len(gross_list),
        }

    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fqdn", help="Provider base domain, e.g. valleymed.org")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    fqdn = args.fqdn.lower().strip().lstrip("www.").split("/")[0]

    # Check if procedures cache exists and is still valid
    procedures_path = os.path.join(CACHE_DIR, fqdn, "procedures.json")
    if not args.force_refresh and os.path.exists(procedures_path):
        provider = load_provider(fqdn)
        print(f"  Cache hit for {fqdn} (MRF: {provider.get('mrf_last_updated', 'unknown')})")
        print(f"  Use --force-refresh to re-parse.")
        with open(procedures_path) as f:
            procs = json.load(f)
        print(f"  {len(procs)} procedures indexed.")
        return 0

    provider = load_provider(fqdn)
    mrf_url = provider.get("mrf_url")
    if not mrf_url:
        print(f"ERROR: No MRF URL in provider.json for {fqdn}. Run discover_mrf.py first.")
        return 1

    priority_cpts = load_priority_cpts()
    print(f"\n=== MRF Parse: {fqdn} ===")
    print(f"  Priority CPT codes: {len(priority_cpts)}")

    raw, payers, discount_samples, hospital_meta = stream_parse_v2(mrf_url, priority_cpts)

    self_pay_discount = compute_self_pay_discount(discount_samples)
    print(f"\n  Self-pay discount rate: {self_pay_discount:.1%}" if self_pay_discount else "\n  Could not compute self-pay discount rate.")
    print(f"  Unique payers found: {len(payers)}")
    print(f"  Priority CPTs matched: {len(raw)}")

    procedures = summarize_procedures(raw, priority_cpts)

    write_procedures(fqdn, procedures)

    # Update provider.json with computed values
    update_provider(fqdn, {
        "self_pay_discount_rate": self_pay_discount,
        "payers_available": sorted(list(payers)),
        "hospital_name": hospital_meta.get("hospital_name") or provider.get("hospital_name"),
        "procedures_indexed": len(procedures),
        "parsed_at": __import__("datetime").date.today().isoformat(),
    })

    print(f"\nDone. {len(procedures)} procedures indexed for {fqdn}.")
    missing = [cpt for cpt in priority_cpts if cpt not in procedures]
    if missing:
        print(f"  CPTs not found in MRF ({len(missing)}): {', '.join(missing)}")
    print(f"\nNext step: python scripts/generate_xlsx.py '<inputs_json>' {fqdn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
