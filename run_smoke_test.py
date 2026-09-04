import csv
import json
import os
from datetime import datetime
import re

INPUT = 'data/condo_transactions_raw.csv'
OUT_CLEAN = 'data/clean_transactions.csv'
OUT_SUMMARY = 'data/summary.json'
SQM_TO_SQFT = 10.7639


def normalize_project_name(s):
    if s is None:
        return ''
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.title()


def normalize_district(s):
    if s is None:
        return ''
    s = str(s).strip().upper()
    s = s.replace('D', '')
    try:
        n = int(s)
        return f'D{n:02d}'
    except:
        return s


def parse_price(s):
    if s is None:
        return None
    s = s.strip()
    if s == '':
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", s)
    if not m:
        return None
    num = m.group(0).replace(',', '')
    try:
        val = float(num)
        return int(round(val))
    except:
        return None


def parse_area_to_sqft(s):
    if s is None:
        return None
    s0 = s.strip().lower()
    if s0 == '':
        return None
    m = re.search(r"[\d,.]+", s0)
    if not m:
        return None
    num = m.group(0).replace(',', '')
    try:
        val = float(num)
    except:
        return None
    if ('m' in s0 and 'ft' not in s0) or 'sqm' in s0 or 'sq m' in s0 or 'm2' in s0:
        return val * SQM_TO_SQFT
    return val


def parse_sale_date(s):
    if s is None or s.strip() == '':
        return None
    s = s.strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d %b %Y', '%d %B %Y', '%d %m %Y'):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except:
            continue
    # try fallback parsing of common shapes
    try:
        parts = s.split()
        # e.g. '01 Jan 2025'
        return datetime.strptime(s, '%d %b %Y').date().isoformat()
    except:
        pass
    # last resort: try YYYY
    return None


def normalize_sale_type(s):
    if s is None:
        return ''
    return s.strip().title()


rows = []
with open(INPUT, newline='') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

raw_row_count = len(rows)
seen = set()
deduped = []
for r in rows:
    tid = r.get('transaction_id')
    if tid in seen:
        continue
    seen.add(tid)
    deduped.append(r)

duplicate_rows_removed = raw_row_count - len(deduped)
unique_transactions = len(deduped)

excluded_counts = {'invalid_price': 0, 'missing_area': 0, 'outlier_psf': 0}
cleaned = []
for r in deduped:
    tid = r.get('transaction_id')
    project = normalize_project_name(r.get('project_name'))
    district = normalize_district(r.get('district'))
    price = parse_price(r.get('price'))
    if price is None:
        excluded_counts['invalid_price'] += 1
        continue
    area = parse_area_to_sqft(r.get('area'))
    if area is None or area == 0:
        excluded_counts['missing_area'] += 1
        continue
    psf = price / area
    if psf < 500 or psf > 6000:
        excluded_counts['outlier_psf'] += 1
        continue
    sale_date = parse_sale_date(r.get('sale_date'))
    sale_type = normalize_sale_type(r.get('sale_type'))
    tenure = r.get('tenure') or ''
    cleaned.append({'transaction_id': tid, 'project_name': project, 'district': district, 'price': price, 'area_sqft': round(area,2), 'psf': round(psf,2), 'sale_date': sale_date, 'sale_type': sale_type, 'tenure': tenure})

# write cleaned csv
os.makedirs(os.path.dirname(OUT_CLEAN), exist_ok=True)
with open(OUT_CLEAN, 'w', newline='') as f:
    fieldnames = ['transaction_id','project_name','district','price','area_sqft','psf','sale_date','sale_type','tenure']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for r in cleaned:
        writer.writerow(r)

# build summary
summary = {'raw_row_count': raw_row_count, 'duplicate_rows_removed': duplicate_rows_removed, 'unique_transactions': unique_transactions, 'excluded_counts': excluded_counts, 'clean_row_count': len(cleaned), 'projects': {}, 'district_median_psf': {}, 'top5_projects_by_median_psf_2025': []}

# aggregate per project
from collections import defaultdict
proj_map = defaultdict(list)
for r in cleaned:
    proj_map[r['project_name']].append(r)

for proj, lst in proj_map.items():
    district = lst[0]['district'] if lst else ''
    transaction_count = len(lst)
    median_psf = sorted([x['psf'] for x in lst])[len(lst)//2]
    median_price = sorted([x['price'] for x in lst])[len(lst)//2]
    dates = [x['sale_date'] for x in lst if x['sale_date']]
    dates_dt = [datetime.fromisoformat(d) for d in dates]
    first_sale = min(dates_dt).date().isoformat() if dates_dt else None
    last_sale = max(dates_dt).date().isoformat() if dates_dt else None
    # median_psf_by_year
    med_by_year = {}
    year_map = defaultdict(list)
    for x in lst:
        if x['sale_date']:
            y = datetime.fromisoformat(x['sale_date']).year
            year_map[y].append(x['psf'])
    for y, vals in year_map.items():
        vals_sorted = sorted(vals)
        med = vals_sorted[len(vals)//2]
        med_by_year[str(y)] = round(med,2)
    summary['projects'][proj] = {'district': district, 'transaction_count': transaction_count, 'median_psf': round(median_psf,2), 'median_price': round(median_price,2), 'first_sale': first_sale, 'last_sale': last_sale, 'median_psf_by_year': med_by_year}

# district median
dist_map = defaultdict(list)
for r in cleaned:
    dist_map[r['district']].append(r['psf'])
for d, vals in dist_map.items():
    vals_sorted = sorted(vals)
    med = vals_sorted[len(vals)//2]
    summary['district_median_psf'][d] = round(med,2)

# top5 2025
proj_2025 = []
for p, info in summary['projects'].items():
    med = info['median_psf_by_year'].get('2025')
    if med is not None:
        proj_2025.append((p, med))
proj_2025_sorted = sorted(proj_2025, key=lambda x: x[1], reverse=True)[:5]
summary['top5_projects_by_median_psf_2025'] = [[p,m] for p,m in proj_2025_sorted]

with open(OUT_SUMMARY, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"Smoke test wrote {OUT_CLEAN} ({len(cleaned)} rows) and {OUT_SUMMARY}")
