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

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or st.secrets.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") or st.secrets.get("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI") or st.secrets.get("REDIRECT_URI")

# ==== OPENAI CLIENT SETUP ====
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("Missing OpenAI API key. Please add OPENAI_API_KEY in Streamlit secrets.")
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)
