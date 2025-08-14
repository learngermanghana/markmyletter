# ==== Standard Library ====
import atexit, base64, difflib, hashlib
import html as html_stdlib
import io, json, os, random, math, re, sqlite3, tempfile, time
import urllib.parse as _urllib
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from typing import Optional

# ==== Third-Party Packages ====
import bcrypt
import firebase_admin
import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from docx import Document
from firebase_admin import credentials, firestore
from fpdf import FPDF
from gtts import gTTS
from openai import OpenAI
from streamlit.components.v1 import html as st_html
from streamlit_cookies_manager import EncryptedCookieManager
from streamlit_quill import st_quill

# ---- Streamlit page config MUST be first Streamlit call ----
st.set_page_config(
    page_title="Falowen – Your German Conversation Partner",
    page_icon="👋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Top spacing + chrome (tighter)
st.markdown("""
<style>
/* Remove Streamlit's top padding */
[data-testid="stAppViewContainer"] > .main .block-container {
  padding-top: 0 !important;
}

/* First rendered block (often a head-inject) — keep a small gap only */
[data-testid="stAppViewContainer"] .main .block-container > div:first-child {
  margin-top: 0 !important;
  margin-bottom: 8px !important;   /* was 24px */
  padding-top: 0 !important;
  padding-bottom: 0 !important;
}

/* If that first block is an iframe, collapse it completely */
[data-testid="stAppViewContainer"] .main .block-container > div:first-child [data-testid="stIFrame"] {
  display: block;
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  border: 0 !important;
  overflow: hidden !important;
}

/* Keep hero flush and compact */
.hero {
  margin-top: 4px !important;      /* was 0/12 — pulls hero up */
  margin-bottom: 8px !important;   /* tighter space before tabs */
  padding-top: 6px !important;
  display: flow-root;
}
.hero h1:first-child { margin-top: 0 !important; }

/* Trim default gap above Streamlit tabs */
[data-testid="stTabs"] {
  margin-top: 8px !important;
}

/* Hide default Streamlit chrome */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# Compatibility alias
html = st_html

# ---- PWA head helper (define BEFORE you call it) ----
BASE = st.secrets.get("PUBLIC_BASE_URL", "")
_manifest = f'{BASE}/static/manifest.webmanifest' if BASE else "/static/manifest.webmanifest"
_icon180  = f'{BASE}/static/icons/falowen-180.png' if BASE else "/static/icons/falowen-180.png"

def _inject_meta_tags():
    components.html(f"""
      <link rel="manifest" href="{_manifest}">
      <link rel="apple-touch-icon" href="{_icon180}">
      <meta name="apple-mobile-web-app-capable" content="yes">
      <meta name="apple-mobile-web-app-title" content="Falowen">
      <meta name="apple-mobile-web-app-status-bar-style" content="black">
      <meta name="theme-color" content="#000000">
      <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    """, height=0)

# --- State bootstrap ---
def _bootstrap_state():
    defaults = {
        "logged_in": False,
        "student_row": None,
        "student_code": "",
        "student_name": "",
        "session_token": "",
        "cookie_synced": False,
        "__last_refresh": 0.0,
        "__ua_hash": "",
        "_oauth_state": "",
        "_oauth_code_redeemed": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
_bootstrap_state()

# ==== Hide Streamlit chrome ====
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==== FIREBASE ADMIN INIT (Firestore only; no Firebase Auth in login) ====
try:
    if not firebase_admin._apps:
        cred_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    st.error(f"Firebase init failed: {e}")
    st.stop()

# ---- Firestore sessions (server-side auth state) ----
SESSIONS_COL = "sessions"
SESSION_TTL_MIN = 60 * 24 * 14         # 14 days
SESSION_ROTATE_AFTER_MIN = 60 * 24 * 7 # 7 days

def _rand_token(nbytes: int = 48) -> str:
    return base64.urlsafe_b64encode(os.urandom(nbytes)).rstrip(b"=").decode("ascii")

def create_session_token(student_code: str, name: str, ua_hash: str = "") -> str:
    now = time.time()
    token = _rand_token()
    db.collection(SESSIONS_COL).document(token).set({
        "student_code": (student_code or "").strip().lower(),
        "name": name or "",
        "issued_at": now,
        "expires_at": now + (SESSION_TTL_MIN * 60),
        "ua_hash": ua_hash or "",
    })
    return token

def validate_session_token(token: str, ua_hash: str = "") -> dict | None:
    if not token:
        return None
    try:
        snap = db.collection(SESSIONS_COL).document(token).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if float(data.get("expires_at", 0)) < time.time():
            return None
        if data.get("ua_hash") and ua_hash and data["ua_hash"] != ua_hash:
            return None
        return data
    except Exception:
        return None

def refresh_or_rotate_session_token(token: str) -> str:
    try:
        ref = db.collection(SESSIONS_COL).document(token)
        snap = ref.get()
        if not snap.exists:
            return token
        data = snap.to_dict() or {}
        now = time.time()
        # Extend TTL
        ref.update({"expires_at": now + (SESSION_TTL_MIN * 60)})
        # Rotate if old
        if now - float(data.get("issued_at", now)) > (SESSION_ROTATE_AFTER_MIN * 60):
            new_token = _rand_token()
            db.collection(SESSIONS_COL).document(new_token).set({
                **data,
                "issued_at": now,
                "expires_at": now + (SESSION_TTL_MIN * 60),
            })
            try:
                ref.delete()
            except Exception:
                pass
            return new_token
    except Exception:
        pass
    return token

def destroy_session_token(token: str) -> None:
    try:
        db.collection(SESSIONS_COL).document(token).delete()
    except Exception:
        pass

# ==== OPENAI CLIENT SETUP ====
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("Missing OpenAI API key. Please add OPENAI_API_KEY in Streamlit secrets.")
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

# ==== DB CONNECTION & INITIALIZATION ====
def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect(
            "vocab_progress.db", check_same_thread=False
        )
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

def init_db():
    conn = get_connection()
    c = conn.cursor()
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS exam_progress (
            student_code TEXT,
            level TEXT,
            teil TEXT,
            remaining TEXT,
            used TEXT,
            PRIMARY KEY (student_code, level, teil)
        )
    """)
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
init_db()

# ==== CONSTANTS ====
FALOWEN_DAILY_LIMIT = 20
VOCAB_DAILY_LIMIT = 20
SCHREIBEN_DAILY_LIMIT = 5

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

def has_sprechen_quota(student_code, limit=FALOWEN_DAILY_LIMIT):
    return get_sprechen_usage(student_code) < limit

# ==== YOUTUBE PLAYLIST HELPERS ====
YOUTUBE_API_KEY = st.secrets.get("YOUTUBE_API_KEY", "AIzaSyBA3nJi6dh6-rmOLkA4Bb0d7h0tLAp7xE4")

YOUTUBE_PLAYLIST_IDS = {
    "A1": ["PL5vnwpT4NVTdwFarD9kwm1HONsqQ11l-b"],
    "A2": ["PLs7zUO7VPyJ7YxTq_g2Rcl3Jthd5bpTdY", "PLquImyRfMt6dVHL4MxFXMILrFh86H_HAc", "PLs7zUO7VPyJ5Eg0NOtF9g-RhqA25v385c"],
    "B1": ["PLs7zUO7VPyJ5razSfhOUVbTv9q6SAuPx-", "PLB92CD6B288E5DB61"],
    "B2": ["PLs7zUO7VPyJ5XMfT7pLvweRx6kHVgP_9C", "PLs7zUO7VPyJ6jZP-s6dlkINuEjFPvKMG0", "PLs7zUO7VPyJ4SMosRdB-35Q07brhnVToY"],
}


@st.cache_data(ttl=43200)
def fetch_youtube_playlist_videos(playlist_id, api_key=YOUTUBE_API_KEY):
    base_url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {"part": "snippet", "playlistId": playlist_id, "maxResults": 50, "key": api_key}
    videos, next_page = [], ""
    while True:
        if next_page:
            params["pageToken"] = next_page
        response = requests.get(base_url, params=params, timeout=12)
        data = response.json()
        for item in data.get("items", []):
            vid = item["snippet"]["resourceId"]["videoId"]
            videos.append({"title": item["snippet"]["title"], "url": f"https://www.youtube.com/watch?v={vid}"})
        next_page = data.get("nextPageToken")
        if not next_page:
            break
    return videos

# ==== STUDENT SHEET LOADING ====
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/gviz/tq?tqx=out:csv&sheet=Sheet1"

@st.cache_data(ttl=300)
def load_student_data():
    try:
        resp = requests.get(GOOGLE_SHEET_CSV, timeout=12)
        resp.raise_for_status()
        # guard: ensure CSV not HTML
        txt = resp.text
        if "<html" in txt[:512].lower():
            raise RuntimeError("Expected CSV, got HTML (check sheet privacy).")
        df = pd.read_csv(io.StringIO(txt), dtype=str, keep_default_na=True, na_values=["", " ", "nan", "NaN", "None"])
    except Exception as e:
        st.error(f"❌ Could not load student data. {e}")
        st.stop()

    # Normalize headers and trim cells while preserving NaN
    df.columns = df.columns.str.strip().str.replace(" ", "")
    for col in df.columns:
        s = df[col]
        df[col] = s.where(s.isna(), s.astype(str).str.strip())

    # Keep only rows with a ContractEnd value
    df = df[df["ContractEnd"].notna() & (df["ContractEnd"].str.len() > 0)]

    # Robust parse
    def _parse_contract_end(s: str):
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return pd.to_datetime(s, format=fmt, errors="raise")
            except Exception:
                continue
        return pd.to_datetime(s, errors="coerce")

    df["ContractEnd_dt"] = df["ContractEnd"].apply(_parse_contract_end)
    df = df[df["ContractEnd_dt"].notna()]

    # Normalize identifiers
    if "StudentCode" in df.columns:
        df["StudentCode"] = df["StudentCode"].str.lower().str.strip()
    if "Email" in df.columns:
        df["Email"] = df["Email"].str.lower().str.strip()

    # Keep most recent per student
    df = (df.sort_values("ContractEnd_dt", ascending=False)
            .drop_duplicates(subset=["StudentCode"], keep="first")
            .drop(columns=["ContractEnd_dt"]))
    return df

def is_contract_expired(row):
    expiry_str = str(row.get("ContractEnd", "") or "").strip()
    if not expiry_str or expiry_str.lower() == "nan":
        return True
    expiry_date = None
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            expiry_date = datetime.strptime(expiry_str, fmt); break
        except ValueError:
            continue
    if expiry_date is None:
        parsed = pd.to_datetime(expiry_str, errors="coerce")
        if pd.isnull(parsed): return True
        expiry_date = parsed.to_pydatetime()
    return expiry_date.date() < datetime.utcnow().date()

# ==== Query param helpers (stable) ====
def qp_get():
    # returns a dict-like object
    return st.query_params

def qp_clear():
    # clears all query params from the URL
    st.query_params.clear()

def qp_clear_keys(*keys):
    # remove only the specified keys
    for k in keys:
        try:
            del st.query_params[k]
        except KeyError:
            pass

# ==== Cookie helpers (normal cookies) ====
def _expire_str(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

def _js_set_cookie(name: str, value: str, max_age_sec: int, expires_gmt: str, secure: bool, domain: Optional[str] = None):
    base = (
        f'var c = {json.dumps(name)} + "=" + {json.dumps(_urllib.quote(value, safe=""))} + '
        f'"; Path=/; Max-Age={max_age_sec}; Expires={json.dumps(expires_gmt)}; SameSite=Lax";\n'
        f'if ({str(bool(secure)).lower()}) c += "; Secure";\n'
    )
    if domain:
        base += f'c += "; Domain=" + {domain};\n'
    base += "document.cookie = c;\n"
    return base

def set_student_code_cookie(cookie_manager, value: str, expires: datetime):
    key = "student_code"
    norm = (value or "").strip().lower()
    use_secure = (os.getenv("ENV", "prod") != "dev")
    max_age = 60 * 60 * 24 * 180  # 180 days
    exp_str = _expire_str(expires)
    # Library cookie (encrypted; host-only)
    try:
        cookie_manager.set(key, norm, expires=expires, secure=use_secure, samesite="Lax", path="/")
        cookie_manager.save()
    except Exception:
        try:
            cookie_manager[key] = norm; cookie_manager.save()
        except Exception:
            pass
    # JS host-only + base-domain (guard invalid hosts)
    host_cookie_name = (getattr(cookie_manager, 'prefix', '') or '') + key
    host_js = _js_set_cookie(host_cookie_name, norm, max_age, exp_str, use_secure, domain=None)
    script = f"""
    <script>
      (function(){{
        try {{
          {host_js}
          try {{
            var h = (window.location.hostname||'').split('.').filter(Boolean);
            if (h.length >= 2) {{
              var base = '.' + h.slice(-2).join('.');
              {_js_set_cookie(host_cookie_name, norm, max_age, exp_str, use_secure, "base")}
            }}
          }} catch(e) {{}}
          try {{ localStorage.setItem('student_code', {json.dumps(norm)}); }} catch(e) {{}}
        }} catch(e) {{}}
      }})();
    </script>
    """
    components.html(script, height=0)

def set_session_token_cookie(cookie_manager, token: str, expires: datetime):
    key = "session_token"
    val = (token or "").strip()
    use_secure = (os.getenv("ENV", "prod") != "dev")
    max_age = 60 * 60 * 24 * 30  # 30 days
    exp_str = _expire_str(expires)
    try:
        cookie_manager.set(key, val, expires=expires, secure=use_secure, samesite="Lax", path="/")
        cookie_manager.save()
    except Exception:
        try:
            cookie_manager[key] = val; cookie_manager.save()
        except Exception:
            pass
    host_cookie_name = (getattr(cookie_manager, 'prefix', '') or '') + key
    host_js = _js_set_cookie(host_cookie_name, val, max_age, exp_str, use_secure, domain=None)
    script = f"""
    <script>
      (function(){{
        try {{
          {host_js}
          try {{
            var h = (window.location.hostname||'').split('.').filter(Boolean);
            if (h.length >= 2) {{
              var base = '.' + h.slice(-2).join('.');
              {_js_set_cookie(host_cookie_name, val, max_age, exp_str, use_secure, "base")}
            }}
          }} catch(e) {{}}
          try {{ localStorage.setItem('session_token', {json.dumps(val)}); }} catch(e) {{}}
        }} catch(e) {{}}
      }})();
    </script>
    """
    components.html(script, height=0)

def _persist_session_client(token: str, student_code: str = "") -> None:
    components.html(f"""
    <script>
      try {{
        localStorage.setItem('session_token', {json.dumps(token)});
        if ({json.dumps(student_code)} !== "") {{
          localStorage.setItem('student_code', {json.dumps(student_code)});
        }}
        const u = new URL(window.location);
        ['code','state'].forEach(k => u.searchParams.delete(k));
        window.history.replaceState({{}}, '', u);
      }} catch(e) {{}}
    </script>
    """, height=0)

# ==== Cookie manager init ====
COOKIE_SECRET = os.getenv("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET")
if not COOKIE_SECRET:
    st.error("Cookie secret missing. Add COOKIE_SECRET to your Streamlit secrets.")
    st.stop()
cookie_manager = EncryptedCookieManager(prefix="falowen_", password=COOKIE_SECRET)
if not cookie_manager.ready():
    st.warning("Cookies not ready; please refresh.")
    st.stop()

# ---- Restore from existing session token (cookie) ----
restored = False
if not st.session_state.get("logged_in", False):
    cookie_tok = (cookie_manager.get("session_token") or "").strip()
    if cookie_tok:
        data = validate_session_token(cookie_tok, st.session_state.get("__ua_hash", ""))
        if data:
            # Validate the student still exists and contract active
            try:
                df_students = load_student_data()
                found = df_students[df_students["StudentCode"] == data.get("student_code","")]
            except Exception:
                found = pd.DataFrame()
            if not found.empty and not is_contract_expired(found.iloc[0]):
                row = found.iloc[0]
                st.session_state.update({
                    "logged_in": True,
                    "student_row": row.to_dict(),
                    "student_code": row["StudentCode"],
                    "student_name": row["Name"],
                    "session_token": cookie_tok,
                })
                new_tok = refresh_or_rotate_session_token(cookie_tok) or cookie_tok
                st.session_state["session_token"] = new_tok
                set_session_token_cookie(cookie_manager, new_tok, expires=datetime.utcnow() + timedelta(days=30))
                restored = True


# --- 2) Global CSS (tightened spacing) ---
st.markdown("""
<style>
  .hero {
    background: #fff; border-radius: 12px; padding: 24px; margin: 12px auto; max-width: 800px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.05);
  }
  .help-contact-box {
    background: #fff; border-radius: 14px; padding: 20px; margin: 8px auto; max-width: 500px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.04); border:1px solid #ebebf2; text-align:center;
  }
  .quick-links { display: flex; flex-wrap: wrap; gap:12px; justify-content:center; }
  .quick-links a {
    background: #e2e8f0; padding: 8px 16px; border-radius: 8px; font-weight:600; text-decoration:none;
    color:#0f172a; border:1px solid #cbd5e1;
  }
  .quick-links a:hover { background:#cbd5e1; }
  .stButton > button { background:#2563eb; color:#ffffff; font-weight:700; border-radius:8px; border:2px solid #1d4ed8; }
  .stButton > button:hover { background:#1d4ed8; }
  a:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible, [role="button"]:focus-visible {
    outline:3px solid #f59e0b; outline-offset:2px; box-shadow:none !important;
  }
  input, textarea { color:#0f172a !important; }
  .page-wrap { max-width: 1100px; margin: 0 auto; }
  @media (max-width:600px){ .hero, .help-contact-box { padding:16px 4vw; } }
</style>
""", unsafe_allow_html=True)

GOOGLE_CLIENT_ID     = st.secrets.get("GOOGLE_CLIENT_ID", "180240695202-3v682khdfarmq9io9mp0169skl79hr8c.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "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")
REDIRECT_URI         = st.secrets.get("GOOGLE_REDIRECT_URI", "https://www.falowen.app/")


def _handle_google_oauth(code: str, state: str) -> None:
    df = load_student_data()
    df["Email"] = df["Email"].str.lower().str.strip()
    try:
        if st.session_state.get("_oauth_state") and state != st.session_state["_oauth_state"]:
            st.error("OAuth state mismatch. Please try again."); return
        if st.session_state.get("_oauth_code_redeemed") == code:
            return
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        resp = requests.post(token_url, data=data, timeout=10)
        if not resp.ok:
            st.error(f"Google login failed: {resp.status_code} {resp.text}"); return
        access_token = resp.json().get("access_token")
        if not access_token:
            st.error("Google login failed: no access token."); return
        st.session_state["_oauth_code_redeemed"] = code
        userinfo = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        ).json()
        email = (userinfo.get("email") or "").lower().strip()
        match = df[df["Email"] == email]
        if match.empty:
            st.error("No student account found for that Google email."); return
        student_row = match.iloc[0]
        if is_contract_expired(student_row):
            st.error("Your contract has expired. Contact the office."); return
        ua_hash = st.session_state.get("__ua_hash", "")
        sess_token = create_session_token(student_row["StudentCode"], student_row["Name"], ua_hash=ua_hash)
        st.session_state.update({
            "logged_in": True,
            "student_row": student_row.to_dict(),
            "student_code": student_row["StudentCode"],
            "student_name": student_row["Name"],
            "session_token": sess_token,
        })
        set_student_code_cookie(cookie_manager, student_row["StudentCode"], expires=datetime.utcnow() + timedelta(days=180))
        _persist_session_client(sess_token, student_row["StudentCode"])
        set_session_token_cookie(cookie_manager, sess_token, expires=datetime.utcnow() + timedelta(days=30))
        qp_clear()
        st.success(f"Welcome, {student_row['Name']}!")
        st.rerun()
    except Exception as e:
        st.error(f"Google OAuth error: {e}")


def render_google_oauth():
    import secrets, urllib.parse

    def _qp_first(val):
        return val[0] if isinstance(val, list) else val

    qp = qp_get()
    code = _qp_first(qp.get("code")) if hasattr(qp, "get") else None
    state = _qp_first(qp.get("state")) if hasattr(qp, "get") else None
    if code:
        _handle_google_oauth(code, state)
        return
    st.session_state["_oauth_state"] = secrets.token_urlsafe(24)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "prompt": "select_account",
        "state": st.session_state["_oauth_state"],
        "include_granted_scopes": "true",
        "access_type": "online",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    st.markdown(
        """<div class="page-wrap" style='text-align:center;margin:12px 0;'>
                <a href="{url}">
                    <button aria-label="Sign in with Google"
                            style="background:#4285f4;color:white;padding:8px 24px;border:none;border-radius:6px;cursor:pointer;">
                        Sign in with Google
                    </button>
                </a>
           </div>""".replace("{url}", auth_url),
        unsafe_allow_html=True,
    )


def render_login_form():
    with st.form("login_form", clear_on_submit=False):
        login_id = st.text_input("Student Code or Email", help="Use your school email or Falowen code (e.g., felixa2)." ).strip().lower()
        login_pass = st.text_input("Password", type="password")
        login_btn = st.form_submit_button("Log In")
    if not login_btn:
        return
    df = load_student_data()
    df["StudentCode"] = df["StudentCode"].str.lower().str.strip()
    df["Email"] = df["Email"].str.lower().str.strip()
    lookup = df[(df["StudentCode"] == login_id) | (df["Email"] == login_id)]
    if lookup.empty:
        st.error("No matching student code or email found."); return
    student_row = lookup.iloc[0]
    if is_contract_expired(student_row):
        st.error("Your contract has expired. Contact the office."); return
    doc_ref = db.collection("students").document(student_row["StudentCode"])
    doc = doc_ref.get()
    if not doc.exists:
        st.error("Account not found. Please use 'Sign Up (Approved)' first."); return
    data = doc.to_dict() or {}
    stored_pw = data.get("password", "")
    is_hash = stored_pw.startswith(("$2a$", "$2b$", "$2y$")) and len(stored_pw) >= 60
    try:
        ok = bcrypt.checkpw(login_pass.encode("utf-8"), stored_pw.encode("utf-8")) if is_hash else stored_pw == login_pass
        if ok and not is_hash:
            new_hash = bcrypt.hashpw(login_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            doc_ref.update({"password": new_hash})
    except Exception:
        ok = False
    if not ok:
        st.error("Incorrect password."); return
    ua_hash = st.session_state.get("__ua_hash", "")
    sess_token = create_session_token(student_row["StudentCode"], student_row["Name"], ua_hash=ua_hash)
    st.session_state.update({
        "logged_in": True,
        "student_row": dict(student_row),
        "student_code": student_row["StudentCode"],
        "student_name": student_row["Name"],
        "session_token": sess_token,
    })
    set_student_code_cookie(cookie_manager, student_row["StudentCode"], expires=datetime.utcnow() + timedelta(days=180))
    _persist_session_client(sess_token, student_row["StudentCode"])
    set_session_token_cookie(cookie_manager, sess_token, expires=datetime.utcnow() + timedelta(days=30))
    st.success(f"Welcome, {student_row['Name']}!")
    st.rerun()


def render_signup_form():
    with st.form("signup_form", clear_on_submit=False):
        new_name = st.text_input("Full Name", key="ca_name")
        new_email = st.text_input(
            "Email (must match teacher’s record)",
            help="Use the school email your tutor added to the roster.",
            key="ca_email",
        ).strip().lower()
        new_code = st.text_input("Student Code (from teacher)", help="Example: felixa2", key="ca_code").strip().lower()
        new_password = st.text_input("Choose a Password", type="password", key="ca_pass")
        signup_btn = st.form_submit_button("Create Account")
    if not signup_btn:
        return
    if not (new_name and new_email and new_code and new_password):
        st.error("Please fill in all fields."); return
    if len(new_password) < 8:
        st.error("Password must be at least 8 characters."); return
    df = load_student_data()
    df["StudentCode"] = df["StudentCode"].str.lower().str.strip()
    df["Email"] = df["Email"].str.lower().str.strip()
    valid = df[(df["StudentCode"] == new_code) & (df["Email"] == new_email)]
    if valid.empty:
        st.error("Your code/email aren’t registered. Use 'Request Access' first."); return
    doc_ref = db.collection("students").document(new_code)
    if doc_ref.get().exists:
        st.error("An account with this student code already exists. Please log in instead."); return
    hashed_pw = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    doc_ref.set({"name": new_name, "email": new_email, "password": hashed_pw})
    st.success("Account created! Please log in on the Returning tab.")


def render_reviews():
    REVIEWS = [
        {"quote": "Falowen helped me pass A2 in 8 weeks. The assignments and feedback were spot on.", "author": "Ama — Accra, Ghana 🇬🇭", "level": "A2"},
        {"quote": "The Course Book and Results emails keep me consistent. The vocab trainer is brilliant.", "author": "Tunde — Lagos, Nigeria 🇳🇬", "level": "B1"},
        {"quote": "Clear lessons, easy submissions, and I get notified quickly when marked.", "author": "Mariama — Freetown, Sierra Leone 🇸🇱", "level": "A1"},
        {"quote": "I like the locked submissions and the clean Results tab.", "author": "Kwaku — Kumasi, Ghana 🇬🇭", "level": "B2"},
    ]
    _reviews_html = """
    <div class="page-wrap" style="max-width:900px;margin-top:20px;">
      <div id="reviews" style="position:relative;height:270px;overflow:hidden;border-radius:10px;border:1px solid #ddd;background:#fff;padding:24px 16px;">
        <blockquote id="rev_quote" style="font-size:1.05em;line-height:1.4;margin:0;"></blockquote>
        <div id="rev_author" style="margin-top:12px;font-weight:bold;color:#1e293b;"></div>
        <div id="rev_level" style="color:#475569;"></div>
      </div>
    </div>
    <script>
      const r=__DATA__,q=document.getElementById('rev_quote'),a=document.getElementById('rev_author'),l=document.getElementById('rev_level');
      let i=0;function show(){const c=r[i];q.textContent='"'+c.quote+'"';a.textContent=c.author;l.textContent='Level '+c.level}
      function next(){i=(i+1)%r.length;show()}
      const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(!reduced){setInterval(next,6000)}show();
    </script>
    """
    _reviews_json = json.dumps(REVIEWS)
    components.html(_reviews_html.replace("__DATA__", _reviews_json), height=320, scrolling=True)

def login_page():

    # Optional container width helper (safe if you already defined it in global CSS)
    st.markdown('<style>.page-wrap{max-width:1100px;margin:0 auto;}</style>', unsafe_allow_html=True)

    # HERO FIRST — this is the first visible element on the page
    st.markdown("""
    <div class="page-wrap">
      <div class="hero" aria-label="Falowen app introduction">
        <h1 style="text-align:center; color:#25317e;">👋 Welcome to <strong>Falowen</strong></h1>
        <p style="text-align:center; font-size:1.1em; color:#555;">
          Falowen is your all-in-one German learning platform, powered by
          <b>Learn Language Education Academy</b>, with courses and vocabulary from
          <b>A1 to C1</b> levels and live tutor support.
        </p>
        <ul style="max-width:700px; margin:16px auto; color:#444; font-size:1em; line-height:1.5;">
          <li>📊 <b>Dashboard</b>: Track your learning streaks, assignment progress, active contracts, and more.</li>
          <li>📚 <b>Course Book</b>: Access lecture videos, grammar modules, and submit assignments for levels A1–C1 in one place.</li>
          <li>📝 <b>Exams & Quizzes</b>: Take practice tests and official exam prep right in the app.</li>
          <li>💬 <b>Custom Chat</b>: Sprechen & expression trainer for live feedback on your speaking.</li>
          <li>🏆 <b>Results Tab</b>: View your grades, feedback, and historical performance at a glance.</li>
          <li>🔤 <b>Vocab Trainer</b>: Practice and master A1–C1 vocabulary with spaced-repetition quizzes.</li>
          <li>✍️ <b>Schreiben Trainer</b>: Improve your writing with guided exercises and instant corrections.</li>
        </ul>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Inject PWA/meta link tags AFTER the hero (zero-height iframe)
    _inject_meta_tags()

    # Inject SEO head tags AFTER the hero (using components.html)
    components.html("""
    <script>
      document.title = "Falowen – Learn German with Learn Language Education Academy";
      const desc = "Falowen is the German learning companion from Learn Language Education Academy. Join live classes or self-study with A1–C1 courses, recorded lectures, and real progress tracking.";
      let m = document.querySelector('meta[name="description"]');
      if (!m) { m = document.createElement('meta'); m.name = "description"; document.head.appendChild(m); }
      m.setAttribute("content", desc);
      const canonicalHref = window.location.origin + "/";
      let link = document.querySelector('link[rel="canonical"]');
      if (!link) { link = document.createElement('link'); link.rel = "canonical"; document.head.appendChild(link); }
      link.href = canonicalHref;
      function setOG(p, v){ let t=document.querySelector(`meta[property="${p}"]`);
        if(!t){ t=document.createElement('meta'); t.setAttribute('property', p); document.head.appendChild(t); }
        t.setAttribute('content', v);
      }
      setOG("og:title", "Falowen – Learn German with Learn Language Education Academy");
      setOG("og:description", desc);
      setOG("og:type", "website");
      setOG("og:url", canonicalHref);
      const ld = {"@context":"https://schema.org","@type":"WebSite","name":"Falowen","alternateName":"Falowen by Learn Language Education Academy","url": canonicalHref};
      const s = document.createElement('script'); s.type = "application/ld+json"; s.text = JSON.stringify(ld); document.head.appendChild(s);
    </script>
    """, height=0)

    # ===== Compact stats strip =====
    st.markdown("""
      <style>
        .stats-strip { display:flex; flex-wrap:wrap; gap:10px; justify-content:center; margin:10px auto 4px auto; max-width:820px; }
        .stat { background:#0ea5e9; color:#ffffff; border-radius:12px; padding:12px 14px; min-width:150px; text-align:center;
                box-shadow:0 2px 10px rgba(2,132,199,0.15); outline: none; }
        .stat:focus-visible { outline:3px solid #1f2937; outline-offset:2px; }
        .stat .num { font-size:1.25rem; font-weight:800; line-height:1; }
        .stat .label { font-size:.92rem; opacity:.98; }
        @media (max-width:560px){ .stat { min-width:46%; } }
      </style>
      <div class="stats-strip" role="list" aria-label="Falowen highlights">
        <div class="stat" role="listitem" tabindex="0" aria-label="Active learners: over 300">
          <div class="num">300+</div>
          <div class="label">Active learners</div>
        </div>
        <div class="stat" role="listitem" tabindex="0" aria-label="Assignments submitted">
          <div class="num">1,200+</div>
          <div class="label">Assignments submitted</div>
        </div>
        <div class="stat" role="listitem" tabindex="0" aria-label="Levels covered: A1 to C1">
          <div class="num">A1–C1</div>
          <div class="label">Full course coverage</div>
        </div>
        <div class="stat" role="listitem" tabindex="0" aria-label="Average student feedback">
          <div class="num">4.8/5</div>
          <div class="label">Avg. feedback</div>
        </div>
      </div>
    """, unsafe_allow_html=True)

    # Short explainer: which option to use
    st.markdown("""
    <div class="page-wrap" style="max-width:900px;margin-top:4px;">
      <div style="background:#f1f5f9;border:1px solid #e2e8f0;padding:12px 14px;border-radius:10px;">
        <b>Which option should I use?</b><br>
        • <b>Returning student</b>: you already created a password — log in.<br>
        • <b>Sign up (approved)</b>: you’ve paid and your email & code are on the roster, but no account yet — create one.<br>
        • <b>Request access</b>: brand new learner — fill the form and we’ll contact you.
      </div>
    </div>
    """, unsafe_allow_html=True)

    render_reviews()

    tab1, tab2, tab3 = st.tabs(["👋 Returning", "🧾 Sign Up (Approved)", "📝 Request Access"])

    with tab1:
        render_google_oauth()
        st.markdown("<div class='page-wrap' style='text-align:center; margin:8px 0;'>⎯⎯⎯ or ⎯⎯⎯</div>", unsafe_allow_html=True)
        render_login_form()

    with tab2:
        render_signup_form()

    # --- Request Access ---
    with tab3:
        st.markdown(
            """
            <div class="page-wrap" style="text-align:center; margin-top:20px;">
                <p style="font-size:1.1em; color:#444;">
                    If you don't have an account yet, please request access by filling out this form.
                </p>
                <a href="https://docs.google.com/forms/d/e/1FAIpQLSenGQa9RnK9IgHbAn1I9rSbWfxnztEUcSjV0H-VFLT-jkoZHA/viewform?usp=header" 
                   target="_blank" rel="noopener">
                    <button style="background:#25317e; color:white; padding:10px 20px; border:none; border-radius:6px; cursor:pointer;">
                        📝 Open Request Access Form
                    </button>
                </a>
            </div>
            """,
            unsafe_allow_html=True
        )

    
    st.markdown("""
    <div class="page-wrap">
      <div class="help-contact-box" aria-label="Help and contact options">
        <b>❓ Need help or access?</b><br>
        <a href="https://api.whatsapp.com/send?phone=233205706589" target="_blank" rel="noopener">📱 WhatsApp us</a>
        &nbsp;|&nbsp;
        <a href="mailto:learngermanghana@gmail.com" target="_blank" rel="noopener">✉️ Email</a>
      </div>
    </div>
    """, unsafe_allow_html=True)


    # --- Centered Video (pick a frame style by changing the class) ---
    st.markdown("""
    <div class="page-wrap">
      <div class="video-wrap">
        <div class="video-shell style-gradient">
          <video
            width="360"
            autoplay
            muted
            loop
            playsinline
            tabindex="-1"
            oncontextmenu="return false;"
            draggable="false"
            style="pointer-events:none; user-select:none; -webkit-user-select:none; -webkit-touch-callout:none;">
            <source src="https://raw.githubusercontent.com/learngermanghana/a1spreche/main/falowen.mp4" type="video/mp4">
            Sorry, your browser doesn't support embedded videos.
          </video>
        </div>
      </div>
    </div>

    <style>
      /* Layout */
      .video-wrap{
        display:flex; justify-content:center; align-items:center;
        margin: 12px 0 24px;
      }
      .video-shell{
        position:relative; border-radius:16px; padding:4px;
      }
      .video-shell > video{
        display:block; width:min(360px, 92vw); border-radius:12px; margin:0;
        box-shadow: 0 4px 12px rgba(0,0,0,.08);
      }

      /* 1) Soft gradient frame (default) */
      .video-shell.style-gradient{
        background: linear-gradient(135deg,#e8eeff,#f6f9ff);
        box-shadow: 0 8px 24px rgba(0,0,0,.08);
      }

      /* 2) Glow pulse */
      .video-shell.style-glow{
        background:#0b1220;
        box-shadow: 0 0 0 2px #1d4ed8, 0 0 18px #1d4ed8;
        animation: glowPulse 3.8s ease-in-out infinite;
      }
      @keyframes glowPulse{
        0%,100%{ box-shadow:0 0 0 2px #1d4ed8, 0 0 12px #1d4ed8; }
        50%{    box-shadow:0 0 0 2px #06b6d4, 0 0 22px #06b6d4; }
      }

      /* 3) Glassmorphism */
      .video-shell.style-glass{
        background: rgba(255,255,255,.25);
        border: 1px solid rgba(255,255,255,.35);
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
        box-shadow: 0 10px 30px rgba(0,0,0,.10);
      }

      /* 4) Animated dashes */
      .video-shell.style-dash{
        padding:6px; border-radius:18px;
        background:
          repeating-linear-gradient(90deg,#1d4ed8 0 24px,#93c5fd 24px 48px);
        background-size: 48px 100%;
        animation: dashMove 6s linear infinite;
      }
      @keyframes dashMove { to { background-position: 48px 0; } }

      /* 5) Shimmer frame */
      .video-shell.style-shimmer{
        background: linear-gradient(120deg,#e5e7eb, #f8fafc, #e5e7eb);
        background-size: 200% 200%;
        animation: shimmer 6s linear infinite;
        box-shadow: 0 8px 24px rgba(0,0,0,.08);
      }
      @keyframes shimmer{ 0%{background-position:0% 50%;} 100%{background-position:100% 50%;} }

      /* Mobile nudge */
      @media (max-width:600px){
        .video-wrap{ margin: 8px 0 16px; }
      }
    </style>
    """, unsafe_allow_html=True)
    #
#

    # Quick Links
    st.markdown("""
    <div class="page-wrap">
      <div class="quick-links" aria-label="Useful links">
        <a href="https://www.learngermanghana.com/tutors"           target="_blank" rel="noopener">👩‍🏫 Tutors</a>
        <a href="https://www.learngermanghana.com/upcoming-classes" target="_blank" rel="noopener">🗓️ Upcoming Classes</a>
        <a href="https://www.learngermanghana.com/accreditation"    target="_blank" rel="noopener">✅ Accreditation</a>
        <a href="https://www.learngermanghana.com/privacy-policy"   target="_blank" rel="noopener">🔒 Privacy</a>
        <a href="https://www.learngermanghana.com/terms-of-service" target="_blank" rel="noopener">📜 Terms</a>
        <a href="https://www.learngermanghana.com/contact-us"       target="_blank" rel="noopener">✉️ Contact</a>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    LOGIN_IMG_URL      = "https://i.imgur.com/pFQ5BIn.png"
    COURSEBOOK_IMG_URL = "https://i.imgur.com/pqXoqSC.png"
    RESULTS_IMG_URL    = "https://i.imgur.com/uiIPKUT.png"

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""
        <img src="{LOGIN_IMG_URL}" alt="Login screenshot"
             style="width:100%; height:220px; object-fit:cover; border-radius:12px; pointer-events:none; user-select:none;">
        <div style="height:8px;"></div>
        <h3 style="margin:0 0 4px 0;">1️⃣ Sign in</h3>
        <p style="margin:0;">Use your <b>student code or email</b> and start your level (A1–C1).</p>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <img src="{COURSEBOOK_IMG_URL}" alt="Course Book screenshot"
             style="width:100%; height:220px; object-fit:cover; border-radius:12px; pointer-events:none; user-select:none;">
        <div style="height:8px;"></div>
        <h3 style="margin:0 0 4px 0;">2️⃣ Learn & submit</h3>
        <p style="margin:0;">Watch lessons, practice vocab, and <b>submit assignments</b> in the Course Book.</p>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <img src="{RESULTS_IMG_URL}" alt="Results screenshot"
             style="width:100%; height:220px; object-fit:cover; border-radius:12px; pointer-events:none; user-select:none;">
        <div style="height:8px;"></div>
        <h3 style="margin:0 0 4px 0;">3️⃣ Get results</h3>
        <p style="margin:0;">You’ll get an <b>email when marked</b>. Check <b>Results & Resources</b> for feedback.</p>
        """, unsafe_allow_html=True)

    st.markdown("---")

    with st.expander("How do I log in?"):
        st.write("Use your school email **or** Falowen code (e.g., `felixa2`). If you’re new, request access first.")
    with st.expander("Where do I see my scores?"):
        st.write("Scores are emailed to you and live in **Results & Resources** inside the app.")
    with st.expander("How do assignments work?"):
        st.write("Type your answer, confirm, and **submit**. The box locks. Your tutor is notified automatically.")
    with st.expander("What if I open the wrong lesson?"):
        st.write("Check the blue banner at the top (Level • Day • Chapter). Use the dropdown to switch to the correct page.")

    st.markdown("""
    <div class="page-wrap" style="text-align:center; margin:24px 0;">
      <a href="https://www.youtube.com/YourChannel" target="_blank" rel="noopener">📺 YouTube</a>
      &nbsp;|&nbsp;
      <a href="https://api.whatsapp.com/send?phone=233205706589" target="_blank" rel="noopener">📱 WhatsApp</a>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="page-wrap" style="text-align:center;color:#64748b; margin-bottom:16px;">
      © {datetime.utcnow().year} Learn Language Education Academy • Accra, Ghana<br>
      Need help? <a href="mailto:learngermanghana@gmail.com">Email</a> • 
      <a href="https://api.whatsapp.com/send?phone=233205706589" target="_blank" rel="noopener">WhatsApp</a>
    </div>
    """, unsafe_allow_html=True)

    st.stop()


if not st.session_state.get("logged_in", False):
    login_page()

# --- Logged In UI ---
st.write(f"👋 Welcome, **{st.session_state['student_name']}**")

_inject_meta_tags()

if st.button("Log out"):
    try:
        tok = st.session_state.get("session_token", "")
        if tok: destroy_session_token(tok)
    except Exception:
        pass

    try:
        set_student_code_cookie(cookie_manager, "", expires=datetime.utcnow() - timedelta(seconds=1))
        set_session_token_cookie(cookie_manager, "", expires=datetime.utcnow() - timedelta(seconds=1))
    except Exception:
        pass

    try:
        cookie_manager.delete("student_code")
        cookie_manager.delete("session_token")
        cookie_manager.save()
    except Exception:
        pass

    # clear LS + strip OAuth params
    components.html("""
    <script>
      (function(){
        try {
          localStorage.removeItem('student_code');
          localStorage.removeItem('session_token');
          const u = new URL(window.location);
          ['code','state'].forEach(k => u.searchParams.delete(k));
          window.history.replaceState({}, '', u);
          window.location.reload();
        } catch(e){}
      })();
    </script>
    """, height=0)

    for k, v in {
        "logged_in": False,
        "student_row": None,
        "student_code": "",
        "student_name": "",
        "session_token": "",
        "cookie_synced": False,
        "__last_refresh": 0.0,
        "__ua_hash": "",
        "_oauth_state": "",
        "_oauth_code_redeemed": "",
    }.items():
        st.session_state[k] = v

    st.stop()
