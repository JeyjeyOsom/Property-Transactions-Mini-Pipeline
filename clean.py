import re
import os
import sys
import json
from datetime import datetime
from dateutil import parser as date_parser
import pandas as pd

INPUT_DEFAULT = "data/condo_transactions_raw.csv"
OUTPUT_CLEAN = "data/clean_transactions.csv"
OUTPUT_SUMMARY = "data/summary.json"

SQM_TO_SQFT = 10.7639


def normalize_project_name(s):
    if pd.isna(s):
        return ""
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.title()


def normalize_district(s):
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()
    s = s.replace("D", "")
    try:
        n = int(s)
        return f"D{n:02d}"
    except Exception:
        return s


def parse_price(s):
    if pd.isna(s):
        return None
    s = str(s).strip()
    if s == "":
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", s)
    if not m:
        return None
    num = m.group(0).replace(",", "")
    try:
        val = float(num)
        return int(round(val))
    except Exception:
        return None


def parse_area_to_sqft(s):
    if pd.isna(s):
        return None
    s0 = str(s).strip().lower()
    if s0 == "":
        return None
    # Extract number
    m = re.search(r"[\d,.]+", s0)
    if not m:
        return None
    num = m.group(0).replace(",", "")
    try:
        val = float(num)
    except Exception:
        return None
    # Determine unit: if contains 'm' and not 'ft' treat as sqm
    if ("m" in s0 and "ft" not in s0) or "sqm" in s0 or "sq m" in s0 or "m2" in s0:
        return val * SQM_TO_SQFT
    # otherwise assume sqft
    return val


def parse_sale_date(s):
    if pd.isna(s):
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        # dayfirst=True handles DD/MM/YYYY and 'DD Mon YYYY'
        dt = date_parser.parse(s, dayfirst=True)
        return dt.date().isoformat()
    except Exception:
        return None


def normalize_sale_type(s):
    if pd.isna(s):
        return ""
    return str(s).strip().title()


def main(input_path=None):
    input_path = input_path or INPUT_DEFAULT
    if not os.path.exists(input_path):
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    df = pd.read_csv(input_path, dtype=str)
    raw_row_count = len(df)

    # Deduplicate on transaction_id
    if 'transaction_id' not in df.columns:
        print('transaction_id column missing')
        sys.exit(1)

    df_dedup = df.drop_duplicates(subset=['transaction_id'], keep='first')
    duplicate_rows_removed = raw_row_count - len(df_dedup)
    unique_transactions = len(df_dedup)

    excluded_counts = {"invalid_price": 0, "missing_area": 0, "outlier_psf": 0}
    cleaned_rows = []

    for _, row in df_dedup.iterrows():
        tid = row.get('transaction_id')
        project = normalize_project_name(row.get('project_name', ''))
        district = normalize_district(row.get('district', ''))
        price = parse_price(row.get('price'))
        if price is None:
            excluded_counts['invalid_price'] += 1
            continue
        area_sqft = parse_area_to_sqft(row.get('area'))
        if area_sqft is None or area_sqft == 0:
            excluded_counts['missing_area'] += 1
            continue
        psf = price / area_sqft
        if psf < 500 or psf > 6000:
            excluded_counts['outlier_psf'] += 1
            continue
        sale_date = parse_sale_date(row.get('sale_date'))
        sale_type = normalize_sale_type(row.get('sale_type'))
        tenure = row.get('tenure') if not pd.isna(row.get('tenure')) else ''

        cleaned_rows.append({
            'transaction_id': tid,
            'project_name': project,
            'district': district,
            'price': int(price),
            'area_sqft': round(area_sqft, 2),
            'psf': round(psf, 2),
            'sale_date': sale_date,
            'sale_type': sale_type,
            'tenure': tenure
        })

    clean_df = pd.DataFrame(cleaned_rows)
    clean_row_count = len(clean_df)

    # Write cleaned CSV
    os.makedirs(os.path.dirname(OUTPUT_CLEAN), exist_ok=True)
    clean_df.to_csv(OUTPUT_CLEAN, index=False)

    # Build summary
    summary = {
        'raw_row_count': int(raw_row_count),
        'duplicate_rows_removed': int(duplicate_rows_removed),
        'unique_transactions': int(unique_transactions),
        'excluded_counts': excluded_counts,
        'clean_row_count': int(clean_row_count),
        'projects': {},
        'district_median_psf': {},
        'top5_projects_by_median_psf_2025': []
    }

    if clean_row_count > 0:
        # per project stats
        for proj, g in clean_df.groupby('project_name'):
            district_val = g['district'].dropna().unique()
            district_val = district_val[0] if len(district_val) > 0 else ''
            transaction_count = int(len(g))
            median_psf = round(float(g['psf'].median()), 2)
            median_price = round(float(g['price'].median()), 2)
            # first and last sale
            dates = pd.to_datetime(g['sale_date'], errors='coerce').dropna()
            first_sale = dates.min().date().isoformat() if not dates.empty else None
            last_sale = dates.max().date().isoformat() if not dates.empty else None
            # median psf by year
            med_by_year = {}
            g_dates = pd.to_datetime(g['sale_date'], errors='coerce').dropna()
            if not g_dates.empty:
                years = g_dates.dt.year.unique()
                for y in sorted(years):
                    subset = g[g_dates.dt.year == y]
                    if len(subset) > 0:
                        med_by_year[str(y)] = round(float(subset['psf'].median()), 2)
            summary['projects'][proj] = {
                'district': district_val,
                'transaction_count': transaction_count,
                'median_psf': median_psf,
                'median_price': median_price,
                'first_sale': first_sale,
                'last_sale': last_sale,
                'median_psf_by_year': med_by_year
            }

        # district median psf
        dist_med = clean_df.groupby('district')['psf'].median()
        for dist, med in dist_med.items():
            summary['district_median_psf'][dist] = round(float(med), 2)

        # top5 projects by median psf in 2025
        proj_2025 = []
        for proj, info in summary['projects'].items():
            med = info.get('median_psf_by_year', {}).get('2025')
            if med is not None:
                proj_2025.append((proj, med))
        proj_2025_sorted = sorted(proj_2025, key=lambda x: x[1], reverse=True)[:5]
        summary['top5_projects_by_median_psf_2025'] = [[p, m] for p, m in proj_2025_sorted]

    # Write summary
    with open(OUTPUT_SUMMARY, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote {OUTPUT_CLEAN} ({clean_row_count} rows) and {OUTPUT_SUMMARY}")


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
