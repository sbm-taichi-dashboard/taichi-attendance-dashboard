# Tai Chi Attendance Dashboard

A dashboard for the SBM Falls Prevention Program (Stony Brook Medicine, Trauma Center).
It takes the weekly Zoom attendance files and turns them into real time participant
tracking, follow up lists, and attendance reporting.

This guide is written so you can open and run the dashboard on your own computer.
The steps are grouped into two parts: a one time setup, and the short routine you
follow every time you want to use it.

---

## Part 1: One time setup (you only do this once)

**1. Make sure Python is installed.**
Open the Terminal app (press Command and Spacebar, type "Terminal", press Enter).
Type this and press Enter:

```bash
python3 --version
```

If it shows a version number, you are good. If not, download Python from python.org
and install it, then try again.

**2. Get the project from GitHub.**
In Terminal, type this and press Enter (this downloads the project into a folder):

```bash
git clone https://github.com/AshieJam/taichi-attendance-dashboard.git
```

**3. Go into the project folder.**

```bash
cd taichi-attendance-dashboard
```

**4. Set up the environment (a private space for the app's parts).**
Type these one at a time, pressing Enter after each:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

When this finishes, the one time setup is done.

---

## Part 2: Every time you want to use the dashboard

**1. Open Terminal and go into the project folder.**

```bash
cd taichi-attendance-dashboard
```

**2. Turn on the environment.**

```bash
source .venv/bin/activate
```

You will know it worked when you see (.venv) at the start of the line.

**3. Start the dashboard.**

```bash
streamlit run app.py
```

The dashboard opens in your web browser. When you are finished, close the browser tab
and go back to Terminal and press Control and C to stop it.

---

## Getting the latest updates

The application is still being improved. When there is a new version ready, open Terminal,
go into the project folder, and run this before starting the app:

```bash
cd taichi-attendance-dashboard
git pull
```

Then start it the usual way (turn on the environment, then run streamlit).

---

## A note on the data

The database file that holds participant information stays on your own computer. It is
never uploaded to GitHub, which keeps the participant data private. Keep that file in the
project folder so the dashboard can find it.

## Questions or something not working

Use the GitHub issue ticket system to let the team know what is happening, or reach out
directly. Please do not worry about breaking anything. If something looks off, a note with
what you were doing and what you saw is all we need.
