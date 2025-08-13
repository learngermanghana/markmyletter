# minimal_login.py — drop into a fresh Streamlit file and run: streamlit run minimal_login.py
import io
from datetime import datetime
import requests
import pandas as pd
import bcrypt
import streamlit as st

# --- Optional Firestore (for passwords) ---
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except Exception:
    firebase_admin = None
    firestore = None

# ===== Config =====
ROSTER_CSV = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/gviz/tq?tqx=out:csv&sheet=Sheet1"

# ===== Firestore init (optional) =====
def get_db():
    if not firebase_admin or not firestore:
        return None
    try:
        if not firebase_admin._apps:
            # expects a service account in secrets: FIREBASE_SERVICE_ACCOUNT
            sa = st.secrets.get("FIREBASE_SERVICE_ACCOUNT", None)
            if sa:
                cred = credentials.Certificate(sa)
                firebase_admin.initialize_app(cred)
            else:
                return None
        return firestore.client()
    except Exception:
        return None

DB = get_db()

# ===== Helpers =====
@st.cache_data(ttl=300)
def load_roster():
    """Load and normalize the student roster from Google Sheet."""
    r = requests.get(ROSTER_CSV, timeout=10)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), dtype=str)
    df.columns = df.columns.str.strip().str.replace(" ", "")
    for c in ("StudentCode","Email","Name","ContractEnd"):
        if c not in df.columns:
            df[c] = ""
    # normalize
    df["StudentCode"] = df["StudentCode"].fillna("").str.strip().str.lower()
    df["Email"]       = df["Email"].fillna("").str.strip().str.lower()
    df["Name"]        = df["Name"].fillna("").str.strip()
    df["ContractEnd"] = df["ContractEnd"].fillna("").str.strip()
    # latest per student
    def _parse(d):
        for fmt in ("%m/%d/%Y","%d/%m/%Y","%Y-%m-%d"):
            try:
                return datetime.strptime(d, fmt)
            except Exception:
                pass
        try:
            return pd.to_datetime(d, errors="coerce").to_pydatetime()
        except Exception:
            return None
    df["__dt"] = df["ContractEnd"].apply(_parse)
    df = df[df["__dt"].notna()].sort_values("__dt", ascending=False).drop_duplicates("StudentCode")
    return df.drop(columns="__dt")

def contract_expired(contract_end: str) -> bool:
    if not contract_end:
        return True
    for fmt in ("%m/%d/%Y","%d/%m/%Y","%Y-%m-%d"):
        try:
            dt = datetime.strptime(contract_end, fmt)
            return dt.date() < datetime.utcnow().date()
        except Exception:
            continue
    try:
        dt = pd.to_datetime(contract_end, errors="coerce")
        return pd.isna(dt) or dt.date() < pd.Timestamp.utcnow().date()
    except Exception:
        return True

def check_password(student_code: str, email: str, password: str):
    """
    Returns (ok, student_row_dict or None, message).
    Password is verified against Firestore students/{code}.password (bcrypt or plain).
    """
    df = load_roster()
    code = student_code.strip().lower()
    mail = email.strip().lower()

    row = None
    if code:
        m = df[df["StudentCode"] == code]
        if not m.empty:
            row = m.iloc[0]
    if row is None and mail:
        m = df[df["Email"] == mail]
        if not m.empty:
            row = m.iloc[0]

    if row is None:
        return False, None, "No matching student code or email."

    if contract_expired(row["ContractEnd"]):
        return False, None, "Your contract has expired. Contact the office."

    # Firestore password check
    if DB:
        try:
            doc = DB.collection("students").document(row["StudentCode"]).get()
            if not doc.exists:
                return False, None, "Account not found. Ask your tutor to create it."
            stored = (doc.to_dict() or {}).get("password", "")
            def is_bcrypt(s): return isinstance(s, str) and s.startswith(("$2a$","$2b$","$2y$")) and len(s) >= 60
            ok = False
            if is_bcrypt(stored):
                ok = bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
            else:
                ok = (stored == password)
            if not ok:
                return False, None, "Incorrect password."
            return True, dict(row), "Welcome!"
        except Exception as e:
            return False, None, f"Login error: {e}"

    # Fallback demo (when Firestore not configured)
    if (code == "demo" or mail == "demo") and password == "demo123":
        return True, {"StudentCode":"demo","Name":"Demo User"}, "Welcome (demo mode)!"
    return False, None, "Firestore not configured; use demo / demo123 to try."

# ===== UI =====
st.set_page_config(page_title="Minimal Login", page_icon="🔐", layout="centered")

st.title("🔐 Minimal Login (no URL/cookies)")
st.caption("Checks your Google Sheet for the student and Firestore for the password. No URL tricks, no cookies.")

# Logged-in view
if st.session_state.get("logged_in"):
    st.success(f"Welcome, {st.session_state.get('student_name','Student')}!")
    st.write(f"Student Code: `{st.session_state.get('student_code','')}`")
    if st.button("Log out"):
        for k in ("logged_in","student_name","student_code"):
            st.session_state.pop(k, None)
        st.experimental_rerun()
else:
    with st.form("login", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            login_code = st.text_input("Student Code (or leave empty)", placeholder="e.g., felixa2")
        with col2:
            login_email = st.text_input("Email (or leave empty)", placeholder="name@school.com")
        login_pass = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        ok, row, msg = check_password(login_code, login_email, login_pass)
        if ok:
            st.session_state["logged_in"]   = True
            st.session_state["student_code"] = row.get("StudentCode","")
            st.session_state["student_name"] = row.get("Name","")
            st.success(msg)
            st.experimental_rerun()
        else:
            st.error(msg)

st.divider()
st.markdown(
    "Test quickly without Firestore by logging in with **demo / demo123**. "
    "To use real passwords, add your service account JSON to `st.secrets['FIREBASE_SERVICE_ACCOUNT']` "
    "and ensure documents exist at `students/{StudentCode}` with field `password`."
)
