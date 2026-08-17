# Tai Chi Attendance Dashboard

A web application for the SBM Falls Prevention Program (Stony Brook Medicine, Trauma Center).
It turns Zoom attendance and registration exports into live participant tracking, follow-up
lists, and reports.

Built with Python, Streamlit, pandas, and SQLite.

---

## For students taking over the project

This guide gets the dashboard running on your own computer. You should be comfortable
using the terminal, but you do not need to be an expert. If anything is unclear, there is
also a separate maintainer's guide with more detail on how the code works.

### 1. Install Python 3.12

Use Python 3.12 specifically. Newer versions such as 3.14 can crash the app, because some
of the libraries it relies on are not stable on them yet.

- Download it from python.org (choose 3.12).
- **Windows:** during the installer, check the box that says "Add Python to PATH."
- **Mac:** run the installer through to the end.

Check it worked by opening a terminal and running:

```
python --version
```

(On Mac you may need to type `python3.12` instead of `python` throughout this guide.)

### 2. Copy the project from GitHub

In a terminal, clone the repository:

```
git clone https://github.com/sbm-taichi-dashboard/taichi-attendance-dashboard.git
```

Then move into the project folder:

```
cd taichi-attendance-dashboard
```

### 3. Install what the app needs (one time)

```
python -m pip install -r requirements.txt
```

### 4. Start the dashboard

```
python -m streamlit run app.py
```

It opens automatically in your web browser at a local address (localhost). To stop it, go
back to the terminal and press Control and C.

---

## Loading data

The app has no data until you add it. On the home page, create a database and upload the
Zoom **participation** and **registration** files. The dashboard processes them and saves
everything into a local database file (taichi.db) so your data is there next time.

**File naming:** registration files can be named anything, the app reads the class name from
inside each file. Participation files also need no special naming.

---

## Getting updates

To pull the latest version of the code before you run it:

```
git pull
```

---

## A note on data and privacy

The database file (taichi.db) holds participant information and stays on your own computer
only. It is never committed to GitHub, and the project is set up to keep it out. Never move
participant data into the repository or anywhere public.

---

## Want to know how it works inside?

See the maintainer's guide (shared separately). It explains how the code is organized, where
the calculations live, and, importantly, what to do if Zoom ever changes its export format.