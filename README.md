# Tai Chi Attendance Dashboard

A Streamlit dashboard for the SBM Falls Prevention Program (Stony Brook
Medicine, Trauma Center). It turns raw Zoom attendance exports into
real-time participant tracking, follow-up lists, and by-level reporting.

## Tech stack

- Python with Streamlit for the interface
- pandas for the data engine (cleaning, deduplication, status calculation)
- SQLite / SQL for storage (a single taichi.db file, created at runtime)

## Running it locally

1. Clone the repo and open the folder.
2. Create and activate a virtual environment:
   - Windows:  python -m venv .venv  then  .venv\Scripts\activate
   - Mac:      python3 -m venv .venv  then  source .venv/bin/activate
3. Install dependencies:  pip install -r requirements.txt
4. Run the app:  streamlit run app.py

Upload the Zoom participation and registration CSV files to create a
database for a quarter.

## Files

- app.py — the application
- SBTC_dark.png — program logo (keep alongside app.py)
- requirements.txt — Python dependencies
- .gitignore — keeps the database and data files out of version control

## Important

The taichi.db database holds participant data and is intentionally not
committed (see .gitignore). Each person runs their own local copy.

## Collaborating

Work on a branch, then open a pull request for review before merging into main.
