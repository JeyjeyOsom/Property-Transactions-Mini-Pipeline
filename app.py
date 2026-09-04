from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd
import json
import os
import unicodedata

CLEAN_CSV = 'data/clean_transactions.csv'
SUMMARY_JSON = 'data/summary.json'

app = FastAPI(title='Property Transactions Mini-Pipeline')

# Load data at startup
clean_df = pd.DataFrame()
summary = {}

if os.path.exists(SUMMARY_JSON):
    with open(SUMMARY_JSON, 'r') as f:
        summary = json.load(f)
if os.path.exists(CLEAN_CSV):
    clean_df = pd.read_csv(CLEAN_CSV, dtype={'transaction_id': str, 'project_name': str, 'district': str, 'price': float, 'area_sqft': float, 'psf': float, 'sale_date': str})
    clean_df['sale_date_dt'] = pd.to_datetime(clean_df['sale_date'], errors='coerce')
    clean_df['sale_year'] = clean_df['sale_date_dt'].dt.year
    # add a normalized project name column for case-insensitive, whitespace-tolerant lookups
    def _normalize_text(s: str):
        if pd.isna(s):
            return ''
        t = str(s)
        t = unicodedata.normalize('NFKC', t)
        t = t.strip()
        t = ' '.join(t.split())
        return t.lower()

    clean_df['project_name_norm'] = clean_df['project_name'].apply(_normalize_text)


def _find_project_key(name: str):
    if not summary or 'projects' not in summary:
        return None
    def _norm(s: str):
        if s is None:
            return ''
        t = str(s)
        t = unicodedata.normalize('NFKC', t)
        t = t.strip()
        t = ' '.join(t.split())
        return t.lower()

    target = _norm(name)
    for k in summary['projects'].keys():
        if _norm(k) == target:
            return k
    # fallback: try matching against cleaned dataframe normalized project names
    try:
        if not clean_df.empty:
            mapping = {}
            for orig, normed in zip(clean_df['project_name'], clean_df['project_name_norm']):
                if normed not in mapping:
                    mapping[normed] = orig
            if target in mapping:
                return mapping[target]
    except Exception:
        pass
    return None


@app.get('/projects')
def list_projects():
    projects = []
    for name, info in summary.get('projects', {}).items():
        projects.append({
            'project_name': name,
            'district': info.get('district'),
            'transaction_count': info.get('transaction_count'),
            'median_psf': info.get('median_psf')
        })
    return projects


@app.get('/projects/{project_name}')
def get_project(project_name: str, year: int = None):
    key = _find_project_key(project_name)
    if not key:
        raise HTTPException(status_code=404, detail={'error': 'project not found'})
    proj = summary['projects'][key].copy()
    if year and not clean_df.empty:
        df = clean_df[clean_df['project_name'].str.strip().str.lower() == key.strip().lower()]
        df_year = df[df['sale_year'] == year]
        count = int(len(df_year))
        median_psf = round(float(df_year['psf'].median()), 2) if count > 0 else None
        median_price = round(float(df_year['price'].median()), 2) if count > 0 else None
        proj['transaction_count'] = count
        proj['median_psf'] = median_psf
        proj['median_price'] = median_price
    return proj


@app.get('/estimate')
def estimate(project: str, area_sqft: float):
    """Estimate price using the project's median psf over the most recent 12 months of data available."""
    key = _find_project_key(project)
    if not key:
        raise HTTPException(status_code=404, detail={'error': 'project not found'})
    if clean_df.empty:
        raise HTTPException(status_code=500, detail={'error': 'no cleaned data available'})

    df = clean_df[clean_df['project_name'].str.strip().str.lower() == key.strip().lower()].copy()
    if df.empty:
        raise HTTPException(status_code=404, detail={'error': 'project has no transactions'})

    # determine latest sale date in dataset for this project
    latest = df['sale_date_dt'].max()
    if pd.isna(latest):
        raise HTTPException(status_code=404, detail={'error': 'no valid sale dates for project'})
    window_start = latest - pd.Timedelta(days=365)
    recent = df[df['sale_date_dt'] >= window_start]
    # fall back to all data if no recent transactions
    used = recent if not recent.empty else df
    transactions_used = int(len(used))
    median_psf = round(float(used['psf'].median()), 2)
    estimated_price = round(median_psf * float(area_sqft), 2)

    return JSONResponse({
        'project_name': key,
        'area_sqft': float(area_sqft),
        'estimated_price': estimated_price,
        'median_psf_used': median_psf,
        'transactions_used': transactions_used
    })


@app.get('/')
def root():
    return {'status': 'ok'}
