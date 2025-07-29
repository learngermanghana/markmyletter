# ==== Standard Library ====
import os                  # OS file ops
import random              # Randomization
import difflib             # Optional: For fuzzy matching
import sqlite3             # Optional: Local DB (not needed if using Firestore only)
import atexit              # Optional: Exit hooks
import json                # JSON ops
import re                  # Regex
from datetime import date, datetime, timedelta
import time                # Timing
import io                  # IO streams
import bcrypt
import tempfile            # Temp file creation
import urllib.parse        # URL encoding/decoding

# ==== Third-Party Packages ====
import pandas as pd                        # Data handling
import streamlit as st                     # App framework
import matplotlib.pyplot as plt            # Charts/plots
import requests                            # HTTP requests (for Google Sheets, etc)
from openai import OpenAI                  # OpenAI API client
import firebase_admin                      # Firebase app
from firebase_admin import credentials, firestore    # Firestore DB
from fpdf import FPDF                      # PDF export
from streamlit_cookies_manager import EncryptedCookieManager   # Cookie/session handling
from docx import Document                  # Optional: DOCX notes download
from gtts import gTTS                      # Text-to-speech for vocab audio

# If you ever add fuzzy matching, you can use:
# from thefuzz import fuzz, process      # Uncomment if using fuzzy answer checking


# ==== HIDE STREAMLIT FOOTER/MENU ====
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True
)

# ==== FIREBASE ADMIN INIT ====
if not firebase_admin._apps:
    # Convert SecretDict to plain dict for Certificate()
    cred_dict = dict(st.secrets["firebase"])
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==== OPENAI CLIENT SETUP ====
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("Missing OpenAI API key. Please add OPENAI_API_KEY in Streamlit secrets.")
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)


YOUTUBE_PLAYLIST_IDS = {
    "A1": [
        "PL5vnwpT4NVTdwFarD9kwm1HONsqQ11l-b",   # Playlist 1 for A1
    ],
    "A2": [
        "PLs7zUO7VPyJ7YxTq_g2Rcl3Jthd5bpTdY",
        "PLquImyRfMt6dVHL4MxFXMILrFh86H_HAc&index=5",
        "PLs7zUO7VPyJ5Eg0NOtF9g-RhqA25v385c",
    ],
    "B1": [
        "PLs7zUO7VPyJ5razSfhOUVbTv9q6SAuPx-",
        "PLB92CD6B288E5DB61",
    ],
    # etc.
}


@st.cache_data(ttl=3600*12)  # cache for 12 hours
def fetch_youtube_playlist_videos(playlist_id, api_key):
    base_url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": 50,
        "key": api_key,
    }
    videos = []
    next_page = ""
    while True:
        if next_page:
            params["pageToken"] = next_page
        response = requests.get(base_url, params=params)
        data = response.json()
        for item in data.get("items", []):
            vid = item["snippet"]["resourceId"]["videoId"]
            url = f"https://www.youtube.com/watch?v={vid}"
            title = item["snippet"]["title"]
            videos.append({"title": title, "url": url})
        next_page = data.get("nextPageToken")
        if not next_page:
            break
    return videos


# ==== DB CONNECTION ====
def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect("vocab_progress.db", check_same_thread=False)
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

# ==== INITIALIZE DB TABLES ====
def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Vocab Progress Table (NO daily limit)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vocab_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            word TEXT,
            student_answer TEXT,
            is_correct INTEGER,
            date TEXT
        )
    """)
    # Schreiben Progress Table (DAILY LIMIT)
    c.execute("""
        CREATE TABLE IF NOT EXISTS schreiben_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            essay TEXT,
            score INTEGER,
            feedback TEXT,
            date TEXT
        )
    """)
    # Sprechen Progress Table (DAILY LIMIT)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sprechen_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            teil TEXT,
            message TEXT,
            score INTEGER,
            feedback TEXT,
            date TEXT
        )
    """)
    # Scores Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            assignment TEXT,
            score REAL,
            comments TEXT,
            date TEXT,
            level TEXT
        )
    """)
    # Exam Progress Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS exam_progress (
            student_code TEXT,
            level        TEXT,
            teil         TEXT,
            remaining    TEXT,
            used         TEXT,
            PRIMARY KEY (student_code, level, teil)
        )
    """)
    # My Vocab Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS my_vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            level TEXT,
            word TEXT,
            translation TEXT,
            date_added TEXT
        )
    """)
    # Sprechen Daily Usage Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS sprechen_usage (
            student_code TEXT,
            date TEXT,
            count INTEGER,
            PRIMARY KEY (student_code, date)
        )
    """)
    # Letter Coach Daily Usage Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS letter_coach_usage (
            student_code TEXT,
            date TEXT,
            count INTEGER,
            PRIMARY KEY (student_code, date)
        )
    """)
    # Schreiben Daily Usage Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS schreiben_usage (
            student_code TEXT,
            date TEXT,
            count INTEGER,
            PRIMARY KEY (student_code, date)
        )
    """)
    conn.commit()

init_db()  # <<-- Make sure this is before any other DB calls!

# ==== DB CONNECTION ====
def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect(
            "vocab_progress.db", check_same_thread=False
        )
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

# ==== INITIALIZE DB TABLES ====
def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Vocab Progress Table (NO daily limit)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vocab_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            word TEXT,
            student_answer TEXT,
            is_correct INTEGER,
            date TEXT
        )
    """)
    # Schreiben Progress Table (DAILY LIMIT)
    c.execute("""
        CREATE TABLE IF NOT EXISTS schreiben_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            essay TEXT,
            score INTEGER,
            feedback TEXT,
            date TEXT
        )
    """)
    # Sprechen Progress Table (DAILY LIMIT)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sprechen_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            teil TEXT,
            message TEXT,
            score INTEGER,
            feedback TEXT,
            date TEXT
        )
    """)
    # Scores Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            assignment TEXT,
            score REAL,
            comments TEXT,
            date TEXT,
            level TEXT
        )
    """)
    # Exam Progress Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS exam_progress (
            student_code TEXT,
            level        TEXT,
            teil         TEXT,
            remaining    TEXT,
            used         TEXT,
            PRIMARY KEY (student_code, level, teil)
        )
    """)
    # My Vocab Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS my_vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            level TEXT,
            word TEXT,
            translation TEXT,
            date_added TEXT
        )
    """)
    # Daily Usage Tables
    for tbl in ["sprechen_usage", "letter_coach_usage", "schreiben_usage"]:
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {tbl} (
                student_code TEXT,
                date TEXT,
                count INTEGER,
                PRIMARY KEY (student_code, date)
            )
        """)
    conn.commit()


# ==== CONSTANTS ====
FALOWEN_DAILY_LIMIT = 20
VOCAB_DAILY_LIMIT = 20
SCHREIBEN_DAILY_LIMIT = 5

# ==== USAGE COUNTERS ====

def get_sprechen_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT count FROM sprechen_usage WHERE student_code=? AND date=?",
        (student_code, today)
    )
    row = c.fetchone()
    return row[0] if row else 0

def inc_sprechen_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO sprechen_usage (student_code, date, count)
        VALUES (?, ?, 1)
        ON CONFLICT(student_code, date)
        DO UPDATE SET count = count + 1
        """,
        (student_code, today)
    )
    conn.commit()

def has_sprechen_quota(student_code, limit=FALOWEN_DAILY_LIMIT):
    return get_sprechen_usage(student_code) < limit

def get_schreiben_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT count FROM schreiben_usage WHERE student_code=? AND date=?",
        (student_code, today)
    )
    row = c.fetchone()
    return row[0] if row else 0

def inc_schreiben_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO schreiben_usage (student_code, date, count)
        VALUES (?, ?, 1)
        ON CONFLICT(student_code, date)
        DO UPDATE SET count = count + 1
        """,
        (student_code, today)
    )
    conn.commit()

def get_letter_coach_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT count FROM letter_coach_usage WHERE student_code=? AND date=?",
        (student_code, today)
    )
    row = c.fetchone()
    return row[0] if row else 0

def inc_letter_coach_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO letter_coach_usage (student_code, date, count)
        VALUES (?, ?, 1)
        ON CONFLICT(student_code, date)
        DO UPDATE SET count = count + 1
        """,
        (student_code, today)
    )
    conn.commit()

def get_writing_stats(student_code):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*), SUM(score>=17) FROM schreiben_progress WHERE student_code=?
    """, (student_code,))
    result = c.fetchone()
    attempted = result[0] or 0
    passed = result[1] if result[1] is not None else 0
    accuracy = round(100 * passed / attempted) if attempted > 0 else 0
    return attempted, passed, accuracy

def get_student_stats(student_code):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT level, SUM(score >= 17), COUNT(*) 
        FROM schreiben_progress 
        WHERE student_code=?
        GROUP BY level
    """, (student_code,))
    stats = {}
    for level, correct, attempted in c.fetchall():
        stats[level] = {"correct": int(correct or 0), "attempted": int(attempted or 0)}
    return stats

# --- ALIAS for legacy code (use this so your old code works without errors!) ---
has_falowen_quota = has_sprechen_quota


def get_letter_coach_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT count FROM letter_coach_usage WHERE student_code=? AND date=?",
        (student_code, today)
    )
    row = c.fetchone()
    return row[0] if row else 0

def inc_letter_coach_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO letter_coach_usage (student_code, date, count)
        VALUES (?, ?, 1)
        ON CONFLICT(student_code, date)
        DO UPDATE SET count = count + 1
        """,
        (student_code, today)
    )
    conn.commit()


# ==== YOUTUBE PLAYLIST HELPERS ====

YOUTUBE_API_KEY = "AIzaSyBA3nJi6dh6-rmOLkA4Bb0d7h0tLAp7xE4"

YOUTUBE_PLAYLIST_IDS = {
    "A1": [
        "PL5vnwpT4NVTdwFarD9kwm1HONsqQ11l-b",
    ],
    "A2": [
        "PLs7zUO7VPyJ7YxTq_g2Rcl3Jthd5bpTdY",
        "PLquImyRfMt6dVHL4MxFXMILrFh86H_HAc&index=5",
        "PLs7zUO7VPyJ5Eg0NOtF9g-RhqA25v385c",
    ],
    "B1": [
        "PLs7zUO7VPyJ5razSfhOUVbTv9q6SAuPx-",
        "PLB92CD6B288E5DB61",
    ],
}

@st.cache_data(ttl=43200)  # cache for 12 hours
def fetch_youtube_playlist_videos(playlist_id, api_key=YOUTUBE_API_KEY):
    base_url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": 50,
        "key": api_key,
    }
    videos = []
    next_page = ""
    while True:
        if next_page:
            params["pageToken"] = next_page
        response = requests.get(base_url, params=params)
        data = response.json()
        for item in data.get("items", []):
            vid = item["snippet"]["resourceId"]["videoId"]
            url = f"https://www.youtube.com/watch?v={vid}"
            title = item["snippet"]["title"]
            videos.append({"title": title, "url": url})
        next_page = data.get("nextPageToken")
        if not next_page:
            break
    return videos

# ==== FIRESTORE HELPERS (LETTER COACH, SCHREIBEN STATS) ====

def save_letter_coach_progress(student_code, schreiben_level, letter_coach_prompt, chat_history):
    """Auto-saves the student's Letter Coach progress in Firestore."""
    doc_ref = db.collection("letter_coach_progress").document(student_code)
    doc_ref.set({
        "level": schreiben_level,
        "prompt": letter_coach_prompt,
        "chat": chat_history,
        "last_update": firestore.SERVER_TIMESTAMP
    })

def load_letter_coach_progress(student_code):
    """Loads most recent Letter Coach progress from Firestore."""
    doc_ref = db.collection("letter_coach_progress").document(student_code)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return data.get("prompt", ""), data.get("chat", [])
    return "", []

def get_schreiben_stats(student_code):
    doc_ref = db.collection("schreiben_stats").document(student_code)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    else:
        return {
            "total": 0, "passed": 0, "average_score": 0, "best_score": 0,
            "pass_rate": 0, "last_attempt": None, "attempts": [], "last_letter": ""
        }



# --- Streamlit page config ---
st.set_page_config(
    page_title="Falowen – Your German Conversation Partner",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ---- Falowen Header ----
st.markdown(
    """
    <div style='display: flex; align-items: center; justify-content: space-between; margin-bottom: 22px; width: 100%;'>
        <!-- Left Flag -->
        <span style='font-size:2.2rem; flex: 0 0 auto;'>🇬🇭</span>
        <!-- Center Block -->
        <div style='flex: 1; text-align: center;'>
            <span style='font-size:2.1rem; font-weight:bold; color:#17617a; letter-spacing:2px;'>
                Falowen App
            </span>
            <br>
            <span style='font-size:1.08rem; color:#ff9900; font-weight:600;'>Learn Language Education Academy</span>
            <br>
            <span style='font-size:1.05rem; color:#268049; font-weight:400;'>
                Your All-in-One German Learning Platform for Speaking, Writing, Exams, and Vocabulary
            </span>
            <br>
            <span style='font-size:1.01rem; color:#1976d2; font-weight:500;'>
                Website: <a href='https://www.learngermanghana.com' target='_blank' style='color:#1565c0; text-decoration:none;'>www.learngermanghana.com</a>
            </span>
            <br>
            <span style='font-size:0.98rem; color:#666; font-weight:500;'>
                Competent German Tutors Team
            </span>
        </div>
        <!-- Right Flag -->
        <span style='font-size:2.2rem; flex: 0 0 auto;'>🇩🇪</span>
    </div>
    """,
    unsafe_allow_html=True
)

# ==== 2) Helpers to load & save progress ====
def load_progress(student_code, level, teil):
    c.execute(
        "SELECT remaining, used FROM exam_progress WHERE student_code=? AND level=? AND teil=?",
        (student_code, level, teil)
    )
    row = c.fetchone()
    if row:
        return json.loads(row[0]), json.loads(row[1])
    return None, None

def save_progress(student_code, level, teil, remaining, used):
    c.execute(
        "REPLACE INTO exam_progress (student_code, level, teil, remaining, used) VALUES (?,?,?,?,?)",
        (student_code, level, teil, json.dumps(remaining), json.dumps(used))
    )
    conn.commit()

def save_schreiben_attempt(student_code, name, level, score):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO schreiben_progress (student_code, name, level, essay, score, feedback, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (student_code, name, level, "", score, "", str(date.today()))
    )
    conn.commit()

def handle_google_login():
    query_params = get_query_params()
    if "code" not in query_params:
        return False
    code = query_params["code"]
    if isinstance(code, list):
        code = code[0]
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    try:
        resp = requests.post(token_url, data=data, timeout=10)
        if not resp.ok:
            # Only show the error if it's not the common invalid_grant from reload
            try:
                err_json = resp.json()
                if err_json.get("error") == "invalid_grant":
                    return False
                st.error(f"Google login failed. Details: {resp.text}")
            except Exception:
                st.error(f"Google login failed. Details: {resp.text}")
            return False
        # ... rest of your code goes here ...
    except Exception as e:
        st.error(f"Google login failed. Error: {e}")
        return False


# Bubble CSS
bubble_user = "background:#e3f2fd;padding:12px 20px;border-radius:18px 18px 6px 18px;margin:8px 0;display:inline-block;"
bubble_assistant = "background:#fff9c4;padding:12px 20px;border-radius:18px 18px 18px 6px;margin:8px 0;display:inline-block;"

# Highlight function and words
highlight_words = ["correct", "should", "mistake", "improve", "tip"]
def highlight_keywords(text, words):
    import re
    pattern = r'(' + '|'.join(map(re.escape, words)) + r')'
    return re.sub(pattern, r"<span style='color:#d63384;font-weight:600'>\1</span>", text, flags=re.IGNORECASE)


    
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/gviz/tq?tqx=out:csv"

@st.cache_data
def load_student_data():
    # 1) Fetch CSV
    try:
        resp = requests.get(GOOGLE_SHEET_CSV, timeout=10)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), dtype=str)
    except Exception:
        st.error("❌ Could not load student data.")
        st.stop()

    # 2) Strip whitespace
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    # 3) Drop rows missing a ContractEnd
    df = df[df["ContractEnd"].notna() & (df["ContractEnd"] != "")]

    # 4) Parse ContractEnd into datetime (two formats)
    df["ContractEnd_dt"] = pd.to_datetime(
        df["ContractEnd"], format="%m/%d/%Y", errors="coerce", dayfirst=False
    )
    # Fallback European format where needed
    mask = df["ContractEnd_dt"].isna()
    df.loc[mask, "ContractEnd_dt"] = pd.to_datetime(
        df.loc[mask, "ContractEnd"], format="%d/%m/%Y", errors="coerce", dayfirst=True
    )

    # 5) Sort by latest ContractEnd_dt and drop duplicates
    df = df.sort_values("ContractEnd_dt", ascending=False)
    df = df.drop_duplicates(subset=["StudentCode"], keep="first")

    # 6) Clean up helper column
    df = df.drop(columns=["ContractEnd_dt"])

    return df

def is_contract_expired(row):
    expiry_str = str(row.get("ContractEnd", "")).strip()
    # Debug lines removed

    if not expiry_str or expiry_str.lower() == "nan":
        return True

    # Try known formats
    expiry_date = None
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            expiry_date = datetime.strptime(expiry_str, fmt)
            break
        except ValueError:
            continue

    # Fallback to pandas auto-parse
    if expiry_date is None:
        parsed = pd.to_datetime(expiry_str, errors="coerce")
        if pd.isnull(parsed):
            return True
        expiry_date = parsed.to_pydatetime()

    today = datetime.now().date()
    # Debug lines removed

    return expiry_date.date() < today


# ---- Cookie & Session Setup ----
COOKIE_SECRET = os.getenv("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET")
if not COOKIE_SECRET:
    raise ValueError("COOKIE_SECRET environment variable not set")

cookie_manager = EncryptedCookieManager(prefix="falowen_", password=COOKIE_SECRET)
cookie_manager.ready()
if not cookie_manager.ready():
    st.warning("Cookies are not ready. Please refresh.")
    st.stop()

for key, default in [("logged_in", False), ("student_row", None), ("student_code", ""), ("student_name", "")]:
    st.session_state.setdefault(key, default)

code_from_cookie = cookie_manager.get("student_code") or ""
code_from_cookie = str(code_from_cookie).strip().lower()

# --- Auto-login via Cookie ---
if not st.session_state["logged_in"] and code_from_cookie:
    df_students = load_student_data()
    # Normalize for matching
    df_students["StudentCode"] = df_students["StudentCode"].str.lower().str.strip()
    df_students["Email"] = df_students["Email"].str.lower().str.strip()

    found = df_students[df_students["StudentCode"] == code_from_cookie]
    if not found.empty:
        student_row = found.iloc[0]
        if is_contract_expired(student_row):
            st.error("Your contract has expired. Please contact the office for renewal.")
            cookie_manager["student_code"] = ""
            cookie_manager.save()
            st.stop()
        st.session_state.update({
            "logged_in": True,
            "student_row": student_row.to_dict(),
            "student_row": student_row.to_dict(),  
            "student_code": student_row["StudentCode"],
            "student_name": student_row["Name"]
        })
        
# --- Manual Login & Account Creation Block ---
if not st.session_state["logged_in"]:
    # === WELCOME / HELP / INSTRUCTIONS (always at top, always visible) ===
    st.markdown(
        """
        <div style='border-left:4px solid #1976d2; padding:14px 9px 14px 14px; border-radius:7px; margin-bottom:20px; font-size:1.13rem; line-height:1.6; color:#232323; background:rgba(255,255,255,0.96);'>
            <b>👋 Welcome to Falowen!</b><br>
            <ul style="margin:10px 0 0 0; padding-left:22px;">
                <li style="margin-bottom:7px;"><span style="font-size:1.1em;">🔑</span> <b>Returning?</b> Log in with your <b style="color:#17617a;">Student Code or Email</b> and password.</li>
                <li style="margin-bottom:7px;"><span style="font-size:1.1em;">🆕</span> <b>New?</b> Click <b>Create Account</b> below <b>after</b> your teacher gives you a code.</li>
                <li style="margin-bottom:7px;"><span style="font-size:1.1em;">📱</span> <b>iPhone/iPad:</b> Tap “Save Password” if asked.</li>
                <li style="margin-bottom:7px;"><span style="font-size:1.1em;">⌛</span> <b>Expired?</b> If you see a contract expiry message, contact the school office.</li>
                <li style="margin-bottom:7px;"><span style="font-size:1.1em;">🔒</span> <b>Privacy:</b> Only you &amp; your teacher see your progress.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True
    )

    # --- 1) (Optional) Google OAuth ---
    # (You can move/remove if you want only password login!)
    GOOGLE_CLIENT_ID     = "180240695202-3v682khdfarmq9io9mp0169skl79hr8c.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "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"
    REDIRECT_URI         = "https://falowen.streamlit.app/"  # Your deployed Streamlit URL

    def get_query_params():
        return st.query_params

    def do_google_oauth():
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "prompt": "select_account"
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
        st.markdown(
            f"""<div style='text-align:center;margin:12px 0;'>
                <a href="{auth_url}">
                    <button style="background:#4285f4;color:white;padding:8px 24px;border:none;border-radius:6px;cursor:pointer;">
                        Sign in with Google
                    </button>
                </a>
            </div>""",
            unsafe_allow_html=True
        )

    def handle_google_login():
        qp = get_query_params()
        if "code" not in qp:
            return False
        code = qp["code"][0] if isinstance(qp["code"], list) else qp["code"]
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code"
        }
        try:
            resp = requests.post(token_url, data=data, timeout=10)
            if not resp.ok:
                err = resp.json().get("error")
                if err != "invalid_grant":
                    st.error(f"Google login failed: {resp.text}")
                return False
            access_token = resp.json().get("access_token")
            if not access_token:
                return False
            userinfo = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            ).json()
            email = userinfo.get("email", "").lower()
            df = load_student_data()
            df["Email"] = df["Email"].str.lower().str.strip()
            match = df[df["Email"] == email]
            if match.empty:
                st.error("No student account found for that Google email.")
                return False
            student_row = match.iloc[0]
            if is_contract_expired(student_row):
                st.error("Your contract has expired. Contact the office.")
                return False
            st.session_state.update({
                "logged_in": True,
                "student_row": student_row.to_dict(),
                "student_code": student_row["StudentCode"],
                "student_name": student_row["Name"]
            })
            cookie_manager["student_code"] = student_row["StudentCode"]
            cookie_manager.save()
            st.success(f"Welcome, {student_row['Name']}!")
            st.rerun()
        except Exception as e:
            st.error(f"Google OAuth error: {e}")
        return False

    if handle_google_login():
        st.stop()
    st.markdown("<div style='text-align:center;margin:8px 0;'>⎯⎯⎯ or ⎯⎯⎯</div>", unsafe_allow_html=True)
    do_google_oauth()

    # --- 2) Manual Login (Student Code/Email & Password) ---
    login_id       = st.text_input("Student Code or Email")
    login_password = st.text_input("Password", type="password")
    if st.button("Login"):
        df = load_student_data()
        df["StudentCode"] = df["StudentCode"].str.lower().str.strip()
        df["Email"]       = df["Email"].str.lower().str.strip()
        lookup = df[
            ((df["StudentCode"] == login_id.lower()) | (df["Email"] == login_id.lower()))
        ]
        if lookup.empty:
            st.error("No matching student code or email found.")
        else:
            student_row = lookup.iloc[0]
            if is_contract_expired(student_row):
                st.error("Your contract has expired. Contact the office.")
            else:
                doc = db.collection("students").document(student_row["StudentCode"]).get()
                if not doc.exists:
                    st.error("Account not found. Please create one below.")
                else:
                    data = doc.to_dict()
                    if data.get("password") != login_password:
                        st.error("Incorrect password.")
                    else:
                        st.session_state.update({
                            "logged_in": True,
                            "student_row": student_row.to_dict(),
                            "student_code": student_row["StudentCode"],
                            "student_name": student_row["Name"]
                        })
                        cookie_manager["student_code"] = student_row["StudentCode"]
                        cookie_manager.save()
                        st.success(f"Welcome, {student_row['Name']}!")
                        st.rerun()

    # --- 3) Create Account (always visible, always left) ---
    st.markdown("### Create an Account")
    new_name     = st.text_input("Full Name", key="ca_name")
    new_email    = st.text_input("Email (must match teacher’s record)", key="ca_email").strip().lower()
    new_code     = st.text_input("Student Code (from teacher)", key="ca_code").strip().lower()
    new_password = st.text_input("Choose a Password", type="password", key="ca_pass")
    if st.button("Create Account"):
        if not (new_name and new_email and new_code and new_password):
            st.error("Please fill in all fields.")
        else:
            df = load_student_data()
            df["StudentCode"] = df["StudentCode"].str.lower().str.strip()
            df["Email"]       = df["Email"].str.lower().str.strip()
            valid = df[
                (df["StudentCode"] == new_code) &
                (df["Email"] == new_email)
            ]
            if valid.empty:
                st.error("Your code/email aren’t registered. Ask your teacher to add you first.")
            else:
                db.collection("students").document(new_code).set({
                    "name":     new_name,
                    "email":    new_email,
                    "password": new_password
                })
                st.success("Account created! Please log in above.")

    st.stop()

# --- Logged In UI ---
st.write(f"👋 Welcome, **{st.session_state['student_name']}**")
if st.button("Log out"):
    cookie_manager["student_code"] = ""
    cookie_manager.save()
    for k in ["logged_in", "student_row", "student_code", "student_name"]:
        st.session_state[k] = False if k == "logged_in" else ""
    st.success("You have been logged out.")
    st.rerun()


    
# ==== GOOGLE SHEET LOADING FUNCTIONS ====

@st.cache_data
def load_student_data():
    SHEET_ID = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
    csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Sheet1"
    df = pd.read_csv(csv_url)
    df.columns = df.columns.str.strip().str.replace(" ", "")
    return df

@st.cache_data
def load_assignment_scores():
    SHEET_ID = "1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ"
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Sheet1"
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip().str.lower()
    return df

@st.cache_data
def load_reviews():
    SHEET_ID = "137HANmV9jmMWJEdcA1klqGiP8nYihkDugcIbA-2V1Wc"
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Sheet1"
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip().str.lower()
    return df

# ==== PARSE CONTRACT END ====
def parse_contract_end(date_str):
    if not date_str or str(date_str).lower() in ("nan", "none", ""):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y"):  
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

if st.session_state.get("logged_in"):
    student_code = st.session_state["student_code"].strip().lower()
    student_name = st.session_state["student_name"]

    # Load student info
    df_students = load_student_data()
    matches = df_students[df_students["StudentCode"].str.lower() == student_code]
    student_row = matches.iloc[0].to_dict() if not matches.empty else {}

    # Greeting and contract info
    first_name = (student_row.get('Name') or student_name or "Student").split()[0].title()

    # --- Contract End and Renewal Policy (ALWAYS VISIBLE) ---
    MONTHLY_RENEWAL = 1000
    contract_end_str = student_row.get("ContractEnd", "")
    today = datetime.today()
    contract_end = parse_contract_end(contract_end_str)
    if contract_end:
        days_left = (contract_end - today).days
        if 0 < days_left <= 30:
            st.warning(
                f"⏰ **Your contract ends in {days_left} days ({contract_end.strftime('%d %b %Y')}).**\n"
                f"If you need more time, you can renew for **₵{MONTHLY_RENEWAL:,} per month**."
            )
        elif days_left < 0:
            st.error(
                f"⚠️ **Your contract has ended!** Please contact the office to renew for **₵{MONTHLY_RENEWAL:,} per month**."
            )
    else:
        st.info("Contract end date unavailable or in wrong format.")

    st.info(
        f"🔄 **Renewal Policy:** If your contract ends before you finish, renew for **₵{MONTHLY_RENEWAL:,} per month**. "
        "Do your best to complete your course on time to avoid extra fees!"
    )

    # --- Assignment Streak + Weekly Goal (ALWAYS VISIBLE, BEFORE TAB SELECTION) ---
    df_assign = load_assignment_scores()
    df_assign['date'] = pd.to_datetime(
        df_assign['date'], format="%Y-%m-%d", errors="coerce"
    ).dt.date
    mask_student = df_assign['studentcode'].str.lower().str.strip() == student_code

    from datetime import timedelta, date
    dates = sorted(df_assign[mask_student]['date'].dropna().unique(), reverse=True)
    streak = 1 if dates else 0
    for i in range(1, len(dates)):
        if (dates[i-1] - dates[i]).days == 1:
            streak += 1
        else:
            break

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    assignment_count = df_assign[mask_student & (df_assign['date'] >= monday)].shape[0]
    WEEKLY_GOAL = 3

    st.markdown("### 🏅 Assignment Streak & Weekly Goal")
    col1, col2 = st.columns(2)
    col1.metric("Streak", f"{streak} days")
    col2.metric("Submitted", f"{assignment_count} / {WEEKLY_GOAL}")
    if assignment_count >= WEEKLY_GOAL:
        st.success("🎉 You’ve reached your weekly goal of 3 assignments!")
    else:
        rem = WEEKLY_GOAL - assignment_count
        st.info(f"Submit {rem} more assignment{'s' if rem>1 else ''} by Sunday to hit your goal.")

    st.divider()


    # ---------- Tab Tips Section (only on Dashboard) ----------
    DASHBOARD_REMINDERS = [
        "🤔 **Have you tried the Course Book?** Explore every lesson, see your learning progress, and never miss a topic.",
        "📊 **Have you checked My Results and Resources?** View your quiz results, download your work, and see where you shine.",
        "📝 **Have you used Exams Mode & Custom Chat?** Practice your speaking and real exam questions or ask your own. Get instant writing feedback and AI help!",
        "🗣️ **Have you done some Vocab Trainer this week?** Practicing new words daily is proven to boost your fluency.",
        "✍️ **Have you used the Schreiben Trainer?** Try building your letters with the Ideas Generator—then self-check before your tutor does!",
        "📒 **Have you added notes in My Learning Notes?** Organize, pin, and download your best ideas and study tips.",
    ]
    import random
    dashboard_tip = random.choice(DASHBOARD_REMINDERS)
    st.info(dashboard_tip)  # This line gives the tip as a friendly info box

    # --- Main Tab Selection ---
    tab = st.radio(
        "How do you want to practice?",
        [
            "Dashboard",
            "Course Book",
            "My Results and Resources",
            "Exams Mode & Custom Chat",
            "Vocab Trainer",
            "Schreiben Trainer",
            "My Learning Notes",
        ],
        key="main_tab_select"
    )

if tab == "Dashboard":
    # --- Helper to avoid AttributeError on any row type ---
    def safe_get(row, key, default=""):
        # mapping-style
        try:
            return row.get(key, default)
        except Exception:
            pass
        # attribute-style
        try:
            return getattr(row, key, default)
        except Exception:
            pass
        # index/key access
        try:
            return row[key]
        except Exception:
            return default

    # --- Ensure student_row is something we can call safe_get() on ---
    if not student_row:
        st.info("🚩 No student selected.")
        st.stop()
    # (no need to convert to dict—safe_get covers all cases)

    # --- Student Info & Balance ---
    name = safe_get(student_row, "Name")
    st.markdown(f"### 👤 {name}")
    st.markdown(
        f"- **Level:** {safe_get(student_row, 'Level')}\n"
        f"- **Code:** `{safe_get(student_row, 'StudentCode')}`\n"
        f"- **Email:** {safe_get(student_row, 'Email')}\n"
        f"- **Phone:** {safe_get(student_row, 'Phone')}\n"
        f"- **Location:** {safe_get(student_row, 'Location')}\n"
        f"- **Contract:** {safe_get(student_row, 'ContractStart')} ➔ {safe_get(student_row, 'ContractEnd')}\n"
        f"- **Enroll Date:** {safe_get(student_row, 'EnrollDate')}\n"
        f"- **Status:** {safe_get(student_row, 'Status')}"
    )
    try:
        bal = float(safe_get(student_row, "Balance", 0))
        if bal > 0:
            st.warning(f"💸 Balance to pay: ₵{bal:.2f}")
    except Exception:
        pass

    # ==== CLASS SCHEDULES DICTIONARY ====
    GROUP_SCHEDULES = {
        "A1 Munich Klasse": {
            "days": ["Monday", "Tuesday", "Wednesday"],
            "time": "6:00pm–7:00pm",
            "start_date": "2025-07-08",
            "end_date": "2025-09-02",
            "doc_url": "https://drive.google.com/file/d/1en_YG8up4C4r36v4r7E714ARcZyvNFD6/view?usp=sharing"
        },
        "A1 Berlin Klasse": {
            "days": ["Thursday", "Friday", "Saturday"],
            "time": "Thu/Fri: 6:00pm–7:00pm, Sat: 9:00am–10:00am",
            "start_date": "2025-06-14",
            "end_date": "2025-08-09",
            "doc_url": "https://drive.google.com/file/d/1foK6MPoT_dc2sCxEhTJbtuK5ZzP-ERzt/view?usp=sharing"
        },
        "A1 Koln Klasse": {
            "days": ["Monday", "Tuesday", "Wednesday"],
            "time": "6:00pm–7:00pm",
            "start_date": "",
            "end_date": "",
            "doc_url": ""
        },
        "A2 Munich Klasse": {
            "days": ["Monday", "Tuesday", "Wednesday"],
            "time": "7:30pm–9:00pm",
            "start_date": "2025-06-24",
            "end_date": "2025-08-26",
            "doc_url": "https://drive.google.com/file/d/1Zr3iN6hkAnuoEBvRELuSDlT7kHY8s2LP/view?usp=sharing"
        },
        "A2 Berlin Klasse": {
            "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "time": "Mon–Wed: 11:00am–12:00pm, Thu/Fri: 11:00am–12:00pm, Wed: 2:00pm–3:00pm",
            "start_date": "",
            "end_date": "",
            "doc_url": ""
        },
        "A2 Koln Klasse": {
            "days": ["Wednesday", "Thursday", "Friday"],
            "time": "Wed: 2:00pm–3:00pm, Thu/Fri: 11:00am–12:00pm",
            "start_date": "2025-08-06",
            "end_date": "2025-10-08",
            "doc_url": ""
        },
        "B1 Munich Klasse": {
            "days": ["Thursday", "Friday"],
            "time": "7:30pm–9:00pm",
            "start_date": "2025-07-31",
            "end_date": "2025-10-31",
            "doc_url": "https://drive.google.com/file/d/1ZRWUKfW3j_fEs24X1gSBtfdXsDMurT9n/view?usp=sharing"
        },
    }

    # ==== SHOW UPCOMING CLASSES CARD ====
    from datetime import datetime, timedelta, date

    # use safe_get instead of direct .get()
    class_name = str(safe_get(student_row, "ClassName", "")).strip()
    class_schedule = GROUP_SCHEDULES.get(class_name)
    week_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    if not class_name or not class_schedule:
        st.info("🚩 Your class is not set yet. Please contact your teacher or the office.")
    else:
        days      = class_schedule.get("days", [])
        time_str  = class_schedule.get("time", "")
        start_dt  = class_schedule.get("start_date", "")
        end_dt    = class_schedule.get("end_date", "")
        doc_url   = class_schedule.get("doc_url", "")

        # map day names → indices
        day_indices = [week_days.index(d) for d in days if d in week_days] if isinstance(days, list) else []

        # check if class ended
        class_over = False
        end_date_obj = None
        if end_dt:
            try:
                end_date_obj = datetime.strptime(end_dt, "%Y-%m-%d").date()
                class_over = datetime.today().date() > end_date_obj
            except Exception:
                pass

        if class_over:
            st.error(
                f"❌ Your class ({class_name}) ended on "
                f"{end_date_obj.strftime('%d %b %Y') if end_date_obj else end_dt}. "
                "Please contact the office for next steps."
            )
        else:
            # build next up to 3 sessions
            next_classes = []
            if day_indices:
                today_idx = datetime.today().weekday()
                for offset in range(7):
                    idx = (today_idx + offset) % 7
                    if idx in day_indices:
                        next_classes.append((
                            week_days[idx],
                            (datetime.today() + timedelta(days=offset)).strftime("%d %b")
                        ))
                        if len(next_classes) == 3:
                            break

            st.markdown(
                f"""
                <div style='border:2px solid #17617a; border-radius:14px;
                            padding:13px 11px; margin-bottom:13px;
                            background:#eaf6fb; font-size:1.15em;
                            line-height:1.65; color:#232323;'>
                    <b style="font-size:1.09em;">🗓️ Your Next Classes ({class_name}):</b><br>
                    {'<ul style="padding-left:16px; margin:9px 0 0 0;">' + ''.join([
                        f"<li style='margin-bottom:6px;'><b>{d}</b> "
                        f"<span style='color:#1976d2;'>{dt}</span> "
                        f"<span style='color:#333;'>{time_str}</span></li>"
                        for d, dt in next_classes
                    ]) + '</ul>' if next_classes else
                      '<span style="color:#c62828;">Schedule not set yet.</span>'}
                    <div style="font-size:0.98em; margin-top:6px;">
                        <b>Course period:</b> {start_dt or '[not set]'} to {end_dt or '[not set]'}
                    </div>
                    {f'<a href="{doc_url}" target="_blank" '
                      f'style="font-size:1em;color:#17617a;'
                      f'text-decoration:underline;margin-top:6px;'
                      f'display:inline-block;">📄 View/download full class schedule</a>'
                      if doc_url else ''}
                </div>
                """,
                unsafe_allow_html=True
            )


    # --- Goethe Exam Countdown & Video of the Day (per level) ---
    GOETHE_EXAM_DATES = {
        "A1": (date(2025, 10, 13), 2850, None),
        "A2": (date(2025, 10, 14), 2400, None),
        "B1": (date(2025, 10, 15), 2750, 880),
        "B2": (date(2025, 10, 16), 2500, 840),
        "C1": (date(2025, 10, 17), 2450, 700),
    }
    level = (student_row.get("Level", "") or "").upper().replace(" ", "")
    exam_info = GOETHE_EXAM_DATES.get(level)

    st.subheader("⏳ Goethe Exam Countdown & Video of the Day")
    if exam_info:
        exam_date, fee, module_fee = exam_info
        days_to_exam = (exam_date - date.today()).days
        fee_text = f"**Fee:** ₵{fee:,}"
        if module_fee:
            fee_text += f" &nbsp; | &nbsp; **Per Module:** ₵{module_fee:,}"
        if days_to_exam > 0:
            st.info(
                f"Your {level} exam is in {days_to_exam} days ({exam_date:%d %b %Y}).  \n"
                f"{fee_text}  \n"
                "[Register online here](https://www.goethe.de/ins/gh/en/spr/prf.html)"
            )
        elif days_to_exam == 0:
            st.success("🚀 Exam is today! Good luck!")
        else:
            st.error(
                f"❌ Your {level} exam was on {exam_date:%d %b %Y}, {abs(days_to_exam)} days ago.  \n"
                f"{fee_text}"
            )

        # ---- Per-level YouTube Playlist ----
        playlist_id = YOUTUBE_PLAYLIST_IDS.get(level)
        if playlist_id:
            video_list = fetch_youtube_playlist_videos(playlist_id, YOUTUBE_API_KEY)
            if video_list:
                today_idx = date.today().toordinal()
                pick = today_idx % len(video_list)
                video = video_list[pick]
                st.markdown(f"**🎬 Video of the Day for {level}: {video['title']}**")
                st.video(video['url'])
            else:
                st.info("No videos found for your level’s playlist. Check back soon!")
        else:
            st.info("No playlist found for your level yet. Stay tuned!")
    else:
        st.warning("No exam date configured for your level.")

    # --- Reviews Section ---
    st.markdown("### 🗣️ What Our Students Say")
    reviews = load_reviews()
    if reviews.empty:
        st.info("No reviews yet. Be the first to share your experience!")
    else:
        rev_list = reviews.to_dict("records")
        if "rev_idx" not in st.session_state:
            st.session_state["rev_idx"] = 0
            st.session_state["rev_last_time"] = time.time()
        if time.time() - st.session_state["rev_last_time"] > 8:
            st.session_state["rev_idx"] = (st.session_state["rev_idx"] + 1) % len(rev_list)
            st.session_state["rev_last_time"] = time.time()
            st.rerun()
        r = rev_list[st.session_state["rev_idx"]]
        stars = "★" * int(r.get("rating", 5)) + "☆" * (5 - int(r.get("rating", 5)))
        st.markdown(
            f"> {r.get('review_text','')}\n"
            f"> — **{r.get('student_name','')}**  \n"
            f"> {stars}"
        )



            
def get_a1_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Lesen & Hören 0.1",
            "chapter": "0.1",
            "goal": "You will learn to introduce yourself, greet others in German, and ask about people's well-being.",
            "instruction": "Watch the video, review grammar, do the workbook, submit assignment.",
            "grammar_topic": "Formal and Informal Greetings",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/7QZhrb-gvxY",
                "grammarbook_link": "https://drive.google.com/file/d/1D9Pwg29qZ89xh6caAPBcLJ1K671VUc0_/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1wjtEyPphP0N7jLbF3AWb5wN_FuJZ5jUQ/view?usp=sharing"
            }
        },
        # DAY 2 – Multi chapter
        {
            "day": 2,
            "topic": "Lesen & Hören 0.2 and 1.1 ",
            "chapter": "0.2_1.1",
            "goal": "Understand the German alphabets, personal pronouns and verb conjugation in German.",
            "instruction": "You are doing Lesen and Hören chapter 0.2 and 1.1. Make sure to follow up attentively.",
            "grammar_topic": "German Alphabets and Personal Pronouns",
            "lesen_hören": [
                {
                    "chapter": "0.2",
                    "video": "https://youtu.be/S7n6TlAQRLQ",
                    "grammarbook_link": "https://drive.google.com/file/d/1KtJCF15Ng4cLU88wdUCX5iumOLY7ZA0a/view?usp=sharing",
                    "assignment": True,
                    "workbook_link": "https://drive.google.com/file/d/1R6PqzgsPm9f5iVn7JZXSNVa_NttoPU9Q/view?usp=sharing",
                },
                {
                    "chapter": "1.1",
                    "video": "https://youtu.be/AjsnO1hxDs4",
                    "grammarbook_link": "https://drive.google.com/file/d/1DKhyi-43HX1TNs8fxA9bgRvhylubilBf/view?usp=sharing",
                    "assignment": True,
                    "workbook_link": "https://drive.google.com/file/d/1A1D1pAssnoncF1JY0v54XT2npPb6mQZv/view?usp=sharing",
                }
            ]
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Schreiben & Sprechen 1.1 and Lesen & Hören 1.2",
            "chapter": "1.1_1.2",
            "goal": "Recap what we have learned so far: be able to introduce yourself in German and know all the pronouns.",
            "instruction": (
                "Begin with the practicals at **Schreiben & Sprechen** (writing & speaking). "
                "Then, move to **Lesen & Hören** (reading & listening). "
                "**Do assignments only at Lesen & Hören.**\n\n"
                "Schreiben & Sprechen activities are for self-practice and have answers provided for self-check. "
                "Main assignment to be marked is under Lesen & Hören below."
            ),
            "grammar_topic": "German Pronouns",
            "schreiben_sprechen": {
                "video": "https://youtu.be/hEe6rs0lkRg",
                "workbook_link": "https://drive.google.com/file/d/1GXWzy3cvbl_goP4-ymFuYDtX4X23D70j/view?usp=sharing",
                "assignment": False,
            },
            "lesen_hören": [
                {
                    "chapter": "1.2",
                    "video": "https://youtu.be/NVCN4fZXEk0",
                    "grammarbook_link": "https://drive.google.com/file/d/1OUJT9aSU1XABi3cdZlstUvfBIndyEOwb/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1Lubevhd7zMlbvPcvHHC1D0GzW7xqa4Mp/view?usp=sharing",
                    "assignment": True
                }
            ]
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Lesen & Hören 2",
            "chapter": "2",
            "goal": "Learn numbers from one to 10 thousand. Also know the difference between city and street",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "grammar_topic": "German Numbers",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/BzI2n4A8Oak",
                "grammarbook_link": "https://drive.google.com/file/d/1f2CJ492liO8ccudCadxHIISwGJkHP6st/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1C4VZDUj7VT27Qrn9vS5MNc3QfRqpmDGE/view?usp=sharing",
                "assignment": True
            }
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Schreiben & Sprechen 1.2 (Recap)",
            "chapter": "1.2",
            "goal": "Consolidate your understanding of introductions.",
            "instruction": "Use self-practice workbook and review answers for self-check.",
            "assignment": False,
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1ojXvizvJz_qGes7I39pjdhnmlul7xhxB/view?usp=sharing"
            }
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Schreiben & Sprechen 2.3",
            "chapter": "2.3",
            "goal": "Learn about family and expressing your hobby",
            "assignment": False,
            "instruction": "Use self-practice workbook and review answers for self-check.",
            "schreiben_sprechen": {
                "video": "https://youtu.be/JrYSpnZN6P0",
                "workbook_link": "https://drive.google.com/file/d/1xellIzaxzoBTFOUdaCEHu_OiiuEnFeWT/view?usp=sharing"
            }
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Lesen & Hören 3",
            "chapter": "3",
            "goal": "Know how to ask for a price and also the use of mogen and gern to express your hobby",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.Do schreiben and sprechen 2.3 before this chapter for better understanding",
            "grammar_topic": "Fragen nach dem Preis; gern/lieber/mögen (Talking about price and preferences)",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/dGIj1GbK4sI",
                "grammarbook_link": "https://drive.google.com/file/d/1sCE5y8FVctySejSVNm9lrTG3slIucxqY/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1lL4yrZLMtKLnNuVTC2Sg_ayfkUZfIuak/view?usp=sharing"
            }
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Lesen & Hören 4",
            "chapter": "4",
            "goal": "Learn about schon mal and noch nie, irregular verbs and all the personal pronouns",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "grammar_topic": "schon mal, noch nie; irregular verbs; personal pronouns",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/JfTc1G9mubs",
                "grammarbook_link": "https://drive.google.com/file/d/1obsYT3dP3qT-i06SjXmqRzCT2pNoJJZp/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1woXksV9sTZ_8huXa8yf6QUQ8aUXPxVug/view?usp=sharing"
            }
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Lesen & Hören 5",
            "chapter": "5",
            "goal": "Learn about the German articles and cases",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "grammar_topic": "Nominative & Akkusative, Definite & Indefinite Articles",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/Yi5ZA-XD-GY?si=nCX_pceEYgAL-FU0",
                "grammarbook_link": "https://drive.google.com/file/d/17y5fGW8nAbfeVgolV7tEW4BLiLXZDoO6/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1zjAqvQqNb7iKknuhJ79bUclimEaTg-mt/view?usp=sharing"
            }
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Lesen & Hören 6 and Schreiben & Sprechen 2.4",
            "chapter": "6_2.4",
            "goal": "Understand Possessive Determiners and its usage in connection with nouns",
            "instruction": "The assignment is the lesen and horen chapter 6 but you must also go through schreiben and sprechnen 2.4 for full understanding",         
            "lesen_hören": {
                "video": "https://youtu.be/SXwDqcwrR3k",
                "grammarbook_link": "https://drive.google.com/file/d/1Fy4bKhaHHb4ahS2xIumrLtuqdQ0YAFB4/view?usp=sharing",
                "assignment": True,
                "workbook_link": "https://drive.google.com/file/d/1Da1iw54oAqoaY-UIw6oyIn8tsDmIi1YR/view?usp=sharing"
            },
            "schreiben_sprechen": {
                "video": "https://youtu.be/5qnB2Gocp8s",
                "workbook_link": "https://drive.google.com/file/d/1GbIc44ToWh2upnHv6eX3ZjFrvnf4fcEM/view?usp=sharing",
                "assignment": False,
            }
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Lesen & Hören 7",
            "chapter": "7",
            "goal": "Understand the 12 hour clock system",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/uyvXoCoqjiE",
                "grammarbook_link": "https://drive.google.com/file/d/1pSaloRhfh8eTKK_r9mzwp6xkbfdkCVox/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1QyDdRae_1qv_umRb15dCJZTPdXi7zPWd/view?usp=sharing"
            }
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Lesen & Hören 8",
            "chapter": "8",
            "goal": "Understand the 24 hour clock and date system in German",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/hLpPFOthVkU",
                "grammarbook_link": "https://drive.google.com/file/d/1fW2ChjnDKW_5SEr65ZgE1ylJy1To46_p/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1onzokN8kQualNO6MSsPndFXiRwsnsVM9/view?usp=sharing"
            }
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Schreiben & Sprechen 3.5",
            "chapter": "3.5",
            "goal": "Recap from the lesen and horen. Understand numbers, time, asking of price and how to formulate statements in German",
            "instruction": "Use the statement rule to talk about your weekly routine using the activities listed. Share with your tutor when done",
            "schreiben_sprechen": {
                "video": "https://youtu.be/PwDLGmfBUDw",
                "assignment": False,
                "workbook_link": "https://drive.google.com/file/d/12oFKrKrHBwSpSnzxLX_e-cjPSiYtCFVs/view?usp=sharing"
            }
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Schreiben & Sprechen 3.6",
            "chapter": "3.6",
            "goal": "Understand how to use modal verbs with main verbs and separable verbs",
            "assignment": False,
            "instruction": "This is a practical exercise. All the answers are included in the document except for the last paragraph. You can send a screenshot of that to your tutor",
            "grammar_topic": "Modal Verbs",
            "schreiben_sprechen": {
                "video": "https://youtu.be/XwFPjLjvDog",
                "workbook_link": "https://drive.google.com/file/d/1wnZehLNfkjgKMFw1V3BX8V399rZg6XLv/view?usp=sharing"
            }
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Schreiben & Sprechen 4.7",
            "chapter": "4.7",
            "assignment": False,
            "goal": "Understand imperative statements and learn how to use them in your Sprechen exams, especially in Teil 3.",
            "instruction": "After completing this chapter, go to the Falowen Exam Chat Mode, select A1 Teil 3, and start practicing",
            "grammar_topic": "Imperative",
            "schreiben_sprechen": {
                "video": "https://youtu.be/IVtUc9T3o0Y",
                "workbook_link": "https://drive.google.com/file/d/1953B01hB9Ex7LXXU0qIaGU8xgCDjpSm4/view?usp=sharing"
            }
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Lesen & Hören 9 and 10",
            "chapter": "9_10",
            "goal": "Understand how to negate statements using nicht,kein and nein",
            "instruction": "This chapter has two assignments. Do the assignments for chapter 9 and after chapter 10. Chapter 10 has no grammar",
            "grammar_topic": "Negation",
            "lesen_hören": [
                {
                    "chapter": "9",
                    "video": "https://youtu.be/MrB3BPtQN6A",
                    "assignment": True,
                    "grammarbook_link": "https://drive.google.com/file/d/1g-qLEH1ZDnFZCT83TW-MPLxNt2nO7UAv/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1hKtQdXg5y3yJyFBQsCMr7fZ11cYbuG7D/view?usp=sharing"
                },
                {
                    "chapter": "10",
                    "video": "",
                    "grammarbook_link": "",
                    "assignment": True,
                    "workbook_link": "https://drive.google.com/file/d/1rJXshXQSS5Or4ipv1VmUMsoB0V1Vx4VK/view?usp=sharing"
                }
            ]
        },
        # DAY 17
        {
            "day": 17,
            "topic": "Lesen & Hören 11",
            "chapter": "11",
            "goal": "Understand instructions and request in German using the Imperative rule",
            "grammar_topic": "Direction",
            "instruction": "",
            "lesen_hören": {
                "video": "https://youtu.be/k2ZC3rXPe1k",
                "assignment": True,
                "grammarbook_link": "https://drive.google.com/file/d/1lMzZrM4aAItO8bBmehODvT6gG7dz8I9s/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/17FNSfHBxyga9sKxzicT_qkP7PA4vB5-A/view?usp=sharing"
            }
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Lesen & Hören 12.1 and 12.2",
            "chapter": "12.1_12.2",
            "goal": "Learn about German professions and how to use two-way prepositions",
            "instruction": "Do assignments for 12.1 and 12.2 and use the schreiben and sprechen below for practicals for full understanding",
            "grammar_topic": "Two Case Preposition",
            "lesen_hören": [
                {
                    "chapter": "12.1",
                    "video": "https://youtu.be/-vTEvx9a8Ts",
                    "assignment": True,
                    "grammarbook_link": "https://drive.google.com/file/d/1wdWYVxBhu4QtRoETDpDww-LjjzsGDYva/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1A0NkFl1AG68jHeqSytI3ygJ0k7H74AEX/view?usp=sharing"
                },
                {
                    "chapter": "12.2",
                    "video": "",
                    "assignment": True,
                    "grammarbook_link": "",
                    "workbook_link": "https://drive.google.com/file/d/1xojH7Tgb5LeJj3nzNSATUVppWnJgJLEF/view?usp=sharing"
                }
            ],
            "schreiben_sprechen": {
                "video": "https://youtu.be/xVyYo7upDGo",
                "assignment": False,
                "workbook_link": "https://drive.google.com/file/d/1iyYBuxu3bBEovxz0j9QeSu_1URX92fvN/view?usp=sharing"
            }
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Schreiben & Sprechen 5.9",
            "chapter": "5.9",
            "goal": "Understand the difference between Erlaubt and Verboten and how to use it in the exams hall",
            "instruction": "Review the workbook and do the practicals in it. Answers are attached",
            "grammar_topic": "Erlaubt and Verboten",
            "schreiben_sprechen": {
                "video": "https://youtu.be/MqAp84GthAo",
                "assignment": False,
                "workbook_link": "https://drive.google.com/file/d/1CkoYa_qeqsGju0kTS6ElurCAlEW6pVFL/view?usp=sharing"
            }
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Introduction to Letter Writing 12.3 ",
            "chapter": "12.3",
            "goal": "Practice how to write both formal and informal letters",
            "assignment": True,
            "instruction": "Write all the two letters in this document and send to your tutor for corrections",
            "grammar_topic": "Formal and Informal Letter",
            "schreiben_sprechen": {
                "video": "https://youtu.be/sHRHE1soH6I",
                "workbook_link": "https://drive.google.com/file/d/1SjaDH1bYR7O-BnIbM2N82XOEjeLCfPFb/view?usp=sharing"
            }
        },
        # DAY 21
        {
            "day": 21,
            "topic": "Lesen & Hören 13",
            "chapter": "13",
            "assignment": True,
            "goal": "",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "grammar_topic": "Weather and Past Tense. How to form Perfekt statement in German",
            "lesen_hören": {
                "video": "https://youtu.be/6cBs3Qfvdk4",
                "assignment": True,
                "grammarbook_link": "https://drive.google.com/file/d/1PCXsTIg9iNlaAUkwH8BYekw_3v1HJjGq/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1GZeUi5p6ayDGnPcebFVFfaNavmoWyoVM/view?usp=sharing"
            }
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Lesen & Hören 14.1",
            "chapter": "14.1",
            "goal": "Understand health and talking about body parts in German",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "grammar_topic": "Health and Body Parts",
            "lesen_hören": {
                "video": "https://youtu.be/Zx_TFF9FNGo",
                "assignment": True,
                "grammarbook_link": "https://drive.google.com/file/d/1QoG4mNxA1w8AeTMPfLtMQ_rAHrmC1DdO/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1LkDUU7r78E_pzeFnHKw9vfD9QgUAAacu/view?usp=sharing"
            }
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Lesen & Hören 14.2",
            "chapter": "14.2",
            "goal": "Understand adjective declension and dative verbs",
            "instruction": " This chapter has no assignment. Only grammar",
            "grammar_topic": "Adjective Declension and Dative Verbs",
            "lesen_hören": {
                "video": "",
                "assignment": False,
                "grammarbook_link": "https://drive.google.com/file/d/16h-yS0gkB2_FL1zxCC4MaqRBbKne7GI1/view?usp=sharing",
                "workbook_link": ""
            }
        },
        # DAY 24
        {
            "day": 24,
            "topic": "Schreiben & Sprechen 5.10",
            "chapter": "5.10",
            "goal": "Learn about conjunctions and how to apply them in your exams",
            "instruction": "This chapter has no assignments. It gives you ideas to progress for A2 and how to use conjunctions",
            "grammar_topic": "German Conjunctions",
            "assignment": False,
            "schreiben_sprechen": {
                "video": "https://youtu.be/WVq9x69dCeE",
                "workbook_link": "https://drive.google.com/file/d/1LE1b9ilkLLobE5Uw0TVLG0RIVpLK5k1t/view?usp=sharing"
            }
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Goethe Mock Test 15",
            "chapter": "15",
            "assignment": True,
            "goal": "This test should help the student have an idea about how the lesen and horen will look like",
            "instruction": "Open the link and answer the questions using the link. After submit and alert your tutor.",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://forms.gle/FP8ZPNhwxcAZsTfY6"
            }
        }
    ]

def get_a2_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Small Talk 1.1 (Exercise)",
            "chapter": "1.1",
            "goal": "Practice basic greetings and small talk.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "assignment": True,
            "video": "https://youtu.be/siF0jWZdIwk",
            "grammarbook_link": "https://drive.google.com/file/d/1NsCKO4K7MWI-queLWCeBuclmaqPN04YQ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1LXDI1yyJ4aT4LhX5eGDbKnkCkJZ2EE2T/view?usp=sharing"
        },
        # DAY 2
        {
            "day": 2,
            "topic": "Personen Beschreiben 1.2 (Exercise)",
            "chapter": "1.2",
            "goal": "Describe people and their appearance.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Subordinate Clauses (Nebensätze) with dass and weil",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1xMpEAPD8C0HtIFsmgqYO-wZaKDrQtiYp/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/128lWaKgCZ2V-3tActM-dwNy6igLLlzH3/view?usp=sharing"
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Dinge und Personen vergleichen 1.3",
            "chapter": "1.3",
            "goal": "Learn to compare things and people.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Positive, Comparative, and Superlative in German",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1Z3sSDCxPQz27TDSpN9r8lQUpHhBVfhYZ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/18YXe9mxyyKTars1gL5cgFsXrbM25kiN8/view?usp=sharing"
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Wo möchten wir uns treffen? 2.4",
            "chapter": "2.4",
            "goal": "Arrange and discuss meeting places.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Nominalization of Verbs",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/14qE_XJr3mTNr6PF5aa0aCqauh9ngYTJ8/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1RaXTZQ9jHaJYwKrP728zevDSQHFKeR0E/view?usp=sharing"
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Was machst du in deiner Freizeit? 2.5 ",
            "chapter": "2.5",
            "goal": "Talk about free time activities.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Dative Preposition",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/11yEcMioSB9x1ZD-x5_67ApFzP53iau-N/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1dIsFg7wNaqyyOHm95h7xv4Ssll5Fm0V1/view?usp=sharing"
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Möbel und Räume kennenlernen 3.6",
            "chapter": "3.6",
            "goal": "Identify furniture and rooms.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Two Case Preposition",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1MSahBEyElIiLnitWoJb5xkvRlB21yo0y/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/16UfBIrL0jxCqWtqqZaLhKWflosNQkwF4/view?usp=sharing"
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Eine Wohnung suchen (Übung) 3.7",
            "chapter": "3.7",
            "goal": "Practice searching for an apartment.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Identifying German Nouns and their Gender",
            "video": "https://youtu.be/ScU6w8VQgNg", 
            "grammarbook_link": "https://drive.google.com/file/d/1clWbDAvLlXpgWx7pKc71Oq3H2p0_GZnV/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1EF87TdHa6Y-qgLFUx8S6GAom9g5EBQNP/view?usp=sharing"
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Rezepte und Essen (Exercise) 3.8",
            "chapter": "3.8",
            "assignment": True,
            "goal": "Learn about recipes and food. Practice using sequence words like zuerst', 'nachdem', and 'außerdem' to organize your letter.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Zuerst, Nachdem, and Talking About Sequence in German",
            "video": "https://youtu.be/_xQMNp3qcDQ",
            "grammarbook_link": "https://drive.google.com/file/d/16lh8sPl_IDZ3dLwYNvL73PqOFCixidrI/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1c8JJyVlKYI2mz6xLZZ6RkRHLnH3Dtv0c/view?usp=sharing"
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Urlaub 4.9",
            "chapter": "4.9",
            "goal": "Discuss vacation plans.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Understanding Präteritum and Perfekt",
            "video": "https://youtu.be/NxoQH-BY9Js",
            "grammarbook_link": "https://drive.google.com/file/d/1kOb7c08Pkxf21OQE_xIGEaif7Xq7k-ty/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1NzRxbGUe306Vq0mq9kKsc3y3HYqkMhuA/view?usp=sharing"
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Tourismus und Traditionelle Feste 4.10",
            "chapter": "4.10",
            "assignment": True,
            "goal": "Learn about tourism and festivals.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Präteritum",
            "video": "https://youtu.be/XFxV3GSSm8E",
            "grammarbook_link": "https://drive.google.com/file/d/1snFsDYBK8RrPRq2n3PtWvcIctSph-zvN/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1vijZn-ryhT46cTzGmetuF0c4zys0yGlB/view?usp=sharing"
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Unterwegs: Verkehrsmittel vergleichen 4.11",
            "chapter": "4.11",
            "assignment": True,
            "goal": "Compare means of transportation.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Prepositions in and naxh",
            "video": "https://youtu.be/RkvfRiPCZI4",
            "grammarbook_link": "https://drive.google.com/file/d/19I7oOHX8r4daxXmx38mNMaZO10AXHEFu/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1c7ITea0iVbCaPO0piark9RnqJgZS-DOi/view?usp=sharing"
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Mein Traumberuf (Übung) 5.12",
            "chapter": "5.12",
            "assignment": True,
            "goal": "Learn how to talk about a dream job and future goals.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Konjunktiv II",
            "video": "https://youtu.be/w81bsmssGXQ",
            "grammarbook_link": "https://drive.google.com/file/d/1dyGB5q92EePy8q60eWWYA91LXnsWQFb1/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/18u6FnHpd2nAh1Ev_2mVk5aV3GdVC6Add/view?usp=sharing"
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Ein Vorstellungsgespräch (Exercise) 5.13",
            "chapter": "5.13",
            "assignment": True,
            "goal": "Prepare for a job interview.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Konjunktive II with modal verbs",
            "video": "https://youtu.be/urKBrX5VAYU",
            "grammarbook_link": "https://drive.google.com/file/d/1tv2tYzn9mIG57hwWr_ilxV1My7kt-RKQ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1sW2yKZptnYWPhS7ciYdi0hN5HV-ycsF0/view?usp=sharing"
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Beruf und Karriere (Exercise) 5.14",
            "chapter": "5.14",
            "assignment": True,
            "goal": "Discuss jobs and careers.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Modal Verbs",
            "video": "https://youtu.be/IyBvx-yVT-0",
            "grammarbook_link": "https://drive.google.com/file/d/13mVpVGfhY1NQn-BEb7xYUivnaZbhXJsK/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1rlZoo49bYBRjt7mu3Ydktzgfdq4IyK2q/view?usp=sharing"
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Mein Lieblingssport 6.15",
            "chapter": "6.15",
            "assignment": True,
            "goal": "Talk about your favorite sport.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Reflexive Pronouns",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1dGZjcHhdN1xAdK2APL54RykGH7_msUyr/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1iiExhUj66r5p0SJZfV7PsmCWOyaF360s/view?usp=sharing"
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Wohlbefinden und Entspannung 6.16",
            "chapter": "6.16",
            "goal": "Express well-being and relaxation.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Verbs and Adjectives with Prepositions",
            "video": "https://youtu.be/r4se8KuS8cA",
            "grammarbook_link": "https://drive.google.com/file/d/1BiAyDazBR3lTplP7D2yjaYmEm2btUT1D/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1G_sRFKG9Qt5nc0Zyfnax-0WXSMmbWB70/view?usp=sharing"
        },
        # DAY 17
        {
            "day": 17,
            "topic": "In die Apotheke gehen 6.17",
            "chapter": "6.17",
            "goal": "Learn phrases for the pharmacy.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Notes on German Indefinite Pronouns",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1O040UoSuBdy4llTK7MbGIsib63uNNcrV/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1vsdVR_ubbu5gbXnm70vZS5xGFivjBYoA/view?usp=sharing"
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Die Bank anrufen 7.18",
            "chapter": "7.18",
            "goal": "Practice calling the bank.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "grammar_topic": "Notes on Opening a Bank Account in Germany",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1qNHtY8MYOXjtBxf6wHi6T_P_X1DGFtPm/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1GD7cCPU8ZFykcwsFQZuQMi2fiNrvrCPg/view?usp=sharing"
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Einkaufen? Wo und wie? (Exercise) 7.19",
            "chapter": "7.19",
            "goal": "Shop and ask about locations.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1Qt9oxn-74t8dFdsk-NjSc0G5OT7MQ-qq/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1CEFn14eYeomtf6CpZJhyW00CA2f_6VRc/view?usp=sharing"
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Typische Reklamationssituationen üben 7.20",
            "chapter": "7.20",
            "goal": "Handle typical complaints.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1-72wZuNJE4Y92Luy0h5ygWooDnBd9PQW/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1_GTumT1II0E1PRoh6hMDwWsTPEInGeed/view?usp=sharing"
        },
        # DAY 21
        {
            "day": 21,
            "topic": "Ein Wochenende planen 8.21",
            "chapter": "8.21",
            "goal": "Plan a weekend.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1FcCg7orEizna4rAkX3_FCyd3lh_Bb3IT/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1mMtZza34QoJO_lfUiEX3kwTa-vsTN_RK/view?usp=sharing"
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Die Woche Planung 8.22",
            "chapter": "8.22",
            "goal": "Make a weekly plan.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1dWr4QHw8zT1RPbuIEr_X13cPLYpH-mms/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1mg_2ytNAYF00_j-TFQelajAxgQpmgrhW/view?usp=sharing"
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Wie kommst du zur Schule / zur Arbeit? 9.23",
            "chapter": "9.23",
            "goal": "Talk about your route to school or work.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1XbWKmc5P7ZAR-OqFce744xqCe7PQguXo/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1Ialg19GIE_KKHiLBDMm1aHbrzfNdb7L_/view?usp=sharing"
        },
        # DAY 24
        {
            "day": 24,
            "topic": "Einen Urlaub planen 9.24",
            "chapter": "9.24",
            "goal": "Plan a vacation.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1tFXs-DNKvt97Q4dsyXsYvKVQvT5Qqt0y/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1t3xqddDJp3-1XeJ6SesnsYsTO5xSm9vG/view?usp=sharing"
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Tagesablauf (Exercise) 9.25",
            "chapter": "9.25",
            "goal": "Describe a daily routine.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1jfWDzGfXrzhfGZ1bQe1u5MXVQkR5Et43/view?usp=sharing"
        },
        # DAY 26
        {
            "day": 26,
            "topic": "Gefühle in verschiedenen Situationen beschreiben 10.26",
            "chapter": "10.26",
            "goal": "Express feelings in various situations.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/126MQiti-lpcovP1TdyUKQAK6KjqBaoTx/view?usp=sharing"
        },
        # DAY 27
        {
            "day": 27,
            "topic": "Digitale Kommunikation 10.27",
            "chapter": "10.27",
            "goal": "Talk about digital communication.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1UdBu6O2AMQ2g6Ot_abTsFwLvT87LHHwY/view?usp=sharing"
        },
        # DAY 28
        {
            "day": 28,
            "topic": "Über die Zukunft sprechen 10.28",
            "chapter": "10.28",
            "goal": "Discuss the future.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1164aJFtkZM1AMb87s1-K59wuobD7q34U/view?usp=sharing"
        },
#
        # DAY 29
        {
            "day": 29,
            "topic": "Goethe Mock Test 10.29",
            "chapter": "10.29",
            "goal": "Practice how the final exams for the lesen will look like",
            "assignment": True,
            "instruction": "Answer everything on the phone and dont write in your book. The answers will be sent to your email",
            "video": "",
            "workbook_link": "https://forms.gle/YqCEMXTF5d3N9Q7C7"
        },
    ]

def get_b1_schedule():
    return [
        # TAG 1
        {
            "day": 1,
            "topic": "Traumwelten (Übung) 1.1",
            "chapter": "1.1",
            "goal": "Über Traumwelten und Fantasie sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "grammar_topic": "Präsens & Perfekt",
            "video": "https://youtu.be/wMrdW2DhD5o",
            "grammarbook_link": "https://drive.google.com/file/d/17dO2pWXKQ3V3kWZIgLHXpLJ-ozKHKxu5/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1gTcOHHGW2bXKkhxAC38jdl6OikgHCT9g/view?usp=sharing"
        },
        # TAG 2
        {
            "day": 2,
            "topic": "Freunde fürs Leben (Übung) 1.2",
            "chapter": "1.2",
            "goal": "Freundschaften und wichtige Eigenschaften beschreiben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "grammar_topic": "Präteritum – Vergangene Erlebnisse erzählen",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1St8MpH616FiJmJjTYI9b6hEpNCQd5V0T/view?usp=sharing",
            "workbook_link": ""
        },
        # TAG 3
        {
            "day": 3,
            "topic": "Erfolgsgeschichten (Übung) 1.3",
            "chapter": "1.3",
            "goal": "Über Erfolge und persönliche Erlebnisse berichten.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 4
        {
            "day": 4,
            "topic": "Wohnung suchen (Übung) 2.4",
            "chapter": "2.4",
            "goal": "Über Wohnungssuche und Wohnformen sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 5
        {
            "day": 5,
            "topic": "Der Besichtigungstermin (Übung) 2.5",
            "chapter": "2.5",
            "goal": "Einen Besichtigungstermin beschreiben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 6
        {
            "day": 6,
            "topic": "Leben in der Stadt oder auf dem Land? 2.6",
            "chapter": "2.6",
            "goal": "Stadtleben und Landleben vergleichen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 7
        {
            "day": 7,
            "topic": "Fast Food vs. Hausmannskost 3.7",
            "chapter": "3.7",
            "goal": "Fast Food und Hausmannskost vergleichen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 8
        {
            "day": 8,
            "topic": "Alles für die Gesundheit 3.8",
            "chapter": "3.8",
            "goal": "Tipps für Gesundheit geben und Arztbesuche besprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 9
        {
            "day": 9,
            "topic": "Work-Life-Balance im modernen Arbeitsumfeld 3.9",
            "chapter": "3.9",
            "goal": "Über Work-Life-Balance und Stress sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 10
        {
            "day": 10,
            "topic": "Digitale Auszeit und Selbstfürsorge 4.10",
            "chapter": "4.10",
            "goal": "Über digitale Auszeiten und Selbstfürsorge sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 11
        {
            "day": 11,
            "topic": "Teamspiele und Kooperative Aktivitäten 4.11",
            "chapter": "4.11",
            "goal": "Über Teamarbeit und kooperative Aktivitäten sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 12
        {
            "day": 12,
            "topic": "Abenteuer in der Natur 4.12",
            "chapter": "4.12",
            "goal": "Abenteuer und Erlebnisse in der Natur beschreiben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 13
        {
            "day": 13,
            "topic": "Eigene Filmkritik schreiben 4.13",
            "chapter": "4.13",
            "goal": "Eine Filmkritik schreiben und Filme bewerten.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 14
        {
            "day": 14,
            "topic": "Traditionelles vs. digitales Lernen 5.14",
            "chapter": "5.14",
            "goal": "Traditionelles und digitales Lernen vergleichen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 15
        {
            "day": 15,
            "topic": "Medien und Arbeiten im Homeoffice 5.15",
            "chapter": "5.15",
            "goal": "Über Mediennutzung und Homeoffice sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 16
        {
            "day": 16,
            "topic": "Prüfungsangst und Stressbewältigung 5.16",
            "chapter": "5.16",
            "goal": "Prüfungsangst und Strategien zur Stressbewältigung besprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 17
        {
            "day": 17,
            "topic": "Wie lernt man am besten? 5.17",
            "chapter": "5.17",
            "goal": "Lerntipps geben und Lernstrategien vorstellen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 18
        {
            "day": 18,
            "topic": "Wege zum Wunschberuf 6.18",
            "chapter": "6.18",
            "goal": "Über Wege zum Wunschberuf sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 19
        {
            "day": 19,
            "topic": "Das Vorstellungsgespräch 6.19",
            "chapter": "6.19",
            "goal": "Über Vorstellungsgespräche berichten und Tipps geben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 20
        {
            "day": 20,
            "topic": "Wie wird man …? (Ausbildung und Qu) 6.20",
            "chapter": "6.20",
            "goal": "Über Ausbildung und Qualifikationen sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 21
        {
            "day": 21,
            "topic": "Lebensformen heute – Familie, Wohnge 7.21",
            "chapter": "7.21",
            "goal": "Lebensformen, Familie und Wohngemeinschaften beschreiben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 22
        {
            "day": 22,
            "topic": "Was ist dir in einer Beziehung wichtig? 7.22",
            "chapter": "7.22",
            "goal": "Über Werte in Beziehungen sprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 23
        {
            "day": 23,
            "topic": "Erstes Date – Typische Situationen 7.23",
            "chapter": "7.23",
            "goal": "Typische Situationen beim ersten Date beschreiben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # TAG 24
        {
            "day": 24,
            "topic": "Konsum und Nachhaltigkeit 8.24",
            "chapter": "8.24",
            "goal": "Nachhaltigen Konsum und Umweltschutz diskutieren.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1x8IM6xcjR2hv3jbnnNudjyxLWPiT0-VL/view?usp=sharing"
        },
        # TAG 25
        {
            "day": 25,
            "topic": "Online einkaufen – Rechte und Risiken 8.25",
            "chapter": "8.25",
            "goal": "Rechte und Risiken beim Online-Shopping besprechen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1If0R3cIT8KwjeXjouWlQ-VT03QGYOSZz/view?usp=sharing"
        },
        # TAG 26
        {
            "day": 26,
            "topic": "Reiseprobleme und Lösungen 9.26",
            "chapter": "9.26",
            "goal": "Reiseprobleme und Lösungen beschreiben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1BMwDDkfPJVEhL3wHNYqGMAvjOts9tv24/view?usp=sharing"
        },
        # TAG 27
        {
            "day": 27,
            "topic": "Umweltfreundlich im Alltag 10.27",
            "chapter": "10.27",
            "goal": "Umweltfreundliches Verhalten im Alltag beschreiben.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/15fjOKp_u75GfcbvRJVbR8UbHg-cgrgWL/view?usp=sharing"
        },
        # TAG 28
        {
            "day": 28,
            "topic": "Klimafreundlich leben 10.28",
            "chapter": "10.28",
            "goal": "Klimafreundliche Lebensweisen vorstellen.",
            "assignment": True,
            "instruction": "Schau das Video, wiederhole die Grammatik und mache die Aufgabe.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1iBeZHMDq_FnusY4kkRwRQvyOfm51-COU/view?usp=sharing"
        },
    ]


# === B2 Schedule Template ===
def get_b2_schedule():
    return [
        {
            "day": 1,
            "topic": "B2 Welcome & Orientation",
            "chapter": "0.0",
            "goal": "Get familiar with the B2 curriculum and course expectations.",
            "instruction": "Read the course orientation material and introduce yourself in the chat.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        {
            "day": 2,
            "topic": "B2 Diagnostic Test (Optional)",
            "chapter": "0.1",
            "goal": "Assess your current level before starting.",
            "instruction": "Take the B2 diagnostic or placement test if available.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        }
        # You can add more B2 lessons here in the future
    ]

# === C1 Schedule Template ===
def get_c1_schedule():
    return [
        {
            "day": 1,
            "topic": "C1 Welcome & Orientation",
            "chapter": "0.0",
            "goal": "Get familiar with the C1 curriculum and expectations.",
            "instruction": "Read the C1 orientation, join the forum, and write a short self-intro.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        {
            "day": 2,
            "topic": "C1 Diagnostic Writing",
            "chapter": "0.1",
            "goal": "Write a sample essay for initial assessment.",
            "instruction": "Write and upload a short essay on the assigned topic.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        }
        # You can add more C1 lessons here in the future
    ]


# --- FORCE A MOCK LOGIN FOR TESTING ---
if "student_row" not in st.session_state:
    st.session_state["student_row"] = {
        "Name": "Test Student",
        "Level": "A1",
        "StudentCode": "demo001"
    }



student_row = st.session_state.get("student_row", {})
student_level = student_row.get("Level", "A1").upper()

# --- Cache level schedules with TTL for periodic refresh ---
@st.cache_data(ttl=86400)
def load_level_schedules():
    return {
        "A1": get_a1_schedule(),
        "A2": get_a2_schedule(),
        "B1": get_b1_schedule(),
        "B2": get_b2_schedule(),
        "C1": get_c1_schedule(),
    }

# --- Helpers ---

def render_assignment_reminder():
    """
    Render a responsive, mobile-friendly assignment reminder box with clear contrast.
    """
    st.markdown(
        '''
        <div style="
            box-sizing: border-box;
            width: 100%;
            max-width: 600px;
            padding: 16px;
            background: #ffc107;
            color: #000;
            border-left: 6px solid #e0a800;
            margin: 16px auto;
            border-radius: 8px;
            font-size: 1.1rem;
            line-height: 1.4;
            text-align: center;
            overflow-wrap: break-word;
            word-wrap: break-word;
        ">
            ⬆️ <strong>Your Assignment:</strong><br>
            Complete the exercises in your <em>workbook</em> for this chapter.
        </div>
        ''',
        unsafe_allow_html=True
    )

def render_link(label, url):
    st.markdown(f"- [{label}]({url})")

@st.cache_data(ttl=86400)
def build_wa_message(name, code, level, day, chapter, answer):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"Learn Language Education Academy – Assignment Submission\n"
        f"Name: {name}\n"
        f"Code: {code}\n"
        f"Level: {level}\n"
        f"Day: {day}\n"
        f"Chapter: {chapter}\n"
        f"Date: {timestamp}\n"
        f"Answer: {answer if answer.strip() else '[See attached file/photo]'}"
    )


def highlight_terms(text, terms):
    """Wrap each term in <span> for highlight in markdown/html."""
    if not text: return ""
    for term in terms:
        if not term.strip():
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        text = pattern.sub(f"<span style='background:yellow;border-radius:0.23em;'>{term}</span>", text)
    return text

def filter_matches(lesson, terms):
    """Check if ANY term appears in ANY searchable field."""
    searchable = (
        str(lesson.get('topic', '')).lower() +
        str(lesson.get('chapter', '')).lower() +
        str(lesson.get('goal', '')).lower() +
        str(lesson.get('instruction', '')).lower() +
        str(lesson.get('grammar_topic', '')).lower() +
        str(lesson.get('day', '')).lower()
    )
    return any(term in searchable for term in terms)
    
def render_section(day_info, key, title, icon):
    content = day_info.get(key)
    if not content:
        return
    items = content if isinstance(content, list) else [content]
    st.markdown(f"#### {icon} {title}")
    for idx, part in enumerate(items):
        if len(items) > 1:
            st.markdown(f"###### {icon} Part {idx+1} of {len(items)}: Chapter {part.get('chapter','')}")
        if part.get('video'):
            st.video(part['video'])
        if part.get('grammarbook_link'):
            render_link("📘 Grammar Book (Notes)", part['grammarbook_link'])
            st.markdown(
                '<em>Further notice:</em> 📘 contains notes; 📒 is your workbook assignment.',
                unsafe_allow_html=True
            )
        if part.get('workbook_link'):
            render_link("📒 Workbook (Assignment)", part['workbook_link'])
            render_assignment_reminder()
        extras = part.get('extra_resources')
        if extras:
            for ex in (extras if isinstance(extras, list) else [extras]):
                render_link("🔗 Extra", ex)

RESOURCE_LABELS = {
    'video': '🎥 Video',
    'grammarbook_link': '📘 Grammar',
    'workbook_link': '📒 Workbook',
    'extra_resources': '🔗 Extra'
}

if tab == "Course Book":
    st.markdown(
        '''
        <div style="
            padding: 16px;
            background: #007bff;
            color: #ffffff;
            border-radius: 8px;
            text-align: center;
            margin-bottom: 16px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        ">
            <span style="font-size:1.8rem; font-weight:600;">📈 Course Book</span>
        </div>
        ''', unsafe_allow_html=True
    )
    st.divider()

    schedules = load_level_schedules()
    schedule = schedules.get(student_level, schedules.get('A1', []))

    query = st.text_input("🔍 Search for topic, chapter, grammar, day, or anything…")
    search_terms = [q for q in query.strip().lower().split() if q] if query else []

    if search_terms:
        matches = [(i, d) for i, d in enumerate(schedule) if filter_matches(d, search_terms)]
        if not matches:
            st.warning("No matching lessons. Try simpler terms or check spelling.")
            st.stop()
        labels = []
        for _, d in matches:
            title = highlight_terms(f"Day {d['day']}: {d['topic']}", search_terms)
            grammar = highlight_terms(d.get('grammar_topic', ''), search_terms)
            labels.append(f"{title}  {'<span style=\"color:#007bff\">['+grammar+']</span>' if grammar else ''}")
        sel = st.selectbox("Lessons:", list(range(len(matches))), format_func=lambda i: labels[i], key="course_search_sel")
        idx = matches[sel][0]
    else:
        idx = st.selectbox(
            "Choose your lesson/day:",
            range(len(schedule)),
            format_func=lambda i: f"Day {schedule[i]['day']} - {schedule[i]['topic']}"
        )

    # ===== Progress Bar (just for scrolling/selection) =====
    total_assignments = len(schedule)
    assignments_done = idx + 1
    percent = int((assignments_done / total_assignments) * 100) if total_assignments else 0
    st.progress(percent)
    st.markdown(f"**You’ve loaded {assignments_done} / {total_assignments} lessons ({percent}%)**")

    # ===== Estimated time for just this lesson =====
    LEVEL_TIME = {
        "A1": 15,
        "A2": 25,
        "B1": 30,
        "B2": 40,
        "C1": 45
    }
    current_time = LEVEL_TIME.get(student_level, 20)
    st.info(f"⏱️ **Recommended:** Invest about {current_time} minutes to complete this lesson fully.")

    # ====== SUGGESTED END DATE CALCULATION (THREE PACES) ======
    contract_start_str = student_row.get('ContractStart', '')
    contract_start_date = None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            contract_start_date = datetime.strptime(contract_start_str, fmt).date()
            break
        except Exception:
            continue

    if contract_start_date:
        # 3 per week
        weeks_3 = (total_assignments + 2) // 3
        end_3 = contract_start_date + timedelta(weeks=weeks_3)
        # 2 per week
        weeks_2 = (total_assignments + 1) // 2
        end_2 = contract_start_date + timedelta(weeks=weeks_2)
        # 1 per week
        weeks_1 = total_assignments
        end_1 = contract_start_date + timedelta(weeks=weeks_1)

        st.success(f"🎯 **At 3 lessons/week, you can finish by:** {end_3.strftime('%A, %d %b %Y')}")
        st.info(f"🟢 **At 2 lessons/week, you can finish by:** {end_2.strftime('%A, %d %b %Y')}")
        st.warning(f"🟡 **At 1 lesson/week, you can finish by:** {end_1.strftime('%A, %d %b %Y')}")
        st.caption("Stay consistent – choose your pace and finish on time.")
    else:
        st.warning("❓ Start date missing or wrong format. Please contact admin to update your contract start date for end date suggestion.")


    info = schedule[idx]
    st.markdown(
        f"### {highlight_terms('Day ' + str(info['day']) + ': ' + info['topic'], search_terms)} (Chapter {info['chapter']})",
        unsafe_allow_html=True
    )
    if info.get('grammar_topic'):
        st.markdown(f"**🔤 Grammar Focus:** {highlight_terms(info['grammar_topic'], search_terms)}", unsafe_allow_html=True)
    if info.get('goal'):
        st.markdown(f"**🎯 Goal:**  {info['goal']}")
    if info.get('instruction'):
        st.markdown(f"**📝 Instruction:**  {info['instruction']}")

    render_section(info, 'lesen_hören', 'Lesen & Hören', '📚')
    render_section(info, 'schreiben_sprechen', 'Schreiben & Sprechen', '📝')

    if student_level in ['A2', 'B1', 'B2', 'C1']:
        for res, label in RESOURCE_LABELS.items():
            val = info.get(res)
            if val:
                if res == 'video':
                    st.video(val)
                else:
                    st.markdown(f"- [{label}]({val})", unsafe_allow_html=True)
        st.markdown(
            '<em>Further notice:</em> 📘 contains notes; 📒 is your workbook assignment.',
            unsafe_allow_html=True
        )

    st.divider()

    st.info("Before you submit your assignment, do you mind watching the Video of the Day? Click below to open it.")

    with st.expander("🎬 Video of the Day for Your Level"):
        playlist_id = YOUTUBE_PLAYLIST_IDS.get(student_level)
        if playlist_id:
            video_list = fetch_youtube_playlist_videos(playlist_id, YOUTUBE_API_KEY)
            if video_list:
                today_idx = date.today().toordinal()
                pick = today_idx % len(video_list)
                video = video_list[pick]
                st.markdown(f"**{video['title']}**")
                st.video(video['url'])
            else:
                st.info("No videos found for your level’s playlist. Check back soon!")
        else:
            st.info("No playlist found for your level yet. Stay tuned!")

    st.header("📲 Submit Assignment (WhatsApp)")

    def render_whatsapp():
        st.subheader("👤 Your Name & Code")
        name = st.text_input("Name", value=student_row.get('Name',''))
        code = st.text_input("Code", value=student_row.get('StudentCode',''))
        st.subheader("✍️ Your Answer")
        ans = st.text_area("Answer (or attach on WhatsApp)", height=500)
        msg = build_wa_message(name, code, student_level, info['day'], info['chapter'], ans)
        url = "https://api.whatsapp.com/send?phone=233205706589&text=" + urllib.parse.quote(msg)
        if st.button("📤 Send via WhatsApp"):
            st.success("Click link below to open WhatsApp.")
            st.markdown(f"[📨 Open WhatsApp]({url})")
        st.text_area("📋 Copy message:", msg, height=500)

    render_whatsapp()

    st.info(
        """
    - Tap the links above to open resources in a new tab.
    - Mention which task you're submitting.
    - Use your correct name and code.
        """
    )


    st.info(
        """
- Tap the links above to open resources in a new tab.
- Mention which task you're submitting.
- Use your correct name and code.
        """
    )



if tab == "My Results and Resources":
    # 📊 Compact Results & Resources header
    st.markdown(
        '''
        <div style="
            padding: 8px 12px;
            background: #17a2b8;
            color: #fff;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 8px;
            font-size: 1.3rem;
        ">
            📊 My Results & Resources
        </div>
        ''',
        unsafe_allow_html=True
    )
    st.divider()
    
    import requests, io, pandas as pd, re, base64
    from fpdf import FPDF
    from collections import Counter

    # ============ LEVEL SCHEDULES (assume these functions are defined above) ============
    LEVEL_SCHEDULES = {
        "A1": get_a1_schedule(),
        "A2": get_a2_schedule(),
        "B1": get_b1_schedule(),
        "B2": get_b2_schedule(),
        "C1": get_c1_schedule(),
    }

    # --- LIVE GOOGLE SHEETS CSV LINK ---
    GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ/gviz/tq?tqx=out:csv"

    def get_pdf_download_link(pdf_bytes, filename="results.pdf"):
        b64 = base64.b64encode(pdf_bytes).decode()
        return f'<a href="data:application/pdf;base64,{b64}" download="{filename}" style="font-size:1.1em;font-weight:600;color:#2563eb;">📥 Click here to download PDF (manual)</a>'

    @st.cache_data
    def fetch_scores():
        response = requests.get(GOOGLE_SHEET_CSV, timeout=7)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text), engine='python')
        df.columns = [col.strip().lower().replace('studentcode', 'student_code') for col in df.columns]
        required_cols = ["student_code", "name", "assignment", "score", "date", "level"]
        df = df.dropna(subset=required_cols)
        return df

    # --- Session Vars ---
    student_code = st.session_state.get("student_code", "")
    student_name = st.session_state.get("student_name", "")
    st.header("📈 My Results and Resources Hub")
    st.markdown("View and download your assignment history. All results are private and only visible to you.")

    # ========== REFRESH BUTTON ==========
    if st.button("🔄 Refresh for your latest results"):
        st.cache_data.clear()
        st.success("Cache cleared! Reloading…")
        st.rerun()

    # ========== FETCH AND FILTER DATA ==========
    df_scores = fetch_scores()
    required_cols = {"student_code", "name", "assignment", "score", "date", "level"}
    if not required_cols.issubset(df_scores.columns):
        st.error("Data format error. Please contact support.")
        st.write("Columns found:", df_scores.columns.tolist())
        st.stop()

    code = student_code.lower().strip()
    df_user = df_scores[df_scores.student_code.str.lower().str.strip() == code]
    if df_user.empty:
        st.info("No results yet. Complete an assignment to see your scores!")
        st.stop()

    # --- Choose level
    df_user['level'] = df_user.level.str.upper().str.strip()
    levels = sorted(df_user['level'].unique())
    level = st.selectbox("Select level:", levels)
    df_lvl = df_user[df_user.level == level]

    # ========== METRICS ==========
    totals = {"A1": 18, "A2": 29, "B1": 28, "B2": 24, "C1": 24}
    total = totals.get(level, 0)
    completed = df_lvl.assignment.nunique()
    df_lvl = df_lvl.copy()
    df_lvl['score'] = pd.to_numeric(df_lvl['score'], errors='coerce')
    avg_score = df_lvl['score'].mean() or 0
    best_score = df_lvl['score'].max() or 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Assignments", total)
    col2.metric("Completed", completed)
    col3.metric("Average Score", f"{avg_score:.1f}")
    col4.metric("Best Score", best_score)

    # ========== DETAILED RESULTS ==========
    st.markdown("---")
    st.info("🔎 **Scroll down and expand the box below to see your full assignment history and feedback!**")

    # --- Score label function ---
    def score_label(score):
        try:
            score = float(score)
        except:
            return ""
        if score >= 90:
            return "Excellent 🌟"
        elif score >= 75:
            return "Good 👍"
        elif score >= 60:
            return "Sufficient ✔️"
        else:
            return "Needs Improvement ❗"

    with st.expander("📋 SEE DETAILED RESULTS (ALL ASSIGNMENTS & FEEDBACK)", expanded=False):
        if 'comments' in df_lvl.columns:
            df_display = (
                df_lvl.sort_values(['assignment', 'score'], ascending=[True, False])
                [['assignment', 'score', 'date', 'comments']]
                .reset_index(drop=True)
            )
            for idx, row in df_display.iterrows():
                perf = score_label(row['score'])
                st.markdown(
                    f"""
                    <div style="margin-bottom: 18px;">
                    <span style="font-size:1.05em;font-weight:600;">{row['assignment']}</span>  
                    <br>Score: <b>{row['score']}</b> <span style='margin-left:12px;'>{perf}</span> | Date: {row['date']}<br>
                    <div style='margin:8px 0; padding:10px 14px; background:#f2f8fa; border-left:5px solid #007bff; border-radius:7px; color:#333; font-size:1em;'>
                    <b>Feedback:</b> {row['comments'] if pd.notnull(row['comments']) and str(row['comments']).strip().lower() != 'nan' else '<i>No feedback</i>'}
                    </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                st.divider()
        else:
            df_display = (
                df_lvl.sort_values(['assignment', 'score'], ascending=[True, False])
                [['assignment', 'score', 'date']]
                .reset_index(drop=True)
            )
            st.table(df_display)
    st.markdown("---") 

    # ========== BADGES & TROPHIES ==========
    st.markdown("### 🏅 Badges & Trophies")
    with st.expander("What badges can you earn?", expanded=False):
        st.markdown(
            """
            - 🏆 **Completion Trophy**: Finish all assignments for your level.
            - 🥇 **Gold Badge**: Maintain an average score above 80.
            - 🥈 **Silver Badge**: Average score above 70.
            - 🥉 **Bronze Badge**: Average score above 60.
            - 🌟 **Star Performer**: Score 85 or higher on any assignment.
            """
        )

    badge_count = 0
    if completed >= total and total > 0:
        st.success("🏆 **Congratulations!** You have completed all assignments for this level!")
        badge_count += 1
    if avg_score >= 90:
        st.info("🥇 **Gold Badge:** Average score above 90!")
        badge_count += 1
    elif avg_score >= 75:
        st.info("🥈 **Silver Badge:** Average score above 75!")
        badge_count += 1
    elif avg_score >= 60:
        st.info("🥉 **Bronze Badge:** Average score above 60!")
        badge_count += 1
    if best_score >= 95:
        st.info("🌟 **Star Performer:** You scored 95 or above on an assignment!")
        badge_count += 1
    if badge_count == 0:
        st.warning("No badges yet. Complete more assignments to earn badges!")

    # ========== SKIPPED ASSIGNMENTS LOGIC ==========
    def extract_all_chapter_nums(chapter_str):
        parts = re.split(r'[_\s,;]+', str(chapter_str))
        nums = []
        for part in parts:
            match = re.search(r'\d+(?:\.\d+)?', part)
            if match:
                nums.append(float(match.group()))
        return nums

    # Build a set of all chapter numbers completed by student
    completed_nums = set()
    for _, row in df_lvl.iterrows():
        nums = extract_all_chapter_nums(row['assignment'])
        completed_nums.update(nums)

    last_num = max(completed_nums) if completed_nums else 0

    schedule = LEVEL_SCHEDULES.get(level, [])
    skipped_assignments = []
    for lesson in schedule:
        chapter_field = lesson.get("chapter", "")
        lesson_nums = extract_all_chapter_nums(chapter_field)
        day = lesson.get("day", "")
        has_assignment = lesson.get("assignment", False)
        for chap_num in lesson_nums:
            if (
                has_assignment
                and chap_num < last_num
                and chap_num not in completed_nums
            ):
                skipped_assignments.append(
                    f"Day {day}: Chapter {chapter_field} – {lesson.get('topic','')}"
                )
                break  # Only need to flag once per lesson

    if skipped_assignments:
        st.markdown(
            f"""
            <div style="
                background-color: #fff3cd;
                border-left: 6px solid #ffecb5;
                color: #7a6001;
                padding: 16px 18px 16px 16px;
                border-radius: 8px;
                margin: 12px 0;
                font-size: 1.05em;">
                <b>⚠️ You have skipped the following assignments.<br>
                Please complete them for full progress:</b><br>
                {"<br>".join(skipped_assignments)}
            </div>
            """,
            unsafe_allow_html=True
        )

    # ========== NEXT ASSIGNMENT RECOMMENDATION ==========
    def is_recommendable_assignment(lesson):
        topic = str(lesson.get("topic", "")).lower()
        # Skip if both "schreiben" and "sprechen" in topic
        if "schreiben" in topic and "sprechen" in topic:
            return False
        return True

    def extract_chapter_num(chapter):
        nums = re.findall(r'\d+(?:\.\d+)?', str(chapter))
        if not nums:
            return None
        return max(float(n) for n in nums)

    completed_chapters = []
    for assignment in df_lvl['assignment']:
        num = extract_chapter_num(assignment)
        if num is not None:
            completed_chapters.append(num)
    last_num = max(completed_chapters) if completed_chapters else 0

    next_assignment = None
    for lesson in schedule:
        chap_num = extract_chapter_num(lesson.get("chapter", ""))
        if not is_recommendable_assignment(lesson):
            continue  # Skip Schreiben & Sprechen lessons
        if chap_num and chap_num > last_num:
            next_assignment = lesson
            break
    if next_assignment:
        st.success(
            f"**Your next recommended assignment:**\n\n"
            f"**Day {next_assignment['day']}: {next_assignment['chapter']} – {next_assignment['topic']}**\n\n"
            f"**Goal:** {next_assignment.get('goal','')}\n\n"
            f"**Instruction:** {next_assignment.get('instruction','')}"
        )
    else:
        st.info("🎉 Great Job!")

    # ========== DOWNLOAD PDF SUMMARY ==========
    # Constants for layout
    COL_ASSN_W = 45
    COL_SCORE_W = 18
    COL_DATE_W = 30
    PAGE_WIDTH = 210  # A4 width in mm
    MARGIN = 10       # default margin
    FEEDBACK_W = PAGE_WIDTH - 2 * MARGIN - (COL_ASSN_W + COL_SCORE_W + COL_DATE_W)
    LOGO_URL = "https://i.imgur.com/iFiehrp.png"

    @st.cache_data
    def fetch_logo():
        import requests, tempfile
        try:
            resp = requests.get(LOGO_URL, timeout=6)
            resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.write(resp.content)
            tmp.flush()
            return tmp.name
        except Exception:
            return None

    from fpdf import FPDF
    class PDFReport(FPDF):
        def header(self):
            logo_path = fetch_logo()
            if logo_path:
                try:
                    self.image(logo_path, 10, 8, 30)
                    self.ln(20)
                except Exception:
                    self.ln(20)
            else:
                self.ln(28)
            self.set_font("Arial", 'B', 16)
            self.cell(0, 12, clean_for_pdf("Learn Language Education Academy"), ln=1, align='C')
            self.ln(3)

        def footer(self):
            self.set_y(-15)
            self.set_font("Arial", 'I', 9)
            self.set_text_color(120, 120, 120)
            footer_text = clean_for_pdf("Learn Language Education Academy — Results generated on ") + pd.Timestamp.now().strftime("%d.%m.%Y")
            self.cell(0, 8, footer_text, 0, 0, 'C')
            self.set_text_color(0, 0, 0)
            self.alias_nb_pages()

    if st.button("⬇️ Download PDF Summary"):
        import unicodedata
        def clean_for_pdf(text):
            if not isinstance(text, str):
                text = str(text)
            text = unicodedata.normalize('NFKD', text)
            text = ''.join(c if 32 <= ord(c) <= 255 else '?' for c in text)
            text = text.replace('\n', ' ').replace('\r', ' ')
            return text

        def score_label(score):
            try:
                s = float(score)
            except:
                return "Needs Improvement"
            if s >= 90:
                return "Excellent"
            elif s >= 75:
                return "Good"
            elif s >= 60:
                return "Sufficient"
            else:
                return "Needs Improvement"

        # Create PDF and add first page
        pdf = PDFReport()
        pdf.add_page()

        # Student Info
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 8, clean_for_pdf(f"Name: {df_user.name.iloc[0]}"), ln=1)
        pdf.cell(0, 8, clean_for_pdf(f"Code: {code}     Level: {level}"), ln=1)
        pdf.cell(0, 8, clean_for_pdf(f"Date: {pd.Timestamp.now():%Y-%m-%d %H:%M}"), ln=1)
        pdf.ln(5)

        # Summary Metrics
        pdf.set_font("Arial", 'B', 13)
        pdf.cell(0, 10, clean_for_pdf("Summary Metrics"), ln=1)
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, clean_for_pdf(f"Total: {total}   Completed: {completed}   Avg: {avg_score:.1f}   Best: {best_score}"), ln=1)
        pdf.ln(6)

        # Table Header
        pdf.set_font("Arial", 'B', 11)
        pdf.set_fill_color(235, 235, 245)
        pdf.cell(COL_ASSN_W, 9, "Assignment", 1, 0, 'C', True)
        pdf.cell(COL_SCORE_W, 9, "Score", 1, 0, 'C', True)
        pdf.cell(COL_DATE_W, 9, "Date", 1, 0, 'C', True)
        pdf.cell(FEEDBACK_W, 9, "Feedback", 1, 1, 'C', True)
        pdf.set_font("Arial", '', 10)
        pdf.set_fill_color(249, 249, 249)
        row_fill = False

        # Table Rows with wrapped feedback
        for _, row in df_display.iterrows():
            assn = clean_for_pdf(str(row['assignment'])[:24])
            score_txt = clean_for_pdf(str(row['score']))
            date_txt = clean_for_pdf(str(row['date']))
            label = clean_for_pdf(score_label(row['score']))
            pdf.cell(COL_ASSN_W, 8, assn, 1, 0, 'L', row_fill)
            pdf.cell(COL_SCORE_W, 8, score_txt, 1, 0, 'C', row_fill)
            pdf.cell(COL_DATE_W, 8, date_txt, 1, 0, 'C', row_fill)
            pdf.multi_cell(FEEDBACK_W, 8, label, 1, 'C', row_fill)
            row_fill = not row_fill

        # Output Download
        pdf_bytes = pdf.output(dest='S').encode('latin1', 'replace')
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"{code}_results_{level}.pdf",
            mime="application/pdf"
        )
        st.markdown(get_pdf_download_link(pdf_bytes, f"{code}_results_{level}.pdf"), unsafe_allow_html=True)
        st.info("If the button does not work, right-click the blue link above and choose 'Save link as...' to download your PDF.")

    st.markdown("---")
    st.subheader("📚 Useful Resources")
    st.markdown(
        """
**1. [A1 Schreiben Practice Questions](https://drive.google.com/file/d/1X_PFF2AnBXSrGkqpfrArvAnEIhqdF6fv/view?usp=sharing)**  
Practice writing tasks and sample questions for A1.

**2. [A1 Exams Sprechen Guide](https://drive.google.com/file/d/1UWvbCCCcrW3_j9x7pOuWug6_Odvzcvaa/view?usp=sharing)**  
Step-by-step guide to the A1 speaking exam.

**3. [German Writing Rules](https://drive.google.com/file/d/1o7_ez3WSNgpgxU_nEtp6EO1PXDyi3K3b/view?usp=sharing)**  
Tips and grammar rules for better writing.

**4. [A2 Sprechen Guide](https://drive.google.com/file/d/1TZecDTjNwRYtZXpEeshbWnN8gCftryhI/view?usp=sharing)**  
A2-level speaking exam guide.

**5. [B1 Sprechen Guide](https://drive.google.com/file/d/1snk4mL_Q9-xTBXSRfgiZL_gYRI9tya8F/view?usp=sharing)**  
How to prepare for your B1 oral exam.
        """
    )



# ================================
# 5a. EXAMS MODE & CUSTOM CHAT TAB (block start, pdf helper, prompt builders)
# ================================

def save_exam_progress(student_code, progress_items):
    doc_ref = db.collection("exam_progress").document(student_code)
    doc = doc_ref.get()
    data = doc.to_dict() if doc.exists else {}
    all_progress = data.get("completed", [])
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for item in progress_items:
        # Only add if not already present (avoid duplicates)
        already = any(
            p["level"] == item["level"] and
            p["teil"] == item["teil"] and
            p["topic"] == item["topic"]
            for p in all_progress
        )
        if not already:
            all_progress.append({
                "level": item["level"],
                "teil": item["teil"],
                "topic": item["topic"],
                "date": now
            })
    doc_ref.set({"completed": all_progress}, merge=True)

def back_step(to_stage=1):
    # Clear relevant session state values depending on the step
    if to_stage == 1:
        keys_to_clear = [
            "falowen_mode", "falowen_level", "falowen_teil", "falowen_messages",
            "custom_topic_intro_done", "falowen_exam_topic", "falowen_exam_keyword",
            "remaining_topics", "used_topics", "_falowen_loaded"
        ]
    elif to_stage == 2:
        keys_to_clear = [
            "falowen_level", "falowen_teil", "falowen_messages",
            "custom_topic_intro_done", "falowen_exam_topic", "falowen_exam_keyword",
            "remaining_topics", "used_topics", "_falowen_loaded"
        ]
    elif to_stage == 3:
        keys_to_clear = [
            "falowen_teil", "falowen_messages",
            "custom_topic_intro_done", "falowen_exam_topic", "falowen_exam_keyword",
            "remaining_topics", "used_topics", "_falowen_loaded"
        ]
    else:
        keys_to_clear = []
    for k in keys_to_clear:
        st.session_state[k] = None
    st.session_state["falowen_stage"] = to_stage
    st.rerun()


# --- CONFIG ---
exam_sheet_id = "1zaAT5NjRGKiITV7EpuSHvYMBHHENMs9Piw3pNcyQtho"
exam_sheet_name = "exam_topics"   # <-- update if your tab is named differently
exam_csv_url = f"https://docs.google.com/spreadsheets/d/{exam_sheet_id}/gviz/tq?tqx=out:csv&sheet={exam_sheet_name}"

@st.cache_data
def load_exam_topics():
    df = pd.read_csv(exam_csv_url)
    # Fill missing columns for Teil 3 if you only have a prompt
    for col in ['Level', 'Teil', 'Topic', 'Keyword']:
        if col not in df.columns:
            df[col] = ""
    return df

df_exam = load_exam_topics()

bubble_user = (
    "background:#1976d2; color:#fff; border-radius:18px 18px 2px 18px;"
    "padding:10px 16px; margin:5px 0 5px auto; max-width:90vw; display:inline-block; font-size:1.12em;"
    "box-shadow:0 2px 8px rgba(0,0,0,0.09); word-break:break-word;"
)
bubble_assistant = (
    "background:#faf9e4; color:#2d2d2d; border-radius:18px 18px 18px 2px;"
    "padding:10px 16px; margin:5px auto 5px 0; max-width:90vw; display:inline-block; font-size:1.12em;"
    "box-shadow:0 2px 8px rgba(0,0,0,0.09); word-break:break-word;"
)
highlight_words = [
    "Fehler", "Tipp", "Achtung", "gut", "korrekt", "super", "nochmals", "Bitte", "Vergessen Sie nicht"
]

def highlight_keywords(text, words):
    for w in words:
        text = text.replace(w, f"<span style='background:#ffe082; color:#d84315; font-weight:bold;'>{w}</span>")
    return text

if tab == "Exams Mode & Custom Chat":
    # --- UNIQUE LOGIN & SESSION ISOLATION BLOCK (inserted at the top) ---
    if "student_code" not in st.session_state or not st.session_state["student_code"]:
        code = st.text_input("Enter your Student Code to continue:", key="login_code")
        if st.button("Login"):
            st.session_state["student_code"] = code.strip()
            st.session_state["last_logged_code"] = code.strip()
            st.rerun()
        st.stop()
    else:
        code = st.session_state["student_code"]
        last_code = st.session_state.get("last_logged_code", None)
        if last_code != code:
            # Clear all chat-related session state for new login
            for k in [
                "falowen_messages", "falowen_stage", "falowen_teil", "falowen_mode",
                "custom_topic_intro_done", "falowen_turn_count",
                "falowen_exam_topic", "falowen_exam_keyword", "remaining_topics", "used_topics",
                "_falowen_loaded", "falowen_practiced_topics"
            ]:
                if k in st.session_state: del st.session_state[k]
            st.session_state["last_logged_code"] = code
            st.rerun()

    # --- PROGRESS TRACKING: PRACTICED TOPICS (unique per login) ---
    if "falowen_practiced_topics" not in st.session_state:
        st.session_state["falowen_practiced_topics"] = []


        
    # 🗣️ Compact tab header
    st.markdown(
        '''
        <div style="
            padding: 8px 12px;
            background: #28a745;
            color: #fff;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 8px;
            font-size: 1.3rem;
        ">
            🗣️ Exam Simulator & Custom Chat
        </div>
        ''',
        unsafe_allow_html=True
    )
    st.divider()

    # ---- Exam Sample Images (A1/A2 Template) ----
    image_map = {
        ("A1", "Teil 1"): {
            "url": "https://i.imgur.com/sKQDrpx.png",
            "caption": "Sample – A1 Teil 1"
        },
        ("A1", "Teil 2"): {
            "url": "https://i.imgur.com/xTTIUME.png",  # Replace with real image if you get a valid link!
            "caption": "Sample – A1 Teil 2"
        },
        ("A1", "Teil 3"): {
            "url": "https://i.imgur.com/MxBUCR8.png",
            "caption": "Sample – A1 Teil 3"
        },
        # Add A2 etc:
        # ("A2", "Teil 1"): { ... }
    }

    # Display image only for selected level/teil and at the start of chat
    level = st.session_state.get("falowen_level")
    teil = st.session_state.get("falowen_teil")
    msgs = st.session_state.get("falowen_messages", [])
    # Show image if no chat yet, or only the 1st assistant instruction
    if level and teil and (not msgs or (len(msgs) == 1 and msgs[0].get("role") == "assistant")):
        for (map_level, map_teil), v in image_map.items():
            if level == map_level and map_teil in teil:
                st.image(v["url"], width=380, caption=v["caption"])


    # ---- PDF Helper ----
    def falowen_download_pdf(messages, filename):
        from fpdf import FPDF
        import os
        def safe_latin1(text):
            return text.encode("latin1", "replace").decode("latin1")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        chat_text = ""
        for m in messages:
            role = "Herr Felix" if m["role"] == "assistant" else "Student"
            safe_msg = safe_latin1(m["content"])
            chat_text += f"{role}: {safe_msg}\n\n"
        pdf.multi_cell(0, 10, chat_text)
        pdf_output = f"{filename}.pdf"
        pdf.output(pdf_output)
        with open(pdf_output, "rb") as f:
            pdf_bytes = f.read()
        os.remove(pdf_output)
        return pdf_bytes

    # ---- PROMPT BUILDERS (ALL LOGIC) ----
    def build_a1_exam_intro():
        return (
            "**A1 – Teil 1: Basic Introduction**\n\n"
            "In the A1 exam's first part, you will be asked to introduce yourself. "
            "Typical information includes: your **Name, Land, Wohnort, Sprachen, Beruf, Hobby**.\n\n"
            "After your introduction, you will be asked 3 basic questions such as:\n"
            "- Haben Sie Geschwister?\n"
            "- Wie alt ist deine Mutter?\n"
            "- Bist du verheiratet?\n\n"
            "You might also be asked to spell your name (**Buchstabieren**). "
            "Please introduce yourself now using all the keywords above."
        )

    def build_exam_instruction(level, teil):
        if level == "A1":
            if "Teil 1" in teil:
                return build_a1_exam_intro()
            elif "Teil 2" in teil:
                return (
                    "**A1 – Teil 2: Question and Answer**\n\n"
                    "You will get a topic and a keyword. Your job: ask a question using the keyword, "
                    "then answer it yourself. Example: Thema: Geschäft – Keyword: schließen → "
                    "Wann schließt das Geschäft?\nLet's try one. Type 'Yes' in the chatbox so we start?"
                )
            elif "Teil 3" in teil:
                return (
                    "**A1 – Teil 3: Making a Request**\n\n"
                    "You'll receive a prompt (e.g. 'Radio anmachen'). Write a polite request or imperative. "
                    "Example: Können Sie bitte das Radio anmachen?\nReady?"
                    "Type Yes in the chatbox so we start?"
                )
        if level == "A2":
            if "Teil 1" in teil:
                return (
                    "**A2 – Teil 1: Fragen zu Schlüsselwörtern**\n\n"
                    "You'll get a topic (e.g. 'Wohnort'). Ask a question, then answer it yourself. "
                    "When you're ready, type 'Begin'."
                )
            elif "Teil 2" in teil:
                return (
                    "**A2 – Teil 2: Über das Thema sprechen**\n\n"
                    "Talk about the topic in 3–4 sentences. I'll correct and give tips. Start when ready."
                )
            elif "Teil 3" in teil:
                return (
                    "**A2 – Teil 3: Gemeinsam planen**\n\n"
                    "Let's plan something together. Respond and make suggestions. Start when ready."
                )
        if level == "B1":
            if "Teil 1" in teil:
                return (
                    "**B1 – Teil 1: Gemeinsam planen**\n\n"
                    "We'll plan an activity together (e.g., a trip or party). Give your ideas and answer questions."
                )
            elif "Teil 2" in teil:
                return (
                    "**B1 – Teil 2: Präsentation**\n\n"
                    "Give a short presentation on the topic (about 2 minutes). I'll ask follow-up questions."
                )
            elif "Teil 3" in teil:
                return (
                    "**B1 – Teil 3: Feedback & Fragen stellen**\n\n"
                    "Answer questions about your presentation. I'll give you feedback on your language and structure."
                )
        if level == "B2":
            if "Teil 1" in teil:
                return (
                    "**B2 – Teil 1: Diskussion**\n\n"
                    "We'll discuss a topic. Express your opinion and justify it."
                )
            elif "Teil 2" in teil:
                return (
                    "**B2 – Teil 2: Präsentation**\n\n"
                    "Present a topic in detail. I'll challenge your points and help you improve."
                )
            elif "Teil 3" in teil:
                return (
                    "**B2 – Teil 3: Argumentation**\n\n"
                    "Argue your perspective. I'll give feedback and counterpoints."
                )
        if level == "C1":
            if "Teil 1" in teil:
                return (
                    "**C1 – Teil 1: Vortrag**\n\n"
                    "Bitte halte einen kurzen Vortrag zum Thema. Ich werde anschließend Fragen stellen und deine Sprache bewerten."
                )
            elif "Teil 2" in teil:
                return (
                    "**C1 – Teil 2: Diskussion**\n\n"
                    "Diskutiere mit mir über das gewählte Thema. Ich werde kritische Nachfragen stellen."
                )
            elif "Teil 3" in teil:
                return (
                    "**C1 – Teil 3: Bewertung**\n\n"
                    "Bewerte deine eigene Präsentation. Was würdest du beim nächsten Mal besser machen?"
                )
        return ""

    def build_exam_system_prompt(level, teil):
        if level == "A1":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a supportive A1 German examiner. "
                    "Ask the student to introduce themselves using the keywords (Name, Land, Wohnort, Sprachen, Beruf, Hobby). "
                    "Check if all info is given, correct any errors (explain in English), and give the right way to say things in German. "
                    "1. Always explain errors and suggestion in English only. Only next question should be German. They are just A1 student "
                    "After their intro, ask these three questions one by one: "
                    "'Haben Sie Geschwister?', 'Wie alt ist deine Mutter?', 'Bist du verheiratet?'. "
                    "Correct their answers (explain in English). At the end, mention they may be asked to spell their name ('Buchstabieren') and wish them luck."
                    "Give them a score out of 25 and let them know if they passed or not"
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, an A1 examiner. Randomly give the student a Thema and Keyword from the official list. "
                    "Let them know you have 52 cards available and here to help them prepare for the exams. Let them know they can relax and continue another time when tired. Explain in English "
                    "Tell them to ask a question with the keyword and answer it themselves, then correct their German (explain errors in English, show the correct version), and move to the next topic."
                     "1.After every input, let them know if they passed or not and explain why you said so"
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, an A1 examiner. Give the student a prompt (e.g. 'Radio anmachen'). "
                    "Let them know you have 20 cards available and you here to help them prepare for the exams. Let them know they can relax and continue another time when tired. Explain in English "
                    "Ask them to write a polite request or imperative and answer themseves like their partners will do. Check if it's correct and polite, explain errors in English, and provide the right German version. Then give the next prompt."
                    " They respond using Ja gerne or In ordnung. They can also answer using Ja, Ich kann and the question of the verb at the end (e.g 'Ich kann das Radio anmachen'). "
                )
        if level == "A2":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a Goethe A2 examiner. Give a topic from the A2 list. "
                    "Always let the student know that you are to help them pass their exams so they should sit for some minutes and be consistent. Teach them how to pass the exams."
                    "1. After student input, let the student know you will ask just 3 questions and after give a score out of 25 marks "
                    "2. Use phrases like your next recommended question to ask for the next question"
                    "Ask the student to ask and answer a question on it. Always correct their German (explain errors in English), show the correct version, and encourage."
                    "Ask one question at a time"
                    "Pick 3 random keywords from the topic and ask the student 3 questions only per keyword. One question based on one keyword"
                    "When student make mistakes and explaining, use English and simple German to explain the mistake and make correction"
                    "After the third questions, mark the student out of 25 marks and tell the student whether they passed or not. Explain in English for them to understand"
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, an A2 examiner. Give a topic. Student gives a short monologue. Correct errors (in English), give suggestions, and follow up with one question."
                    "Always let the student know that you are to help them pass their exams so they should sit for some minutes and be consistent. Teach them how to pass the exams."
                    "1. After student input, let the student know you will ask just 3 questions and after give a score out of 25 marks "
                    "2. Use phrases like your next recommended question to ask for the next question"
                    "Pick 3 random keywords from the topic and ask the student 3 questions only per keyword. One question based on one keyword"
                    "When student make mistakes and explaining, use English and simple German to explain the mistake and make correction"
                    "After the third questions, mark the student out of 25 marks and tell the student whether they passed or not. Explain in English for them understand"
                    
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, an A2 examiner. Plan something together (e.g., going to the cinema). Check student's suggestions, correct errors, and keep the conversation going."
                    "Always let the student know that you are to help them pass their exams so they should sit for some minutes and be consistent. Teach them how to pass the exams."
                    "Alert students to be able to plan something with you for you to agree with exact 5 prompts"
                    "After the last prompt, mark the student out of 25 marks and tell the student whether they passed or not. Explain in English for them to understand"
                )
        if level == "B1":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a Goethe B1 supportive examiner. You and the student plan an activity together. "
                    "Always give feedback in both German and English, correct mistakes, suggest improvements, and keep it realistic."
                    "Always let the student know that you are to help them pass their exams so they should sit for some minutes and be consistent. Teach them how to pass the exams."
                    "1. Give short answers that encourages the student to also type back"
                    "2. After student input, let the student know you will ask just 5 questions and after give a score out of 25 marks. Explain in English for them to understand. "
                    "3. Ask only 5 questions and try and end the conversation"
                    "4. Give score after every presentation whether they passed or not"
                    "5. Use phrases like your next recommended question to ask for the next question"
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, a Goethe B1 examiner. Student gives a presentation. Give constructive feedback in German and English, ask for more details, and highlight strengths and weaknesses."
                    "Always let the student know that you are to help them pass their exams so they should sit for some minutes and be consistent. Teach them how to pass the exams."
                    "1. After student input, let the student know you will ask just 3 questions and after give a score out of 25 marks. Explain in English for them to understand. "
                    "2. Ask only 3 questions and one question at a time"
                    "3. Dont make your reply too long and complicated but friendly"
                    "4. After your third question, mark and give the student their scores"
                    "5. Use phrases like your next recommended question to ask for the next question"
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, a Goethe B1 examiner. Student answers questions about their presentation. "
                    "Always let the student know that you are to help them pass their exams so they should sit for some minutes and be consistent. Teach them to pass the exams. Tell them to ask questions if they dont understand and ask for translations of words. You can help than they going to search for words "
                    "Give exam-style feedback (in German and English), correct language, and motivate."
                    "1. Ask only 3 questions and one question at a time"
                    "2. Dont make your reply too long and complicated but friendly"
                    "3. After your third question, mark and give the student their scores out of 25 marks. Explain in English for them to understand"
                    "4. Use phrases like your next recommended question to ask for the next question"
                )
        if level == "B2":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a B2 examiner. Discuss a topic with the student. Challenge their points. Correct errors (mostly in German, but use English if it's a big mistake), and always provide the correct form."
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, a B2 examiner. Listen to the student's presentation. Give high-level feedback (mostly in German), ask probing questions, and always highlight advanced vocabulary and connectors."
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, a B2 examiner. Argue your perspective. Give detailed, advanced corrections (mostly German, use English if truly needed). Encourage native-like answers."
                )
        if level == "C1":
            if "Teil 1" in teil or "Teil 2" in teil or "Teil 3" in teil:
                return (
                    "Du bist Herr Felix, ein C1-Prüfer. Sprich nur Deutsch. "
                    "Stelle herausfordernde Fragen, gib ausschließlich auf Deutsch Feedback, und fordere den Studenten zu komplexen Strukturen auf."
                )
        return ""
#
    def build_custom_chat_prompt(level):
        if level == "C1":
            return (
                "You are supportive German C1 Teacher. Speak both english and German "
                "Ask student one question at a time"
                "Suggest useful phrases student can use to begin their phrases"
                "Check if student is writing on C1 Level"
                "When there is error, correct for the student and teach them how to say it correctly"
                "Stay on one topic and always ask next question. After 5 intelligent questions only on a topic, give the student their performance and scores and suggestions to improve"
                "Help student progress from B2 to C1 with your support and guidance"
            )
        if level in ["A1", "A2", "B1", "B2"]:
            correction_lang = "in English" if level in ["A1", "A2"] else "half in English and half in German"
            return (
                f"You are Herr Felix, a supportive and innovative German teacher. "
                f"1. Congratulate the student in English for the topic and give interesting tips on the topic. Always let the student know how the session is going to go in English. It shouldnt just be questions but teach them also. The total number of questios,what they should expect,what they would achieve at the end of the session. Let them know they can ask questions or ask for translation if they dont understand anything. You are ready to always help "
                f"Promise them that if they answer all 10 questions, you use their own words to build a presentation of 60 words for them. They only have to be consistent "
                f"Pick 4 useful keywords related to the student's topic and use them as the focus for conversation. Give students ideas and how to build their points for the conversation in English. "
                f"For each keyword, ask the student up to 2 creative, diverse and interesting questions in German only based on student language level, one at a time, not all at once. Just ask the question and don't let student know this is the keyword you are using. "
                f"After each student answer, give feedback and a suggestion to extend their answer if it's too short. Feedback in English and suggestion in German. "
                f"1. Explain difficult words when level is A1,A2,B1,B2. "
                f"After keyword questions, continue with other random follow-up questions that reflect student selected level about the topic in German (until you reach 10 questions in total). "
                f"Never ask more than 2 questions about the same keyword. "
                f"After the student answers 10 questions, write a summary of their performance: what they did well, mistakes, and what to improve in English and end the chat with motivation and tips. "
                f"Also give them 60 words from their own words in a presentation form that they can use in class. Add your own points if their words and responses were small. Tell to improve on it and learn to speak without reading "
                f"All feedback and corrections should be {correction_lang}. "
                f"Encourage the student and keep the chat motivating. "
            )
        return ""
#
    # ---- USAGE LIMIT CHECK ----
    if not has_falowen_quota(student_code):
        st.warning("You have reached your daily practice limit for this section. Please come back tomorrow.")
        st.stop()

# ---- SESSION STATE DEFAULTS ----
    default_state = {
        "falowen_stage": 1,
        "falowen_mode": None,
        "falowen_level": None,
        "falowen_teil": None,
        "falowen_messages": [],
        "falowen_turn_count": 0,
        "custom_topic_intro_done": False,
        "custom_chat_level": None,
        "falowen_exam_topic": None,
        "falowen_exam_keyword": None,
    }
    for key, val in default_state.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # ---- STAGE 1: Mode Selection ----
    if st.session_state["falowen_stage"] == 1:
        st.subheader("Step 1: Choose Practice Mode")

        st.info(
            """
            **Which mode should you choose?**

            - 📝 **Exam Mode**:  
                Practice for your official Goethe exam!  
                - Includes **Speaking** (Sprechen) with a live chat examiner  
                - PLUS quick access to real **Reading (Lesen)** and **Listening (Hören)** past exams  
                - See official exam instructions and practice with authentic topics

            - 💬 **Custom Chat**:  
                Chat about any topic!  
                - Great for practicing presentations, your own ideas, or general German conversation  
                - No exam restrictions—learn at your own pace

            - 🎤 **Pronunciation & Speaking Checker**:  
                Record or upload a short audio, get instant feedback on your pronunciation, fluency, and speaking.  
                - Perfect for practicing real answers and getting AI-based scoring & tips!
            """,
            icon="ℹ️"
        )

        # Mode selection radio
        mode = st.radio(
            "How would you like to practice?",
            [
                "Geführte Prüfungssimulation (Exam Mode)",
                "Eigenes Thema/Frage (Custom Chat)",
                "Pronunciation & Speaking Checker"
            ],
            key="falowen_mode_center"
        )

        # Next button logic
        if st.button("Next ➡️", key="falowen_next_mode"):
            st.session_state["falowen_mode"] = mode
            # Skip level/teil selection if in Pronunciation mode, jump to special stage
            if mode == "Pronunciation & Speaking Checker":
                st.session_state["falowen_stage"] = 99
            else:
                st.session_state["falowen_stage"] = 2
            st.session_state["falowen_level"] = None
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
            st.rerun()


    # ---- STAGE 2: Level Selection ----
    if st.session_state["falowen_stage"] == 2:
        # If Pronunciation & Speaking Checker, skip this stage!
        if st.session_state["falowen_mode"] == "Pronunciation & Speaking Checker":
            st.session_state["falowen_stage"] = 99
            st.rerun()

        st.subheader("Step 2: Choose Your Level")
        level = st.radio(
            "Select your level:",
            ["A1", "A2", "B1", "B2", "C1"],
            key="falowen_level_center"
        )

        # ← Back and Next → in two columns
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅️ Back", key="falowen_back1"):
                # Back from Level → Mode selection
                st.session_state["falowen_stage"] = 1
                st.session_state["falowen_messages"] = []
                st.session_state["_falowen_loaded"] = False
                st.rerun()
        with col2:
            if st.button("Next ➡️", key="falowen_next_level"):
                st.session_state["falowen_level"] = level
                if st.session_state["falowen_mode"] == "Geführte Prüfungssimulation (Exam Mode)":
                    st.session_state["falowen_stage"] = 3
                else:
                    st.session_state["falowen_stage"] = 4
                st.session_state["falowen_teil"] = None
                st.session_state["falowen_messages"] = []
                st.session_state["custom_topic_intro_done"] = False
                st.rerun()

        st.stop()
        
    # ---- STAGE 3: Choose Exam Part ----
    if st.session_state["falowen_stage"] == 3:
        st.subheader("Step 3: Choose Exam Part")

        # 1) exam‑part options per level
        teil_options = {
            "A1": [
                "Teil 1 – Basic Introduction",
                "Teil 2 – Question and Answer",
                "Teil 3 – Making A Request",
                "Lesen – Past Exam Reading",
                "Hören – Past Exam Listening"
            ],
            "A2": [
                "Teil 1 – Fragen zu Schlüsselwörtern",
                "Teil 2 – Über das Thema sprechen",
                "Teil 3 – Gemeinsam planen",
                "Lesen – Past Exam Reading",
                "Hören – Past Exam Listening"
            ],
            "B1": [
                "Teil 1 – Gemeinsam planen (Dialogue)",
                "Teil 2 – Präsentation (Monologue)",
                "Teil 3 – Feedback & Fragen stellen",
                "Lesen – Past Exam Reading",
                "Hören – Past Exam Listening"
            ],
            "B2": [
                "Teil 1 – Diskussion",
                "Teil 2 – Präsentation",
                "Teil 3 – Argumentation",
                "Lesen – Past Exam Reading",
                "Hören – Past Exam Listening"
            ],
            "C1": [
                "Teil 1 – Vortrag",
                "Teil 2 – Diskussion",
                "Teil 3 – Bewertung",
                "Lesen – Past Exam Reading",
                "Hören – Past Exam Listening"
            ]
        }
        level = st.session_state["falowen_level"]
        teil = st.radio(
            "Which exam part?",
            teil_options[level],
            key="falowen_teil_center"
        )

        # 2) If Lesen/Hören, show links + Back
        if "Lesen" in teil or "Hören" in teil:
            if "Lesen" in teil:
                st.markdown(
                    """
                    <div style="background:#e1f5fe;border-radius:10px;
                                padding:1.1em 1.4em;margin:1.2em 0;">
                      <span style="font-size:1.18em;color:#0277bd;">
                        <b>📖 Past Exam: Lesen (Reading)</b>
                      </span><br><br>
                    """,
                    unsafe_allow_html=True
                )
                for label, url in lesen_links.get(level, []):
                    st.markdown(
                        f'<a href="{url}" target="_blank" '
                        f'style="font-size:1.10em;color:#1976d2;font-weight:600">'
                        f'👉 {label}</a><br>',
                        unsafe_allow_html=True
                    )
                st.markdown("</div>", unsafe_allow_html=True)

            if "Hören" in teil:
                st.markdown(
                    """
                    <div style="background:#ede7f6;border-radius:10px;
                                padding:1.1em 1.4em;margin:1.2em 0;">
                      <span style="font-size:1.18em;color:#512da8;">
                        <b>🎧 Past Exam: Hören (Listening)</b>
                      </span><br><br>
                    """,
                    unsafe_allow_html=True
                )
                for label, url in hoeren_links.get(level, []):
                    st.markdown(
                        f'<a href="{url}" target="_blank" '
                        f'style="font-size:1.10em;color:#5e35b1;font-weight:600">'
                        f'👉 {label}</a><br>',
                        unsafe_allow_html=True
                    )
                st.markdown("</div>", unsafe_allow_html=True)

            # Back button
            if st.button("⬅️ Back", key="lesen_hoeren_back"):
                st.session_state["falowen_stage"] = 2
                st.session_state["falowen_messages"] = []
                st.rerun()

        else:
            # 3) Topic-picker / search UI
            teil_number = teil.split()[1]
            topic_col   = "Topic/Prompt"
            keyword_col = "Keyword/Subtopic"
            exam_topics = df_exam[
                (df_exam["Level"] == level) &
                (df_exam["Teil"]  == f"Teil {teil_number}")
            ] if teil_number else pd.DataFrame()

            if not exam_topics.empty:
                topic_vals   = exam_topics[topic_col].astype(str).str.strip()
                keyword_vals = exam_topics[keyword_col].astype(str).str.strip()
                topics_list  = [
                    f"{t} – {k}" if k else t
                    for t, k in zip(topic_vals, keyword_vals) if t
                ]
            else:
                topics_list = []

            search = st.text_input("🔍 Search topic or keyword...", "")
            filtered = (
                [t for t in topics_list if search.lower() in t.lower()]
                if search else topics_list
            )

            if filtered:
                st.markdown("**Preview: Available Topics**")
                for t in filtered[:6]:
                    st.markdown(f"- {t}")
                if len(filtered) > 6:
                    with st.expander(f"See all {len(filtered)} topics"):
                        col1, col2 = st.columns(2)
                        for i, t in enumerate(filtered):
                            with (col1 if i % 2 == 0 else col2):
                                st.markdown(f"- {t}")

                st.write("**Pick your topic or select random:**")
                choice = st.selectbox("", ["(random)"] + filtered, key="topic_picker")
                chosen = random.choice(filtered) if choice == "(random)" else choice

                if " – " in chosen:
                    topic, keyword = chosen.split(" – ", 1)
                    st.session_state["falowen_exam_topic"]   = topic
                    st.session_state["falowen_exam_keyword"] = keyword
                else:
                    st.session_state["falowen_exam_topic"]   = chosen
                    st.session_state["falowen_exam_keyword"] = None

                tp = st.session_state["falowen_exam_topic"]
                kw = st.session_state["falowen_exam_keyword"]
                if tp:
                    st.success(f"**Your exam topic is:** {tp}" + (f" – {kw}" if kw else ""))
            else:
                st.info("No topics found. Try a different search.")

            # Back + Start Practice
            col1, col2 = st.columns([1, 2])
            with col1:
                if st.button("⬅️ Back", key="falowen_back_part"):
                    st.session_state["falowen_stage"]    = 2
                    st.session_state["falowen_messages"] = []
                    st.rerun()
            with col2:
                if st.button("Start Practice", key="falowen_start_practice"):
                    st.session_state["falowen_teil"]            = teil
                    st.session_state["falowen_stage"]           = 4
                    st.session_state["falowen_messages"]        = []
                    st.session_state["custom_topic_intro_done"] = False
                    st.session_state["remaining_topics"]        = filtered.copy()
                    random.shuffle(st.session_state["remaining_topics"])
                    st.session_state["used_topics"]             = []
                    st.rerun()


    # ==========================
    # FIRESTORE CHAT HELPERS
    # ==========================
    def save_falowen_chat(student_code, mode, level, teil, messages):
        doc_ref = db.collection("falowen_chats").document(student_code)
        doc = doc_ref.get()
        data = doc.to_dict() if doc.exists else {}
        chats = data.get("chats", {})
        chat_key = f"{mode}_{level}_{teil or 'custom'}"
        chats[chat_key] = messages
        doc_ref.set({"chats": chats}, merge=True)

    def load_falowen_chat(student_code, mode, level, teil):
        doc_ref = db.collection("falowen_chats").document(student_code)
        doc = doc_ref.get()
        if not doc.exists:
            return []
        chats = doc.to_dict().get("chats", {})
        chat_key = f"{mode}_{level}_{teil or 'custom'}"
        return chats.get(chat_key, [])

     # =========================================
    # ---- STAGE 4: MAIN CHAT ----
    if st.session_state["falowen_stage"] == 4:
        import re

        level = st.session_state["falowen_level"]
        teil = st.session_state["falowen_teil"]
        mode = st.session_state["falowen_mode"]
        is_exam = mode == "Geführte Prüfungssimulation (Exam Mode)"
        is_custom_chat = mode == "Eigenes Thema/Frage (Custom Chat)"

        # Student code
        student_code = st.session_state.get("student_code", "demo")

        # ---- Usage check ----
        used_today = get_sprechen_usage(student_code)
        st.info(f"Today: {used_today} / {FALOWEN_DAILY_LIMIT} Falowen chat messages used.")
        if used_today >= FALOWEN_DAILY_LIMIT:
            st.warning("You have reached your daily practice limit for Falowen today. Please come back tomorrow.")
            st.stop()

        # ---- Load existing chat once ----
        if not st.session_state.get("_falowen_loaded", False):
            loaded = load_falowen_chat(student_code, mode, level, teil)
            if loaded:
                st.session_state["falowen_messages"] = loaded
            st.session_state["_falowen_loaded"] = True

        # ---- Session controls ----
        def reset_chat():
            st.session_state.update({
                "falowen_stage": 1,
                "falowen_messages": [],
                "falowen_teil": None,
                "falowen_mode": None,
                "custom_topic_intro_done": False,
                "falowen_turn_count": 0,
                "falowen_exam_topic": None,
                "falowen_exam_keyword": None,
                "remaining_topics": [],
                "used_topics": [],
                "_falowen_loaded": False,
            })
            st.rerun()

        def back_step():
            # Decide which previous stage to go to based on mode
            if is_exam:
                st.session_state["falowen_stage"] = 3
            elif is_custom_chat:
                st.session_state["falowen_stage"] = 2
            else:
                st.session_state["falowen_stage"] = 1
            # Clear only the chat history (we want them to re-enter step)
            st.session_state["falowen_messages"] = []
            st.session_state["_falowen_loaded"] = False
            st.rerun()

        def change_level():
            st.session_state["falowen_stage"] = 2
            st.session_state["falowen_messages"] = []
            st.session_state["_falowen_loaded"] = False
            st.rerun()

        # ---- Normalize previous messages ----
        def ensure_message_format(msg):
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                return msg
            if isinstance(msg, (list, tuple)) and len(msg) == 2:
                return {"role": msg[0], "content": msg[1]}
            if isinstance(msg, str):
                return {"role": "user", "content": msg}
            return None

        msgs = [ensure_message_format(m) for m in st.session_state["falowen_messages"]]
        st.session_state["falowen_messages"] = [m for m in msgs if m]

        # ---- Render chat bubbles ----
        for msg in st.session_state["falowen_messages"]:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🧑‍🏫"):
                    st.markdown(
                        "<span style='color:#cddc39;font-weight:bold'>🧑‍🏫 Herr Felix:</span><br>"
                        f"<div style='{bubble_assistant}'>{highlight_keywords(msg['content'], highlight_words)}</div>",
                        unsafe_allow_html=True
                    )
            else:
                with st.chat_message("user"):
                    st.markdown(
                        f"<div style='display:flex;justify-content:flex-end;'>"
                        f"<div style='{bubble_user}'>🗣️ {msg['content']}</div></div>",
                        unsafe_allow_html=True
                    )

        # ---- PDF Download Button ----
        if st.session_state["falowen_messages"]:
            pdf_bytes = falowen_download_pdf(
                st.session_state["falowen_messages"],
                f"Falowen_Chat_{level}_{teil.replace(' ', '_') if teil else 'chat'}"
            )
            st.download_button(
                "⬇️ Download Chat as PDF",
                pdf_bytes,
                file_name=f"Falowen_Chat_{level}_{teil.replace(' ', '_') if teil else 'chat'}.pdf",
                mime="application/pdf"
            )

        # ---- TXT Download Button ----
        if st.session_state["falowen_messages"]:
            chat_as_text = "\n".join([
                f"{msg['role'].capitalize()}: {msg['content']}"
                for msg in st.session_state["falowen_messages"]
            ])
            st.download_button(
                "⬇️ Download Chat as TXT",
                chat_as_text.encode("utf-8"),
                file_name=f"Falowen_Chat_{level}_{teil.replace(' ', '_') if teil else 'chat'}.txt",
                mime="text/plain"
            )

        # ---- Session Buttons ----
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Restart Chat"): reset_chat()
        with col2:
            if st.button("Back"): back_step()
        with col3:
            if st.button("Change Level"): change_level()

        # ---- Initial Instruction ----
        if not st.session_state["falowen_messages"]:
            instruction = build_exam_instruction(level, teil) if is_exam else (
                "Hallo! 👋 What would you like to talk about? Give me details of what you want so I can understand."
            )
            st.session_state["falowen_messages"].append({"role": "assistant", "content": instruction})
            save_falowen_chat(student_code, mode, level, teil, st.session_state["falowen_messages"])

        # ---- Build system prompt including topic/context ----
        if is_exam:
            if (not st.session_state.get("falowen_exam_topic")) and st.session_state.get("remaining_topics"):
                next_topic = st.session_state["remaining_topics"].pop(0)
                if " – " in next_topic:
                    topic, keyword = next_topic.split(" – ", 1)
                    st.session_state["falowen_exam_topic"] = topic
                    st.session_state["falowen_exam_keyword"] = keyword
                else:
                    st.session_state["falowen_exam_topic"] = next_topic
                    st.session_state["falowen_exam_keyword"] = None
                st.session_state["used_topics"].append(next_topic)
            base_prompt = build_exam_system_prompt(level, teil)
            topic = st.session_state.get("falowen_exam_topic")
            if topic:
                system_prompt = f"{base_prompt} Thema: {topic}."
            else:
                system_prompt = base_prompt
        else:
            system_prompt = build_custom_chat_prompt(level)

        # ---- Chat input & assistant response ----
        user_input = st.chat_input("Type your answer or message here...", key="falowen_user_input")
        if user_input:
            st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
            inc_sprechen_usage(student_code)

            with st.chat_message("user"):
                st.markdown(
                    f"<div style='display:flex;justify-content:flex-end;'>"
                    f"<div style='{bubble_user}'>🗣️ {user_input}</div></div>",
                    unsafe_allow_html=True
                )

            with st.chat_message(
                "assistant",
                avatar="https://i.imgur.com/aypyUjM_d.jpeg?maxwidth=520&shape=thumb&fidelity=high"
            ):
                with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                    messages = [{"role": "system", "content": system_prompt}] + st.session_state["falowen_messages"]
                    try:
                        resp = client.chat.completions.create(
                            model="gpt-4o",
                            messages=messages,
                            temperature=0.15,
                            max_tokens=600
                        )
                        ai_reply = resp.choices[0].message.content.strip()
                    except Exception as e:
                        ai_reply = f"Sorry, an error occurred: {e}"

                st.markdown(
                    "<span style='color:#cddc39;font-weight:bold'>🧑‍🏫 Herr Felix:</span><br>"
                    f"<div style='{bubble_assistant}'>{highlight_keywords(ai_reply, highlight_words)}</div>",
                    unsafe_allow_html=True
                )

            st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})
            save_falowen_chat(student_code, mode, level, teil, st.session_state["falowen_messages"])

        # ---- End session button & summary ----
        st.divider()
        if st.button("✅ End Session & Show Summary"):
            st.session_state["falowen_stage"] = 5
            st.rerun()

            
    # ---- STAGE 99: Pronunciation & Speaking Checker ----
    if st.session_state.get("falowen_stage") == 99:
        import datetime

        # ====== DAILY LIMIT ENFORCEMENT BLOCK (AT THE TOP) ======
        today_str = datetime.date.today().isoformat()
        uploads_ref = db.collection("pron_uses").document(st.session_state["student_code"])
        doc = uploads_ref.get()
        data = doc.to_dict() if doc.exists else {}
        last_date = data.get("date")
        count = data.get("count", 0)
        if last_date != today_str:
            count = 0
        if count >= 3:
            st.warning("You’ve hit your daily upload limit (3). Try again tomorrow.")
            st.stop()
        # =======================================================

        st.subheader("🎤 Pronunciation & Speaking Checker")
        st.info(
            """
            Record or upload your speaking sample below (max 60 seconds).  
            You’ll see what I understood, plus feedback on pronunciation, grammar, and fluency.
            """
        )

        # Upload (or record via phone/Vocaroo and upload) with 60 s limit
        audio_file = st.file_uploader("Upload a WAV/MP3 file (≤ 60 sec)", type=["wav", "mp3"])
        if audio_file:
            st.audio(audio_file)

            # Transcribe with Whisper
            try:
                transcript_resp = client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-1"
                )
                transcript_text = transcript_resp.text
            except Exception as e:
                st.error(f"Sorry, could not process audio: {e}")
                st.stop()

            # Show what the AI heard
            st.markdown(f"**I heard you say:**  \n> {transcript_text}")

            # Now run a chat-completion to evaluate
            eval_prompt = (
                "You are a German tutor. The student said:\n"
                f"\"{transcript_text}\"\n\n"
                "Please score their Pronunciation, Grammar, and Fluency each out of 100, "
                "and then give three concise tips per category. "
                "Format as:\n"
                "Pronunciation: XX/100\nTips:\n1. …\n2. …\n3. …\n\n"
                "Grammar: XX/100\nTips:\n1. …\n2. …\n3. …\n\n"
                "Fluency: XX/100\nTips:\n1. …\n2. …\n3. …"
            )

            with st.spinner("Evaluating your sample..."):
                eval_resp = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a helpful German tutor."},
                        {"role": "user", "content": eval_prompt}
                    ],
                    temperature=0.2
                )
            st.markdown(eval_resp.choices[0].message.content)

            # After successful upload/evaluation, increment usage count
            uploads_ref.set({"count": count + 1, "date": today_str})

            st.info("💡 Tip: To get ideas and practice your topic before recording, use Custom Chat first.")
            if st.button("🔄 Try Another"):
                st.rerun()

        else:
            st.info("No audio uploaded yet. You can record on your phone or at www.vocaroo.com and then upload.")

        if st.button("⬅️ Back to Main Menu"):
            st.session_state["falowen_stage"] = 1
            st.rerun()

# =========================================
# End
# =========================================

# =========================================
# FIRESTORE STATS HELPERS
# =========================================

def save_vocab_attempt(student_code, level, total, correct, practiced_words):
    """Save one vocab practice attempt to Firestore."""
    doc_ref = db.collection("vocab_stats").document(student_code)
    doc = doc_ref.get()
    data = doc.to_dict() if doc.exists else {}
    history = data.get("history", [])

    attempt = {
        "level": level,
        "total": total,
        "correct": correct,
        "practiced_words": practiced_words,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    history.append(attempt)
    best = max((a["correct"] for a in history), default=0)
    completed = set(sum((a["practiced_words"] for a in history), []))

    doc_ref.set({
        "history":           history,
        "best":              best,
        "last_practiced":    attempt["timestamp"],
        "completed_words":   list(completed),
        "total_sessions":    len(history),
    })

def get_vocab_stats(student_code):
    """Load vocab practice stats from Firestore (or defaults)."""
    doc_ref = db.collection("vocab_stats").document(student_code)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return {
        "history":           [],
        "best":              0,
        "last_practiced":    None,
        "completed_words":   [],
        "total_sessions":    0,
    }

# =========================================
# VOCAB TRAINER TAB (A1–C1)
# =========================================

# Your Google Sheet → CSV
sheet_id = "1I1yAnqzSh3DPjwWRh9cdRSfzNSPsi7o4r5Taj9Y36NU"
csv_url  = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"

# Play German audio
def play_word_audio(word, lang="de"):
    from gtts import gTTS
    import tempfile
    tts = gTTS(text=word, lang=lang)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
        tts.save(fp.name)
        st.audio(fp.name, format="audio/mp3")

# Chat bubble renderer
def render_message(role, msg):
    align   = "left"   if role=="assistant" else "right"
    bgcolor = "#FAFAFA" if role=="assistant" else "#D2F8D2"
    bordcol = "#CCCCCC"
    label   = "Herr Felix 👨‍🏫" if role=="assistant" else "You"
    style = (
        f"padding:14px; border-radius:12px; max-width:96vw; "
        f"margin:7px 0; text-align:{align}; background:{bgcolor}; "
        f"border:1px solid {bordcol}; font-size:1.12em; word-break:break-word;"
    )
    st.markdown(f"<div style='{style}'><b>{label}:</b> {msg}</div>", unsafe_allow_html=True)

# Answer checking
def clean_text(text):
    return text.replace("the ", "").replace(",", "").replace(".", "").strip().lower()

def is_correct_answer(user_input, answer):
    import re
    possible = [a.strip().lower() for a in re.split(r"[,/;]", answer)]
    return clean_text(user_input) in possible

# Robust CSV loader
@st.cache_data
def load_vocab_lists():
    import pandas as pd
    try:
        df = pd.read_csv(csv_url)
    except Exception as e:
        st.error(f"Could not fetch vocab CSV: {e}")
        return {}
    df.columns = df.columns.str.strip()
    missing = [c for c in ("Level","German","English") if c not in df.columns]
    if missing:
        st.error(f"Missing column(s) in your sheet: {missing}")
        return {}
    df = df[["Level","German","English"]].dropna()
    lists = {}
    for lvl, grp in df.groupby("Level"):
        lists[lvl] = list(zip(grp["German"], grp["English"]))
    return lists

VOCAB_LISTS = load_vocab_lists()

# Tab logic
if tab == "Vocab Trainer":
    st.markdown(
        """
        <div style="
            padding:8px 12px; background:#6f42c1; color:#fff;
            border-radius:6px; text-align:center; margin-bottom:8px;
            font-size:1.3rem;
        ">📚 Vocab Trainer</div>
        """,
        unsafe_allow_html=True
    )
    st.divider()

    # initialize
    defaults = {"vt_history":[], "vt_list":[], "vt_index":0, "vt_score":0, "vt_total":None}
    for k,v in defaults.items(): st.session_state.setdefault(k,v)
    student_code = st.session_state.get("student_code","demo")

    # show stats
    stats = get_vocab_stats(student_code)
    st.markdown("### 📝 Your Vocab Stats")
    st.markdown(f"- **Sessions:** {stats['total_sessions']}")
    st.markdown(f"- **Best:** {stats['best']}")
    st.markdown(f"- **Last Practiced:** {stats['last_practiced']}")
    st.markdown(f"- **Unique Words:** {len(stats['completed_words'])}")
    if st.checkbox("Show Last 5 Sessions"):
        for a in stats["history"][-5:][::-1]:
            st.markdown(
                f"- {a['timestamp']} | {a['correct']}/{a['total']} | {a['level']}<br>"
                f"<span style='font-size:0.9em;'>Words: {', '.join(a['practiced_words'])}</span>",
                unsafe_allow_html=True
            )

    # pick level & words
    level       = st.selectbox("Level", list(VOCAB_LISTS.keys()), key="vt_level")
    items       = VOCAB_LISTS.get(level, [])
    completed   = set(stats["completed_words"])
    not_done    = [p for p in items if p[0] not in completed]
    st.info(f"{len(not_done)} words NOT yet done at {level}.")

    # reset
    if st.button("🔁 Start New Practice", key="vt_reset"):
        for k in defaults: st.session_state[k]=defaults[k]

    mode = st.radio("Select words:", ["Only new words","All words"], horizontal=True, key="vt_mode")
    session_vocab = (not_done if mode=="Only new words" else items).copy()

    # how many?
    if st.session_state.vt_total is None:
        maxc = len(session_vocab)
        if maxc==0:
            st.success("🎉 All done! Switch to 'All words' to repeat.")
            st.stop()
        count = st.number_input("How many today?", 1, maxc, min(7,maxc), key="vt_count")
        if st.button("Start", key="vt_start"):
            random.shuffle(session_vocab)
            st.session_state.vt_list    = session_vocab[:count]
            st.session_state.vt_total   = count
            st.session_state.vt_index   = 0
            st.session_state.vt_score   = 0
            st.session_state.vt_history = [("assistant",f"Hallo! Ich bin Herr Felix. Let's do {count} words!")]

    # show chat
    if st.session_state.vt_history:
        st.markdown("### 🗨️ Practice Chat")
        for who,msg in st.session_state.vt_history:
            render_message(who,msg)

    # practice loop
    tot = st.session_state.vt_total
    idx = st.session_state.vt_index
    if isinstance(tot,int) and idx<tot:
        word,answer = st.session_state.vt_list[idx]

        # play/download
        if st.button("🔊 Play & Download", key=f"tts_{idx}"):
            from gtts import gTTS
            import tempfile
            t = gTTS(text=word, lang="de")
            with tempfile.NamedTemporaryFile(delete=False,suffix=".mp3") as fp:
                t.save(fp.name)
                st.audio(fp.name,format="audio/mp3")
                fp.seek(0)
                blob = fp.read()
            st.download_button(f"⬇️ {word}.mp3", data=blob, file_name=f"{word}.mp3", mime="audio/mp3", key=f"tts_dl_{idx}")

        usr = st.text_input(f"{word} = ?", key=f"vt_input_{idx}")
        if usr and st.button("Check", key=f"vt_check_{idx}"):
            st.session_state.vt_history.append(("user",usr))
            if is_correct_answer(usr,answer):
                st.session_state.vt_score += 1
                fb = f"✅ Correct! '{word}' = '{answer}'"
            else:
                fb = f"❌ Nope. '{word}' = '{answer}'"
            st.session_state.vt_history.append(("assistant",fb))
            st.session_state.vt_index += 1

    # done
    if isinstance(tot,int) and idx>=tot:
        score = st.session_state.vt_score
        words = [w for w,_ in st.session_state.vt_list]
        st.markdown(f"### 🏁 Done! You scored {score}/{tot}.")
        save_vocab_attempt(student_code, level, tot, score, words)
        if st.button("Practice Again", key="vt_again"):
            for k in defaults: st.session_state[k]=defaults[k]



# ===== BUBBLE FUNCTION FOR CHAT DISPLAY =====
def bubble(role, text):
    color = "#7b2ff2" if role == "assistant" else "#222"
    bg = "#ede3fa" if role == "assistant" else "#f6f8fb"
    name = "Herr Felix" if role == "assistant" else "You"
    return f"""
        <div style="background:{bg};color:{color};margin-bottom:8px;padding:13px 15px;
        border-radius:14px;max-width:98vw;font-size:1.09rem;">
            <b>{name}:</b><br>{text}
        </div>
    """

if tab == "Schreiben Trainer":
    st.markdown(
        '''
        <div style="
            padding: 8px 12px;
            background: #d63384;
            color: #fff;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 8px;
            font-size: 1.3rem;">
            ✍️ Schreiben Trainer (Writing Practice)
        </div>
        ''',
        unsafe_allow_html=True
    )

    st.info(
        """
        ✍️ **This section is for Writing (Schreiben) only.**
        - Practice your German letters, emails, and essays for A1–C1 exams.
        - **Want to prepare for class presentations, topic expansion, or practice Speaking, Reading (Lesen), or Listening (Hören)?**  
          👉 Go to **Exam Mode & Custom Chat** (tab above)!
        - **Tip:** Choose your exam level on the right before submitting your letter. Your writing will be checked and scored out of 25 marks, just like in the real exam.
        """,
        icon="✉️"
    )

    st.divider()

    # --- Writing stats summary with high-contrast background and dark text ---
    student_code = st.session_state.get("student_code", "demo")
    stats = get_schreiben_stats(student_code)
    if stats:
        total = stats.get("total", 0)
        passed = stats.get("passed", 0)
        pass_rate = stats.get("pass_rate", 0)

        # Milestone and title logic
        if total <= 2:
            writer_title = "🟡 Beginner Writer"
            milestone = "Write 3 letters to become a Rising Writer!"
        elif total <= 5 or pass_rate < 60:
            writer_title = "🟡 Rising Writer"
            milestone = "Achieve 60% pass rate and 6 letters to become a Confident Writer!"
        elif total <= 7 or (60 <= pass_rate < 80):
            writer_title = "🔵 Confident Writer"
            milestone = "Reach 8 attempts and 80% pass rate to become an Advanced Writer!"
        elif total >= 8 and pass_rate >= 80 and not (total >= 10 and pass_rate >= 95):
            writer_title = "🟢 Advanced Writer"
            milestone = "Reach 10 attempts and 95% pass rate to become a Master Writer!"
        elif total >= 10 and pass_rate >= 95:
            writer_title = "🏅 Master Writer!"
            milestone = "You've reached the highest milestone! Keep maintaining your skills 🎉"
        else:
            writer_title = "✏️ Active Writer"
            milestone = "Keep going to unlock your next milestone!"

        st.markdown(
            f"""
            <div style="background:#fff8e1;padding:18px 12px 14px 12px;border-radius:12px;margin-bottom:12px;
                        box-shadow:0 1px 6px #00000010;">
                <span style="font-weight:bold;font-size:1.25rem;color:#d63384;">{writer_title}</span><br>
                <span style="font-weight:bold;font-size:1.09rem;color:#444;">📊 Your Writing Stats</span><br>
                <span style="color:#202020;font-size:1.05rem;"><b>Total Attempts:</b> {total}</span><br>
                <span style="color:#202020;font-size:1.05rem;"><b>Passed:</b> {passed}</span><br>
                <span style="color:#202020;font-size:1.05rem;"><b>Pass Rate:</b> {pass_rate:.1f}%</span><br>
                <span style="color:#e65100;font-weight:bold;font-size:1.03rem;">{milestone}</span>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.info("No writing stats found yet. Write your first letter to see progress!")




    student_code = st.session_state.get("student_code", "demo")
    prev_student_code = st.session_state.get("prev_student_code", None)

    # On student change, load last letter/draft and update session state keys
    if student_code != prev_student_code:
        stats = get_schreiben_stats(student_code)
        st.session_state[f"{student_code}_schreiben_input"] = stats.get("last_letter", "")
        # Reset or initialize other student-specific states as needed
        st.session_state[f"{student_code}_last_feedback"] = None
        st.session_state[f"{student_code}_last_user_letter"] = None
        st.session_state[f"{student_code}_delta_compare_feedback"] = None
        st.session_state[f"{student_code}_final_improved_letter"] = ""
        st.session_state[f"{student_code}_awaiting_correction"] = False
        st.session_state[f"{student_code}_improved_letter"] = ""
        st.session_state["prev_student_code"] = student_code

    # Sub-tabs
    sub_tab = st.radio(
        "Choose Mode",
        ["Mark My Letter", "Ideas Generator (Letter Coach)"],
        horizontal=True,
        key="schreiben_sub_tab"
    )

    # Level picker
    schreiben_levels = ["A1", "A2", "B1", "B2", "C1"]
    prev_level = st.session_state.get("schreiben_level", "A1")
    schreiben_level = st.selectbox(
        "Choose your writing level:",
        schreiben_levels,
        index=schreiben_levels.index(prev_level) if prev_level in schreiben_levels else 0,
        key="schreiben_level_selector"
    )
    st.session_state["schreiben_level"] = schreiben_level

    st.divider()

    # ----------- 1. MARK MY LETTER (NAMESPACED) -----------
    if sub_tab == "Mark My Letter":
        MARK_LIMIT = 3
        daily_so_far = get_schreiben_usage(student_code)
        st.markdown(f"**Daily usage:** {daily_so_far} / {MARK_LIMIT}")

        # Namespaced key for student input
        user_letter = st.text_area(
            "Paste or type your German letter/essay here.",
            key=f"{student_code}_schreiben_input",
            value=st.session_state.get(f"{student_code}_schreiben_input", ""),
            disabled=(daily_so_far >= MARK_LIMIT),
            height=400,
            placeholder="Write your German letter here..."
        )

        # AUTOSAVE LOGIC
        if (
            user_letter.strip() and
            user_letter != get_schreiben_stats(student_code).get("last_letter", "")
        ):
            doc_ref = db.collection("schreiben_stats").document(student_code)
            doc = doc_ref.get()
            data = doc.to_dict() if doc.exists else {}
            data["last_letter"] = user_letter
            doc_ref.set(data, merge=True)

        # --- Word count and Goethe exam rules ---
        import re
        def get_level_requirements(level):
            reqs = {
                "A1": {"min": 20, "max": 40, "desc": "A1 formal/informal letters should be 20–40 words. Cover all bullet points."},
                "A2": {"min": 20, "max": 40, "desc": "A2 formal/informal letters should be 20–40 words. Cover all bullet points."},
                "B1": {"min": 80, "max": 150, "desc": "B1 letters/essays should be about 80–150 words, with all points covered and clear structure."},
                "B2": {"min": 150, "max": 250, "desc": "B2 essays are 180–220 words, opinion essays or reports, with good structure and connectors."},
                "C1": {"min": 250, "max": 350, "desc": "C1 essays are 250–350+ words. Use advanced structures and express opinions clearly."}
            }
            return reqs.get(level.upper(), reqs["A1"])

        def count_words(text):
            return len(re.findall(r'\b\w+\b', text))

        if user_letter.strip():
            words = re.findall(r'\b\w+\b', user_letter)
            chars = len(user_letter)
            st.info(f"**Word count:** {len(words)} &nbsp;|&nbsp; **Character count:** {chars}")

            # -- Apply Goethe writing rules here --
            requirements = get_level_requirements(schreiben_level)
            word_count = count_words(user_letter)
            min_wc = requirements["min"]
            max_wc = requirements["max"]

            # --- Block too-short answers for A1/A2, warn for B1–C1
            if schreiben_level in ("A1", "A2"):
                if word_count < min_wc:
                    st.error(f"⚠️ Your letter is too short for {schreiben_level} ({word_count} words). {requirements['desc']}")
                    st.stop()
                elif word_count > max_wc:
                    st.warning(f"ℹ️ Your letter is a bit long for {schreiben_level} ({word_count} words). The exam expects 20–40 words.")
            else:
                if word_count < min_wc:
                    st.error(f"⚠️ Your essay is too short for {schreiben_level} ({word_count} words). {requirements['desc']}")
                    st.stop()
                elif word_count > max_wc + 40 and schreiben_level in ("B1", "B2"):
                    st.warning(f"ℹ️ Your essay is longer than the usual limit for {schreiben_level} ({word_count} words). Try to stay within the guidelines.")

        # Namespaced correction state per student
        for k, v in [
            ("last_feedback", None),
            ("last_user_letter", None),
            ("delta_compare_feedback", None),
            ("improved_letter", ""),
            ("awaiting_correction", False),
            ("final_improved_letter", "")
        ]:
            session_key = f"{student_code}_{k}"
            if session_key not in st.session_state:
                st.session_state[session_key] = v

        submit_disabled = daily_so_far >= MARK_LIMIT or not user_letter.strip()
        feedback_btn = st.button(
            "Get Feedback",
            type="primary",
            disabled=submit_disabled,
            key=f"feedback_btn_{student_code}"
        )

        # Initial feedback logic
        if feedback_btn:
            st.session_state[f"{student_code}_awaiting_correction"] = True
            ai_prompt = (
                f"You are Herr Felix, a supportive and innovative German letter writing trainer. "
                f"The student has submitted a {schreiben_level} German letter or essay. "
                "Write a brief comment in English about what the student did well and what they should improve while highlighting their points so they understand. "
                "Check if the letter matches their level. Talk as Herr Felix talking to a student and highlight the phrases with errors so they see it. "
                "Don't just say errors—show exactly where the mistakes are. "
                "Mark any mistake phrase or example in [wrong]...[/wrong]. "
                "If something is especially good, you can also use [correct]...[/correct] and say why. "
                "1. Give a score out of 25 marks and always display the score clearly as: Score: X / 25. "
                "2. If the score is 17 or more, write: '**Passed: You may submit to your tutor!**'. "
                "3. If the score is 16 or less, write: '**Keep improving before you submit.**'. "
                "4. Only write one of these two sentences, never both, and place it on a separate bolded line at the end of your feedback. "
                "5. Always explain why you gave the student that score based on grammar, spelling, vocabulary, coherence, and so on. "
                "6. Also check for AI usage or if the student wrote with their own effort. "
                "7. List and show the phrases to improve on with tips, suggestions, and what they should do. Let the student use your suggestions to correct the letter, but don't write the full corrected letter for them. "
                "8. After your feedback, give a clear breakdown in this format (always use the same order):\n"
                "Grammar: [score/5, one-sentence tip]\n"
                "Vocabulary: [score/5, one-sentence tip]\n"
                "Spelling: [score/5, one-sentence tip]\n"
                "Structure: [score/5, one-sentence tip]\n"
                "For each area, rate out of 5 and give a specific, actionable tip in English. "
                "IMPORTANT: For A1 and A2 ONLY, follow these extra rules: "
                "- If the topic is about cancelling appointments, show students how to use simple reasons connected to health or weather, like 'Ich habe Bauchschmerzen' or 'Es regnet stark.' Avoid complex reasons. Teach them to use 'absagen' in their letter, for example, 'Ich schreibe Ihnen, weil ich den Termin absagen möchte.' "
                "- For registration or enquiries, remind students to ask for price using phrases like 'Wie viel kostet...?' and to use 'Anfrage stellen' in the phrase, e.g., 'Ich schreibe Ihnen, weil ich eine Anfrage stellen möchte.' "
                "- For setting a new appointment, use 'vereinbaren,' e.g., 'Ich möchte einen neuen Termin vereinbaren.' "
                "- Teach students to say sorry simply: 'Es tut mir leid.' "
                "- Remind students to start their reason with 'Ich schreibe Ihnen/dir, weil ich...' and usually end with 'möchte' to keep it simple and safe for A1/A2. "
                "Whenever you see these themes, always encourage the simplest phrasing and provide clear examples for the student to copy. Do NOT encourage complex sentence structures at A1/A2 level."
            )

# 
            with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                try:
                    completion = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": ai_prompt},
                            {"role": "user", "content": user_letter},
                        ],
                        temperature=0.6,
                    )
                    feedback = completion.choices[0].message.content
                    st.session_state[f"{student_code}_last_feedback"] = feedback
                    st.session_state[f"{student_code}_last_user_letter"] = user_letter
                    st.session_state[f"{student_code}_delta_compare_feedback"] = None  # Reset
                except Exception as e:
                    st.error("AI feedback failed. Please check your OpenAI setup.")
                    feedback = None

            if feedback:
                inc_schreiben_usage(student_code)
                st.markdown("---")
                st.markdown("#### 📝 Feedback from Herr Felix")
                st.markdown(highlight_feedback(feedback), unsafe_allow_html=True)
                st.session_state[f"{student_code}_awaiting_correction"] = True

                # Save stats
                import datetime, re
                score_match = re.search(r"Score[: ]+(\d+)", feedback)
                score = int(score_match.group(1)) if score_match else 0
                passed = score >= 17
                save_submission(student_code, score, passed, datetime.datetime.now())
                update_schreiben_stats(student_code)

        # DELTA IMPROVEMENT LOGIC + PDF/WHATSAPP, per student
        if st.session_state.get(f"{student_code}_last_feedback") and st.session_state.get(f"{student_code}_last_user_letter"):
            st.markdown("---")
            st.markdown("#### 📝 Feedback from Herr Felix (Reference)")
            st.markdown(
                highlight_feedback(st.session_state[f"{student_code}_last_feedback"]),
                unsafe_allow_html=True
            )
            st.markdown(
                """
                <div style="background:#e3f7da; border-left:7px solid #44c767; 
                color:#295327; padding:1.15em; margin-top:1em; border-radius:10px; font-size:1.09em;">
                    🔁 <b>Try to improve your letter!</b><br>
                    Paste your improved version below and click <b>Compare My Improvement</b>.<br>
                    The AI will highlight what’s better, what’s still not fixed, and give extra tips.<br>
                    <b>You can download or share the improved version & new feedback below.</b>
                </div>
                """, unsafe_allow_html=True
            )
            improved_letter = st.text_area(
                "Your improved version (try to fix the mistakes Herr Felix mentioned):",
                key=f"{student_code}_improved_letter",
                height=400,
                placeholder="Paste your improved letter here..."
            )
            compare_clicked = st.button("Compare My Improvement", key=f"compare_btn_{student_code}")

            if compare_clicked and improved_letter.strip():
                ai_compare_prompt = (
                    "You are Herr Felix, a supportive German writing coach. "
                    "A student first submitted this letter:\n\n"
                    f"{st.session_state[f'{student_code}_last_user_letter']}\n\n"
                    "Your feedback was:\n"
                    f"{st.session_state[f'{student_code}_last_feedback']}\n\n"
                    "Now the student has submitted an improved version below.\n"
                    "Compare both versions and:\n"
                    "- Tell the student exactly what they improved, and which mistakes were fixed.\n"
                    "- Point out if there are still errors left, with new tips for further improvement.\n"
                    "- Encourage the student. If the improvement is significant, say so.\n"
                    "1. If student dont improve after the third try, end the chat politely and tell the student to try again tomorrow. Dont continue to give the feedback after third try.\n"
                    "- Give a revised score out of 25 (Score: X/25)."
                )
                with st.spinner("👨‍🏫 Herr Felix is comparing your improvement..."):
                    try:
                        result = client.chat.completions.create(
                            model="gpt-4o",
                            messages=[
                                {"role": "system", "content": ai_compare_prompt},
                                {"role": "user", "content": improved_letter}
                            ],
                            temperature=0.5,
                        )
                        compare_feedback = result.choices[0].message.content
                        st.session_state[f"{student_code}_delta_compare_feedback"] = compare_feedback
                        st.session_state[f"{student_code}_final_improved_letter"] = improved_letter
                    except Exception as e:
                        st.session_state[f"{student_code}_delta_compare_feedback"] = f"Sorry, there was an error comparing your letters: {e}"

            if st.session_state.get(f"{student_code}_delta_compare_feedback"):
                st.markdown("---")
                st.markdown("### 📝 Improvement Feedback from Herr Felix")
                st.markdown(highlight_feedback(st.session_state[f"{student_code}_delta_compare_feedback"]), unsafe_allow_html=True)

                # PDF & WhatsApp buttons only appear after successful improvement compare
                from fpdf import FPDF
                import urllib.parse, os

                def sanitize_text(text):
                    return text.encode('latin-1', errors='replace').decode('latin-1')

                # Generate the PDF with the improved letter and improvement feedback
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                improved_letter = st.session_state.get(f"{student_code}_final_improved_letter", "")
                improved_feedback = st.session_state[f"{student_code}_delta_compare_feedback"]
                pdf.multi_cell(0, 10, f"Your Improved Letter:\n\n{sanitize_text(improved_letter)}\n\nFeedback from Herr Felix:\n\n{sanitize_text(improved_feedback)}")
                pdf_output = f"Feedback_{student_code}_{schreiben_level}_improved.pdf"
                pdf.output(pdf_output)
                with open(pdf_output, "rb") as f:
                    pdf_bytes = f.read()
                st.download_button(
                    "⬇️ Download Improved Version + Feedback (PDF)",
                    pdf_bytes,
                    file_name=pdf_output,
                    mime="application/pdf"
                )
                os.remove(pdf_output)

                # WhatsApp share
                wa_message = (
                    f"Hi, here is my IMPROVED German letter and AI feedback:\n\n"
                    f"{improved_letter}\n\n"
                    f"Feedback:\n{st.session_state[f'{student_code}_delta_compare_feedback']}"
                )
                wa_url = (
                    "https://api.whatsapp.com/send"
                    "?phone=233205706589"
                    f"&text={urllib.parse.quote(wa_message)}"
                )
                st.markdown(
                    f"[📲 Send Improved Letter & Feedback to Tutor on WhatsApp]({wa_url})",
                    unsafe_allow_html=True
                )
#


    if sub_tab == "Ideas Generator (Letter Coach)":
        import io

        # === NAMESPACED SESSION KEYS (per student) ===
        student_code = st.session_state.get("student_code", "demo")
        ns_prefix = f"{student_code}_letter_coach_"
        def ns(key): return ns_prefix + key

        # --- Reset per-student Letter Coach state on student change ---
        prev_letter_coach_code = st.session_state.get("prev_letter_coach_code", None)
        if student_code != prev_letter_coach_code:
            last_prompt, last_chat = load_letter_coach_progress(student_code)
            st.session_state[ns("prompt")] = last_prompt or ""
            st.session_state[ns("chat")] = last_chat or []
            st.session_state[ns("stage")] = 1 if last_chat else 0
            st.session_state["prev_letter_coach_code"] = student_code

        # --- Set per-student defaults if missing ---
        for k, default in [("prompt", ""), ("chat", []), ("stage", 0)]:
            if ns(k) not in st.session_state:
                st.session_state[ns(k)] = default


        LETTER_COACH_PROMPTS = {
            "A1": (
                "You are Herr Felix, a creative and supportive German letter-writing coach for A1 students. "
                "Always reply in English, never in German. "
                "When a student submits something, first congratulate them with ideas about how to go about the letter. "
                "Analyze if their message is a new prompt, a continuation, or a question. "
                "If it's a question, answer simply and encourage them to keep building their letter step by step. "
                "If it's a continuation, review their writing so far and guide them to the next step. "
                "    1. Always give students short ideas, structure and tips and phrases on how to build their points for the conversation in English and simple German. Don't overfeed students, help them but let them think by themselves also. "
                "    2. For conjunctions, only suggest 'weil', 'deshalb', 'ich möchte wissen, ob' and 'ich möchte wissen, wann'. Don't recommend 'da', 'dass' and relative clauses. "
                "    3. For requests, teach them how to use 'Könnten Sie...' and how it ends with a main verb to make a request when necessary. "
                "    4. For formal/informal letter: guide them to use 'Ich schreibe Ihnen/dir...', and show how to use 'weil' with 'ich' and end with only 'möchte' to prevent mistakes. Be strict with this. "
                "    5. Always check that the student statement is not too long or complicated. For example, if they use two conjunctions, warn them and break it down for them. "
                "    6. Warn students if their statement per input is too long or complicated. When student statement has more than 7 or 8 words, break it down for them with full stops and simple conjunctions. "
                "    7. Always add your ideas after student submits their sentence if necessary. "
                "    8. Make sure the complete letter is between 30 and 40 words. "
                "    9. When the letter is about cancelling appointments, teach students how they can use reasons connected to weather and health to cancel appointments. Teach them how to use 'absagen' to cancel appointments. "
                "    10. For enquiries or registrations, teach students how to use 'Anfrage stellen' for the Ich schreibe. "
                "    11. When the letter is about registrations like a course, teach students how they can use 'anfangen', 'beginnen'. "
                "    12. Asking for price, teach them how to use 'wie viel kostet...' and how they should ask for price always when it is about enquiries. "
                "    13. Teach them to use 'Es tut mir leid.' to say sorry. "
                "    14. Always remind students to use 'Ich schreibe Ihnen/dir, weil ich ... möchte.' for their reasons. "
                "Always make grammar correction or suggest a better phrase when necessary. "
                "If it's a continuation, review their writing so far and guide them to the next step. "
                "If it's a new prompt, give a brief, simple overview (in English) of how to build their letter (greeting, introduction, reason, request, closing), with short examples for each. "
                "For the introduction, always remind the student to use: 'Ich schreibe Ihnen, weil ich ...' for formal letters or 'Ich schreibe dir, weil ich ...' for informal letters. "
                "For the main request, always recommend ending the sentence with 'möchte' or another basic modal verb, as this is the easiest and most correct way at A1 (e.g., 'Ich möchte einen Termin machen.'). "
                "After your overview or advice, always use the phrase 'Your next recommended step:' and ask for only the next part—first the greeting (wait for it), then only the introduction (wait for it), then reason, then request, then closing—one after the other, never more than one at a time. "
                "After each student reply, check their answer, give gentle feedback, and then again state 'Your next recommended step:' and prompt for just the next section. "
                "Only help with basic connectors ('und', 'aber', 'weil', 'deshalb', 'ich möchte wissen'). Never write the full letter yourself—coach one part at a time. "
                "The chat session should last for about 10 student replies. If the student is not done by then, gently remind them: 'Most letters can be completed in about 10 steps. Please try to finish soon.' "
                "If after 14 student replies, the letter is still not finished, end the session with: 'We have reached the end of this coaching session. Please copy your letter so far and paste it into the “Mark My Letter” tool for full AI feedback and a score.' "
                "Throughout, your questions must be progressive, one at a time, and always guide the student logically through the structure."
            ),
            "A2": (
                "You are Herr Felix, a creative and supportive German letter-writing coach for A2 students. "
                "Always reply in English, never in German. "
                "Congratulate the student on their first submission with ideas about how to go about the letter. Analyze whether it is a prompt, a continuation, or a question. "
                "    1. Always give students short ideas, structure and tips and phrases on how to build their points for the conversation in English and simple German. Don't overfeed students; help them but let them think by themselves also. "
                "    2. For structure, require their letter to have clear sequencing with 'Zuerst' (for the first paragraph), 'Dann' or 'Außerdem' (for the body/second idea), and 'Zum Schluss' (for closing/last idea). "
                "       - Always recommend 'Zuerst' instead of 'Erstens' for A2 letters, as it is simpler and more natural for personal or exam letters. "
                "    3. For connectors, use 'und', 'aber', 'weil', 'denn', 'deshalb', and encourage linking words for clarity. "
                "    4. After every reply, give a tip or phrase, but never write the full letter for them. "
                "    5. Remind them not to write sentences longer than 7–8 words; break long sentences into short, clear ideas. "
                "    6. Letter should be between 40 and 50 words. "
                "    7. For cancellations, suggest health/weather reasons ('Ich bin krank.', 'Es regnet stark.') and use 'absagen' (e.g., 'Ich schreibe Ihnen, weil ich absagen möchte.'). "
                "    8. For enquiries/registrations, show 'Anfrage stellen' (e.g., 'Ich schreibe Ihnen, weil ich eine Anfrage stellen möchte.') and include asking for price: 'Wie viel kostet...?'. "
                "    9. For appointments, recommend 'vereinbaren' ('Ich möchte einen neuen Termin vereinbaren.'). "
                "    10. To say sorry, use: 'Es tut mir leid.' "
                "    11. Always correct grammar and suggest improved phrases when needed. "
                "    12. At each step, say 'Your next recommended step:' and ask for only the next section (first greeting, then introduction, then body using 'Zuerst', 'Außerdem', then closing 'Zum Schluss'). "
                "    13. The session should be complete in about 10 student replies; if not, remind them to finish soon. After 14, end and tell the student to copy their letter into 'Mark My Letter' for feedback. "
                "    14. Throughout, do not write the whole letter—guide only one part at a time."
            ),
            "B1": (
                "You are Herr Felix, a supportive German letter/essay coach for B1 students. "
                "Always reply in English, never in German. "
                "Congratulate the student with ideas about how to go about the letter, analyze the type of submission, and determine whether it is a formal letter, informal letter, or opinion essay. "
                "If you are not sure, politely ask the student what type of writing they need help with. "
                f"1. Always give students short ideas,structure and tips and phrases on how to build their points for the conversation in English and simple German. Dont overfeed students, help them but let them think by themselves also "
                f"2. Always check to be sure their letters are organized with paragraphs using sequences and sentence starters "
                f"3. Always add your ideas after student submmit their sentence if necessary "
                f"4. Always be sure that students complete formal letter is between 40 to 50 words,informal letter and opinion essay between 80 to 90 words "
                f"5. When giving ideas for sentences, just give 2 to 3 words and tell student to continue from there. Let the student also think and dont over feed them. "
                "For a formal letter, give a brief overview of the structure (greeting, introduction, main reason/request, closing), with useful examples. "
                "Always make grammar correction or suggest a better phrase when necessary. "
                "For an informal letter, outline the friendly structure (greeting, introduction, reason, personal info, closing), with simple examples. "
                "For an opinion essay, provide a short overview: introduction (with phrases like 'Heutzutage ist ... ein wichtiges Thema.' or 'Ich bin der Meinung, dass...'), main points (advantages, disadvantages, opinion), connectors, and closing. "
                "After your overview, always use the phrase 'Your next recommended step:' and ask for only one section at a time—greeting, then introduction, then main points, then closing—never more than one at a time. "
                "After each answer, provide feedback, then again prompt with 'Your next recommended step:'. "
                "Encourage the use of appropriate connectors ('außerdem', 'trotzdem', 'weil', 'deshalb'). "
                "If the student is still writing after 10 turns, encourage them to finish. At 14, end the chat, reminding them to paste their draft in 'Mark My Letter' for feedback."
            ),
            "B2": (
                "You are Herr Felix, a supportive German writing coach for B2 students. "
                "Always reply in English, never in German. "
                "Congratulate the student with ideas about how to go about the letter, analyze the type of input, and determine if it is a formal letter, informal letter, or an opinion/argumentative essay. "
                "If you are not sure, politely ask the student what type of writing they need help with. "
                f"1. Always give students short ideas,structure and tips and phrases on how to build their points for the conversation in English and simple German. Dont overfeed students, help them but let them think by themselves also "
                f"2. Always check to be sure their letters are organized with paragraphs using sequences and sentence starters "
                f"3. Always add your ideas after student submmit their sentence if necessary "
                f"4. Always be sure that students complete formal letter is between 100 to 150 words and opinion essay is 150 to 170 words "
                f"5. When giving ideas for sentences, just give 2 to 3 words and tell student to continue from there. Let the student also think and dont over feed them. "
                "Always make grammar correction or suggest a better phrase when necessary. "
                "For a formal letter, briefly outline the advanced structure: greeting, introduction, clear argument/reason, supporting details, closing—with examples. "
                "For an informal letter, outline a friendly but organized structure: greeting, personal introduction, main point/reason, examples, closing. "
                "For an opinion or argumentative essay, outline: introduction (with a strong thesis), arguments (with connectors and examples), counterarguments, connectors, conclusion, closing. "
                "After your overview or advice, always use the phrase 'Your next recommended step:' and ask for only one section at a time. "
                "After each student reply, give feedback, then use 'Your next recommended step:' again. "
                "Suggest and model advanced connectors ('denn', 'dennoch', 'außerdem', 'jedoch', 'zum Beispiel', 'einerseits...andererseits'). "
                "If the student is still writing after 10 turns, gently encourage finishing; after 14, end the chat and ask the student to paste their draft in 'Mark My Letter' for feedback."
            ),
            "C1": (
                "You are Herr Felix, an advanced and supportive German writing coach for C1 students. "
                "Always reply in English, and in German when neccessary. If the German is difficult, explain it to the student "
                "Congratulate the student with ideas about how to go about the letter, analyze the type of input, and determine if it is a formal letter, informal letter, or an academic/opinion essay. "
                f"1. Always give students short ideas,structure and tips and phrases on how to build their points for the conversation in English and simple German. Dont overfeed students, help them but let them think by themselves also "
                f"2. Always check to be sure their letters are organized with paragraphs using sequence and sentence starters "
                f"3. Always add your ideas after student submmit their sentence if necessary "
                f"4. Always be sure that students complete formal letter is between 120 to 150 words and opinion essay is 230 to 250 words "
                f"5. When giving ideas for sentences, just give 2 to 3 words and tell student to continue from there. Let the student also think and dont over feed them. "
                "If you are not sure, politely ask the student what type of writing they need help with. "
                "For a formal letter, give a precise overview: greeting, sophisticated introduction, detailed argument, supporting evidence, closing, with nuanced examples. "
                "Always make grammar correction or suggest a better phrase when necessary. "
                "For an informal letter, outline a nuanced and expressive structure: greeting, detailed introduction, main point/reason, personal opinion, nuanced closing. "
                "For academic or opinion essays, provide a clear outline: introduction (with a strong thesis and background), well-structured arguments, counterpoints, advanced connectors, conclusion, and closing—with C1-level examples. "
                "After your overview or advice, always use the phrase 'Your next recommended step:' and ask for only one section at a time. "
                "After each answer, provide feedback, then again prompt with 'Your next recommended step:'. "
                "Model and suggest advanced connectors ('nicht nur... sondern auch', 'obwohl', 'dennoch', 'folglich', 'somit'). "
                "If the student is still writing after 10 turns, gently encourage finishing; after 14, end the chat and ask the student to paste their draft in 'Mark My Letter' for feedback and a score."
            ),
        }

        def reset_letter_coach():
            for k in [
                "letter_coach_stage", "letter_coach_chat", "letter_coach_prompt",
                "letter_coach_type", "selected_letter_lines", "letter_coach_uploaded"
            ]:
                st.session_state[k] = 0 if k == "letter_coach_stage" else []
            st.session_state["letter_coach_uploaded"] = False

        def bubble(role, text):
            if role == "assistant":
                return f"""<div style='background: #f4eafd; color: #7b2ff2; border-radius: 16px 16px 16px 3px; margin-bottom: 8px; margin-right: 80px; box-shadow: 0 2px 8px rgba(123,47,242,0.08); padding: 13px 18px; text-align: left; max-width: 88vw; font-size: 1.12rem;'><b>👨‍🏫 Herr Felix:</b><br>{text}</div>"""
            return f"""<div style='background: #eaf4ff; color: #1a237e; border-radius: 16px 16px 3px 16px; margin-bottom: 8px; margin-left: 80px; box-shadow: 0 2px 8px rgba(26,35,126,0.07); padding: 13px 18px; text-align: right; max-width: 88vw; font-size: 1.12rem;'><b>🙋 You:</b><br>{text}</div>"""

        # --- General Instructions for Students (Minimal Welcome + Subline) ---
        st.markdown(
            """
            <div style="
                background: linear-gradient(97deg, #f4eafd 75%, #ffe0f5 100%);
                border-radius: 12px;
                border: 1px solid #e6d3fa;
                box-shadow: 0 2px 8px #e5e1fa22;
                padding: 0.75em 1em 0.72em 1em;
                margin-bottom: 1.1em;
                margin-top: 0.1em;
                color: #4b2976;
                font-size: 1.03rem;
                font-family: 'Segoe UI', 'Roboto', 'Arial', sans-serif;
                text-align: center;
                ">
                <span style="font-size:1.19em; vertical-align:middle;">✉️</span>
                <span style="font-size:1.05em; font-weight: 500; margin-left:0.24em;">
                    Welcome to <span style="color:#7b2ff2;">Letter Coach</span>
                </span>
                <div style="color:#b48be6; font-size:0.97em; margin-top:0.35em;">
                    Get started below 👇
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

 
        IDEAS_LIMIT = 14
        ideas_so_far = get_letter_coach_usage(student_code)
        st.markdown(f"**Daily usage:** {ideas_so_far} / {IDEAS_LIMIT}")
        if ideas_so_far >= IDEAS_LIMIT:
            st.warning("You have reached today's letter coach limit. Please come back tomorrow.")
            st.stop()

        # --- Stage 0: Prompt input ---
        if st.session_state[ns("stage")] == 0:
            st.markdown("### ✏️ Enter your exam prompt or draft to start coaching")
            with st.form(ns("prompt_form"), clear_on_submit=True):
                prompt = st.text_area(
                    "",
                    value=st.session_state[ns("prompt")],
                    height=120,
                    placeholder="e.g., Schreiben Sie eine formelle E-Mail an Ihre Nachbarin ..."
                )
                send = st.form_submit_button("✉️ Start Letter Coach")

            if prompt:
                word_count = len(prompt.split())
                char_count = len(prompt)
                st.markdown(
                    f"<div style='color:#7b2ff2; font-size:0.97em; margin-bottom:0.18em;'>"
                    f"Words: <b>{word_count}</b> &nbsp;|&nbsp; Characters: <b>{char_count}</b>"
                    "</div>",
                    unsafe_allow_html=True
                )

            if send and prompt:
                st.session_state[ns("prompt")] = prompt
                student_level = st.session_state.get("schreiben_level", "A1")
                system_prompt = LETTER_COACH_PROMPTS[student_level].format(prompt=prompt)
                chat_history = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
                try:
                    resp = client.chat.completions.create(
                        model="gpt-4o",
                        messages=chat_history,
                        temperature=0.22,
                        max_tokens=380
                    )
                    ai_reply = resp.choices[0].message.content
                except Exception as e:
                    ai_reply = "Sorry, there was an error generating a response. Please try again."
                chat_history.append({"role": "assistant", "content": ai_reply})

                st.session_state[ns("chat")] = chat_history
                st.session_state[ns("stage")] = 1
                inc_letter_coach_usage(student_code)
                save_letter_coach_progress(
                    student_code,
                    student_level,
                    st.session_state[ns("prompt")],
                    st.session_state[ns("chat")],
                )
                st.rerun()

            if prompt:
                st.markdown("---")
                st.markdown(f"📝 **Letter/Essay Prompt or Draft:**\n\n{prompt}")

        # --- Stage 1: Coaching Chat ---
        elif st.session_state[ns("stage")] == 1:
            st.markdown("---")
            st.markdown(f"📝 **Letter/Essay Prompt:**\n\n{st.session_state[ns('prompt')]}")
            chat_history = st.session_state[ns("chat")]
            for msg in chat_history[1:]:
                st.markdown(bubble(msg["role"], msg["content"]), unsafe_allow_html=True)
            num_student_turns = sum(1 for msg in chat_history[1:] if msg["role"] == "user")
            if num_student_turns == 10:
                st.info("🔔 You have written 10 steps. Most students finish in 7–10 turns. Try to complete your letter soon!")
            elif num_student_turns == 12:
                st.warning(
                    "⏰ You have reached 12 writing turns. "
                    "Usually, your letter should be complete by now. "
                    "If you want feedback, click **END SUMMARY** or download your letter as TXT. "
                    "You can always start a new session for more practice."
                )
            elif num_student_turns > 12:
                st.warning(
                    f"🚦 You are now at {num_student_turns} turns. "
                    "Long letters are okay, but usually a good letter is finished in 7–12 turns. "
                    "Try to wrap up, click **END SUMMARY** or download your letter as TXT."
                )

            with st.form(ns("letter_coach_chat_form"), clear_on_submit=True):
                user_input = st.text_area(
                    "",
                    value="",
                    key=ns("user_input"),
                    height=400,
                    placeholder="Type your reply, ask about a section, or paste your draft here..."
                )
                send = st.form_submit_button("Send")
            if send and user_input.strip():
                chat_history.append({"role": "user", "content": user_input})
                student_level = st.session_state.get("schreiben_level", "A1")
                system_prompt = LETTER_COACH_PROMPTS[student_level].format(prompt=st.session_state[ns("prompt")])
                with st.spinner("👨‍🏫 Herr Felix is typing..."):
                    resp = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "system", "content": system_prompt}] + chat_history[1:] + [{"role": "user", "content": user_input}],
                        temperature=0.22,
                        max_tokens=380
                    )
                    ai_reply = resp.choices[0].message.content
                chat_history.append({"role": "assistant", "content": ai_reply})
                st.session_state[ns("chat")] = chat_history
                save_letter_coach_progress(
                    student_code,
                    student_level,
                    st.session_state[ns("prompt")],
                    st.session_state[ns("chat")],
                )
                st.rerun()

            # ----- LIVE AUTO-UPDATING LETTER DRAFT, Download + Copy -----
            import streamlit.components.v1 as components

            user_msgs = [
                msg["content"]
                for msg in st.session_state[ns("chat")][1:]
                if msg.get("role") == "user"
            ]

            st.markdown("""
                **📝 Your Letter Draft**
                - Tick the lines you want to include in your letter draft.
                - You can untick any part you want to leave out.
                - Only ticked lines will appear in your downloadable draft below.
            """)

            # Store selection in session state (keeps selection per student)
            if ns("selected_letter_lines") not in st.session_state or \
                len(st.session_state[ns("selected_letter_lines")]) != len(user_msgs):
                st.session_state[ns("selected_letter_lines")] = [True] * len(user_msgs)

            selected_lines = []
            for i, line in enumerate(user_msgs):
                st.session_state[ns("selected_letter_lines")][i] = st.checkbox(
                    line,
                    value=st.session_state[ns("selected_letter_lines")][i],
                    key=ns(f"letter_line_{i}")
                )
                if st.session_state[ns("selected_letter_lines")][i]:
                    selected_lines.append(line)

            letter_draft = "\n".join(selected_lines)

            # --- Live word/character count for the letter draft ---
            draft_word_count = len(letter_draft.split())
            draft_char_count = len(letter_draft)
            st.markdown(
                f"<div style='color:#7b2ff2; font-size:0.97em; margin-bottom:0.18em;'>"
                f"Words: <b>{draft_word_count}</b> &nbsp;|&nbsp; Characters: <b>{draft_char_count}</b>"
                "</div>",
                unsafe_allow_html=True
            )

            # --- Modern, soft header (copy/download) ---
            st.markdown(
                """
                <div style="
                    background:#23272b;
                    color:#eee;
                    border-radius:10px;
                    padding:0.72em 1.04em;
                    margin-bottom:0.4em;
                    font-size:1.07em;
                    font-weight:400;
                    border:1px solid #343a40;
                    box-shadow:0 2px 10px #0002;
                    text-align:left;
                ">
                    <span style="font-size:1.12em; color:#ffe082;">📝 Your Letter So Far</span><br>
                    <span style="font-size:1.00em; color:#b0b0b0;">copy often or download below to prevent data loss</span>
                </div>
                """,
                unsafe_allow_html=True
            )

            # --- Mobile-friendly copy/download box ---
            components.html(f"""
                <textarea id="letterBox_{student_code}" readonly rows="6" style="
                    width: 100%;
                    border-radius: 12px;
                    background: #f9fbe7;
                    border: 1.7px solid #ffe082;
                    color: #222;
                    font-size: 1.12em;
                    font-family: 'Fira Mono', 'Consolas', monospace;
                    padding: 1em 0.7em;
                    box-shadow: 0 2px 8px #ffe08266;
                    margin-bottom: 0.5em;
                    resize: none;
                    overflow:auto;
                " onclick="this.select()">{letter_draft}</textarea>
                <button onclick="navigator.clipboard.writeText(document.getElementById('letterBox_{student_code}').value)" 
                    style="
                        background:#ffc107;
                        color:#3e2723;
                        font-size:1.08em;
                        font-weight:bold;
                        padding:0.48em 1.12em;
                        margin-top:0.4em;
                        border:none;
                        border-radius:7px;
                        cursor:pointer;
                        box-shadow:0 2px 8px #ffe08255;
                        width:100%;
                        max-width:320px;
                        display:block;
                        margin-left:auto;
                        margin-right:auto;
                    ">
                    📋 Copy Text
                </button>
                <style>
                    @media (max-width: 480px) {{
                        #letterBox_{student_code} {{
                            font-size: 1.16em !important;
                            min-width: 93vw !important;
                        }}
                    }}
                </style>
            """, height=175)

            st.markdown("""
                <div style="
                    background:#ffe082;
                    padding:0.9em 1.2em;
                    border-radius:10px;
                    margin:0.4em 0 1.2em 0;
                    color:#543c0b;
                    font-weight:600;
                    border-left:6px solid #ffc107;
                    font-size:1.08em;">
                    📋 <span>On phone, tap in the box above to select all for copy.<br>
                    Or just tap <b>Copy Text</b>.<br>
                    To download, use the button below.</span>
                </div>
            """, unsafe_allow_html=True)

            st.download_button(
                "⬇️ Download Letter as TXT",
                letter_draft.encode("utf-8"),
                file_name="my_letter.txt"
            )

            if st.button("Start New Letter Coach"):
                st.session_state[ns("chat")] = []
                st.session_state[ns("prompt")] = ""
                st.session_state[ns("selected_letter_lines")] = []
                st.session_state[ns("stage")] = 0
                save_letter_coach_progress(
                    student_code,
                    st.session_state.get("schreiben_level", "A1"),
                    "",
                    [],
                )
                st.rerun()



# --- Helper functions for Firestore ---
def load_notes_from_db(student_code):
    ref = db.collection("learning_notes").document(student_code)
    doc = ref.get()
    return doc.to_dict().get("notes", []) if doc.exists else []

def save_notes_to_db(student_code, notes):
    ref = db.collection("learning_notes").document(student_code)
    ref.set({"notes": notes}, merge=True)

# ======================================
# == Main Tab Logic ==
if tab == "My Learning Notes":
    st.markdown("""
        <div style="padding: 14px; background: #8d4de8; color: #fff; border-radius: 8px; 
        text-align:center; font-size:1.5rem; font-weight:700; margin-bottom:16px; letter-spacing:.5px;">
        📒 My Learning Notes
        </div>
    """, unsafe_allow_html=True)

    student_code = st.session_state.get("student_code", "demo001")
    key_notes = f"notes_{student_code}"

    # ---- Load notes from Firestore on first tab entry ---
    if key_notes not in st.session_state:
        st.session_state[key_notes] = load_notes_from_db(student_code)
    notes = st.session_state[key_notes]

    # ----- PROGRAMMATIC TAB SWITCH HANDLING -----
    # If flags are set, switch tab before rendering radio
    if st.session_state.get("switch_to_edit_note"):
        st.session_state["notebook_radio"] = "➕ Add/Edit Note"
        del st.session_state["switch_to_edit_note"]
    elif st.session_state.get("switch_to_library"):
        st.session_state["notebook_radio"] = "📚 My Notes Library"
        del st.session_state["switch_to_library"]

    subtab = st.radio(
        "Notebook", 
        ["➕ Add/Edit Note", "📚 My Notes Library"], 
        horizontal=True, 
        key="notebook_radio"
    )

    # === Add/Edit Note Subtab ===
    if subtab == "➕ Add/Edit Note":
        st.markdown("#### ✍️ Create a new note or update an old one")
        editing = st.session_state.get("edit_note_idx", None) is not None
        if editing:
            idx = st.session_state["edit_note_idx"]
            title = st.session_state.get("edit_note_title", "")
            tag = st.session_state.get("edit_note_tag", "")
            text = st.session_state.get("edit_note_text", "")
        else:
            title, tag, text = "", "", ""

        with st.form("note_form", clear_on_submit=not editing):
            new_title = st.text_input("Note Title", value=title, max_chars=50)
            new_tag = st.text_input("Category/Tag (optional)", value=tag, max_chars=20)
            new_text = st.text_area("Your Note", value=text, height=200, max_chars=3000)
            save_btn = st.form_submit_button("💾 Save Note")
            cancel_btn = editing and st.form_submit_button("❌ Cancel Edit")

        if save_btn:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            if not new_title.strip():
                st.warning("Please enter a title.")
                st.stop()
            note = {
                "title": new_title.strip().title(),
                "tag": new_tag.strip().title(),
                "text": new_text.strip(),
                "pinned": False,
                "created": timestamp,
                "updated": timestamp
            }
            if editing:
                notes[idx] = note
                for k in ["edit_note_idx", "edit_note_title", "edit_note_text", "edit_note_tag"]:
                    if k in st.session_state: del st.session_state[k]
                st.success("Note updated!")
            else:
                notes.insert(0, note)
                st.success("Note added!")
            st.session_state[key_notes] = notes
            save_notes_to_db(student_code, notes)
            st.session_state["switch_to_library"] = True
            st.experimental_rerun()

        if cancel_btn:
            for k in ["edit_note_idx", "edit_note_title", "edit_note_text", "edit_note_tag"]:
                if k in st.session_state: del st.session_state[k]
            st.session_state["switch_to_library"] = True
            st.experimental_rerun()

    # === Notes Library Subtab ===
    elif subtab == "📚 My Notes Library":
        st.markdown("#### 📚 All My Notes")

        if not notes:
            st.info("No notes yet. Add your first note in the ➕ tab!")
        else:
            search_term = st.text_input("🔎 Search your notes…", "")
            if search_term.strip():
                filtered = []
                st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
                for n in notes:
                    if (search_term.lower() in n.get("title","").lower() or 
                        search_term.lower() in n.get("tag","").lower() or 
                        search_term.lower() in n.get("text","").lower()):
                        filtered.append(n)
                notes_to_show = filtered
                if not filtered:
                    st.warning("No matching notes found!")
            else:
                notes_to_show = notes

            # --- Download Buttons (TXT, PDF, DOCX) ---
            all_notes = []
            for n in notes_to_show:
                note_text = f"Title: {n.get('title','')}\n"
                if n.get('tag'):
                    note_text += f"Tag: {n['tag']}\n"
                note_text += n.get('text','') + "\n"
                note_text += f"Date: {n.get('updated', n.get('created',''))}\n"
                note_text += "-"*32 + "\n"
                all_notes.append(note_text)
            txt_data = "\n".join(all_notes)

            st.download_button(
                label="⬇️ Download All Notes (TXT)",
                data=txt_data.encode("utf-8"),
                file_name=f"{student_code}_notes.txt",
                mime="text/plain"
            )

            # --- PDF Download ---
            import tempfile
            from fpdf import FPDF
            class PDF(FPDF):
                def header(self):
                    self.set_font('Arial', 'B', 16)
                    self.cell(0, 12, "My Learning Notes", align="C", ln=1)
                    self.ln(5)
            def safe_latin1(text):
                return text.encode("latin1", "replace").decode("latin1")
            pdf = PDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.set_font("Arial", size=12)
            pdf.set_font("Arial", "B", 13)
            pdf.cell(0, 10, "Table of Contents", ln=1)
            pdf.set_font("Arial", "", 11)
            for idx, note in enumerate(notes_to_show):
                pdf.cell(0, 8, f"{idx+1}. {safe_latin1(note.get('title',''))} - {note.get('created', note.get('updated',''))}", ln=1)
            pdf.ln(5)
            for n in notes_to_show:
                pdf.set_font("Arial", "B", 13)
                pdf.cell(0, 10, safe_latin1(f"Title: {n.get('title','')}"), ln=1)
                pdf.set_font("Arial", "I", 11)
                if n.get("tag"):
                    pdf.cell(0, 8, safe_latin1(f"Tag: {n['tag']}"), ln=1)
                pdf.set_font("Arial", "", 12)
                for line in n.get('text','').split("\n"):
                    pdf.multi_cell(0, 7, safe_latin1(line))
                pdf.ln(1)
                pdf.set_font("Arial", "I", 11)
                pdf.cell(0, 8, safe_latin1(f"Date: {n.get('updated', n.get('created',''))}"), ln=1)
                pdf.ln(5)
                pdf.set_font("Arial", "", 10)
                pdf.cell(0, 4, '-' * 55, ln=1)
                pdf.ln(8)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                pdf.output(tmp_pdf.name)
                tmp_pdf.seek(0)
                pdf_bytes = tmp_pdf.read()
            os.remove(tmp_pdf.name)
            st.download_button(
                label="⬇️ Download All Notes (PDF)",
                data=pdf_bytes,
                file_name=f"{student_code}_notes.pdf",
                mime="application/pdf"
            )

            # --- DOCX Download ---
            from docx import Document
            def export_notes_to_docx(notes, student_code="student"):
                doc = Document()
                doc.add_heading("My Learning Notes", 0)
                doc.add_heading("Table of Contents", level=1)
                for idx, note in enumerate(notes):
                    doc.add_paragraph(f"{idx+1}. {note.get('title', '(No Title)')} - {note.get('created', note.get('updated',''))}")
                doc.add_page_break()
                for note in notes:
                    doc.add_heading(note.get('title','(No Title)'), level=1)
                    if note.get("tag"):
                        doc.add_paragraph(f"Tag: {note.get('tag','')}")
                    doc.add_paragraph(note.get('text', ''))
                    doc.add_paragraph(f"Date: {note.get('created', note.get('updated',''))}")
                    doc.add_paragraph('-' * 40)
                    doc.add_paragraph("")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as f:
                    doc.save(f.name)
                    return f.name
            docx_path = export_notes_to_docx(notes_to_show, student_code)
            with open(docx_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download All Notes (DOCX)",
                    data=f.read(),
                    file_name=f"{student_code}_notes.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
            os.remove(docx_path)

            st.markdown("---")
            pinned_notes = [n for n in notes_to_show if n.get("pinned")]
            other_notes = [n for n in notes_to_show if not n.get("pinned")]
            show_list = pinned_notes + other_notes
            for i, note in enumerate(show_list):
                st.markdown(
                    f"<div style='padding:12px 0 6px 0; font-weight:600; color:#7c3aed; font-size:1.18rem;'>"
                    f"{'📌 ' if note.get('pinned') else ''}{note.get('title','(No Title)')}"
                    f"</div>", unsafe_allow_html=True)
                if note.get("tag"):
                    st.caption(f"🏷️ Tag: {note['tag']}")
                st.markdown(
                    f"<div style='margin-top:-5px; margin-bottom:6px; font-size:1.08rem; line-height:1.7;'>{note['text']}</div>",
                    unsafe_allow_html=True)
                st.caption(f"🕒 {note.get('updated',note.get('created',''))}")
                cols = st.columns([1,1,1,1])
                with cols[0]:
                    if st.button("✏️ Edit", key=f"edit_{i}"):
                        st.session_state["edit_note_idx"] = i
                        st.session_state["edit_note_title"] = note["title"]
                        st.session_state["edit_note_text"] = note["text"]
                        st.session_state["edit_note_tag"] = note.get("tag", "")
                        st.session_state["switch_to_edit_note"] = True
                        st.rerun()
                with cols[1]:
                    if st.button("🗑️ Delete", key=f"del_{i}"):
                        notes.remove(note)
                        st.session_state[key_notes] = notes
                        save_notes_to_db(student_code, notes)
                        st.success("Note deleted.")
                        st.experimental_rerun()
                with cols[2]:
                    if note.get("pinned"):
                        if st.button("📌 Unpin", key=f"unpin_{i}"):
                            note["pinned"] = False
                            st.session_state[key_notes] = notes
                            save_notes_to_db(student_code, notes)
                            st.rerun()
                    else:
                        if st.button("📍 Pin", key=f"pin_{i}"):
                            note["pinned"] = True
                            st.session_state[key_notes] = notes
                            save_notes_to_db(student_code, notes)
                            st.rerun()
                with cols[3]:
                    st.caption("")
# ---------------------- END TAB -------------------------




