def render_dropdown_nav():
    """
    Mobile-friendly dropdown nav with a one-time coachmark that says:
    'Tap the arrow ▾ to open the menu and see all sections.'

    - Remembers dismissal in session_state["nav_hint_dismissed"]
    - Syncs with URL query param ?tab=...
    - Keeps st.session_state["main_tab_select"] in sync
    - Persists last choice to localStorage (and restores it if ?tab is missing)
    """
    # --- If no ?tab= in URL, restore last selection from localStorage (once) ---
    if "tab" not in st.query_params and not st.session_state.get("__nav_synced", False):
        components.html("""
        <script>
          try {
            const last = localStorage.getItem('last_tab');
            const u = new URL(window.location);
            if (last && !u.searchParams.get('tab')) {
              u.searchParams.set('tab', last);
              window.location.replace(u);
            }
          } catch(e) {}
        </script>
        """, height=0)
        st.session_state["__nav_synced"] = True

    tabs = [
        "Dashboard",
        "My Course",
        "My Results and Resources",
        "Exams Mode & Custom Chat",
        "Vocab Trainer",
        "Schreiben Trainer",
    ]
    icons = {
        "Dashboard": "🏠",
        "My Course": "📚",
        "My Results and Resources": "📊",
        "Exams Mode & Custom Chat": "🤖",
        "Vocab Trainer": "🗣️",
        "Schreiben Trainer": "✍️",
    }

    # --- One-time coachmark (shows until dismissed) ---
    if not st.session_state.get("nav_hint_dismissed", False):
        with st.container():
            st.markdown(
                "<div style='background:#fff7ed;border:1px solid #fed7aa;"
                "border-radius:10px;padding:8px 10px;margin:4px 0;'>"
                "👉 <b>Tip:</b> Tap the arrow <b>▾</b> to open the menu and see all sections."
                "</div>",
                unsafe_allow_html=True,
            )
            if st.button("Got it", key="nav_hint_gotit"):
                st.session_state["nav_hint_dismissed"] = True
                st.rerun()

    # --- Default from URL (?tab=...) or session ---
    default = st.query_params.get(
        "tab",
        [st.session_state.get("main_tab_select", "Dashboard")]
    )[0]
    if default not in tabs:
        default = "Dashboard"

    # --- Selectbox with help tooltip and icons in labels ---
    def _fmt(x: str) -> str:
        return f"{icons.get(x,'•')}  {x}"

    sel = st.selectbox(
        "Choose a section (tap ▾)",
        tabs,
        index=tabs.index(default),
        key="nav_dd",
        format_func=_fmt,
        help="Tap the arrow ▾ to open the menu and view all sections."
    )

    # --- Persist selection to URL + session ---
    if sel != default:
        st.query_params["tab"] = sel
    st.session_state["main_tab_select"] = sel

    # --- Persist to localStorage so we can restore if URL is clean next time ---
    components.html(f"""
    <script>
      try {{
        localStorage.setItem('last_tab', {json.dumps(sel)});
      }} catch(e) {{}}
    </script>
    """, height=0)

    return sel

# usage:
tab = render_dropdown_nav()
