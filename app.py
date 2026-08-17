import streamlit as st
import pandas as pd
import sqlite3, hashlib, re, os, glob, io
from datetime import date

#avoid the pyarrow-backed string engine, which can hard-crash Python 3.14
for _opt in ("future.infer_string", "mode.string_storage"):
    try:
        pd.set_option(_opt, False if _opt=="future.infer_string" else "python")
    except Exception:
        pass

st.set_page_config(page_title="SBM Tai Chi Attendance", layout="wide",
                   initial_sidebar_state="expanded")

#Constants
ROGUE_TOPICS = ["virtual otago", "parkinson", "sbm falls", "dissertaion",
                "dissertation", "tca-v", "instructor meeting", "zoom test"]
STAFF_KEYWORDS = ["fallsfree", "stonybrook"]
LEVEL_MAP = {"full form": 3, "level 2": 2, "level 1": 1}

#Styling
st.markdown("""<style>
[data-testid="stSidebar"] { background:#12122a; }
[data-testid="stSidebar"] * { color:#e8e8f0; }
[data-testid="stSidebar"] .sidebar-label {
    font-size:11px; font-weight:700; text-transform:uppercase;
    letter-spacing:.08em; color:#8888aa; margin:1rem 0 .3rem; }
[data-testid="stSidebar"] [data-baseweb="tag"] {
    background:#2e2e50 !important; border:1px solid #4a4a6a !important; }
[data-testid="stSidebar"] [data-baseweb="tag"] span { color:#c8c8e8 !important; }
.page-head {
    background:#8B0000; color:#fff; padding:.85rem 1.25rem;
    border-radius:8px; font-size:18px; font-weight:700; margin-bottom:1.25rem; }
.metric-card {
    background:#fff; border:1px solid #efe7e7; border-top:3px solid #8B0000;
    border-radius:14px; padding:1.1rem 1.25rem;
    box-shadow:0 2px 10px rgba(139,0,0,.06);
    transition:transform .12s ease, box-shadow .12s ease; }
.metric-card:hover { transform:translateY(-2px); box-shadow:0 7px 20px rgba(139,0,0,.13); }
.metric-num { font-size:32px; font-weight:800; color:#8B0000; line-height:1; }
.metric-lbl { font-size:11px; text-transform:uppercase; letter-spacing:.05em;
    color:#777; margin-top:.45rem; }
.prog-row { margin:.6rem 0; }
.prog-top { display:flex; justify-content:space-between; align-items:baseline;
    font-size:13px; color:#333; margin-bottom:5px; }
.prog-top b { color:#8B0000; font-size:14px; }
.prog-track { background:#f1ecec; border-radius:8px; height:15px; overflow:hidden; }
.prog-fill { background:linear-gradient(90deg,#8B0000,#c0524f); height:100%;
    border-radius:8px; }
.card { background:#fff; border:1px solid #eee; border-radius:8px;
    padding:1.25rem; margin-bottom:1rem; }
.card-title { font-size:13px; font-weight:700; text-transform:uppercase;
    letter-spacing:.05em; color:#8B0000; margin-bottom:.75rem; }
div[data-testid="stDataFrame"] { border:1px solid #eee; border-radius:8px; }
/* Sidebar nav buttons — dark theme */
[data-testid="stSidebar"] button {
    background:#1e1e3a !important; color:#c8c8e8 !important;
    border:1px solid #2e2e50 !important; font-weight:500 !important; }
[data-testid="stSidebar"] button:hover {
    background:#2a2a4a !important; border-color:#8B0000 !important; }
[data-testid="stSidebar"] button[kind="primary"] {
    background:#8B0000 !important; color:#fff !important; border:none !important; }
/* Sidebar multiselect input dark */
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background:#1e1e3a !important; border-color:#2e2e50 !important; }
[data-testid="stSidebar"] [data-baseweb="select"] input { color:#c8c8e8 !important; }
[data-testid="stSidebar"] label { color:#c8c8e8 !important; }
</style>""", unsafe_allow_html=True)

#Session State
for k, v in {"page":"Home", "flow":None, "loaded":False, "db_path":"taichi.db",
             "merged":None, "ps":None, "mr":None}.items():
    st.session_state.setdefault(k, v)

DB_PATH = st.session_state["db_path"]

#keep filter/picker choices alive when the user visits another page and comes back
for _pk in ["at_mode","at_from","at_to","at_class","at_level","at_view","at_flagby","at_flaggedonly","fu_pick","pr_pick"]:
    if _pk in st.session_state:
        st.session_state[_pk] = st.session_state[_pk]

#Data Engine
def read_csv_smart(f):
    """Read a Zoom CSV. Registration files have 5 metadata rows; participation
    files have headers on row 1. Tries header=5 first, falls back to header=0."""
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            f.seek(0)
            d5 = pd.read_csv(f, header=5, dtype=str, encoding=enc,
                             on_bad_lines="skip").dropna(how="all")
            d5.columns = [str(c).replace("\ufeff","").strip() for c in d5.columns]
            if len(d5.columns) >= 4 and any(
                c.lower() in ["email","first name","topic","type","name (original name)"]
                for c in d5.columns):
                return d5
        except Exception: pass
        try:
            f.seek(0)
            d0 = pd.read_csv(f, dtype=str, encoding=enc,
                             on_bad_lines="skip").dropna(how="all")
            d0.columns = [str(c).replace("\ufeff","").strip() for c in d0.columns]
            if len(d0.columns) >= 4:
                return d0
        except Exception: continue
    raise ValueError("Could not read file — save as UTF-8 CSV")

def is_staff(email):
    return any(k in str(email).lower() for k in STAFF_KEYWORDS)

def is_rogue(topic):
    return any(r in str(topic).lower() for r in ROGUE_TOPICS)

def get_quarter(dt):
    if pd.isna(dt): return "Unknown"
    m, y = dt.month, dt.year
    if   m in (1,2,3):   return f"Winter {y}"
    elif m in (4,5,6):   return f"Spring {y}"
    elif m in (7,8,9):   return f"Summer {y}"
    else:                return f"Fall {y}"

def highest_level(topics):
    best = 0
    for t in topics:
        tl = str(t).lower()
        for key, score in LEVEL_MAP.items():
            if key in tl: best = max(best, score)
    return {3:"Full Form Practice", 2:"Level 2", 1:"Level 1", 0:"Unknown"}[best]

# Levels tracked individually (in display order)
LEVELS = ["Level 1", "Level 2", "Full Form"]

def topic_level(topic):
    """Return which level a single class topic belongs to, or None."""
    tl = str(topic).lower()
    if "full form" in tl: return "Full Form"
    if "level 2" in tl:   return "Level 2"
    if "level 1" in tl:   return "Level 1"
    return None

def classify_days(days):
    """Active <14, Inactive 14-30, Dropped >30, No Attendance if no date."""
    if pd.isna(days): return "No Attendance"
    d = int(days)
    if d < 14:    return "Active"
    elif d <= 30: return "Inactive"
    else:         return "Dropped"

def process(part_files, reg_files):
    """Returns dict with merged, ps (participant status), mr (registration), skipped."""
    skipped = []

    # ---- PARTICIPATION ----
    pdfs = []
    for f in part_files:
        try:
            raw = read_csv_smart(f)
            raw = raw.rename(columns={"ID":"Meeting ID", "User Email":"Email"})
            if "Email" not in raw.columns: skipped.append(f.name); continue
            pdfs.append(raw)
        except Exception as e:
            skipped.append(f"{f.name} ({e})")
    if not pdfs:
        return {"error":"No participation files could be read.", "skipped":skipped}

    mp = pd.concat(pdfs, ignore_index=True)
    mp["Email"] = mp["Email"].astype(str).str.strip().str.lower()
    dur_col = "Duration (minutes).1" if "Duration (minutes).1" in mp.columns else \
              next((c for c in mp.columns if "duration" in c.lower() and ".1" in c), None) or \
              next((c for c in mp.columns if "duration" in c.lower()), None)
    mp["dur"] = pd.to_numeric(mp.get(dur_col, 0), errors="coerce").fillna(0)
    mp["Meeting ID"] = mp.get("Meeting ID","").astype(str).str.replace(" ","").str.strip()
    mp["Start time"] = pd.to_datetime(mp.get("Start time"), errors="coerce", format="mixed")
    mp["Topic"] = mp.get("Topic","Unknown").astype(str)
    mp["Quarter"] = mp["Start time"].apply(get_quarter)

    # filter staff, blanks, rogue topics
    mp = mp[~mp["Email"].apply(is_staff)]
    mp = mp[(mp["Email"]!="nan") & (mp["Email"]!="") & mp["Email"].notna()]
    mp = mp[~mp["Topic"].apply(is_rogue)]

    # unique session = meeting ID + full start time; sum duration across joins
    mp["session_key"] = mp["Meeting ID"] + "_" + mp["Start time"].astype(str)
    mp["durationMinutesTotal"] = mp.groupby(["Email","session_key"])["dur"].transform("sum")
    mp = mp.drop_duplicates(subset=["Email","session_key"], keep="last")

    # ---- REGISTRATION ----
    mr = None
    if reg_files:
        rdfs = []
        for f in reg_files:
            try:
                reg_topic = ""
                try:
                    f.seek(0)
                    _h = pd.read_csv(f, header=2, nrows=1, dtype=str)
                    if "Topic" in _h.columns:
                        reg_topic = str(_h["Topic"].iloc[0]).strip()
                    f.seek(0)
                except Exception:
                    pass
                raw = read_csv_smart(f)
                raw = raw.rename(columns={"User Email":"Email","Zip_Postal_Code":"Zip/Postal Code"})
                if "Email" not in raw.columns: skipped.append(f.name); continue
                raw["Email"] = raw["Email"].astype(str).str.strip().str.lower()
                m = re.search(r"\d{9,12}", f.name)
                raw["Meeting ID"] = (m.group(0) if m else "")
                raw["_RegTopic"] = reg_topic
                if "Approval Status" in raw.columns:
                    raw = raw[raw["Approval Status"].str.strip().str.lower()=="approved"]
                raw = raw[~raw["Email"].apply(is_staff)]
                rdfs.append(raw)
            except Exception as e:
                skipped.append(f"{f.name} ({e})")
        if rdfs:
            mr = pd.concat(rdfs, ignore_index=True)
            # class name: prefer the topic written INSIDE the registration file (filenames may be
            # renamed and no longer contain the Zoom meeting ID). Fall back to the ID->topic map.
            id_topic = mp.drop_duplicates("Meeting ID").set_index("Meeting ID")["Topic"].to_dict()
            mapped = mr["Meeting ID"].map(id_topic)
            if "_RegTopic" in mr.columns:
                mr["Topic"] = mr["_RegTopic"].where(mr["_RegTopic"].astype(str).str.strip()!="", mapped)
            else:
                mr["Topic"] = mapped

    # ---- BUILD MERGED (participation base + never-attended registrants) ----
    merged = mp.copy()
    merged["Attendance_Status"] = merged["durationMinutesTotal"].apply(
        lambda d: "Attended 20+ Minutes" if d>=20 else
                  ("Attended Under 20 Minutes" if d>0 else "Registered, Not Attended"))

    if mr is not None:
        attended = set(mp["Email"].unique())
        never = mr[~mr["Email"].isin(attended)].drop_duplicates("Email")
        if len(never):
            # use the quarter detected from actual sessions (the current quarter)
            detected_q = mp["Quarter"].dropna()
            detected_q = detected_q[detected_q!="Unknown"].mode()
            quarter_val = detected_q.iloc[0] if len(detected_q) else "Unknown"
            nrows = pd.DataFrame({
                "Email": never["Email"].values,
                "durationMinutesTotal": 0,
                "Topic": never["Topic"].values if "Topic" in never else None,
                "Quarter": quarter_val,
                "Start time": pd.NaT,
                "Meeting ID": never["Meeting ID"].values,
                "Attendance_Status": "Registered, Not Attended",
            })
            for c in ["First Name","Last Name","Phone","Zip/Postal Code"]:
                if c in never.columns: nrows[c] = never[c].values
            merged = pd.concat([merged, nrows], ignore_index=True)

    # ---- PARTICIPANT STATUS ----
    valid = mp[mp["durationMinutesTotal"]>=20]
    pcount = valid.groupby("Email")["session_key"].nunique().reset_index(name="Participation Count")
    dates  = valid.groupby("Email")["Start time"].agg(["min","max"]).reset_index()
    dates.columns = ["Email","First Attended Date","Last Attended Date"]
    levels = (valid.groupby("Email")["Topic"].apply(lambda ts: highest_level(ts))
              .reset_index(name="Highest level"))

    # base list: everyone in registration if available, else everyone who attended
    if mr is not None:
        agg = {}
        for c in ["First Name","Last Name","Phone","Zip/Postal Code"]:
            if c in mr.columns: agg[c] = "first"
        if "Registration Time" in mr.columns: agg["Registration Time"] = "min"
        reg_wk = mr.groupby("Email")["Meeting ID"].nunique().reset_index(name="Total Workshops Registered")
        ps = (mr.groupby("Email").agg(agg).reset_index()
              .merge(reg_wk, on="Email", how="left"))
        if "Registration Time" in ps.columns:
            ps = ps.rename(columns={"Registration Time":"Registration Date"})
    else:
        names = mp[["Email","Name (original name)"]].drop_duplicates("Email") \
                if "Name (original name)" in mp.columns else mp[["Email"]].drop_duplicates()
        ps = names.rename(columns={"Name (original name)":"Display Name"})

    ps = (ps.merge(pcount, on="Email", how="left")
            .merge(dates, on="Email", how="left")
            .merge(levels, on="Email", how="left"))
    ps["Participation Count"] = ps["Participation Count"].fillna(0).astype(int)
    ps["Participation Status"] = ps["Participation Count"].apply(
        lambda x: "Completer" if x>10 else "Non-Completer")

    # Active status — relative to TODAY (live use during a quarter)
    ps["Last Attended Date"] = pd.to_datetime(ps["Last Attended Date"], errors="coerce")
    ps["Days Since Last Attended"] = (pd.Timestamp(date.today()) - ps["Last Attended Date"]).dt.days
    def classify(r):
        d = r["Days Since Last Attended"]
        if pd.isna(d) or r["Participation Count"]==0: return "No Attendance"
        d = int(d)
        if d < 14: return "Active"
        elif d <= 30: return "Inactive"
        else: return "Dropped"
    ps["Active Status"] = ps.apply(classify, axis=1)

    # ---- PER-LEVEL STATUS ----
    # For each level, find each person's most recent 20+ min session in a class
    # of that level, store the date, and classify. Dates are stored so the live
    # view can recompute status against the chosen reference date.
    vlvl = valid.copy()
    vlvl["__level"] = vlvl["Topic"].apply(topic_level)
    for lvl in LEVELS:
        sub = vlvl[vlvl["__level"] == lvl]
        last = sub.groupby("Email")["Start time"].max()
        col_date = f"{lvl} Last"
        ps[col_date] = ps["Email"].map(last.to_dict())
        ps[col_date] = pd.to_datetime(ps[col_date], errors="coerce")
        days = (pd.Timestamp(date.today()) - ps[col_date]).dt.days
        ps[f"{lvl} Status"] = days.apply(classify_days)

    ps = ps.sort_values("Days Since Last Attended", ascending=False, na_position="last")

    ##Last class each person attended (most recent 20+ min session)
    if len(valid):
        last_idx = valid.sort_values("Start time").groupby("Email").tail(1)
        last_class = dict(zip(last_idx["Email"], last_idx["Topic"]))
        ps["Last Class Attended"] = ps["Email"].map(last_class).fillna("")
        # tidy the label (drop the "Tai Chi:" prefix and " ET ..." suffix)
        ps["Last Class Attended"] = ps["Last Class Attended"].apply(
            lambda t: t.split(":")[1].strip().split(" ET")[0] if ":" in str(t) else t)
    else:
        ps["Last Class Attended"] = ""

    return {"merged":merged, "ps":ps, "mr":mr, "skipped":skipped,
            "part_count":len(part_files), "reg_count":len(reg_files or [])}

#Stored File Handling
import io as _io

class StoredFile:
    """Wraps stored bytes so process() can read it like an upload object."""
    def __init__(self, name, content):
        self.name = name
        self._buf = _io.BytesIO(content)
    def seek(self, p): self._buf.seek(p)
    def read(self, *a): return self._buf.read(*a)

def store_file(path, fobj, ftype, quarter):
    """Save raw file bytes into the database."""
    fobj.seek(0)
    content = fobj.read()
    if isinstance(content, str): content = content.encode("utf-8", "replace")
    c = sqlite3.connect(path)
    c.execute("INSERT OR REPLACE INTO stored_files (filename, file_type, quarter, content, added_at) "
              "VALUES (?,?,?,?,datetime('now'))", (fobj.name, ftype, quarter, content))
    c.commit(); c.close()

def list_stored_files(path):
    if not os.path.exists(path): return pd.DataFrame(columns=["filename","file_type","quarter"])
    c = sqlite3.connect(path)
    try:
        df = pd.read_sql("SELECT filename, file_type, quarter, added_at FROM stored_files ORDER BY file_type, filename", c)
    except Exception:
        df = pd.DataFrame(columns=["filename","file_type","quarter"])
    c.close(); return df

def get_stored_files(path):
    """Return (part_files, reg_files) as StoredFile objects from the database."""
    c = sqlite3.connect(path)
    rows = c.execute("SELECT filename, file_type, content FROM stored_files").fetchall()
    c.close()
    part, reg = [], []
    for name, ftype, content in rows:
        sf = StoredFile(name, content)
        (part if ftype=="participation" else reg).append(sf)
    return part, reg

def remove_stored_file(path, filename):
    c = sqlite3.connect(path)
    c.execute("DELETE FROM stored_files WHERE filename=?", (filename,))
    c.commit(); c.close()

def reprocess_from_stored(path):
    """Rebuild attendance + participants from all currently-stored files."""
    part, reg = get_stored_files(path)
    if not part:
        # no participation files left — clear data tables
        c = sqlite3.connect(path)
        c.execute("DELETE FROM attendance"); c.execute("DELETE FROM participants")
        c.commit(); c.close()
        return {"error":"No participation files remain in the database."}
    res = process(part, reg)
    if "error" in res: return res
    q = res["merged"]["Quarter"].dropna()
    q = q[q!="Unknown"].mode()
    quarter = q.iloc[0] if len(q) else "Unknown"
    # full rebuild — clear then save
    c = sqlite3.connect(path)
    c.execute("DELETE FROM attendance"); c.execute("DELETE FROM participants")
    c.commit(); c.close()
    save_db(path, res["merged"], res["ps"], quarter)
    return res

#Database
def init_db(path):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE IF NOT EXISTS attendance(
        email TEXT, first_name TEXT, last_name TEXT, phone TEXT, zip TEXT,
        topic TEXT, quarter TEXT, session_date TEXT, duration REAL,
        status TEXT, meeting_id TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS participants(
        email TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, phone TEXT, zip TEXT,
        reg_date TEXT, total_registered INTEGER, participation_count INTEGER,
        participation_status TEXT, first_attended TEXT, last_attended TEXT,
        days_since INTEGER, active_status TEXT, highest_level TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS loaded_files(
        file_hash TEXT PRIMARY KEY, filename TEXT, quarter TEXT,
        file_type TEXT, loaded_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS comments(
        email TEXT PRIMARY KEY, note TEXT, override_status TEXT,
        absence_start TEXT, absence_end TEXT, participant_type TEXT,
        updated_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS households(
        email_a TEXT, email_b TEXT, household_name TEXT,
        PRIMARY KEY (email_a, email_b))""")
    c.execute("""CREATE TABLE IF NOT EXISTS stored_files(
        filename TEXT PRIMARY KEY, file_type TEXT, quarter TEXT,
        content BLOB, added_at TEXT DEFAULT (datetime('now')))""")
    ##migrate older comments tables that lack participant_type
    cols = [r[1] for r in c.execute("PRAGMA table_info(comments)")]
    if "participant_type" not in cols:
        try: c.execute("ALTER TABLE comments ADD COLUMN participant_type TEXT")
        except Exception: pass
    c.commit(); c.close()

def db_has_data(path):
    try:
        if not os.path.exists(path): return False
        c = sqlite3.connect(path)
        tabs = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "attendance" not in tabs: c.close(); return False
        n = c.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        c.close(); return n > 0
    except Exception: return False

def save_db(path, merged, ps, quarter):
    init_db(path)  # create tables if this is a new database
    c = sqlite3.connect(path)
    att = merged.rename(columns={
        "Email":"email","First Name":"first_name","Last Name":"last_name",
        "Phone":"phone","Zip/Postal Code":"zip","Topic":"topic","Quarter":"quarter",
        "Start time":"session_date","durationMinutesTotal":"duration",
        "Attendance_Status":"status","Meeting ID":"meeting_id"})
    keep = ["email","first_name","last_name","phone","zip","topic","quarter",
            "session_date","duration","status","meeting_id"]
    for k in keep:
        if k not in att.columns: att[k] = ""
    att = att[keep].copy()
    att["duration"] = pd.to_numeric(att["duration"], errors="coerce").fillna(0)
    for col in keep:
        if col != "duration": att[col] = att[col].fillna("").astype(str)
    c.execute("DELETE FROM attendance WHERE quarter=?", (quarter,))
    att.to_sql("attendance", c, if_exists="append", index=False)

    p = ps.rename(columns={
        "Email":"email","First Name":"first_name","Last Name":"last_name",
        "Phone":"phone","Zip/Postal Code":"zip","Registration Date":"reg_date",
        "Total Workshops Registered":"total_registered",
        "Participation Count":"participation_count",
        "Participation Status":"participation_status",
        "First Attended Date":"first_attended","Last Attended Date":"last_attended",
        "Days Since Last Attended":"days_since","Active Status":"active_status",
        "Highest level":"highest_level",
        "Last Class Attended":"last_class"})
    pk = ["email","first_name","last_name","phone","zip","reg_date","total_registered",
          "participation_count","participation_status","first_attended","last_attended",
          "days_since","active_status","highest_level","last_class"]
    # include per-level columns (kept with their original names, e.g. "Level 1 Status")
    level_cols = [f"{lvl} {suf}" for lvl in LEVELS for suf in ("Status", "Last")]
    for lc in level_cols:
        if lc in p.columns: pk.append(lc)
    for k in pk:
        if k not in p.columns: p[k] = ""
    p = p[pk].copy()
    for ic in ["total_registered","participation_count","days_since"]:
        p[ic] = pd.to_numeric(p[ic], errors="coerce").fillna(0).astype(int)
    # date-typed per-level "Last" columns -> store as string
    for lc in level_cols:
        if lc in p.columns and lc.endswith("Last"):
            p[lc] = pd.to_datetime(p[lc], errors="coerce").astype(str).replace("NaT","")
    for col in pk:
        if col not in ["total_registered","participation_count","days_since"] and not col.endswith("Last"):
            p[col] = p[col].fillna("").astype(str)
    p.to_sql("participants", c, if_exists="replace", index=False)
    c.commit(); c.close()

def mark_file(path, fname, quarter, ftype):
    c = sqlite3.connect(path)
    h = hashlib.md5(fname.encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO loaded_files VALUES (?,?,?,?,datetime('now'))",
              (h, fname, quarter, ftype))
    c.commit(); c.close()

def load_db(path):
    c = sqlite3.connect(path)
    merged = pd.read_sql("SELECT * FROM attendance", c)
    ps = pd.read_sql("SELECT * FROM participants", c)
    files = pd.read_sql("SELECT * FROM loaded_files ORDER BY loaded_at DESC", c)
    c.close()
    merged = merged.rename(columns={
        "email":"Email","first_name":"First Name","last_name":"Last Name",
        "phone":"Phone","zip":"Zip/Postal Code","topic":"Topic","quarter":"Quarter",
        "session_date":"Start time","duration":"durationMinutesTotal",
        "status":"Attendance_Status","meeting_id":"Meeting ID"})
    merged["Start time"] = pd.to_datetime(merged["Start time"], errors="coerce")
    ps = ps.rename(columns={
        "email":"Email","first_name":"First Name","last_name":"Last Name",
        "phone":"Phone","zip":"Zip/Postal Code","reg_date":"Registration Date",
        "total_registered":"Total Workshops Registered",
        "participation_count":"Participation Count",
        "participation_status":"Participation Status",
        "first_attended":"First Attended Date","last_attended":"Last Attended Date",
        "days_since":"Days Since Last Attended","active_status":"Active Status",
        "highest_level":"Highest level",
        "last_class":"Last Class Attended"})
    # ensure required columns exist (older databases may be missing some)
    for col, default in [("Last Attended Date", pd.NaT), ("Participation Count", 0),
                          ("First Attended Date", pd.NaT), ("Active Status", "No Attendance"),
                          ("Highest level", "Unknown")]:
        if col not in ps.columns:
            ps[col] = default
    # per-level columns (older DBs won't have them)
    for lvl in LEVELS:
        if f"{lvl} Status" not in ps.columns: ps[f"{lvl} Status"] = "No Attendance"
        if f"{lvl} Last" not in ps.columns:   ps[f"{lvl} Last"] = pd.NaT
        ps[f"{lvl} Last"] = pd.to_datetime(ps[f"{lvl} Last"], errors="coerce")
    # recompute active status from today
    ps["Last Attended Date"] = pd.to_datetime(ps["Last Attended Date"], errors="coerce")
    ps["Participation Count"] = pd.to_numeric(ps["Participation Count"], errors="coerce").fillna(0).astype(int)
    ps["Days Since Last Attended"] = (pd.Timestamp(date.today()) - ps["Last Attended Date"]).dt.days
    def cl(r):
        d = r["Days Since Last Attended"]
        if pd.isna(d) or r["Participation Count"]==0: return "No Attendance"
        d=int(d)
        return "Active" if d<14 else ("Inactive" if d<=30 else "Dropped")
    ps["Active Status"] = ps.apply(cl, axis=1)
    return merged, ps, files

# Database is only created when the user saves data (process or create new)
# — not automatically on startup, so no empty taichi.db appears

#Navigation Helpers
def go(page): st.session_state["page"] = page
def set_flow(f): st.session_state["flow"]=f; st.session_state["page"]="Upload"
def reset():
    for k in ["loaded","merged","ps","mr"]:
        st.session_state[k] = None if k!="loaded" else False
    st.session_state["page"]="Home"; st.session_state["flow"]=None
def open_db():
    try:
        merged, ps, files = load_db(DB_PATH)
        st.session_state.update({"merged":merged,"ps":ps,"loaded":True,"page":"Summary"})
    except Exception as e:
        st.error(f"Could not open database: {e}")

def person_options(psdf):
    """Return (labels, {label: email}) for a type-to-search participant picker."""
    labels = []
    if psdf is None or "Email" not in getattr(psdf, "columns", []):
        return [], {}
    rows = []
    for _, r in psdf.iterrows():
        em = str(r.get("Email","") or "").strip()
        if not em or em == "nan": continue
        nm = f"{r.get('First Name','') or ''} {r.get('Last Name','') or ''}".strip()
        lab = f"{nm} — {em}" if nm else em
        rows.append((nm.lower(), lab, em))
    rows.sort()
    return [l for _, l, _ in rows], {l: e for _, l, e in rows}

#Home Page
if st.session_state["page"]=="Home":
    st.markdown("<div class='page-head'>SBM Falls Prevention — Tai Chi Attendance Dashboard</div>",
                unsafe_allow_html=True)

    dbs = sorted(glob.glob("taichi*.db"))  # only actually-existing databases
    if not dbs:
        st.info("No database yet. Upload a quarter's files to create one, or name a new database below.")
    dc1, dc2 = st.columns([2,1])
    with dc1:
        cur = st.session_state["db_path"]
        if dbs:
            sel = st.selectbox("Database", dbs, index=dbs.index(cur) if cur in dbs else 0)
            if sel != cur:
                st.session_state["db_path"]=sel; st.rerun()
        else:
            st.selectbox("Database", ["(none yet)"], disabled=True)
    with dc2:
        new = st.text_input("Or create new", placeholder="e.g. Spring 2026")
        if st.button("Create & Upload", type="primary"):
            if new.strip():
                st.session_state["db_path"]=f"taichi_{new.strip().replace(' ','_').lower()}.db"
                st.session_state["flow"]="new"
                st.session_state["page"]="Upload"
                st.rerun()
            else:
                st.warning("Type a name first (e.g. Spring 2026)")

    st.write("")
    c1, c3 = st.columns(2)
    with c1:
        n = "stored" if db_has_data(DB_PATH) else "empty"
        st.markdown(f"<div class='card' style='border-top:3px solid #8B0000'>"
                    f"<div class='card-title'>Open Database</div>"
                    f"<div style='font-size:12px;color:#777'>Current database is {n}.</div></div>",
                    unsafe_allow_html=True)
        st.button("Open", key="b_db", on_click=open_db, type="primary",
                  use_container_width=True, disabled=not db_has_data(DB_PATH))
    with c3:
        st.markdown("<div class='card' style='border-top:3px solid #555'>"
                    "<div class='card-title'>Historical Reports</div>"
                    "<div style='font-size:12px;color:#777'>Load prior master report files.</div></div>",
                    unsafe_allow_html=True)
        st.button("Load", key="b_hist", on_click=set_flow, args=("historical",),
                  use_container_width=True)
    st.stop()

#Upload Page
if st.session_state["page"]=="Upload" and not st.session_state["loaded"]:
    st.markdown("<div class='page-head'>Upload Zoom Files</div>", unsafe_allow_html=True)
    st.button("← Back", on_click=reset)

    u1, u2 = st.columns(2)
    with u1:
        st.markdown("**Participation Files** (required)")
        pf = st.file_uploader("participation", type="csv", accept_multiple_files=True,
                              label_visibility="collapsed")
    with u2:
        st.markdown("**Registration Files**")
        rf = st.file_uploader("registration", type="csv", accept_multiple_files=True,
                              label_visibility="collapsed")

    if pf and st.button("Process Files", type="primary"):
        with st.spinner("Processing..."):
            res = process(pf, rf)
        if "error" in res:
            st.error(res["error"])
        else:
            q = res["merged"]["Quarter"].dropna()
            q = q[q!="Unknown"].mode()
            quarter = q.iloc[0] if len(q) else "Unknown"
            save_db(DB_PATH, res["merged"], res["ps"], quarter)
            for f in (pf or []):   mark_file(DB_PATH, f.name, quarter, "participation"); store_file(DB_PATH, f, "participation", quarter)
            for f in (rf or []):   mark_file(DB_PATH, f.name, quarter, "registration"); store_file(DB_PATH, f, "registration", quarter)
            st.session_state.update({"merged":res["merged"], "ps":res["ps"],
                "mr":res["mr"], "loaded":True, "page":"Summary"})
            if res["skipped"]:
                st.warning("Skipped: " + ", ".join(res["skipped"][:5]))
            st.rerun()
    st.stop()

#Loaded — Sidebar + Filters
merged = st.session_state["merged"]
ps     = st.session_state["ps"]

with st.sidebar:
    if os.path.exists("SBTC_dark.png"):
        st.image("SBTC_dark.png", use_container_width=True)
    st.markdown("<div class='sidebar-label'>Navigation</div>", unsafe_allow_html=True)
    for label in ["Summary","Follow-Up List","Attendance Records","Attendance Trends",
                  "Participant Records","Export","Database"]:
        st.button(label, key=f"nav_{label}", on_click=go, args=(label,),
                  use_container_width=True,
                  type="primary" if st.session_state["page"]==label else "secondary")
    st.markdown("<br>", unsafe_allow_html=True)
    st.button("Load Different Data", on_click=reset, use_container_width=True)

    st.markdown("<div class='sidebar-label'>Filters</div>", unsafe_allow_html=True)
    all_q = sorted(merged["Quarter"].dropna().unique()) if "Quarter" in merged.columns else []
    all_q = [q for q in all_q if q and q!="Unknown"]
    all_t = sorted([t for t in merged["Topic"].dropna().unique()
                    if t and len(str(t))>2 and not is_rogue(t)]) if "Topic" in merged.columns else []

    st.markdown("<div class='sidebar-label'>Status Reference</div>", unsafe_allow_html=True)
    status_ref = st.radio("Calculate Active/Inactive/Dropped from",
        ["Today's date", "Last session date"],
        help="Today = live view of who is currently active. Last session = status as of the most recent class (useful after a quarter ends).",
        label_visibility="collapsed")

    sel_q = st.multiselect("Quarter", all_q, default=all_q,
        help="Click the box and type to search a quarter.")
    sel_t = st.multiselect("Class", all_t, default=all_t,
        help="Click the box and type to search a class.")

if not sel_q: sel_q = all_q
if not sel_t: sel_t = all_t

fm = merged.copy()
if sel_q and "Quarter" in fm.columns: fm = fm[fm["Quarter"].isin(sel_q)]
if sel_t and "Topic" in fm.columns:   fm = fm[fm["Topic"].isin(sel_t)]

# Recalculate Active Status based on chosen reference date
if "Last Attended Date" in ps.columns:
    if status_ref == "Last session date":
        ref_date = pd.to_datetime(ps["Last Attended Date"], errors="coerce").max()
        if pd.isna(ref_date): ref_date = pd.Timestamp(date.today())
    else:
        ref_date = pd.Timestamp(date.today())
    ps = ps.copy()
    ps["Days Since Last Attended"] = (ref_date - pd.to_datetime(ps["Last Attended Date"], errors="coerce")).dt.days
    def _classify(r):
        d = r["Days Since Last Attended"]
        if pd.isna(d) or r.get("Participation Count",0)==0: return "No Attendance"
        d=int(d)
        return "Active" if d<14 else ("Inactive" if d<=30 else "Dropped")
    ps["Active Status"] = ps.apply(_classify, axis=1)

    # Recompute per-level status against the same reference date
    for lvl in LEVELS:
        lcol = f"{lvl} Last"
        if lcol in ps.columns:
            ldays = (ref_date - pd.to_datetime(ps[lcol], errors="coerce")).dt.days
            ps[f"{lvl} Status"] = ldays.apply(classify_days)
    try:
        if os.path.exists(DB_PATH):
            ch = sqlite3.connect(DB_PATH)
            hh = pd.read_sql("SELECT email_a, email_b FROM households", ch)
            ch.close()
            if len(hh):
                last_map = dict(zip(ps["Email"], pd.to_datetime(ps["Last Attended Date"], errors="coerce")))
                status_map = dict(zip(ps["Email"], ps["Active Status"]))
                for _, row in hh.iterrows():
                    a, b = row["email_a"], row["email_b"]
                    # whichever attended most recently — both inherit that status
                    da, db_ = last_map.get(a), last_map.get(b)
                    best = max([d for d in [da, db_] if pd.notna(d)], default=pd.NaT)
                    if pd.notna(best):
                        best_status = "Active" if (ref_date - best).days < 14 else \
                                      ("Inactive" if (ref_date - best).days <= 30 else "Dropped")
                        for e in [a, b]:
                            if e in status_map:
                                ps.loc[ps["Email"]==e, "Active Status"] = best_status
    except Exception:
        pass

    ##Apply On Hold flags + surface notes / participant type / household into the list
    ps["On Hold"] = "No"
    ps["Comments"] = ""
    ps["Participant Type"] = "Participant"
    ps["Household"] = ""
    try:
        if os.path.exists(DB_PATH):
            cc = sqlite3.connect(DB_PATH)
            cmts = pd.read_sql("SELECT * FROM comments", cc)
            hh = pd.read_sql("SELECT email_a, household_name FROM households", cc)
            cc.close()
            today = pd.Timestamp(date.today())
            for _, cm in cmts.iterrows():
                em = cm["email"]
                note = str(cm.get("note") or "")
                if note:
                    ps.loc[ps["Email"]==em, "Comments"] = note
                ptype = str(cm.get("participant_type") or "").strip()
                if ptype:
                    ps.loc[ps["Email"]==em, "Participant Type"] = ptype
                ov = str(cm.get("override_status") or "").strip().lower()
                if ov == "on hold":
                    h_end = pd.to_datetime(cm.get("absence_end"), errors="coerce")
                    # auto-clear once the hold's end date has passed
                    if pd.isna(h_end) or today <= h_end:
                        ps.loc[ps["Email"]==em, "On Hold"] = "Yes"
            # household family name
            if len(hh):
                hmap = dict(zip(hh["email_a"], hh["household_name"]))
                ps["Household"] = ps["Email"].map(hmap).fillna("")
    except Exception:
        pass

    st.session_state["ps"] = ps

page = st.session_state["page"]

#Summary
if page=="Summary":
    st.markdown("<div class='page-head'>Summary</div>", unsafe_allow_html=True)

    attended = fm[fm["Attendance_Status"]=="Attended 20+ Minutes"]
    total_p  = len(ps)
    uniq_att = attended["Email"].nunique()
    comp     = (ps["Participation Count"]>10).sum()
    avg      = attended.groupby("Email").size().mean() if len(attended) else 0

    m = st.columns(4)
    for col, num, lbl in zip(m,
        [f"{total_p:,}", f"{uniq_att:,}", f"{comp:,}", f"{avg:.1f}"],
        ["Total Participants","Unique Attendees 20+ Min","Completers (10+)","Avg Sessions / Person"]):
        col.markdown(f"<div class='metric-card'><div class='metric-num'>{num}</div>"
                     f"<div class='metric-lbl'>{lbl}</div></div>", unsafe_allow_html=True)

    st.write("")
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("<div class='card'><div class='card-title'>Avg Attendance per Session by Class</div>",
                    unsafe_allow_html=True)
        if len(attended) and "Start time" in attended.columns:
            per = attended.groupby(["Topic","Start time"])["Email"].nunique().reset_index(name="n")
            avgc = per.groupby("Topic")["n"].mean().round(1).sort_values(ascending=False)
            avgc.index = [i.split(":")[1].strip().split(" ET")[0] if ":" in i else i for i in avgc.index]
            st.bar_chart(avgc, height=300, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with g2:
        st.markdown("<div class='card'><div class='card-title'>Unique Attendees by Quarter</div>",
                    unsafe_allow_html=True)
        if len(attended):
            uq = attended.groupby("Quarter")["Email"].nunique()
            st.bar_chart(uq, height=300, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Participant Status & Level Breakdown", expanded=True):
        def _bars(pairs):
            mx = max([c for _, c in pairs], default=1) or 1
            html = ""
            for lab, c in pairs:
                pct = int(round(c / mx * 100))
                html += (f"<div class='prog-row'><div class='prog-top'><span>{lab}</span>"
                         f"<b>{c:,}</b></div><div class='prog-track'>"
                         f"<div class='prog-fill' style='width:{pct}%'></div></div></div>")
            return html
        b1, b2 = st.columns(2)
        with b1:
            st.markdown("<div class='card-title'>Participants by Attendance Status</div>", unsafe_allow_html=True)
            pairs = [("Completer (10+)", int((ps["Participation Count"]>10).sum())),
                     ("Non-Completer", int(((ps["Participation Count"]<=10)&(ps["Participation Count"]>0)).sum())),
                     ("No Attendance", int((ps["Participation Count"]==0).sum()))]
            st.markdown(_bars(pairs), unsafe_allow_html=True)
        with b2:
            st.markdown("<div class='card-title'>Highest Tai Chi Level Reached</div>", unsafe_allow_html=True)
            if "Highest level" in ps.columns:
                lc = ps["Highest level"].value_counts()
                lc = lc[~lc.index.str.lower().isin(["unknown",""])]
                st.markdown(_bars([(str(i), int(v)) for i, v in lc.items()]), unsafe_allow_html=True)

#Follow-Up List
elif page=="Follow-Up List":
    st.markdown("<div class='page-head'>Participant Follow-Up List</div>", unsafe_allow_html=True)

    f1, f2 = st.columns([1,2])
    sf = f1.selectbox("Status", ["All","Active","Inactive","Dropped","No Attendance"])
    _labels, _emap = person_options(ps)
    picked = f2.selectbox("Search participant (type a name or an email)", [""] + _labels, key="fu_pick")
    sel_email = _emap.get(picked)

    disp = ps if sf == "All" else ps[ps["Active Status"] == sf]
    if sel_email:
        disp = disp[disp["Email"]==sel_email]

    cols = [c for c in ["Email","First Name","Last Name","Phone","Active Status","On Hold",
            "Last Attended Date","Days Since Last Attended","Last Class Attended",
            "Participant Type","Household","Comments"]
            if c in disp.columns]

    st.dataframe(disp[cols], use_container_width=True, height=520, hide_index=True)
    st.caption(f"{len(disp)} participants")
    st.download_button("Download (.csv)", disp[cols].to_csv(index=False).encode(),
                       f"FollowUp_{sf}_{date.today()}.csv", "text/csv")

    ##Participant detail — driven by the search box above
    st.markdown("<div class='card'><div class='card-title'>View Participant Detail</div>", unsafe_allow_html=True)
    if not sel_email:
        st.caption("Pick a participant above (type their name or email) to see their full detail here.")
    else:
        em = sel_email

        person_rows = merged[merged["Email"]==em] if "Email" in merged.columns else pd.DataFrame()
        reg_classes = sorted([t for t in person_rows["Topic"].dropna().unique()
                              if t and not is_rogue(t)]) if "Topic" in person_rows.columns else []
        hist = person_rows[person_rows["durationMinutesTotal"]>=20].copy() if "durationMinutesTotal" in person_rows.columns else pd.DataFrame()

        d1, d2 = st.columns(2)
        with d1:
            st.markdown("**Registered / Attended Classes**")
            if reg_classes:
                for t in reg_classes:
                    st.markdown(f"- {t.split(':')[1].strip() if ':' in t else t}")
            else:
                st.caption("No class records found.")
        with d2:
            prow = ps[ps["Email"]==em]
            if len(prow):
                pr = prow.iloc[0]
                st.markdown("**Status Summary**")
                st.markdown(f"- Active Status: **{pr.get('Active Status','—')}**")
                st.markdown(f"- On Hold: **{pr.get('On Hold','No')}**")
                for lvl in LEVELS:
                    sval = pr.get(f"{lvl} Status")
                    if sval and sval != "No Attendance":
                        st.markdown(f"- {lvl}: **{sval}**")
                st.markdown(f"- Sessions attended: **{int(pr.get('Participation Count',0))}**")
                la = pr.get("Last Attended Date","")
                st.markdown(f"- Last attended: **{str(la)[:10] if pd.notna(la) else '—'}**")
                st.markdown(f"- Highest level: **{pr.get('Highest level','—')}**")
                #participant type (only when not a regular participant)
                ptype = str(pr.get("Participant Type","") or "").strip()
                if ptype and ptype != "Participant":
                    st.markdown(f"- Participant type: **{ptype}**")
                #household members — who else is in their family
                try:
                    hc = sqlite3.connect(DB_PATH)
                    hrows = pd.read_sql("SELECT email_a, email_b, household_name FROM households WHERE email_a=? OR email_b=?", hc, params=(em, em))
                    hc.close()
                    partners = []
                    seen = set()
                    for _, hr in hrows.iterrows():
                        other = hr["email_b"] if hr["email_a"]==em else hr["email_a"]
                        if not other or other==em or other in seen: continue
                        seen.add(other)
                        onm = ps[ps["Email"]==other]
                        oname = f"{onm['First Name'].iloc[0]} {onm['Last Name'].iloc[0]}".strip() if len(onm) and "First Name" in onm.columns else other
                        partners.append(f"{oname or other} ({other})")
                    if partners:
                        hhname = hrows.iloc[0]["household_name"] if len(hrows) and hrows.iloc[0]["household_name"] else ""
                        self_nm = f"{pr.get('First Name','') or ''} {pr.get('Last Name','') or ''}".strip() or em
                        members = [f"{self_nm} ({em})"] + partners
                        st.markdown(f"- Household{f' ({hhname})' if hhname else ''}: **" + "; ".join(members) + "**")
                except Exception:
                    pass

        if len(hist):
            st.markdown("**Attendance History**")
            h = hist[["Topic","Start time","durationMinutesTotal"]].copy()
            h["Topic"] = h["Topic"].apply(lambda t: t.split(":")[1].strip() if ":" in str(t) else t)
            h = h.rename(columns={"Start time":"Date","durationMinutesTotal":"Minutes"})
            h["Date"] = pd.to_datetime(h["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
            st.dataframe(h.sort_values("Date", ascending=False), use_container_width=True, hide_index=True, height=200)
    st.markdown("</div>", unsafe_allow_html=True)

#Attendance Records
elif page=="Attendance Records":
    st.markdown("<div class='page-head'>Attendance Records</div>", unsafe_allow_html=True)

    show = st.radio("Filter", ["All","Attended 20+ Minutes","Attended Under 20 Minutes"],
                    horizontal=True, label_visibility="collapsed")
    d = fm if show=="All" else fm[fm["Attendance_Status"]==show]
    cols = [c for c in ["Email","Topic","Quarter","Start time","durationMinutesTotal","Attendance_Status"]
            if c in d.columns]
    disp = d[cols].rename(columns={"durationMinutesTotal":"Total Minutes","Start time":"Session Date"})
    if "Session Date" in disp.columns:
        disp = disp.sort_values("Session Date", ascending=False, na_position="last")
    st.dataframe(disp, use_container_width=True, height=520, hide_index=True)
    st.caption(f"{len(disp)} records")
    st.download_button("Download (.csv)", disp.to_csv(index=False).encode(),
                       f"Attendance_{date.today()}.csv", "text/csv")

#Export
elif page=="Export":
    st.markdown("<div class='page-head'>Export Reports</div>", unsafe_allow_html=True)
    st.write("Download the full report workbook with all data as separate sheets.")

    import io
    buf = io.BytesIO()
    attended20 = fm[fm["Attendance_Status"]=="Attended 20+ Minutes"] if "Attendance_Status" in fm.columns else fm.iloc[0:0]
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xl:
        wrote = []

        #Summary metrics
        try:
            pc = ps["Participation Count"] if "Participation Count" in ps.columns else pd.Series(dtype=float)
            metrics = pd.DataFrame({
                "Metric":["Total Participants","Unique Attendees (20+ min)","Completers (10+)","Avg Sessions / Person"],
                "Value":[len(ps), attended20["Email"].nunique(),
                         int((pc>=10).sum()) if len(pc) else 0,
                         round(float(pc.mean()),1) if len(pc) else 0]})
            metrics.to_excel(xl, sheet_name="Summary", index=False); wrote.append("Summary")
        except Exception: pass

        #Participant Status (everyone, no-shows included)
        try:
            fu_cols = [c for c in ["Email","First Name","Last Name","Phone","Participant Type",
                       "Participation Count","Participation Status","Active Status","On Hold",
                       "Last Attended Date","Days Since Last Attended","Last Class Attended",
                       "Highest level","Household","Comments"] if c in ps.columns]
            ps[fu_cols].to_excel(xl, sheet_name="Participant Status", index=False); wrote.append("Participant Status")
        except Exception: pass

        #No-Shows (registered but never attended a single class)
        try:
            if "Active Status" in ps.columns:
                #No-Shows: registered but never attended a single class (not time-gated)
                fdf = ps[ps["Active Status"]=="No Attendance"].copy()
                def _short_t(t):
                    return t.split(":")[1].strip().split(" ET")[0] if ":" in str(t) else str(t)
                reg_by_email = {}
                if "Topic" in fm.columns and "Email" in fm.columns:
                    for em, grp in fm.groupby("Email"):
                        reg_by_email[em] = ", ".join(sorted({_short_t(t) for t in grp["Topic"].dropna().unique()}))
                fdf["Registered Classes Not Attending"] = fdf["Email"].map(reg_by_email).fillna("")
                ns_cols = [c for c in ["First Name","Last Name","Email","Phone","Active Status",
                           "Registered Classes Not Attending","On Hold","Comments"] if c in fdf.columns]
                fdf[ns_cols].to_excel(xl, sheet_name="No-Shows", index=False)
                wrote.append("No-Shows")
        except Exception: pass

        #By Class: average attendance per session
        try:
            if "Topic" in attended20.columns and len(attended20):
                bc = attended20.groupby("Topic").agg(Attendances=("Email","count"),
                        Sessions=("Start time","nunique"), Unique_People=("Email","nunique"))
                bc["Avg per Session"] = (bc["Attendances"]/bc["Sessions"].clip(lower=1)).round(1)
                bc.reset_index().to_excel(xl, sheet_name="By Class", index=False); wrote.append("By Class")
        except Exception: pass

        #Attendance By Topic (per-person session counts)
        try:
            if "Topic" in attended20.columns and len(attended20):
                bt = attended20.pivot_table(index="Email", columns="Topic", values="durationMinutesTotal",
                                     aggfunc="count", fill_value=0).reset_index()
                bt.to_excel(xl, sheet_name="Attendance By Topic", index=False); wrote.append("Attendance By Topic")
        except Exception: pass

        #Attendance Records (raw sessions)
        try:
            rec = fm[[c for c in ["Email","Topic","Quarter","Start time","durationMinutesTotal","Attendance_Status"]
                      if c in fm.columns]]
            rec.to_excel(xl, sheet_name="Attendance Records", index=False); wrote.append("Attendance Records")
        except Exception: pass

        #Households (family links with names)
        try:
            hc = sqlite3.connect(DB_PATH)
            hh = pd.read_sql("SELECT email_a, email_b, household_name FROM households", hc)
            hc.close()
            if len(hh):
                def _nm(e):
                    r = ps[ps["Email"]==e]
                    return (f"{r['First Name'].iloc[0]} {r['Last Name'].iloc[0]}".strip()
                            if len(r) and "First Name" in r.columns else e)
                hh.insert(0, "Person A", hh["email_a"].map(_nm))
                hh.insert(2, "Person B", hh["email_b"].map(_nm))
                hh = hh.rename(columns={"email_a":"Email A","email_b":"Email B","household_name":"Household"})
                hh.to_excel(xl, sheet_name="Households", index=False); wrote.append("Households")
        except Exception: pass

        #safety: never write an empty workbook
        if not wrote:
            ps.to_excel(xl, sheet_name="Participant Status", index=False)
    st.download_button("Download Full Workbook (.xlsx)", buf.getvalue(),
                       f"TaiChi_Report_{date.today()}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")

#Attendance Trends
elif page=="Attendance Trends":
    st.markdown("<div class='page-head'>Attendance Trends</div>", unsafe_allow_html=True)

    if "Topic" not in fm.columns or "Start time" not in fm.columns:
        st.info("Session date data not available.")
    else:
        att = fm[fm["durationMinutesTotal"]>=20].copy()
        att["Session Date"] = pd.to_datetime(att["Start time"], errors="coerce")
        att["Week"]  = att["Session Date"].dt.to_period("W").astype(str)
        att["Month"] = att["Session Date"].dt.strftime("%b %Y")
        topics = sorted([t for t in att["Topic"].dropna().unique()
                         if t and len(str(t))>2 and not is_rogue(t)])
        if not topics:
            st.info("No class data available.")
        else:
            mode = st.radio("Group attendance by", ["Class", "Level"], horizontal=True, key="at_mode")

            # date-range filter (defaults to the full span so the first view shows everything)
            att_dates = pd.to_datetime(att["Session Date"], errors="coerce").dropna()
            dmin = att_dates.min().date() if len(att_dates) else date.today()
            dmax = att_dates.max().date() if len(att_dates) else date.today()
            #keep prior picks valid if the dataset changed
            for _k,_def in [("at_from",dmin),("at_to",dmax)]:
                if _k in st.session_state and not (dmin <= st.session_state[_k] <= dmax):
                    st.session_state[_k] = _def
            dc1, dc2 = st.columns(2)
            from_d = dc1.date_input("From", value=dmin, min_value=dmin, max_value=dmax, key="at_from")
            to_d   = dc2.date_input("To",   value=dmax, min_value=dmin, max_value=dmax, key="at_to")

            if mode == "Class":
                _opts = ["All Classes"] + topics
                if st.session_state.get("at_class") not in _opts: st.session_state.pop("at_class", None)
                sel = st.selectbox("Select class", _opts, key="at_class")
                if sel == "All Classes":
                    cdf = att.copy(); unit_label = "All Classes"
                else:
                    cdf = att[att["Topic"]==sel].copy()
                    unit_label = sel.split(":")[1].strip() if ":" in sel else sel
            else:
                lvls_present = [l for l in LEVELS
                                if att["Topic"].apply(topic_level).eq(l).any()]
                _lopts = ["All Levels"] + lvls_present
                if st.session_state.get("at_level") not in _lopts: st.session_state.pop("at_level", None)
                sel = st.selectbox("Select level", _lopts, key="at_level")
                if sel == "All Levels":
                    cdf = att.copy(); unit_label = "All Levels"
                else:
                    cdf = att[att["Topic"].apply(topic_level)==sel].copy()
                    unit_label = sel

            # keep the full unit history (for first-timer detection), then apply the date range
            cdf_full = cdf.copy()
            _sd = pd.to_datetime(cdf["Session Date"], errors="coerce")
            cdf = cdf[(_sd.dt.date >= from_d) & (_sd.dt.date <= to_d)].copy()

            if len(cdf):
                view = st.radio("View by", ["Week","Month"], horizontal=True, key="at_view")
                gcol = "Week" if view=="Week" else "Month"
                gdata = cdf.groupby(gcol)["Email"].nunique().reset_index(name="Attendees")
                if view=="Month":
                    gdata["s"] = pd.to_datetime(gdata["Month"], format="%b %Y", errors="coerce")
                    gdata = gdata.sort_values("s").drop(columns="s")
                else:
                    gdata = gdata.sort_values(gcol)

                ##Overall attendance chart (top, prominent)
                st.markdown(f"<div class='card'><div class='card-title'>Attendance by {view} — {unit_label}</div>", unsafe_allow_html=True)
                st.bar_chart(gdata.set_index(gcol)["Attendees"], height=380, use_container_width=True)
                if len(gdata)>1:
                    gdata["prev"] = gdata["Attendees"].shift(1)
                    gdata["drop"] = ((gdata["prev"]-gdata["Attendees"])/gdata["prev"].replace(0,1)*100).round(0)
                    for _, d in gdata[gdata["drop"]>20].iterrows():
                        st.warning(f"{d[gcol]}: down {int(d['drop'])}% ({int(d['prev'])} → {int(d['Attendees'])} attendees)")
                st.markdown("</div>", unsafe_allow_html=True)

                ##First-timer vs returner (all sessions in the selected timeframe)
                sdates = sorted(cdf["Session Date"].dropna().dt.date.unique())
                if sdates:
                    st.markdown("<div class='card'><div class='card-title'>First-Timers vs Returners</div>", unsafe_allow_html=True)
                    st.caption("First-Timer means it was their first-ever session here; Returner had attended before. Shown for every session in the selected dates.")
                    # each person's first-ever session date in this unit (across all time, not just the window)
                    first_ever = cdf_full.groupby("Email")["Session Date"].min().dt.date.to_dict()
                    rows = []
                    for sd in sdates:
                        day = set(cdf[cdf["Session Date"].dt.date==sd]["Email"])
                        ft = {e for e in day if first_ever.get(e)==sd}
                        rows.append({"Session": str(sd), "First-Timers": len(ft), "Returners": len(day)-len(ft)})
                    st.bar_chart(pd.DataFrame(rows).set_index("Session"), height=300, use_container_width=True)

                    pick = st.selectbox("View participant list for session", [str(s) for s in sdates])
                    pd_pick = pd.Timestamp(pick).date()
                    day_em = set(cdf[cdf["Session Date"].dt.date==pd_pick]["Email"])
                    lst = []
                    for em in day_em:
                        nr = ps[ps["Email"]==em]
                        nm = f"{nr['First Name'].iloc[0]} {nr['Last Name'].iloc[0]}".strip() if len(nr) and "First Name" in nr.columns else em
                        lst.append({"Name": nm or em, "Email": em,
                                    "Status": "First-Timer" if first_ever.get(em)==pd_pick else "Returner"})
                    st.dataframe(pd.DataFrame(lst).sort_values("Status"), use_container_width=True, hide_index=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                ##Session-by-session attendance grid
                st.markdown(f"<div class='card'><div class='card-title'>Session-by-Session Attendance — {unit_label}</div>", unsafe_allow_html=True)
                sess = sorted(cdf["Session Date"].dropna().dt.normalize().unique())
                if not sess:
                    st.caption("No sessions in the selected range.")
                else:
                    #flag basis: whole weeks (forgives skipping one class in a week) or single sessions
                    flag_by = st.radio("Flag absences by", ["Week","Session"], horizontal=True, key="at_flagby",
                        help="A person is judged only on the classes they attend, across the dates shown. Week: flag after missing 3 full weeks in a row. Session: flag after 3 missed meetings in a row.")

                    cur_topics = set(cdf["Topic"].dropna().unique())
                    present_by = {d: set(cdf[cdf["Session Date"].dt.normalize()==d]["Email"]) for d in sess}

                    #per-topic attendance within the visible window (for own-class and cross-class checks)
                    win_lo, win_hi = pd.Timestamp(sess[0]), pd.Timestamp(sess[-1])
                    attw = att[(att["Session Date"].dt.normalize()>=win_lo) & (att["Session Date"].dt.normalize()<=win_hi)]
                    tdates, tpres, tpeople = {}, {}, {}
                    for t in attw["Topic"].dropna().unique():
                        sub = attw[attw["Topic"]==t]
                        ds = sorted(sub["Session Date"].dt.normalize().unique())
                        tdates[t] = ds
                        tpres[t] = {d: set(sub[sub["Session Date"].dt.normalize()==d]["Email"]) for d in ds}
                        tpeople[t] = set(sub["Email"].dropna().unique())

                    def _wk(d): return str(pd.Timestamp(d).to_period("W"))

                    def _flag_person(em, topics_set, by, min_consec=3):
                        if not topics_set: return False
                        dates = sorted(set().union(*[set(tdates.get(t,[])) for t in topics_set]))
                        if not dates: return False
                        if by=="Week":
                            keys = sorted(set(_wk(d) for d in dates))
                            present = set(_wk(d) for t in topics_set for d in tdates.get(t,[]) if em in tpres[t][d])
                        else:
                            keys = dates
                            present = set(d for t in topics_set for d in tdates.get(t,[]) if em in tpres[t][d])
                        if len(keys) < min_consec: return False
                        run = 0
                        for k in reversed(keys):
                            if k in present: break
                            run += 1
                        return run >= min_consec

                    #here (attended in the shown window) vs no-show (registered but never attended at all)
                    attended_here = set(cdf["Email"].dropna().unique())
                    #No-show is judged PER CLASS: registered for a class but never attended THAT class.
                    #The level's list is the union of its classes, so it can't be smaller than any one class.
                    noshow_here = set()
                    if "Topic" in fm.columns:
                        for _t in cur_topics:
                            reg_t = set(fm[fm["Topic"]==_t]["Email"].dropna())
                            att_t = set(att[att["Topic"]==_t]["Email"].dropna())
                            noshow_here |= (reg_t - att_t)
                    people = sorted(attended_here | noshow_here)

                    #flag: judge each person only on the classes they attend, within the window shown
                    ptopic_map = cdf.groupby("Email")["Topic"].agg(lambda s: set(s)).to_dict()
                    flagged_here = set()
                    for em in attended_here:
                        own = ptopic_map.get(em, set()) & cur_topics
                        if own and _flag_person(em, own, flag_by):
                            flagged_here.add(em)

                    ##Cross-class: still keeping up in another class means not a real follow-up
                    active_elsewhere = {}
                    other_topics = [t for t in tdates if t not in cur_topics]
                    for em in people:
                        for t in other_topics:
                            if em in tpeople.get(t, set()) and not _flag_person(em, {t}, flag_by):
                                short = t.split(":")[1].strip().split(" ET")[0] if ":" in t else t
                                active_elsewhere.setdefault(em, []).append(short)

                    nm = ps.set_index("Email") if "Email" in ps.columns else pd.DataFrame()
                    comments_map = dict(zip(ps["Email"], ps["Comments"])) if "Comments" in ps.columns else {}
                    ptype_map = dict(zip(ps["Email"], ps["Participant Type"])) if "Participant Type" in ps.columns else {}

                    date_cols = [pd.Timestamp(d).strftime("%a %b %d") for d in sess]
                    rows = []
                    meta = {}
                    for em in people:
                        attended = [d for d in sess if em in present_by[d]]
                        nm_txt = (f"{nm.loc[em,'First Name']} {nm.loc[em,'Last Name']}".strip()
                                  if em in nm.index and "First Name" in nm.columns else em) or em
                        is_flagged = (em in flagged_here) or (em in noshow_here)
                        elsewhere = sorted(set(active_elsewhere.get(em, [])))
                        #Rule A: absent from THIS class/level = flagged, regardless of other classes.
                        #Active elsewhere only adds a note; it never removes them from the list.
                        priority = is_flagged
                        row = {"Participant": nm_txt, "Email": em}
                        for d, c in zip(sess, date_cols):
                            row[c] = "attended" if em in present_by[d] else ""
                        row["Seen"] = f"{len(attended)} of {len(sess)}"
                        row["Cross-class"] = ("active in " + ", ".join(elsewhere)) if (is_flagged and elsewhere) else ""
                        row["Participant Type"] = ptype_map.get(em, "Participant")
                        row["Comments"] = comments_map.get(em, "")
                        rows.append(row)
                        meta[nm_txt] = (priority, is_flagged and bool(elsewhere))
                    grid = pd.DataFrame(rows)

                    ##Optional: collapse to just the people who have been missing
                    only_flagged = st.checkbox("Show flagged only (missed the last 3 in a row)", value=False, key="at_flaggedonly")
                    if only_flagged:
                        keep = [n for n in grid["Participant"] if meta.get(n,(False,False))[0] or meta.get(n,(False,False))[1]]
                        grid = grid[grid["Participant"].isin(keep)]

                    grid = grid.sort_values("Participant").reset_index(drop=True)

                    disp_cols = ["Participant","Email","Participant Type"] + date_cols + ["Seen","Cross-class","Comments"]
                    def _style(_):
                        sty = pd.DataFrame("", index=grid.index, columns=disp_cols)
                        for c in date_cols:
                            sty[c] = grid[c].map(lambda v: "background-color:#DEF2EA;color:#0F6E56" if v=="attended" else "background-color:#F6F6F4")
                        for i in grid.index:
                            pr, _ae = meta.get(grid.at[i,"Participant"], (False,False))
                            if pr: sty.at[i,"Participant"] = "background-color:#FAEEDA;color:#633806;font-weight:600"
                        return sty
                    disp = grid[disp_cols].copy()
                    for c in date_cols:
                        disp[c] = disp[c].map(lambda v: "✓" if v=="attended" else "")
                    st.dataframe(disp.style.apply(_style, axis=None), use_container_width=True, hide_index=True, height=460)

                    #export to Excel so nothing gets reformatted on open (dates, counts, etc.)
                    dl_cols = ["Participant","Email","Participant Type"] + date_cols + ["Seen","Cross-class","Comments"]
                    out = grid[dl_cols].copy()
                    for c in date_cols:
                        out[c] = out[c].map(lambda v: "Present" if v=="attended" else "")
                    xbuf = io.BytesIO()
                    with pd.ExcelWriter(xbuf, engine="xlsxwriter") as xw:
                        out.to_excel(xw, sheet_name="Attendance", index=False)
                        wb, wsx = xw.book, xw.sheets["Attendance"]
                        txt = wb.add_format({"num_format":"@"})
                        hdr = wb.add_format({"bold":True,"bg_color":"#8A1A1A","font_color":"#FFFFFF","border":1})
                        for ci, cname in enumerate(out.columns):
                            wsx.write(0, ci, cname, hdr)
                            width = 26 if cname in ("Participant","Email","Cross-class","Comments") else 12
                            wsx.set_column(ci, ci, width, txt)
                        #carry the on-screen amber highlight into the file for flagged names
                        amber = wb.add_format({"num_format":"@","bg_color":"#FAEEDA","font_color":"#633806","bold":True})
                        for i in out.index:
                            pr, _s = meta.get(out.at[i,"Participant"], (False,False))
                            if pr:
                                wsx.write(i+1, 0, out.at[i,"Participant"], amber)
                        wsx.freeze_panes(1, 0)
                    st.download_button("Download roster (.xlsx)", xbuf.getvalue(),
                        f"Roster_{unit_label.replace(' ','_')}_{date.today()}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                st.markdown("</div>", unsafe_allow_html=True)

#Comments & Households
elif page=="Participant Records":
    st.markdown("<div class='page-head'>Participant Records</div>", unsafe_allow_html=True)
    init_db(DB_PATH)
    conn = sqlite3.connect(DB_PATH)

    st.markdown("<div class='card'><div class='card-title'>Add or Update a Note</div>", unsafe_allow_html=True)
    n1, n2 = st.columns([2,1])
    _plabels, _pemap = person_options(ps)
    _ppick = n1.selectbox("Find participant (type a name or an email)", [""] + _plabels, key="pr_pick")
    note_email = (_pemap.get(_ppick) or n1.text_input("Or enter email manually").strip().lower())
    on_hold = n2.checkbox("Mark as On Hold")
    ptype = st.selectbox("Participant type",
        ["Participant","Instructor","Tech support","Student observer","Non-participant"])
    st.caption("Participant type lets you flag someone who isn't a regular participant. On Hold keeps the person in the follow-up list but flags them so you know not to reach out; it clears automatically after the 'until' date.")
    note_text = st.text_area("Note", placeholder="e.g. On vacation, will return May 1. / Already spoke by phone.")
    ab1, ab2 = st.columns(2)
    hold_start = ab1.date_input("On Hold from", value=None)
    hold_end   = ab2.date_input("On Hold until", value=None)
    if st.button("Save Note", type="primary"):
        if not note_email:
            st.warning("Enter a participant email.")
        elif on_hold and not hold_end:
            st.warning("An 'On Hold until' date is required when marking someone On Hold.")
        else:
            conn.execute("""INSERT OR REPLACE INTO comments
                (email, note, override_status, absence_start, absence_end, participant_type, updated_at)
                VALUES (?,?,?,?,?,?,datetime('now'))""",
                (note_email, note_text, "On Hold" if on_hold else "",
                 str(hold_start) if hold_start else "", str(hold_end) if hold_end else "", ptype))
            conn.commit()
            st.success(f"Saved record for {note_email}")
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    cmts = pd.read_sql("SELECT * FROM comments ORDER BY updated_at DESC", conn)
    if len(cmts):
        st.markdown("<div class='card'><div class='card-title'>Existing Records</div>", unsafe_allow_html=True)
        disp = cmts.rename(columns={"email":"Email","note":"Note","override_status":"On Hold",
                                     "absence_start":"Hold From","absence_end":"Hold Until",
                                     "participant_type":"Participant Type"})
        disp["On Hold"] = disp["On Hold"].apply(lambda v: "Yes" if str(v).strip().lower()=="on hold" else "No")
        if "Participant Type" not in disp.columns: disp["Participant Type"] = "Participant"
        disp["Participant Type"] = disp["Participant Type"].replace("", "Participant").fillna("Participant")
        st.dataframe(disp[["Email","Participant Type","Note","On Hold","Hold From","Hold Until"]],
                     use_container_width=True, hide_index=True)
        rm1, rm2 = st.columns([2,1])
        rm_email = rm1.selectbox("Remove a record", cmts["email"].tolist(),
                                 index=None, placeholder="Choose a participant...")
        if rm2.button("Remove Record") and rm_email:
            conn.execute("DELETE FROM comments WHERE email=?", (rm_email,))
            conn.commit()
            st.success(f"Removed note for {rm_email}")
            st.rerun()
        st.download_button("Download Notes (.csv)", disp.to_csv(index=False).encode(),
                           f"Comments_{date.today()}.csv", "text/csv")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'><div class='card-title'>Linked Households</div>", unsafe_allow_html=True)
    st.caption("Link two emails (e.g. Mr. & Ms. Vincenzo) so that if one attends, both stay active.")
    hh = pd.read_sql("SELECT DISTINCT household_name, email_a, email_b FROM households", conn)

    # show current links
    if len(hh):
        st.dataframe(hh.rename(columns={"household_name":"Household","email_a":"Email 1","email_b":"Email 2"}),
                     use_container_width=True, hide_index=True)

    # add a new household
    st.markdown("**Add a new household**")
    a1, a2, a3, a4 = st.columns([2,2,2,1])
    ne1 = a1.text_input("Email 1", key="ne1").strip().lower()
    ne2 = a2.text_input("Email 2", key="ne2").strip().lower()
    nnm = a3.text_input("Family name", key="nnm")
    a4.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if a4.button("Add") and ne1 and ne2 and ne1 != ne2:
        conn.execute("INSERT OR REPLACE INTO households VALUES (?,?,?)", (ne1,ne2,nnm))
        conn.execute("INSERT OR REPLACE INTO households VALUES (?,?,?)", (ne2,ne1,nnm))
        conn.commit(); st.success(f"Added {nnm or 'household'}"); st.rerun()

    # edit or remove an existing household
    if len(hh):
        st.markdown("**Edit or remove a household**")
        labels = {f"{(r['household_name'] or 'Household')}  ({r['email_a']} & {r['email_b']})":
                  (r["household_name"], r["email_a"], r["email_b"]) for _, r in hh.iterrows()}
        pick = st.selectbox("Choose a family", list(labels.keys()),
                            index=None, placeholder="Choose a family to edit...")
        if pick:
            old_nm, old_a, old_b = labels[pick]
            e1, e2, e3, e4 = st.columns([2,2,2,1])
            up_a  = e1.text_input("Email 1", value=old_a, key="up_a").strip().lower()
            up_b  = e2.text_input("Email 2", value=old_b, key="up_b").strip().lower()
            up_nm = e3.text_input("Family name", value=old_nm or "", key="up_nm")
            e4.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            uc1, uc2 = st.columns([1,5])
            if uc1.button("Update", type="primary") and up_a and up_b and up_a != up_b:
                # clear old pair, write the corrected one
                conn.execute("DELETE FROM households WHERE (email_a=? AND email_b=?) OR (email_a=? AND email_b=?)",
                             (old_a,old_b,old_b,old_a))
                conn.execute("INSERT OR REPLACE INTO households VALUES (?,?,?)", (up_a,up_b,up_nm))
                conn.execute("INSERT OR REPLACE INTO households VALUES (?,?,?)", (up_b,up_a,up_nm))
                conn.commit(); st.success("Updated"); st.rerun()
            if uc2.button("Remove this household"):
                conn.execute("DELETE FROM households WHERE (email_a=? AND email_b=?) OR (email_a=? AND email_b=?)",
                             (old_a,old_b,old_b,old_a))
                conn.commit(); st.success("Removed"); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    conn.close()

#Database
elif page=="Database":
    st.markdown("<div class='page-head'>Database Management</div>", unsafe_allow_html=True)
    conn = sqlite3.connect(DB_PATH)

    st.markdown("<div class='card'><div class='card-title'>Stored Data</div>", unsafe_allow_html=True)
    try:
        q = pd.read_sql("SELECT quarter, COUNT(*) as records FROM attendance GROUP BY quarter", conn)
        st.dataframe(q, use_container_width=True, hide_index=True)
    except Exception:
        st.caption("No data stored.")
    sz = os.path.getsize(DB_PATH)/1024 if os.path.exists(DB_PATH) else 0
    st.caption(f"Database: {DB_PATH}  |  {sz:.0f} KB  |  Back up this file to keep your data.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'><div class='card-title'>Add Files to This Database</div>", unsafe_allow_html=True)
    st.caption("Upload new participation or registration files. They are added without affecting existing data.")
    a1, a2 = st.columns(2)
    xp = a1.file_uploader("New participation CSVs", type="csv", accept_multiple_files=True, key="xp")
    xr = a2.file_uploader("New registration CSVs", type="csv", accept_multiple_files=True, key="xr")
    if (xp or xr) and st.button("Add to Database", type="primary"):
        with st.spinner("Processing..."):
            res = process(xp or [], xr or [])
        if "error" in res:
            st.error(res["error"])
        else:
            qq = res["merged"]["Quarter"].dropna()
            qq = qq[qq!="Unknown"].mode()
            quarter = qq.iloc[0] if len(qq) else "Unknown"
            save_db(DB_PATH, res["merged"], res["ps"], quarter)
            for f in (xp or []): mark_file(DB_PATH, f.name, quarter, "participation"); store_file(DB_PATH, f, "participation", quarter)
            for f in (xr or []): mark_file(DB_PATH, f.name, quarter, "registration"); store_file(DB_PATH, f, "registration", quarter)
            m2, p2, _ = load_db(DB_PATH)
            st.session_state.update({"merged":m2, "ps":p2})
            st.success("Files added.")
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'><div class='card-title'>Manage Individual Files</div>", unsafe_allow_html=True)
    st.caption("Remove a specific file (e.g. an outdated registration doc) and the database rebuilds from the remaining files. Then upload the corrected version above.")
    sf_df = list_stored_files(DB_PATH)
    if len(sf_df):
        for ftype, label in [("registration","Registration Files"), ("participation","Participation Files")]:
            sub = sf_df[sf_df["file_type"]==ftype]
            if len(sub):
                st.markdown(f"**{label}**")
                for _, row in sub.iterrows():
                    fc1, fc2 = st.columns([5,1])
                    fc1.markdown(f"<div style='font-size:13px;padding-top:6px'>{row['filename']}</div>", unsafe_allow_html=True)
                    if fc2.button("Remove", key=f"rm_{row['filename']}"):
                        remove_stored_file(DB_PATH, row["filename"])
                        with st.spinner("Rebuilding database from remaining files..."):
                            res = reprocess_from_stored(DB_PATH)
                        if "error" in res:
                            st.warning(res["error"])
                        else:
                            m2, p2, _ = load_db(DB_PATH)
                            st.session_state.update({"merged":m2, "ps":p2})
                            st.success(f"Removed {row['filename']} and rebuilt the database.")
                        st.rerun()
    else:
        st.caption("No files stored yet. Files you upload are saved here so you can remove or replace them later.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'><div class='card-title'>Remove an Entire Quarter</div>", unsafe_allow_html=True)
    try:
        qs = [r[0] for r in conn.execute("SELECT DISTINCT quarter FROM attendance").fetchall()]
        if qs:
            rq = st.selectbox("Quarter to remove", qs)
            if st.button("Remove Quarter", type="secondary"):
                conn.execute("DELETE FROM attendance WHERE quarter=?", (rq,))
                conn.execute("DELETE FROM stored_files WHERE quarter=?", (rq,))
                conn.commit()
                st.success(f"Removed {rq}")
                st.rerun()
    except Exception:
        st.caption("No quarters to remove.")
    st.markdown("</div>", unsafe_allow_html=True)
    conn.close()