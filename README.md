# Tai Chi Attendance Dashboard

A dashboard for the SBM Falls Prevention Program (Stony Brook Medicine, Trauma Center).
It takes the weekly Zoom attendance files and turns them into real time participant
tracking, follow up lists, and attendance reporting.

This guide is written so you can open and run the dashboard on your own Mac. The steps
are grouped into two parts: a one time setup, and the short routine you follow each time
you want to use it.

---

## Part 1: One time setup (you only do this once)

**1. Install Python 3.12.**
Go to python.org, open the Downloads page, and install Python 3.12. Please use 3.12
specifically. Newer versions such as 3.14 can cause the app to crash, because some of the
pieces it relies on are not stable on the very newest Python yet.

To check what you have, open the Terminal app (press Command and Spacebar, type Terminal,
press Enter) and run:

```bash
python3.12 --version
```

If it shows a 3.12 version, you are set.

**2. Sign in to GitHub through VS Code.**
Open VS Code. In the bottom left corner, click the small person icon (the Accounts button),
choose Sign in with GitHub, and finish signing in through your web browser. Always sign in
this way, not by typing a password in the Terminal, because the Terminal hides what you type
and looks frozen.

You need to be added to the private repository first. Ask Ashley or Shahin to add your
GitHub account with Read access.

**3. Get the project from GitHub.**
In VS Code, open the Terminal (Terminal menu, then New Terminal) and run:

```bash
git clone https://github.com/sbm-taichi-dashboard/taichi-attendance-dashboard.git
```

**4. Go into the project folder.**

```bash
cd taichi-attendance-dashboard
```

**5. Install the app's parts (one time).**

```bash
python3.12 -m pip install -r requirements.txt
```

When this finishes, the one time setup is done.

---

## Part 2: Every time you want to use the dashboard

**1. Open VS Code, open the project folder, and open the Terminal.**

**2. Start the dashboard.**

```bash
python3.12 -m streamlit run app.py
```

The dashboard opens in your web browser. When you are finished, close the browser tab, go
back to the Terminal, and press Control and C to stop it.

---

## Getting the latest updates

The application is still being improved. When there is a new version ready, get it before
you start the app. The easy way is in VS Code: click the Source Control icon on the left
(the small branch), then click Sync or Pull. If you prefer the Terminal, run this from
inside the project folder:

```bash
git pull
```

Then start the app the usual way.

---

## Naming your files

**Registration files** (these change each quarter): rename each one to match its class,
using this pattern, joined with underscores:

```
Level_Days_Time_QuarterYear
```

For example: `Level2_WF_1030am_Summer2026.csv`. Each new quarter, just change the season,
for example `Fall2026`.

**Participation files**: no renaming needed. The dashboard reads the dates and sessions
from each file on its own.

---

## A note on the data

The database file that holds participant information stays on your own computer. It is
never uploaded to GitHub, which keeps the participant data private. Keep that file in the
project folder so the dashboard can find it, and back it up to OneDrive now and then.

---

## Questions or something not working

Use the GitHub issue ticket system to let the team know what is happening, or reach out
directly. Please do not worry about breaking anything. If something looks off, a note with
what you were doing and what you saw, plus a screenshot, is all we need.