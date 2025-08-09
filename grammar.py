# ==== Standard Library ====
import atexit
import base64
import bcrypt
import difflib
import io
import json
import os
import random
import re
import sqlite3
import tempfile
import time
import urllib.parse
from datetime import date, datetime, timedelta

# ==== Third-Party Packages ====
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
from streamlit.components.v1 import html
from streamlit_cookies_manager import EncryptedCookieManager
from streamlit_quill import st_quill


# --- SEO: head tags (only on public/landing) ---
if not st.session_state.get("logged_in", False):
    html("""
    <script>
      // Page <title>
      document.title = "Falowen – Learn German with Learn Language Education Academy";

      // Meta description
      const desc = "Falowen is the German learning companion from Learn Language Education Academy. Join live classes or self-study with A1–C1 courses, recorded lectures, and real progress tracking.";
      let m = document.querySelector('meta[name="description"]');
      if (!m) {
        m = document.createElement('meta');
        m.name = "description";
        document.head.appendChild(m);
      }
      m.setAttribute("content", desc);

      // Canonical
      const canonicalHref = window.location.origin + "/";
      let link = document.querySelector('link[rel="canonical"]');
      if (!link) {
        link = document.createElement('link');
        link.rel = "canonical";
        document.head.appendChild(link);
      }
      link.href = canonicalHref;

      // Open Graph (helps WhatsApp/FB previews)
      function setOG(p, v){ let t=document.querySelector(`meta[property="${p}"]`);
        if(!t){ t=document.createElement('meta'); t.setAttribute('property', p); document.head.appendChild(t); }
        t.setAttribute('content', v);
      }
      setOG("og:title", "Falowen – Learn German with Learn Language Education Academy");
      setOG("og:description", desc);
      setOG("og:type", "website");
      setOG("og:url", canonicalHref);

      // JSON-LD
      const ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Falowen",
        "alternateName": "Falowen by Learn Language Education Academy",
        "url": canonicalHref
      };
      const s = document.createElement('script');
      s.type = "application/ld+json";
      s.text = JSON.stringify(ld);
      document.head.appendChild(s);
    </script>
    """, height=0)

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
    cred_dict = dict(st.secrets["firebase"])
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ---- Google OAuth config (env -> secrets -> hardcoded) ----
def _get_secret(key: str, default: str | None = None) -> str | None:
    v = os.getenv(key)
    if v: return v
    try:
        v = st.secrets.get(key, None)
    except Exception:
        v = None
    return v or default

GOOGLE_CLIENT_ID = _get_secret("GOOGLE_CLIENT_ID", "123-your-client-id.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = _get_secret("GOOGLE_CLIENT_SECRET", "your-google-client-secret")

# Hardcoded redirect to your domain (must EXACTLY match in Google console)
REDIRECT_URI = _get_secret("REDIRECT_URI", "https://www.falowen.app/")

AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

def google_auth_link():
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,          # <- use the variable
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": st.session_state.get("oauth_state") or str(random.randint(100000, 999999)),
        # If you add PKCE: include code_challenge & code_challenge_method here
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)

# Show Sign-in button when logged out
if not st.session_state.get("logged_in", False):
    st.markdown(f'[🔐 Sign in with Google]({google_auth_link()})')

# --- Handle redirect back to https://www.falowen.app/ ---
_qp = getattr(st, "query_params", None)
qp = _qp if _qp is not None else st.experimental_get_query_params()

code = qp.get("code", [None])[0] if isinstance(qp.get("code"), list) else qp.get("code")
if code:
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,         # <- same exact value as above
        "grant_type": "authorization_code",
    }
    resp = requests.post(TOKEN_URL, data=data, timeout=20)
    if resp.ok:
        tokens = resp.json()
        # TODO: verify id_token and create your session
        st.session_state["logged_in"] = True
        st.success("Signed in with Google.")
    else:
        st.error(f"Token exchange failed: {resp.status_code} — {resp.text}")


# ==== OPENAI CLIENT SETUP ====
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("Missing OpenAI API key. Please add OPENAI_API_KEY in Streamlit secrets.")
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

