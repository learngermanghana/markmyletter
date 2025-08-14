
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

    # Inject SEO head tags AFTER the hero (zero-height iframe)
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

      <!-- ===== Compact stats strip ===== -->
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

    # --- Rotating multi-country reviews (with flags) ---
    import json, streamlit.components.v1 as components
    REVIEWS = [
        {"quote": "Falowen helped me pass A2 in 8 weeks. The assignments and feedback were spot on.",
         "author": "Ama — Accra, Ghana 🇬🇭", "level": "A2"},
        {"quote": "The Course Book and Results emails keep me consistent. The vocab trainer is brilliant.",
         "author": "Tunde — Lagos, Nigeria 🇳🇬", "level": "B1"},
        {"quote": "Clear lessons, easy submissions, and I get notified quickly when marked.",
         "author": "Mariama — Freetown, Sierra Leone 🇸🇱", "level": "A1"},
        {"quote": "I like the locked submissions and the clean Results tab.",
         "author": "Kossi — Lomé, Togo 🇹🇬", "level": "B1"},
        {"quote": "Exactly what I needed for B2 writing — detailed, actionable feedback every time.",
         "author": "Lea — Berlin, Germany 🇩🇪", "level": "B2"},
        {"quote": "Solid grammar explanations and lots of practice. My confidence improved fast.",
         "author": "Sipho — Johannesburg, South Africa 🇿🇦", "level": "A2"},
        {"quote": "Great structure for busy schedules. I can study, submit, and track results easily.",
         "author": "Nadia — Windhoek, Namibia 🇳🇦", "level": "B1"},
    ]
    _reviews_json = json.dumps(REVIEWS, ensure_ascii=False)
    _reviews_html = """
<div class="page-wrap" role="region" aria-label="Student reviews" style="margin-top:10px;">
  <div id="rev-quote" style="
      background:#f8fafc;border-left:4px solid #6366f1;padding:12px 14px;border-radius:10px;
      color:#475569;min-height:82px;display:flex;align-items:center;justify-content:center;text-align:center;">
    Loading…
  </div>
  <div style="display:flex;align-items:center;justify-content:center;gap:10px;margin-top:10px;">
    <button id="rev-prev" aria-label="Previous review" style="background:#0ea5e9;color:#fff;border:none;border-radius:10px;padding:6px 10px;cursor:pointer;">‹</button>
    <div id="rev-dots" aria-hidden="true" style="display:flex;gap:6px;"></div>
    <button id="rev-next" aria-label="Next review" style="background:#0ea5e9;color:#fff;border:none;border-radius:10px;padding:6px 10px;cursor:pointer;">›</button>
  </div>
</div>
<script>
  const data = __DATA__;
  let i = 0;
  const quoteEl = document.getElementById('rev-quote');
  const dotsEl  = document.getElementById('rev-dots');
  const prevBtn = document.getElementById('rev-prev');
  const nextBtn = document.getElementById('rev-next');
  function renderDots(){
    dotsEl.innerHTML = '';
    data.forEach((_, idx) => {
      const d = document.createElement('button');
      d.setAttribute('aria-label', 'Go to review ' + (idx + 1));
      d.style.width = '10px'; d.style.height = '10px'; d.style.borderRadius = '999px';
      d.style.border = 'none'; d.style.cursor = 'pointer';
      d.style.background = (idx === i) ? '#6366f1' : '#c7d2fe';
      d.addEventListener('click', () => { i = idx; render(); });
      dotsEl.appendChild(d);
    });
  }
  function render(){
    const r = data[i];
    quoteEl.innerHTML = '“' + r.quote + '” — <i>' + r.author + ' · ' + r.level + '</i>';
    renderDots();
  }
  function next(){ i = (i + 1) % data.length; render(); }
  function prev(){ i = (i - 1 + data.length) % data.length; render(); }
  prevBtn.addEventListener('click', prev);
  nextBtn.addEventListener('click', next);
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduced) { setInterval(next, 6000); }
  render();
</script>
"""
    components.html(_reviews_html.replace("__DATA__", _reviews_json), height=240)

    # Support / Help section
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

#
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
