import streamlit as st
from openai import OpenAI
import tempfile
import io
from gtts import gTTS
import random
import pandas as pd
import os
from datetime import date
import re

# Streamlit page config
st.set_page_config(
    page_title="Falowen – Your German Conversation Partner",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ---- Falowen / Herr Felix Header ----
st.markdown(
    """
    <div style='display:flex;align-items:center;gap:18px;margin-bottom:22px;'>
        <img src='https://cdn-icons-png.flaticon.com/512/6815/6815043.png' width='54' style='border-radius:50%;border:2.5px solid #51a8d2;box-shadow:0 2px 8px #cbe7fb;'/>
        <div>
            <span style='font-size:2.1rem;font-weight:bold;color:#17617a;letter-spacing:2px;'>Falowen</span><br>
            <span style='font-size:1.08rem;color:#268049;'>Your personal German speaking coach (Herr Felix)</span>
        </div>
    </div>
    """, unsafe_allow_html=True
)

# File/database constants
CODES_FILE = "student_codes.csv"
DAILY_LIMIT = 25
max_turns = 25
TEACHER_PASSWORD = "Felix029"

# Exam topic lists
# --- A1 Exam Topic Lists (Teil 1, 2, 3) ---

A1_TEIL1 = [
    "Name", "Alter", "Wohnort", "Land", "Sprache", "Familie", "Beruf", "Hobby"
]

A1_TEIL2 = [
    ("Geschäft", "schließen"),
    ("Uhr", "Uhrzeit"),
    ("Arbeit", "Kollege"),
    ("Hausaufgabe", "machen"),
    ("Küche", "kochen"),
    ("Freizeit", "lesen"),
    ("Telefon", "anrufen"),
    ("Reise", "Hotel"),
    ("Auto", "fahren"),
    ("Einkaufen", "Obst"),
    ("Schule", "Lehrer"),
    ("Geburtstag", "Geschenk"),
    ("Essen", "Frühstück"),
    ("Arzt", "Termin"),
    ("Zug", "Abfahrt"),
    ("Wetter", "Regen"),
    ("Buch", "lesen"),
    ("Computer", "E-Mail"),
    ("Kind", "spielen"),
    ("Wochenende", "Plan"),
    ("Bank", "Geld"),
    ("Sport", "laufen"),
    ("Abend", "Fernsehen"),
    ("Freunde", "Besuch"),
    ("Bahn", "Fahrkarte"),
    ("Straße", "Stau"),
    ("Essen gehen", "Restaurant"),
    ("Hund", "Futter"),
    ("Familie", "Kinder"),
    ("Post", "Brief"),
    ("Nachbarn", "laut"),
    ("Kleid", "kaufen"),
    ("Büro", "Chef"),
    ("Urlaub", "Strand"),
    ("Kino", "Film"),
    ("Internet", "Seite"),
    ("Bus", "Abfahrt"),
    ("Arztpraxis", "Wartezeit"),
    ("Kuchen", "backen"),
    ("Park", "spazieren"),
    ("Bäckerei", "Brötchen"),
    ("Geldautomat", "Karte"),
    ("Buchladen", "Roman"),
    ("Fernseher", "Programm"),
    ("Tasche", "vergessen"),
    ("Stadtplan", "finden"),
    ("Ticket", "bezahlen"),
    ("Zahnarzt", "Schmerzen"),
    ("Museum", "Öffnungszeiten"),
    ("Handy", "Akku leer"),
]

A1_TEIL3 = [
    "Radio anmachen",
    "Fenster zumachen",
    "Licht anschalten",
    "Tür aufmachen",
    "Tisch sauber machen",
    "Hausaufgaben schicken",
    "Buch bringen",
    "Handy ausmachen",
    "Stuhl nehmen",
    "Wasser holen",
    "Fenster öffnen",
    "Musik leiser machen",
    "Tafel sauber wischen",
    "Kaffee kochen",
    "Deutsch üben",
    "Auto waschen",
    "Kind abholen",
    "Tisch decken",
    "Termin machen",
    "Nachricht schreiben",
]

A2_TEIL1 = [
    "Wohnort", "Tagesablauf", "Freizeit", "Sprachen", "Essen & Trinken", "Haustiere",
    "Lieblingsmonat", "Jahreszeit", "Sport", "Kleidung (Sommer)", "Familie", "Beruf",
    "Hobbys", "Feiertage", "Reisen", "Lieblingsessen", "Schule", "Wetter", "Auto oder Fahrrad", "Perfekter Tag"
]
A2_TEIL2 = [
    "Was machen Sie mit Ihrem Geld?",
    "Was machen Sie am Wochenende?",
    "Wie verbringen Sie Ihren Urlaub?",
    "Wie oft gehen Sie einkaufen und was kaufen Sie?",
    "Was für Musik hören Sie gern?",
    "Wie feiern Sie Ihren Geburtstag?",
    "Welche Verkehrsmittel nutzen Sie?",
    "Wie bleiben Sie gesund?",
    "Was machen Sie gern mit Ihrer Familie?",
    "Wie sieht Ihr Traumhaus aus?",
    "Welche Filme oder Serien mögen Sie?",
    "Wie oft gehen Sie ins Restaurant?",
    "Was ist Ihr Lieblingsfeiertag?",
    "Was machen Sie morgens als Erstes?",
    "Wie lange schlafen Sie normalerweise?",
    "Welche Hobbys hatten Sie als Kind?",
    "Machen Sie lieber Urlaub am Meer oder in den Bergen?",
    "Wie sieht Ihr Lieblingszimmer aus?",
    "Was ist Ihr Lieblingsgeschäft?",
    "Wie sieht ein perfekter Tag für Sie aus?"
]
A2_TEIL3 = [
    "Zusammen ins Kino gehen", "Ein Café besuchen", "Gemeinsam einkaufen gehen",
    "Ein Picknick im Park organisieren", "Eine Fahrradtour planen",
    "Zusammen in die Stadt gehen", "Einen Ausflug ins Schwimmbad machen",
    "Eine Party organisieren", "Zusammen Abendessen gehen",
    "Gemeinsam einen Freund/eine Freundin besuchen", "Zusammen ins Museum gehen",
    "Einen Spaziergang im Park machen", "Ein Konzert besuchen",
    "Zusammen eine Ausstellung besuchen", "Einen Wochenendausflug planen",
    "Ein Theaterstück ansehen", "Ein neues Restaurant ausprobieren",
    "Einen Kochabend organisieren", "Einen Sportevent besuchen", "Eine Wanderung machen"
]

B1_TEIL1 = [
    "Mithilfe beim Sommerfest", "Eine Reise nach Köln planen",
    "Überraschungsparty organisieren", "Kulturelles Ereignis (Konzert, Ausstellung) planen",
    "Museumsbesuch organisieren"
]
B1_TEIL2 = [
    "Ausbildung", "Auslandsaufenthalt", "Behinderten-Sport", "Berufstätige Eltern",
    "Berufswahl", "Bio-Essen", "Chatten", "Computer für jeden Kursraum", "Das Internet",
    "Einkaufen in Einkaufszentren", "Einkaufen im Internet", "Extremsport", "Facebook",
    "Fertigessen", "Freiwillige Arbeit", "Freundschaft", "Gebrauchte Kleidung",
    "Getrennter Unterricht für Jungen und Mädchen", "Haushalt", "Haustiere", "Heiraten",
    "Hotel Mama", "Ich bin reich genug", "Informationen im Internet", "Kinder und Fernsehen",
    "Kinder und Handys", "Kinos sterben", "Kreditkarten", "Leben auf dem Land oder in der Stadt",
    "Makeup für Kinder", "Marken-Kleidung", "Mode", "Musikinstrument lernen",
    "Musik im Zeitalter des Internets", "Rauchen", "Reisen", "Schokolade macht glücklich",
    "Sport treiben", "Sprachenlernen", "Sprachenlernen mit dem Internet",
    "Stadtzentrum ohne Autos", "Studenten und Arbeit in den Ferien", "Studium", "Tattoos",
    "Teilzeitarbeit", "Unsere Idole", "Umweltschutz", "Vegetarische Ernährung", "Zeitungslesen"
]
B1_TEIL3 = [
    "Fragen stellen zu einer Präsentation", "Positives Feedback geben",
    "Etwas überraschend finden oder planen", "Weitere Details erfragen"
]

def load_codes():
    if os.path.exists(CODES_FILE):
        df = pd.read_csv(CODES_FILE)
        if "code" not in df.columns:
            df = pd.DataFrame(columns=["code"])
        df["code"] = df["code"].astype(str).str.strip().str.lower()
    else:
        df = pd.DataFrame(columns=["code"])
    return df

# STAGE 2: Teacher Area Sidebar & Session State Setup

with st.sidebar.expander("👩‍🏫 Teacher Area (Login/Settings)", expanded=False):
    if "teacher_authenticated" not in st.session_state:
        st.session_state["teacher_authenticated"] = False

    if not st.session_state["teacher_authenticated"]:
        st.markdown("<div style='height:25px;'></div>", unsafe_allow_html=True)
        pwd = st.text_input("Teacher Login (for admin only)", type="password")
        login_btn = st.button("Login (Teacher)")
        if login_btn:
            if pwd == TEACHER_PASSWORD:
                st.session_state["teacher_authenticated"] = True
                st.success("Access granted!")
            elif pwd != "":
                st.error("Incorrect password. Please try again.")

    else:
        st.header("👩‍🏫 Teacher Dashboard")
        df_codes = load_codes()
        st.subheader("Current Codes")
        st.dataframe(df_codes, use_container_width=True)

        new_code = st.text_input("Add a new student code")
        if st.button("Add Code"):
            new_code_clean = new_code.strip().lower()
            if new_code_clean and new_code_clean not in df_codes["code"].values:
                df_codes = pd.concat([df_codes, pd.DataFrame({"code": [new_code_clean]})], ignore_index=True)
                df_codes.to_csv(CODES_FILE, index=False)
                st.success(f"Code '{new_code_clean}' added!")
            elif not new_code_clean:
                st.warning("Enter a code to add.")
            else:
                st.warning("Code already exists.")

        remove_code = st.selectbox("Select code to remove", [""] + df_codes["code"].tolist())
        if st.button("Remove Selected Code"):
            if remove_code:
                df_codes = df_codes[df_codes["code"] != remove_code]
                df_codes.to_csv(CODES_FILE, index=False)
                st.success(f"Code '{remove_code}' removed!")
            else:
                st.warning("Choose a code to remove.")

        if st.button("Log out (Teacher)"):
            st.session_state["teacher_authenticated"] = False

# ---- Global session state for app navigation ----
if "step" not in st.session_state:
    st.session_state["step"] = 1
if "student_code" not in st.session_state:
    st.session_state["student_code"] = ""
if "daily_usage" not in st.session_state:
    st.session_state["daily_usage"] = {}
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "corrections" not in st.session_state:
    st.session_state["corrections"] = []
if "turn_count" not in st.session_state:
    st.session_state["turn_count"] = 0

# STAGE 3: Student Login, Welcome, and Mode Selection

if st.session_state["step"] == 1:
    st.title("Student Login")
    code = st.text_input("🔑 Enter your student code to begin:")
    if st.button("Next ➡️", key="stage1_next"):
        code_clean = code.strip().lower()
        df_codes = load_codes()
        if code_clean in df_codes["code"].dropna().tolist():
            st.session_state["student_code"] = code_clean
            st.session_state["step"] = 2
        else:
            st.error("This code is not recognized. Please check with your tutor.")

elif st.session_state["step"] == 2:
    fun_facts = [
        "🇬🇭 Herr Felix was born in Ghana and mastered German up to C1 level!",
        "🎓 Herr Felix studied International Management at IU International University in Germany.",
        "🏫 He founded Learn Language Education Academy to help students pass Goethe exams.",
        "💡 Herr Felix used to run a record label and produce music before becoming a language coach!",
        "🥇 He loves making language learning fun, personal, and exam-focused.",
        "📚 Herr Felix speaks English, German, and loves teaching in both.",
        "🚀 Sometimes Herr Felix will throw in a real Goethe exam question—are you ready?",
        "🤖 Herr Felix built this app himself—so every session is personalized!"
    ]
    st.success(f"**Did you know?** {random.choice(fun_facts)}")
    st.markdown(
        "<h2 style='font-weight:bold;margin-bottom:0.5em'>🧑‍🏫 Welcome to Falowen – Your Friendly German Tutor, Herr Felix!</h2>",
        unsafe_allow_html=True,
    )
    st.markdown("> Practice your German speaking or writing. Get simple AI feedback and audio answers!")
    st.info(
        """
        🎤 **This is not just chat—it's your personal exam preparation bootcamp!**
        Every time you talk to Herr Felix, imagine you are **in the exam hall**.
        Expect realistic A2 and B1 speaking questions, surprise prompts, and real exam tips—sometimes, you’ll even get questions from last year’s exam!
        **Want to prepare for a class presentation or your next homework?**
        👉 You can also enter your **own question or topic** at any time—perfect for practicing real classroom situations or special assignments!
        Let’s make exam training engaging, surprising, and impactful.  
        **Are you ready? Let’s go! 🚀**
        """, icon="💡"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Back", key="stage2_back"):
            st.session_state["step"] = 1
    with col2:
        if st.button("Next ➡️", key="stage2_next"):
            st.session_state["step"] = 3

elif st.session_state["step"] == 3:
    st.header("Wie möchtest du üben? (How would you like to practice?)")
    mode = st.radio(
        "Choose your practice mode:",
        ["Geführte Prüfungssimulation (Exam Mode)", "Eigenes Thema/Frage (Custom Topic Chat)"],
        index=0,
        key="mode_selector"
    )
    st.session_state["selected_mode"] = mode

    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Back", key="stage3_back"):
            st.session_state["step"] = 2
    with col2:
        if st.button("Next ➡️", key="stage3_next"):
            st.session_state["messages"] = []
            st.session_state["turn_count"] = 0
            st.session_state["corrections"] = []
            if mode == "Eigenes Thema/Frage (Custom Topic Chat)":
                st.session_state["step"] = 5
            else:
                st.session_state["step"] = 4

elif st.session_state["step"] == 4:
    st.header("Prüfungsteil wählen / Choose exam part")
    exam_level = st.selectbox(
        "Welches Prüfungsniveau möchtest du üben?",
        ["A1", "A2", "B1"],
        key="exam_level_select",
        index=0
    )
    st.session_state["selected_exam_level"] = exam_level

    # Teil options for each level
    teil_options = (
        [
            "Teil 1 – Basic Introduction",
            "Teil 2 – Question and Answer",
            "Teil 3 – Making A Request"
        ] if exam_level == "A1" else
        [
            "Teil 1 – Fragen zu Schlüsselwörtern",
            "Teil 2 – Bildbeschreibung & Diskussion",
            "Teil 3 – Gemeinsam planen"
        ] if exam_level == "A2" else
        [
            "Teil 1 – Gemeinsam planen (Dialogue)",
            "Teil 2 – Präsentation (Monologue)",
            "Teil 3 – Feedback & Fragen stellen"
        ]
    )
    teil = st.selectbox(
        "Welchen Teil möchtest du üben?",
        teil_options,
        key="exam_teil_select"
    )
    st.session_state["selected_teil"] = teil

    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Back", key="stage4_back"):
            st.session_state["step"] = 3
    with col2:
        if st.button("Start Chat ➡️", key="stage4_start"):
            # --------- PROMPT GENERATION FOR EACH LEVEL ---------
            if exam_level == "A1":
                if teil.startswith("Teil 1"):
                    topic = random.choice(A1_TEIL1)
                    prompt = (
                        f"**A1 Teil 1:** Das Thema ist **{topic}**. "
                        "Stelle eine Frage und beantworte eine Frage zu diesem Thema."
                    )
                elif teil.startswith("Teil 2"):
                    thema, keyword = random.choice(A1_TEIL2)
                    prompt = (
                        f"**A1 Teil 2:** Thema: **{thema}** | Schlüsselwort: **{keyword}**. "
                        "Stelle und beantworte eine Frage mit dem Schlüsselwort."
                    )
                else:  # Teil 3
                    aufgabe = random.choice(A1_TEIL3)
                    prompt = (
                        f"**A1 Teil 3:** Bitten & Planen: **{aufgabe}**. "
                        "Formuliere eine höfliche Bitte oder einen Vorschlag."
                    )
            elif exam_level == "A2":
                if teil.startswith("Teil 1"):
                    topic = random.choice(A2_TEIL1)
                    prompt = (
                        f"**A2 Teil 1:** The Keyword is **{topic}**. "
                        "Stelle eine passende Frage und beantworte eine Frage dazu. "
                        "Beispiel: 'Hast du Geschwister? – Ja, ich habe eine Schwester.'"
                    )
                elif teil.startswith("Teil 2"):
                    topic = random.choice(A2_TEIL2)
                    prompt = f"**A2 Teil 2:** Talk about the topic: **{topic}**."
                else:
                    topic = random.choice(A2_TEIL3)
                    prompt = (
                        f"**A2 Teil 3:** Plan a meeting with Herr Felix: **{topic}**. "
                        "Mache Vorschläge, reagiere, und trefft eine Entscheidung."
                    )
            else:  # B1
                if teil.startswith("Teil 1"):
                    topic = random.choice(B1_TEIL1)
                    prompt = (
                        f"**B1 Teil 1:** Plant gemeinsam: **{topic}**. "
                        "Mache Vorschläge, reagiere auf deinen Partner, und trefft eine Entscheidung."
                    )
                elif teil.startswith("Teil 2"):
                    topic = random.choice(B1_TEIL2)
                    prompt = (
                        f"**B1 Teil 2:** Halte eine Präsentation über das Thema: **{topic}**. "
                        "Begrüße, nenne das Thema, gib deine Meinung, teile Vor- und Nachteile, fasse zusammen."
                    )
                else:
                    topic = random.choice(B1_TEIL3)
                    prompt = (
                        f"**B1 Teil 3:** {topic}: Dein Partner hat eine Präsentation gehalten. "
                        "Stelle 1–2 Fragen dazu und gib positives Feedback."
                    )

            st.session_state["initial_prompt"] = prompt
            st.session_state["messages"] = []
            st.session_state["turn_count"] = 0
            st.session_state["corrections"] = []
            st.session_state["step"] = 5

def show_formatted_ai_reply(ai_reply):
    # Formatting for AI output: Answer, Correction, Grammar Tip (English), Next Question (German)
    lines = [l.strip() for l in ai_reply.split('\n') if l.strip()]
    main, correction, grammatik, followup = '', '', '', ''
    curr_section = 'main'

    for line in lines:
        header = line.lower()
        if header.startswith('correction:') or header.startswith('- correction:'):
            curr_section = 'correction'
            line = line.split(':',1)[-1].strip()
            if line: correction += line + ' '
            continue
        elif header.startswith('grammar tip:') or header.startswith('- grammar tip:') \
             or header.startswith('grammatik-tipp:') or header.startswith('- grammatik-tipp:'):
            curr_section = 'grammatik'
            line = line.split(':',1)[-1].strip()
            if line: grammatik += line + ' '
            continue
        elif header.startswith('next question:') or header.startswith('- next question:') \
             or header.startswith('follow-up question') or header.startswith('folgefrage'):
            curr_section = 'followup'
            line = line.split(':',1)[-1].strip()
            if line: followup += line + ' '
            continue
        if curr_section == 'main':
            main += line + ' '
        elif curr_section == 'correction':
            correction += line + ' '
        elif curr_section == 'grammatik':
            grammatik += line + ' '
        elif curr_section == 'followup':
            followup += line + ' '

    # In case the followup got stuck inside main/grammatik
    for block, setter in [(grammatik, 'grammatik'), (main, 'main')]:
        candidates = [l.strip() for l in block.split('\n') if l.strip()]
        if candidates:
            last = candidates[-1]
            if (last.endswith('?') or (last.endswith('.') and len(last.split()) < 14)) and not followup:
                followup = last
                if setter == 'grammatik':
                    grammatik = grammatik.replace(last, '').strip()
                else:
                    main = main.replace(last, '').strip()

    st.markdown(f"**📝 Answer:**  \n{main.strip()}", unsafe_allow_html=True)
    if correction.strip():
        st.markdown(f"<div style='color:#c62828'><b>✏️ Correction:</b>  \n{correction.strip()}</div>", unsafe_allow_html=True)
    if grammatik.strip():
        st.markdown(f"<div style='color:#1565c0'><b>📚 Grammar Tip:</b>  \n{grammatik.strip()}</div>", unsafe_allow_html=True)
    if followup.strip():
        st.markdown(f"<div style='color:#388e3c'><b>➡️ Next question:</b>  \n{followup.strip()}</div>", unsafe_allow_html=True)

if st.session_state["step"] == 5:
    today_str = str(date.today())
    student_code = st.session_state["student_code"]
    usage_key = f"{student_code}_{today_str}"
    st.session_state.setdefault("daily_usage", {})
    st.session_state["daily_usage"].setdefault(usage_key, 0)
    st.session_state.setdefault("custom_topic_intro_done", False)

    st.info(
        f"Student code: `{student_code}` | "
        f"Today's practice: {st.session_state['daily_usage'][usage_key]}/{DAILY_LIMIT}"
    )

    is_b1_teil3 = (
        st.session_state.get("selected_mode", "").startswith("Geführte") and
        st.session_state.get("selected_exam_level") == "B1" and
        st.session_state.get("selected_teil", "").startswith("Teil 3")
    )

    # --- Mode initializations ---
    if (
        st.session_state.get("selected_mode", "") == "Eigenes Thema/Frage (Custom Topic Chat)"
        and not st.session_state.get("custom_chat_level")
    ):
        level = st.radio(
            "Wähle dein Sprachniveau / Select your level:",
            ["A2", "B1"],
            horizontal=True,
            key="custom_level_select"
        )
        if st.button("Start Custom Chat"):
            st.session_state["custom_chat_level"] = level
            st.session_state["messages"] = [{
                "role": "assistant",
                "content": "Hallo! 👋 What would you like to talk about? Give me details of what you want so I can understand."
            }]
        st.stop()

    if is_b1_teil3 and not st.session_state['messages']:
        topic = random.choice(B1_TEIL2)
        st.session_state['current_b1_teil3_topic'] = topic
        init = (
            f"Imagine am done with my presentation on **{topic}**.\n\n"
            "Your task now:\n"
            "- Ask me **one question** about my presentation (In German).\n"
            "👉 Schreib dein Frage!"
        )
        st.session_state['messages'].append({'role': 'assistant', 'content': init})

    elif (
        st.session_state.get("selected_mode", "") == "Eigenes Thema/Frage (Custom Topic Chat)"
        and st.session_state.get("custom_chat_level")
        and not st.session_state['messages']
    ):
        st.session_state['messages'].append({
            'role': 'assistant',
            'content': 'Hallo! 👋 What would you like to discuss? Schreib dein Präsentationsthema oder eine Frage.'
        })

    elif st.session_state.get("selected_mode", "").startswith("Geführte") and not st.session_state['messages']:
        prompt = st.session_state.get('initial_prompt', '')
        st.session_state['messages'].append({'role': 'assistant', 'content': prompt})

    uploaded = st.file_uploader(
        "Upload an audio file (WAV, MP3, OGG, M4A)",
        type=["wav", "mp3", "ogg", "m4a"],
        key="stage5_audio_upload"
    )
    typed = st.chat_input("💬 Oder tippe deine Antwort hier...", key="stage5_typed_input")
    user_input = None

    if uploaded:
        uploaded.seek(0)
        data = uploaded.read()
        st.audio(data, format=uploaded.type)
        try:
            suffix = "." + uploaded.name.split('.')[-1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                tmp.flush()
            client = OpenAI(api_key=st.secrets['general']['OPENAI_API_KEY'])
            with open(tmp.name, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=f
                )
            os.remove(tmp.name)
            user_input = transcript.text
        except:
            st.warning("Transcription failed; please type your message.")
    elif typed:
        user_input = typed

    session_ended = st.session_state.get('turn_count', 0) >= max_turns
    used_today = st.session_state['daily_usage'][usage_key]

    if user_input and not session_ended:
        if used_today >= DAILY_LIMIT:
            st.warning(
                "You’ve reached today’s free practice limit. "
                "Please come back tomorrow or contact your tutor!"
            )
        else:
            st.session_state['messages'].append({'role': 'user', 'content': user_input})
            st.session_state['turn_count'] += 1
            st.session_state['daily_usage'][usage_key] += 1

            # ---- PROMPT SELECTION, ENFORCING TOPIC & SINGLE QUESTION ----
            # Always set a fallback for ai_system_prompt in case no branch is chosen
            ai_system_prompt = (
                "You are Herr Felix, a supportive and creative German examiner. "
                "Continue the conversation, give simple corrections, and ask the next question."
            )

            if is_b1_teil3:
                b1_topic = st.session_state['current_b1_teil3_topic']
                ai_system_prompt = (
                    "You are Herr Felix, the examiner in a German B1 oral exam (Teil 3: Feedback & Questions). "
                    f"**IMPORTANT: Stay strictly on the topic:** {b1_topic}. "
                    "After student ask the question and you have given the student compliment, give another topic for the student ask the question. "
                    "The student is supposed to ask you one valid question about their presentation. "
                    "1. Read the student's message. "
                    "2. Praise if it's valid or politely indicate what's missing. "
                    "3. If valid, answer briefly in simple German. "
                    "4. End with clear exam tips in English. "
                    "Stay friendly,creative and exam-like."
                )
            elif st.session_state.get('selected_mode') == 'Eigenes Thema/Frage (Custom Topic Chat)':
                lvl = st.session_state.get('custom_chat_level', 'A2')
                if lvl == 'A2':
                    ai_system_prompt = (
                        "You are Herr Felix, a friendly but creative A2 German teacher and exam trainer. "
                        "Greet and give students ideas and examples about how to talk about the topic in English and ask only question. No correction or answer in the statement but only tip and possible phrases to use. This stage only when the student input their first question and not anyother input. "
                        "The first input from the student is their topic and not their reply or sentence or answer. It is always their presentation topic. Only the second and further repliers it their response to your question "
                        "Use simple German and English to correct the student's last answer. Tip and necessay suggestions should be explained in English with German supporting for student to udnerstand. They are A2 beginners student. " 
                        "You can also suggest keywords when needed."
                        "Ask one question only. Format your reply with answer, correction explanation in english, tip in english, and next question."
                    )
                else:
                    if not st.session_state['custom_topic_intro_done']:
                        ai_system_prompt = (
                            "You are Herr Felix, a supportive and creative B1 German teacher. "
                            "The first input from the student is their topic and not their reply or sentence or answer. It is always their presentation topic. Only the second and further repliers it their response to your question "
                            "Provide practical ideas/opinions/advantages/disadvantages/situation in their homeland for the topic in German and English, then ask one opinion question. No correction or answer in the statement but only tip and possible phrases to use. This stage only when the student input their first question and not anyother input. "
                            "Support ideas and opinions explanation in English and German as these students are new B1 students. "
                            "Ask creative question that helps student to learn how to answer opinions,advantages,disadvantages,situation in their country and so on. "
                            "Always put the opinion question on a separate line so the student can notice the question from the ideas and examples"
                        )
                    else:
                        ai_system_prompt = (
                            "You are Herr Felix, a supportive B1 German teacher. "
                            "Reply in German and English, correct last answer, give a tip in English, and ask one question on the same topic."
                        )
            elif st.session_state.get("selected_mode", "").startswith("Geführte"):
                teil = st.session_state.get("selected_teil", "Teil 1")
                if st.session_state["selected_exam_level"] == "A2":
                    if teil == "Teil 1":
                        ai_system_prompt = (
                            "You are Herr Felix, a creative and supportive Goethe A2 examiner. "
                            "This is A2 Sprechen Teil 1. Ask a personal information question (name, age, job, hobby, family, etc.) in German. "
                            "After the answer, ask a natural, personal follow-up. "
                            "After student answer, pick another thema and still test the students knowledge. Support student with english explanation. "
                            "Do NOT ask for keywords. If there's a mistake, correct it in German and give a grammar tip in English."
                        )
                    elif teil == "Teil 2":
                        keyword = st.session_state.get("teil2_keyword", "")
                        ai_system_prompt = (
                            "You are Herr Felix, a supportive and creative Goethe A2 examiner. "
                            "This is A2 Sprechen Teil 2. Ask the student to ask and answer questions using the given keyword. "
                            f"Keyword: {keyword}. Never ask for keywords. "
                            "If there's a mistake, correct it in German and give a grammar tip in English."
                        )
                    elif teil == "Teil 3":
                        ai_system_prompt = (
                            "You are Herr Felix, a strict but friendly Goethe A2 examiner. "
                            "Reply ONLY as an examiner would in the real A2 Sprechen exam. "
                            "Always stay on topic and follow the trend of the communication to agree on a given time for the planning. "
                            "For Teil 3: If the task is to plan something together, you should act as the partner, respond to suggestions, make your own suggestions, and help make a decision together. "
                            "Do NOT ask for keywords. "
                            "Correct the student's most recent answer if needed and give a short grammar tip (in English). "
                            "Keep your reply to 2-3 sentences, simple A2 German. "
                            "Format:\n"
                            "- Your answer (German, as examiner partner)\n"
                            "- Correction: (only if needed)\n"
                            "- Grammar Tip: (in English, one short sentence)\n"
                            "- Next step (German, one prompt or suggestion, but NOT 'please give me keywords')"
                        )
                else:
                    ai_system_prompt = (
                        "You are Herr Felix, a strict but supportive Goethe B1 examiner. "
                        "Answer in B1 German, correct if needed, give a tip in English, then ask the next question."
                    )
            conversation = (
                [{"role": "system", "content": ai_system_prompt}]
                + st.session_state["messages"]
            )
            with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                try:
                    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                    resp = client.chat.completions.create(
                        model="gpt-4o", messages=conversation
                    )
                    ai_reply = resp.choices[0].message.content
                except Exception as e:
                    ai_reply = "Sorry, there was a problem generating a response."
                    st.error(str(e))

            if (
                st.session_state.get("selected_mode") == "Eigenes Thema/Frage (Custom Topic Chat)"
                and st.session_state.get("custom_chat_level") == "B1"
                and not st.session_state["custom_topic_intro_done"]
            ):
                st.session_state["custom_topic_intro_done"] = True

            st.session_state["messages"].append(
                {"role": "assistant", "content": ai_reply}
            )

    for msg in st.session_state["messages"]:
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="🧑‍🏫"):
                st.markdown(
                    "<span style='color:#33691e;font-weight:bold'>🧑‍🏫 Herr Felix:</span>",
                    unsafe_allow_html=True
                )
                show_formatted_ai_reply(msg["content"])
        else:
            with st.chat_message("user"):
                st.markdown(f"🗣️ {msg['content']}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Back", key="stage5_back"):
            prev = 4 if st.session_state["selected_mode"].startswith("Geführte") else 3
            st.session_state.update({
                "step": prev,
                "messages": [],
                "turn_count": 0,
                "custom_chat_level": None,
            })
    with col2:
        if session_ended and st.button("Next ➡️ (Summary)", key="stage5_summary"):
            st.session_state["step"] = 6

elif st.session_state["step"] == 6:
    st.header("Session Summary")
    st.success("Great work today! 🎉")
    st.write(f"Total turns: {st.session_state.get('turn_count', 0)}")
    for msg in st.session_state.get("messages", []):
        role = "Herr Felix" if msg["role"] == "assistant" else "You"
        st.markdown(f"**{role}:** {msg['content']}")
    if st.button("Start New Session"):
        st.session_state.update({
            "step": 1,
            "messages": [],
            "turn_count": 0,
            "custom_chat_level": None,
            "custom_level_prompted": False,
        })
