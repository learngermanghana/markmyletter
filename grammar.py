# ==== Standard Library ====
import atexit, base64, difflib, hashlib
import html as html_stdlib
import io, json, os, random, math, re, sqlite3, tempfile, time
import urllib.parse as _urllib
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

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

# PWA + iOS head tags (served from /static) — now safely after set_page_config
components.html("""
<link rel="manifest" href="/static/manifest.webmanifest">
<link rel="apple-touch-icon" href="/static/icons/falowen-180.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Falowen">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="theme-color" content="#000000">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
""", height=0)

# --- Compatibility alias ---
html = st_html

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
        "__ls_token": "",
        "_oauth_state": "",
        "_oauth_code_redeemed": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
_bootstrap_state()

# --- SEO (only on public/landing) ---
if not st.session_state.get("logged_in", False):
    html("""
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

# ==== Hide Streamlit chrome ====
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ==== FIREBASE ADMIN INIT & SESSION STORE ====
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
# Enable a TTL policy on `expires_at` in Firebase Console for auto-cleanup.
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

# ==== YOUTUBE PLAYLIST HELPERS ====

# Prefer secrets for keys; fallback to existing value
YOUTUBE_API_KEY = st.secrets.get("YOUTUBE_API_KEY", "AIzaSyBA3nJi6dh6-rmOLkA4Bb0d7h0tLAp7xE4")

YOUTUBE_PLAYLIST_IDS = {
    "A1": [
        "PL5vnwpT4NVTdwFarD9kwm1HONsqQ11l-b",
    ],
    "A2": [
        "PLs7zUO7VPyJ7YxTq_g2Rcl3Jthd5bpTdY",
        "PLquImyRfMt6dVHL4MxFXMILrFh86H_HAc",
        "PLs7zUO7VPyJ5Eg0NOtF9g-RhqA25v385c",
    ],
    "B1": [
        "PLs7zUO7VPyJ5razSfhOUVbTv9q6SAuPx-",
        "PLB92CD6B288E5DB61",
    ],
    "B2": [
        "PLs7zUO7VPyJ5XMfT7pLvweRx6kHVgP_9C",
        "PLs7zUO7VPyJ6jZP-s6dlkINuEjFPvKMG0",
        "PLs7zUO7VPyJ4SMosRdB-35Q07brhnVToY",
    ],
}

@st.cache_data(ttl=43200)
def fetch_youtube_playlist_videos(playlist_id, api_key=YOUTUBE_API_KEY):
    base_url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": 50,
        "key": api_key,
    }
    videos, next_page = [], ""
    while True:
        if next_page:
            params["pageToken"] = next_page
        response = requests.get(base_url, params=params, timeout=12)
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


# ================================================
# STUDENT SHEET LOADING & SESSION SETUP (with Firebase silent restore)
# ================================================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/gviz/tq?tqx=out:csv&sheet=Sheet1"

@st.cache_data(ttl=300)  # refresh every 5 minutes
def load_student_data():
    try:
        resp = requests.get(GOOGLE_SHEET_CSV, timeout=10)
        resp.raise_for_status()
        df = pd.read_csv(
            io.StringIO(resp.text),
            dtype=str,
            keep_default_na=True,
            na_values=["", " ", "nan", "NaN", "None"]
        )
    except Exception:
        st.error("❌ Could not load student data.")
        st.stop()

    # Normalize headers and trim cells while preserving NaN
    df.columns = df.columns.str.strip().str.replace(" ", "")
    for col in df.columns:
        s = df[col]
        df[col] = s.where(s.isna(), s.str.strip())

    # Keep only rows with a ContractEnd value
    df = df[df["ContractEnd"].notna() & (df["ContractEnd"].str.len() > 0)]

    # Robust parse (MM/DD/YYYY, DD/MM/YYYY, ISO, fallback)
    def _parse_contract_end(s: str):
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return pd.to_datetime(s, format=fmt, errors="raise")
            except Exception:
                continue
        return pd.to_datetime(s, errors="coerce")

    df["ContractEnd_dt"] = df["ContractEnd"].apply(_parse_contract_end)
    df = df[df["ContractEnd_dt"].notna()]

    # Normalize identifiers for later lookups
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
            expiry_date = datetime.strptime(expiry_str, fmt)
            break
        except ValueError:
            continue

    if expiry_date is None:
        parsed = pd.to_datetime(expiry_str, errors="coerce")
        if pd.isnull(parsed):
            return True
        expiry_date = parsed.to_pydatetime()

    # Use UTC date to avoid local skew/DST issues
    today = datetime.utcnow().date()
    return expiry_date.date() < today


# ============================================================
# 0) Cookie + localStorage “SSO” (+ UA/LS bridge & token-first restore)
# ============================================================

from typing import Optional  # ensure available if you were using 3.9

def _expire_str(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

def _js_set_cookie(name: str, value: str, max_age_sec: int, expires_gmt: str, secure: bool, domain: Optional[str] = None):
    """
    Returns JS code to set a cookie. If 'domain' is the name of a JS variable (e.g., 'base'),
    pass it as that identifier string and we'll emit it as a JS variable (not a quoted literal).
    """
    base = (
        f'var c = {json.dumps(name)} + "=" + {json.dumps(_urllib.quote(value))} + '
        f'"; Path=/; Max-Age={max_age_sec}; Expires={json.dumps(expires_gmt)}; SameSite=Lax";\n'
        f'if ({str(bool(secure)).lower()}) c += "; Secure";\n'
    )
    if domain:
        # 'domain' is intended to be a JS variable identifier, not a string literal
        base += f'c += "; Domain=" + {domain};\n'
    base += "document.cookie = c;\n"
    return base

def set_student_code_cookie(cookie_manager, value: str, expires: datetime):
    """
    iOS/Safari friendly: set both host-only and base-domain cookies for student_code.
    Also mirrors to localStorage.
    """
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
            cookie_manager[key] = norm
            cookie_manager.save()
        except Exception:
            pass

    # JS cookies: host-only AND base-domain (e.g., .falowen.app)
    host_cookie_name = (getattr(cookie_manager, 'prefix', '') or '') + key
    host_js = _js_set_cookie(host_cookie_name, norm, max_age, exp_str, use_secure, domain=None)
    script = f"""
    <script>
      (function(){{
        try {{
          {host_js}
          try {{
            var h = window.location.hostname.split('.');
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
    """
    Mirror the Firestore session token in cookies (host-only + base-domain) and localStorage.
    """
    key = "session_token"
    val = (token or "").strip()
    use_secure = (os.getenv("ENV", "prod") != "dev")
    max_age = 60 * 60 * 24 * 30  # 30 days (Firestore TTL still authoritative)
    exp_str = _expire_str(expires)

    # Library cookie (host-only)
    try:
        cookie_manager.set(key, val, expires=expires, secure=use_secure, samesite="Lax", path="/")
        cookie_manager.save()
    except Exception:
        try:
            cookie_manager[key] = val
            cookie_manager.save()
        except Exception:
            pass

    # JS cookies: host-only + base-domain
    host_cookie_name = (getattr(cookie_manager, 'prefix', '') or '') + key
    host_js = _js_set_cookie(host_cookie_name, val, max_age, exp_str, use_secure, domain=None)
    script = f"""
    <script>
      (function(){{
        try {{
          {host_js}
          try {{
            var h = window.location.hostname.split('.');
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

# 0a) UA/LS query-parameter bridge (no postMessage)
components.html("""
<script>
 (function(){
   async function sha256Hex(s){
     const enc = new TextEncoder(); const data = enc.encode(s);
     const buf = await crypto.subtle.digest('SHA-256', data);
     return Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('');
   }
   (async function(){
     try{
       const ua = navigator.userAgent||''; const lang = navigator.language||'';
       const h  = await sha256Hex(ua + '|' + lang);
       const ls = localStorage.getItem('session_token')||'';
       const url = new URL(window.location);
       let mut = false;
       if (!url.searchParams.get('ua')) { url.searchParams.set('ua', h); mut = true; }
       if (ls && !url.searchParams.get('ls')) { url.searchParams.set('ls', ls); mut = true; }
       if (mut) window.location.replace(url.toString());
     }catch(e){}
   })();
 })();
</script>
""", height=0)

# 0a.5) Firebase Web SDK + silent restore -> ?ftok=
components.html(f"""
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-auth-compat.js"></script>
<script>
(function(){{
  try {{
    var cfg = {{
      apiKey: {json.dumps(st.secrets.get("FIREBASE_WEB_API_KEY",""))},
      authDomain: {json.dumps(st.secrets.get("FIREBASE_AUTH_DOMAIN",""))},
      projectId: {json.dumps(st.secrets.get("FIREBASE_PROJECT_ID",""))}
    }};
    if (!window.firebase) return;
    if (!firebase.apps || !firebase.apps.length) {{ firebase.initializeApp(cfg); }}
    var lastSent = "";
    firebase.auth().onAuthStateChanged(function(user){{
      try {{
        if (!user) return;
        user.getIdToken(false).then(function(idt){{
          try {{
            if (!idt || idt === lastSent) return;
            lastSent = idt;
            var url = new URL(window.location);
            if (url.searchParams.get('ftok') === idt) return;
            url.searchParams.set('ftok', idt);
            window.location.replace(url.toString());
          }} catch(e) {{}}
        }}).catch(function(){{}});
      }} catch(e) {{}}
    }});
  }} catch(e) {{}}
}})();
</script>
""", height=0)

# 0b) Query param helpers
def qp_get():
    try:
        return st.query_params
    except Exception:
        return st.experimental_get_query_params()

def qp_clear():
    try:
        st.query_params.clear()
    except Exception:
        try:
            st.experimental_set_query_params()
        except Exception:
            pass

def qp_clear_keys(*keys):
    try:
        qp = st.query_params
        for k in keys:
            if k in qp:
                del qp[k]
    except Exception:
        try:
            st.experimental_set_query_params(**{k: [] for k in keys})
        except Exception:
            pass
    # scrub in browser history
    components.html("""
    <script>
      (function(){
        try{
          const u = new URL(window.location);
          %s
          window.history.replaceState({}, '', u);
        }catch(e){}
      })();
    </script>
    """ % "\n".join([f"if(u.searchParams.has('{k}')) u.searchParams.delete('{k}');" for k in keys]), height=0)

# 0c) Ingest UA/LS bridge into session_state then scrub
def _ingest_ua_ls_from_query():
    qp = qp_get()
    def _get1(k):
        v = qp.get(k)
        if isinstance(v, list): v = v[0]
        return (v or "").strip()
    ua = _get1("ua")
    ls = _get1("ls")
    changed = False
    if ua and ua != st.session_state.get("__ua_hash"): st.session_state["__ua_hash"] = ua; changed = True
    if ls and ls != st.session_state.get("__ls_token"): st.session_state["__ls_token"] = ls; changed = True
    if ua or ls:
        qp_clear_keys("ua", "ls")
    return changed
_ingest_ua_ls_from_query()

# Defensive scrub in case a shared link includes bridge params
qp_clear_keys("t", "ua", "ls")

# 0d) Init cookie manager once
COOKIE_SECRET = os.getenv("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET")
if not COOKIE_SECRET:
    st.error("Cookie secret missing. Add COOKIE_SECRET to your Streamlit secrets.")
    st.stop()
cookie_manager = EncryptedCookieManager(prefix="falowen_", password=COOKIE_SECRET)
if not cookie_manager.ready():
    st.warning("Cookies not ready; please refresh.")
    st.stop()

# NEW: verify ?ftok=<Firebase ID token> and re-mint Firestore session (AFTER cookie_manager exists)
def handle_firebase_ftok():
    ftok = qp_get().get("ftok")
    if isinstance(ftok, list):
        ftok = ftok[0]
    ftok = (ftok or "").strip()
    if not ftok:
        return False

    try:
        from firebase_admin import auth as fb_auth
        # If you want revocation checks, use: verify_id_token(ftok, check_revoked=True)
        decoded = fb_auth.verify_id_token(ftok)
        email = (decoded.get("email") or "").lower().strip()
        if not email:
            qp_clear_keys("ftok")
            return False

        df = load_student_data()
        df["Email"] = df["Email"].str.lower().str.strip()
        match = df[df["Email"] == email]
        if match.empty:
            qp_clear_keys("ftok")
            return False

        row = match.iloc[0]
        if is_contract_expired(row):
            qp_clear_keys("ftok")
            return False

        ua_hash = st.session_state.get("__ua_hash", "")
        sess_token = create_session_token(row["StudentCode"], row["Name"], ua_hash=ua_hash)

        st.session_state.update({
            "logged_in": True,
            "student_row": row.to_dict(),
            "student_code": row["StudentCode"],
            "student_name": row["Name"],
            "session_token": sess_token,
        })

        # Persist both cookies + localStorage now that cookie_manager exists
        set_student_code_cookie(cookie_manager, row["StudentCode"], expires=datetime.utcnow() + timedelta(days=180))
        set_session_token_cookie(cookie_manager, sess_token, expires=datetime.utcnow() + timedelta(days=30))
        components.html(f"""
        <script>
          try {{
            localStorage.setItem('student_code', {json.dumps(row["StudentCode"])});
            localStorage.setItem('session_token', {json.dumps(sess_token)});
          }} catch(e) {{}}
        </script>
        """, height=0)

        qp_clear_keys("ftok")
        st.rerun()
        return True
    except Exception:
        qp_clear_keys("ftok")
        return False

# Run the silent-restore handler early (but AFTER cookie_manager init)
handle_firebase_ftok()

# 0e) Handshake: set cookie from ?student_code=, then only clear the param after we confirm cookie exists
params = qp_get()
sc_param = params.get("student_code")
if isinstance(sc_param, list):
    sc_param = sc_param[0]
sc_param = (sc_param or "").strip().lower()

if sc_param:
    if not st.session_state.get("__cookie_attempt"):
        st.session_state["__cookie_attempt"] = sc_param
        set_student_code_cookie(cookie_manager, sc_param, expires=datetime.utcnow() + timedelta(days=180))
        st.rerun()
    else:
        attempted = st.session_state.get("__cookie_attempt", "")
        have = (cookie_manager.get("student_code") or "").strip().lower()
        if have == attempted:
            qp_clear_keys("student_code")
            st.session_state.pop("__cookie_attempt", None)
else:
    st.session_state.pop("__cookie_attempt", None)

# 0f) Restore login (PREFER SERVER TOKEN), else fallback to student_code
def _get_token_candidates():
    qp = qp_get()
    t = qp.get("t")
    if isinstance(t, list): t = t[0]
    t = (t or "").strip()
    ls = (st.session_state.get("__ls_token") or "").strip()
    mem = (st.session_state.get("session_token") or "").strip()
    cookie_tok = (cookie_manager.get("session_token") or "").strip()  # NEW: cookie token
    out = [x for x in [mem, t, ls, cookie_tok] if x]
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            uniq.append(x); seen.add(x)
    return uniq

restored = False
if not st.session_state.get("logged_in", False):
    for tok in _get_token_candidates():
        data = validate_session_token(tok, st.session_state.get("__ua_hash", ""))
        if not data:
            continue
        # Roster/contract guard
        try:
            df_students = load_student_data()
            found = df_students[df_students["StudentCode"] == data.get("student_code","")]
        except Exception:
            found = pd.DataFrame()
        if found.empty or is_contract_expired(found.iloc[0]):
            continue

        row = found.iloc[0]
        st.session_state.update({
            "logged_in": True,
            "student_row": row.to_dict(),
            "student_code": row["StudentCode"],
            "student_name": row["Name"],
            "session_token": tok,
        })
        # Refresh/rotate; persist new token client-side; scrub ?t=
        new_tok = refresh_or_rotate_session_token(tok) or tok
        st.session_state["session_token"] = new_tok

        # Persist to LS and cookies
        components.html(f"""
        <script>
          try {{
            localStorage.setItem('session_token', {json.dumps(new_tok)});
            const u = new URL(window.location);
            if (u.searchParams.has('t')) {{ u.searchParams.delete('t'); window.history.replaceState({{}}, '', u); }}
          }} catch(e) {{}}
        </script>
        """, height=0)
        set_session_token_cookie(cookie_manager, new_tok, expires=datetime.utcnow() + timedelta(days=30))  # NEW
        restored = True
        break

# Fallback: original cookie/param login using student_code (no password)
if (not restored) and (not st.session_state.get("logged_in", False)):
    code_cookie = (cookie_manager.get("student_code") or "").strip().lower()
    effective_code = code_cookie or sc_param

    if effective_code:
        try:
            df_students = load_student_data()
            found = df_students[df_students["StudentCode"].str.lower().str.strip() == effective_code]
        except Exception:
            found = pd.DataFrame()

        if not found.empty:
            student_row = found.iloc[0]
            if not is_contract_expired(student_row):
                st.session_state.update({
                    "logged_in": True,
                    "student_row": student_row.to_dict(),
                    "student_code": student_row["StudentCode"],
                    "student_name": student_row["Name"]
                })
            else:
                # Expired: clear cookie + localStorage to avoid loops
                set_student_code_cookie(cookie_manager, "", expires=datetime.utcnow() - timedelta(seconds=1))
                components.html("<script>try{localStorage.removeItem('student_code');}catch(e){}</script>", height=0)

# --- Helper: persist login to cookie + localStorage (kept for back-compat) ----
def save_cookie_after_login(student_code: str) -> None:
    value = str(student_code or "").strip().lower()
    try:
        _cm  = globals().get("cookie_manager")
        _set = globals().get("set_student_code_cookie")
        if _cm and _set:
            _set(_cm, value, expires=datetime.utcnow() + timedelta(days=180))
    except Exception:
        pass
    components.html(
        """
        <script>
          try { localStorage.setItem('student_code', __VAL__); } catch (e) {}
        </script>
        """.replace("__VAL__", json.dumps(value)),
        height=0
    )

# --- NEW: persist session token client-side + scrub URL params -----------------
def _persist_session_client(token: str, student_code: str = "") -> None:
    components.html(f"""
    <script>
      try {{
        localStorage.setItem('session_token', {json.dumps(token)});
        if ({json.dumps(student_code)} !== "") {{
          localStorage.setItem('student_code', {json.dumps(student_code)});
        }}
        const u = new URL(window.location);
        ['t','ua','ls'].forEach(k => u.searchParams.delete(k));
        window.history.replaceState({{}}, '', u);
      }} catch(e) {{}}
    </script>
    """, height=0)

# --- Keep-alive to keep iOS storage fresh + let server extend TTL --------------
components.html("""
<script>
  (function(){
    try {
      let last=0;
      function ping(){
        const now = Date.now();
        if (document.hidden) return;
        if (now - last < 4*60*1000) return; // every ~4min
        last = now;
        try { localStorage.setItem('falowen_alive', String(now)); } catch(e){}
        try {
          const u = new URL(window.location);
          u.hash = 'alive' + now;
          history.replaceState({}, '', u);
        } catch(e){}
      }
      document.addEventListener('visibilitychange', ping, {passive:true});
      setInterval(ping, 60*1000);
      ping();
    } catch(e){}
  })();
</script>
""", height=0)

# --- Early client-side restore gate (no infinite "restoring" state) ---
has_cookie_tok = bool((cookie_manager.get("session_token") or "").strip())

if (not st.session_state.get("logged_in", False)) and (not has_cookie_tok):
    # If Safari nuked cookies but LS still has the token, bounce it into the URL (?ls=...)
    components.html(
        """
        <script>
          (function(){
            try {
              var tok = localStorage.getItem('session_token') || '';
              if (tok) {
                var u = new URL(window.location);
                if (!u.searchParams.get('t') && !u.searchParams.get('ls') && !u.searchParams.get('ftok')) {
                  u.searchParams.set('ls', tok);
                  window.location.replace(u.toString());
                }
              }
            } catch (e) {}
          })();
        </script>
        """,
        height=0
    )
    # NOTE: no st.stop() here — if there's no LS token, we just render the normal homepage.



# --- 2) Global CSS (higher contrast + focus states) ----------------------------
st.markdown("""
<style>
  .hero {
    background: #fff;
    border-radius: 12px;
    padding: 24px;
    margin: 24px auto;
    max-width: 800px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.05);
  }
  .help-contact-box {
    background: #fff;
    border-radius: 14px;
    padding: 20px;
    margin: 16px auto;
    max-width: 500px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.04);
    border:1px solid #ebebf2; text-align:center;
  }
  .quick-links { display: flex; flex-wrap: wrap; gap:12px; justify-content:center; }
  .quick-links a {
    background: #e2e8f0;
    padding: 8px 16px;
    border-radius: 8px;
    font-weight:600;
    text-decoration:none;
    color:#0f172a;
    border:1px solid #cbd5e1;
  }
  .quick-links a:hover { background:#cbd5e1; }

  .stButton > button {
    background:#2563eb;
    color:#ffffff;
    font-weight:700;
    border-radius:8px;
    border:2px solid #1d4ed8;
  }
  .stButton > button:hover { background:#1d4ed8; }

  a:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible,
  [role="button"]:focus-visible {
    outline:3px solid #f59e0b;
    outline-offset:2px;
    box-shadow:none !important;
  }

  input, textarea { color:#0f172a !important; }

  @media (max-width:600px){
    .hero, .help-contact-box { padding:16px 4vw; }
  }
</style>
""", unsafe_allow_html=True)


# --- 3) Public Homepage --------------------------------------------------------
if not st.session_state.get("logged_in", False):

    st.markdown("""
    <style>.page-wrap { max-width: 1100px; margin: 0 auto; }</style>
    """, unsafe_allow_html=True)

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

    # --- Google OAuth (Optional) ---
    GOOGLE_CLIENT_ID     = st.secrets.get("GOOGLE_CLIENT_ID", "180240695202-3v682khdfarmq9io9mp0169skl79hr8c.apps.googleusercontent.com")
    GOOGLE_CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "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")
    REDIRECT_URI         = st.secrets.get("GOOGLE_REDIRECT_URI", "https://www.falowen.app/")

    def _qp_first(val):
        if isinstance(val, list): return val[0]
        return val

    def do_google_oauth():
        import secrets, urllib.parse
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
            unsafe_allow_html=True
        )

    def handle_google_login():
        qp = qp_get()
        code  = _qp_first(qp.get("code")) if hasattr(qp, "get") else None
        state = _qp_first(qp.get("state")) if hasattr(qp, "get") else None
        if not code: return False
        if st.session_state.get("_oauth_state") and state != st.session_state["_oauth_state"]:
            st.error("OAuth state mismatch. Please try again."); return False
        if st.session_state.get("_oauth_code_redeemed") == code:
            return False

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
                st.error(f"Google login failed: {resp.status_code} {resp.text}"); return False
            tokens = resp.json()
            access_token = tokens.get("access_token")
            if not access_token:
                st.error("Google login failed: no access token."); return False
            st.session_state["_oauth_code_redeemed"] = code

            userinfo = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            ).json()
            email = (userinfo.get("email") or "").lower().strip()
            if not email:
                st.error("Google login failed: no email returned."); return False

            df = load_student_data()
            df["Email"] = df["Email"].str.lower().str.strip()
            match = df[df["Email"] == email]
            if match.empty:
                st.error("No student account found for that Google email."); return False

            student_row = match.iloc[0]
            if is_contract_expired(student_row):
                st.error("Your contract has expired. Contact the office."); return False

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
        return False

    if handle_google_login():
        st.stop()

     # Tabs: Returning / Sign Up (Approved) / Request Access
    tab1, tab2, tab3 = st.tabs(["👋 Returning", "🧾 Sign Up (Approved)", "📝 Request Access"])

    # --- Returning ---
    with tab1:
        do_google_oauth()
        st.markdown("<div class='page-wrap' style='text-align:center; margin:8px 0;'>⎯⎯⎯ or ⎯⎯⎯</div>", unsafe_allow_html=True)
        with st.form("login_form", clear_on_submit=False):
            login_id_input   = st.text_input("Student Code or Email", help="Use your school email or Falowen code (e.g., felixa2).")
            login_pass_input = st.text_input("Password", type="password")
            login_btn        = st.form_submit_button("Log In")

        if login_btn:
            login_id   = (login_id_input or "").strip().lower()
            login_pass = (login_pass_input or "")
            df = load_student_data()
            df["StudentCode"] = df["StudentCode"].str.lower().str.strip()
            df["Email"]       = df["Email"].str.lower().str.strip()
            lookup = df[(df["StudentCode"] == login_id) | (df["Email"] == login_id)]

            if lookup.empty:
                st.error("No matching student code or email found.")
            else:
                student_row = lookup.iloc[0]
                if is_contract_expired(student_row):
                    st.error("Your contract has expired. Contact the office.")
                else:
                    doc_ref = db.collection("students").document(student_row["StudentCode"])
                    doc     = doc_ref.get()
                    if not doc.exists:
                        st.error("Account not found. Please use 'Sign Up (Approved)' first.")
                    else:
                        data      = doc.to_dict() or {}
                        stored_pw = data.get("password", "")

                        def _is_bcrypt_hash(s: str) -> bool:
                            return isinstance(s, str) and s.startswith(("$2a$", "$2b$", "$2y$")) and len(s) >= 60

                        ok = False
                        try:
                            if _is_bcrypt_hash(stored_pw):
                                ok = bcrypt.checkpw(login_pass.encode("utf-8"), stored_pw.encode("utf-8"))
                            else:
                                ok = (stored_pw == login_pass)
                                if ok:
                                    new_hash = bcrypt.hashpw(login_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                                    doc_ref.update({"password": new_hash})
                        except Exception:
                            ok = False

                        if not ok:
                            st.error("Incorrect password.")
                        else:
                            ua_hash = st.session_state.get("__ua_hash", "")
                            sess_token = create_session_token(student_row["StudentCode"], student_row["Name"], ua_hash=ua_hash)

                            st.session_state.update({
                                "logged_in":   True,
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

    # --- Sign Up (Approved students — already on roster, no account yet) ---
    with tab2:
        with st.form("signup_form", clear_on_submit=False):
            new_name_input     = st.text_input("Full Name", key="ca_name")
            new_email_input    = st.text_input("Email (must match teacher’s record)", help="Use the school email your tutor added to the roster.", key="ca_email")
            new_code_input     = st.text_input("Student Code (from teacher)", help="Example: felixa2", key="ca_code")
            new_password_input = st.text_input("Choose a Password", type="password", key="ca_pass")
            signup_btn         = st.form_submit_button("Create Account")

        if signup_btn:
            new_name     = (new_name_input or "").strip()
            new_email    = (new_email_input or "").strip().lower()
            new_code     = (new_code_input or "").strip().lower()
            new_password = (new_password_input or "")

            if not (new_name and new_email and new_code and new_password):
                st.error("Please fill in all fields.")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                df = load_student_data()
                df["StudentCode"] = df["StudentCode"].str.lower().str.strip()
                df["Email"]       = df["Email"].str.lower().str.strip()
                valid = df[(df["StudentCode"] == new_code) & (df["Email"] == new_email)]
                if valid.empty:
                    st.error("Your code/email aren’t registered. Use 'Request Access' first.")
                else:
                    doc_ref = db.collection("students").document(new_code)
                    if doc_ref.get().exists:
                        st.error("An account with this student code already exists. Please log in instead.")
                    else:
                        hashed_pw = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                        doc_ref.set({"name": new_name, "email": new_email, "password": hashed_pw})
                        st.success("Account created! Please log in on the Returning tab.")

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
#


    # --- Autoplay Video Demo (insert before Quick Links/footer) ---
    st.markdown("""
    <div style="display:flex; justify-content:center; margin: 24px 0;">
      <video width="350" autoplay muted loop controls style="border-radius: 12px; box-shadow: 0 4px 12px #0002;">
        <source src="https://raw.githubusercontent.com/learngermanghana/a1spreche/main/falowen.mp4" type="video/mp4">
        Sorry, your browser doesn't support embedded videos.
      </video>
    </div>
    """, unsafe_allow_html=True)

    # Quick Links (high-contrast)
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


# --- Logged In UI ---
st.write(f"👋 Welcome, **{st.session_state['student_name']}**")

if st.button("Log out"):
    try:
        tok = st.session_state.get("session_token", "")
        if tok:
            destroy_session_token(tok)
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

    _prefix = getattr(cookie_manager, "prefix", "") or ""
    _cookie_name_code = f"{_prefix}student_code"
    _cookie_name_tok  = f"{_prefix}session_token"
    _secure_js = "true" if (os.getenv("ENV", "prod") != "dev") else "false"

    components.html(f"""
    <script>
      (function() {{
        try {{
          try {{
            localStorage.removeItem('student_code');
            localStorage.removeItem('session_token');
          }} catch (e) {{}}

          const url = new URL(window.location);
          ['student_code','t','ua','ls','ftok'].forEach(k => url.searchParams.delete(k));
          window.history.replaceState({{}}, '', url);

          const isSecure = {_secure_js};
          const past = "Thu, 01 Jan 1970 00:00:00 GMT";
          const names = [{json.dumps(_cookie_name_code)}, {json.dumps(_cookie_name_tok)}];

          function expireCookie(name, domain) {{
            var s = name + "=; Expires=" + past + "; Path=/; SameSite=Lax";
            if (isSecure) s += "; Secure";
            if (domain) s += "; Domain=" + domain;
            document.cookie = s;
          }}

          names.forEach(n => expireCookie(n));

          const host  = window.location.hostname;
          const parts = host.split('.');
          if (parts.length >= 2) {{
            const base = '.' + parts.slice(-2).join('.');
            names.forEach(n => expireCookie(n, base));
          }}

          window.location.replace(url.pathname + url.search);
        }} catch (e) {{}}
      }})();
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
        "__ls_token": "",
    }.items():
        st.session_state[k] = v

    try:
        qp_clear()
    except Exception:
        pass

    st.stop()

