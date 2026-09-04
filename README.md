# Property-Transactions-Mini-Pipeline
This repository implements the Developer Test Task: a small pipeline to clean a messy condo transactions CSV and a tiny HTTP API that serves summaries from the cleaned data.

clone

```bash
gh repo clone JeyjeyOsom/Property-Transactions-Mini-Pipeline
```

Quick start (from a fresh clone):

1. Create and activate a Python 3.10+ virtualenv (optional but recommended).
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the cleaner (reads `data/condo_transactions_raw.csv` and writes cleaned outputs):

```bash
python3 clean.py data/condo_transactions_raw.csv
```

4. Start the API (reads `data/clean_transactions.csv` at startup):

```bash
uvicorn app:app --reload
```

5. Example API calls:

```bash
curl http://127.0.0.1:8000/projects
curl "http://127.0.0.1:8000/projects/cedar%20park?year=2025"
curl "http://127.0.0.1:8000/estimate?project=cedar%20park&area_sqft=1664.98"
```

Walktrhough Video:

https://www.loom.com/share/1dd4fd5628f14492bf563a135e84b533