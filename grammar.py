# ====================================
# 1. IMPORTS, CONSTANTS, AND PAGE SETUP
# ====================================

import streamlit as st
from openai import OpenAI
import random
import pandas as pd
import os
from datetime import date

# --- Streamlit page config ---
st.set_page_config(
    page_title="Falowen – Your German Conversation Partner",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ---- Falowen Header ----
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

# --- File/database constants ---
CODES_FILE = "student_codes.csv"
DAILY_LIMIT = 25
max_turns = 25

# --- Vocab lists for all levels ---
VOCAB_LISTS = {
    "A1": ["Haus", "Auto", "Buch", "Tisch", "Mutter"],
    "A2": ["Gemüse", "Rezept", "Reise", "Wetter", "Feiertag"],
    "B1": ["Fortschritt", "Eindruck", "Unterschied", "Vorschlag", "Erfahrung"],
    "B2": ["Umwelt", "Entwicklung", "Auswirkung", "Verhalten", "Verhältnis"],
    "C1": ["Ausdruck", "Beziehung", "Erkenntnis", "Verfügbarkeit", "Bereich"]
}

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

# ====================================
# 2. STUDENT LOGIN AND TAB SELECTION
# ====================================

def load_codes():
    if os.path.exists(CODES_FILE):
        df = pd.read_csv(CODES_FILE)
        if "code" not in df.columns:
            df = pd.DataFrame(columns=["code"])
        df["code"] = df["code"].astype(str).str.strip().str.lower()
    else:
        df = pd.DataFrame(columns=["code"])
    return df

# --- Session state for navigation and student info ---
if "student_code" not in st.session_state:
    st.session_state["student_code"] = ""
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

# --- Step 1: Student Login ---
if not st.session_state["logged_in"]:
    st.title("🔑 Student Login")
    code = st.text_input("Enter your student code to begin:")
    if st.button("Login"):
        code_clean = code.strip().lower()
        df_codes = load_codes()
        if code_clean in df_codes["code"].dropna().tolist():
            st.session_state["student_code"] = code_clean
            st.session_state["logged_in"] = True
            st.success("Welcome! Login successful.")
        else:
            st.error("This code is not recognized. Please check with your tutor.")

# --- Step 2: Show Tabs After Login ---
if st.session_state["logged_in"]:
    tab = st.sidebar.radio(
        "Choose Practice Mode:",
        ["Falowen Chat", "Vocab Trainer", "Schreiben Trainer"],
        key="main_tab_select"
    )

# ====================================
# 5. FALOWEN CHAT TAB (Multi-Step, All Center)
# ====================================

if st.session_state.get("logged_in") and tab == "Falowen Chat":
    st.header("🗣️ Falowen – Speaking & Exam Trainer")

    # Ensure stage variable is present
    if "falowen_stage" not in st.session_state:
        st.session_state["falowen_stage"] = 1
    if "falowen_mode" not in st.session_state:
        st.session_state["falowen_mode"] = None
    if "falowen_level" not in st.session_state:
        st.session_state["falowen_level"] = None
    if "falowen_teil" not in st.session_state:
        st.session_state["falowen_teil"] = None
    if "falowen_messages" not in st.session_state:
        st.session_state["falowen_messages"] = []
    if "custom_topic_intro_done" not in st.session_state:
        st.session_state["custom_topic_intro_done"] = False

    # ------------- Step 1: Practice Mode -------------
    if st.session_state["falowen_stage"] == 1:
        st.subheader("Step 1: Choose Practice Mode")
        mode = st.radio("How would you like to practice?",
                        ["Geführte Prüfungssimulation (Exam Mode)", "Eigenes Thema/Frage (Custom Chat)"],
                        key="falowen_mode_center")
        if st.button("Next ➡️", key="falowen_next_mode"):
            st.session_state["falowen_mode"] = mode
            st.session_state["falowen_stage"] = 2
            # Clear next step states on mode change
            st.session_state["falowen_level"] = None
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
        st.stop()

    # ------------- Step 2: Level Selection -------------
    if st.session_state["falowen_stage"] == 2:
        st.subheader("Step 2: Choose Your Level")
        level = st.radio("Select your level:", ["A1", "A2", "B1", "B2", "C1"], key="falowen_level_center")
        if st.button("⬅️ Back", key="falowen_back1"):
            st.session_state["falowen_stage"] = 1
            st.stop()
        if st.button("Next ➡️", key="falowen_next_level"):
            st.session_state["falowen_level"] = level
            if st.session_state["falowen_mode"] == "Geführte Prüfungssimulation (Exam Mode)":
                st.session_state["falowen_stage"] = 3
            else:
                st.session_state["falowen_stage"] = 4
            # Clear messages when level changes
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
        st.stop()

    # ---------- Exam Mode: Select Level & Teil ----------
    if mode == "Geführte Prüfungssimulation (Exam Mode)":
        exam_level = st.selectbox(
            "Which level do you want to practice?",
            ["A1", "A2", "B1", "B2", "C1"],
            key="falowen_exam_level"
        )
        teil_options = {
            "A1": [
                "Teil 1 – Basic Introduction",
                "Teil 2 – Question and Answer",
                "Teil 3 – Making A Request"
            ],
            "A2": [
                "Teil 1 – Fragen zu Schlüsselwörtern",
                "Teil 2 – Bildbeschreibung & Diskussion",
                "Teil 3 – Gemeinsam planen"
            ],
            "B1": [
                "Teil 1 – Gemeinsam planen (Dialogue)",
                "Teil 2 – Präsentation (Monologue)",
                "Teil 3 – Feedback & Fragen stellen"
            ],
            "B2": [
                "Teil 1 – Diskussion",
                "Teil 2 – Präsentation",
                "Teil 3 – Argumentation"
            ],
            "C1": [
                "Teil 1 – Vortrag",
                "Teil 2 – Diskussion",
                "Teil 3 – Bewertung"
            ]
        }
        exam_teil = st.selectbox(
            "Which exam part?",
            teil_options[exam_level],
            key="falowen_exam_teil"
        )
        if st.button("Preview All Exam Questions/Prompts"):
            st.write("**Sample exam question lists for each level go here!** (Edit/add as you wish.)")

    # ------------- User Input -------------
    user_input = st.chat_input("💬 Type your answer here...", key="falowen_input")
    session_ended = st.session_state["falowen_usage"][falowen_usage_key] >= FALOWEN_DAILY_LIMIT

    # ============= Main Chat Logic =============
    if user_input and not session_ended:
        st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
        st.session_state["falowen_turn_count"] += 1
        st.session_state["falowen_usage"][falowen_usage_key] += 1

        # --------------- PROMPT SELECTION ---------------
        ai_system_prompt = (
            "You are Herr Felix, a supportive and creative German examiner. Continue the conversation, give simple corrections, and ask the next question."
        )
        # ===== Exam Mode Prompts =====
        if mode == "Geführte Prüfungssimulation (Exam Mode)":
            if exam_level == "A1":
                if exam_teil.startswith("Teil 1"):
                    ai_system_prompt = (
                        "You are Herr Felix, an A1 examiner. Correct the student's self-introduction (name, age, etc), give a grammar tip in English. Praise if perfect. Then, ask a follow-up."
                    )
                elif exam_teil.startswith("Teil 2"):
                    ai_system_prompt = (
                        "You are Herr Felix, an A1 examiner. Check the student's question and answer, correct errors, give a grammar tip in English. Introduce a new Thema/keyword next."
                    )
                elif exam_teil.startswith("Teil 3"):
                    ai_system_prompt = (
                        "You are Herr Felix, an A1 examiner. Check polite request, correct errors, give a grammar tip in English. Give a new request next."
                    )
            elif exam_level == "A2":
                if exam_teil.startswith("Teil 1"):
                    ai_system_prompt = (
                        "You are Herr Felix, an A2 examiner. Give a keyword/topic, ask a simple question, correct the answer, tip in English, and ask a related question next."
                    )
                elif exam_teil.startswith("Teil 2"):
                    ai_system_prompt = (
                        "You are Herr Felix, an A2 examiner. Describe a picture or situation, discuss with the student, give tips in English, and ask follow-up questions."
                    )
                elif exam_teil.startswith("Teil 3"):
                    ai_system_prompt = (
                        "You are Herr Felix, an A2 examiner. Plan together, make suggestions, discuss options, agree on something. Correct mistakes and tip in English."
                    )
            elif exam_level == "B1":
                if exam_teil.startswith("Teil 1"):
                    ai_system_prompt = (
                        "You are Herr Felix, a B1 examiner. Plan something together, make suggestions, react, and come to a decision. Correct mistakes, tip in English."
                    )
                elif exam_teil.startswith("Teil 2"):
                    ai_system_prompt = (
                        "You are Herr Felix, a B1 examiner. The student gives a monologue presentation. Listen, give feedback, correct errors, and ask 1–2 follow-up questions."
                    )
                elif exam_teil.startswith("Teil 3"):
                    ai_system_prompt = (
                        "You are Herr Felix, a B1 examiner. Give feedback on a presentation and ask 1–2 questions. Stay on topic. Correction and tip in English."
                    )
            elif exam_level == "B2":
                if exam_teil.startswith("Teil 1"):
                    ai_system_prompt = (
                        "You are Herr Felix, a B2 examiner. Have a discussion with the student on a given topic, encourage argumentation and critical thinking, correct errors, and give tips."
                    )
                elif exam_teil.startswith("Teil 2"):
                    ai_system_prompt = (
                        "You are Herr Felix, a B2 examiner. The student gives a presentation. Give feedback, correct errors, ask advanced follow-ups, and give tips."
                    )
                elif exam_teil.startswith("Teil 3"):
                    ai_system_prompt = (
                        "You are Herr Felix, a B2 examiner. Ask for arguments, help the student debate, correct and tip."
                    )
            elif exam_level == "C1":
                if exam_teil.startswith("Teil 1"):
                    ai_system_prompt = (
                        "You are Herr Felix, a C1 examiner. Listen to a lecture, check structure and logic, give advanced feedback, correct errors, tip in English and German."
                    )
                elif exam_teil.startswith("Teil 2"):
                    ai_system_prompt = (
                        "You are Herr Felix, a C1 examiner. Discuss with the student, challenge their ideas, correct errors, give nuanced feedback."
                    )
                elif exam_teil.startswith("Teil 3"):
                    ai_system_prompt = (
                        "You are Herr Felix, a C1 examiner. Evaluate and summarize the student's opinions and arguments, correct, and give advanced tips."
                    )

        # ===== Custom Chat Prompts =====
        elif mode == "Eigenes Thema/Frage (Custom Chat)":
            lvl = st.session_state.get("custom_chat_level", "A2")
            if lvl == 'A1':
                ai_system_prompt = (
                    "You are Herr Felix, a supportive and creative A1 German teacher and exam trainer. Give feedback and suggestions in English, ask simple questions, and help improve their A1 German."
                )
            elif lvl == 'A2':
                ai_system_prompt = (
                    "You are Herr Felix, a friendly A2 teacher. Greet, give ideas/examples about the topic in English, ask a question. Correction/tip in English, next question in German."
                )
            elif lvl == 'B1':
                if not st.session_state["custom_topic_intro_done"]:
                    ai_system_prompt = (
                        "You are Herr Felix, a supportive B1 teacher. Give ideas and opinion questions on the student's topic (German and English)."
                    )
                else:
                    ai_system_prompt = (
                        "You are Herr Felix, a supportive B1 teacher. Reply in German and English, correct last answer, tip in English, next question."
                    )
            elif lvl == 'B2':
                ai_system_prompt = (
                    "You are Herr Felix, a supportive but strict B2 teacher. Discuss complex topics, give advanced corrections in both English and German, and help develop arguments."
                )
            elif lvl == 'C1':
                ai_system_prompt = (
                    "You are Herr Felix, a C1 coach. Encourage academic discussion, correct errors in detail, and suggest advanced vocabulary and idioms."
                )

            # Mark intro as done after first student reply for B1–C1
            if lvl in ['B1', 'B2', 'C1'] and not st.session_state["custom_topic_intro_done"]:
                st.session_state["custom_topic_intro_done"] = True

        # -------------- OpenAI Response Call --------------
        conversation = [{"role": "system", "content": ai_system_prompt}] + st.session_state["falowen_messages"]
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
        st.session_state["falowen_messages"].append(
            {"role": "assistant", "content": ai_reply}
        )

    # ------------- Display Chat History --------------
    for msg in st.session_state["falowen_messages"]:
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="🧑‍🏫"):
                st.markdown(
                    "<span style='color:#33691e;font-weight:bold'>🧑‍🏫 Herr Felix:</span>",
                    unsafe_allow_html=True
                )
                st.markdown(msg["content"])
        else:
            with st.chat_message("user"):
                st.markdown(f"🗣️ {msg['content']}")

    # ------------- Navigation Buttons --------------
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("⬅️ Back", key="falowen_back"):
            st.session_state.update({
                "falowen_messages": [],
                "falowen_turn_count": 0,
                "custom_chat_level": None,
                "custom_topic_intro_done": False
            })
    with col2:
        if st.button("🔄 Restart Chat", key="falowen_restart"):
            st.session_state.update({
                "falowen_messages": [],
                "falowen_turn_count": 0,
                "custom_chat_level": None,
                "custom_topic_intro_done": False
            })
            st.experimental_rerun()
    with col3:
        if st.button("Next ➡️ (Summary)", key="falowen_summary"):
            st.success("Summary not implemented yet (placeholder).")

# =========================================
# VOCAB TRAINER TAB (A1–C1)
# =========================================

if st.session_state.get("logged_in") and tab == "Vocab Trainer":
    st.header("🧠 Vocab Trainer")

    # -------- Daily Limit (separate from others) --------
    VOCAB_DAILY_LIMIT = 20
    vocab_usage_key = f"{st.session_state['student_code']}_vocab_{str(date.today())}"
    if "vocab_usage" not in st.session_state:
        st.session_state["vocab_usage"] = {}
    st.session_state["vocab_usage"].setdefault(vocab_usage_key, 0)

    st.info(f"Today's Vocab checks: {st.session_state['vocab_usage'][vocab_usage_key]}/{VOCAB_DAILY_LIMIT}")

    # -------- Level selection and vocab pool --------
    vocab_level = st.selectbox(
        "Choose your level:", ["A1", "A2", "B1", "B2", "C1"], key="vocab_level"
    )
    vocab_list = VOCAB_LISTS.get(vocab_level, [])
    if not vocab_list:
        st.warning("No vocab available for this level.")
        st.stop()

    # -------- Preview all option --------
    if st.button("Preview All Vocabulary"):
        st.write(f"**{vocab_level} Vocab List:**")
        st.write(", ".join(vocab_list))
        st.stop()

    # -------- Vocab practice --------
    if st.session_state["vocab_usage"][vocab_usage_key] >= VOCAB_DAILY_LIMIT:
        st.warning("You've reached today's Vocab Trainer limit. Come back tomorrow!")
    else:
        # Pick a random vocab each time
        if "current_vocab_word" not in st.session_state or st.button("Next Word"):
            st.session_state["current_vocab_word"] = random.choice(vocab_list)
            st.session_state["vocab_result"] = ""

        word = st.session_state["current_vocab_word"]
        st.write(f"**Translate this German word to English:**")
        st.subheader(f"👉 {word}")

        answer = st.text_input("Your English translation", key="vocab_answer")

        if st.button("Check My Answer"):
            # AI prompt
            prompt = (
                f"Is the English translation for the German word '{word}' correct if the student says '{answer}'? "
                "Reply 'Correct!' if it is, otherwise reply 'Incorrect' and provide the correct answer."
            )
            with st.spinner("🧑‍🏫 Herr Felix is checking..."):
                try:
                    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                    resp = client.chat.completions.create(
                        model="gpt-4o", messages=[{"role": "system", "content": prompt}]
                    )
                    ai_result = resp.choices[0].message.content.strip()
                except Exception as e:
                    ai_result = f"Error: {str(e)}"

            st.session_state["vocab_result"] = ai_result
            st.session_state["vocab_usage"][vocab_usage_key] += 1

        if st.session_state.get("vocab_result"):
            st.success(st.session_state["vocab_result"])

# =========================================
# SCHREIBEN TRAINER TAB (A1–C1, Free Input)
# =========================================

if st.session_state.get("logged_in") and tab == "Schreiben Trainer":
    st.header("✍️ Schreiben Trainer")

    # -------- Daily Limit (separate from others) --------
    SCHREIBEN_DAILY_LIMIT = 5
    schreiben_usage_key = f"{st.session_state['student_code']}_schreiben_{str(date.today())}"
    if "schreiben_usage" not in st.session_state:
        st.session_state["schreiben_usage"] = {}
    st.session_state["schreiben_usage"].setdefault(schreiben_usage_key, 0)

    st.info(f"Today's Schreiben submissions: {st.session_state['schreiben_usage'][schreiben_usage_key]}/{SCHREIBEN_DAILY_LIMIT}")

    schreiben_level = st.selectbox(
        "Select your level:",
        ["A1", "A2", "B1", "B2", "C1"],
        key="schreiben_level_select"
    )

    if st.session_state["schreiben_usage"][schreiben_usage_key] >= SCHREIBEN_DAILY_LIMIT:
        st.warning("You've reached today's Schreiben submission limit. Please come back tomorrow!")
    else:
        st.write("**Paste your letter or essay below.** Herr Felix will mark it as a real Goethe examiner and give you feedback.")
        schreiben_text = st.text_area("Your letter/essay", height=250, key=f"schreiben_text_{schreiben_level}")

        if st.button("Check My Writing"):
            if not schreiben_text.strip():
                st.warning("Please write something before submitting.")
            else:
                # AI Prompt (no need for exam question)
                ai_prompt = (
                    f"You are Herr Felix, a strict but supportive Goethe examiner. "
                    f"The student has submitted a {schreiben_level} German letter or essay. "
                    "1. Read the full text. Mark and correct grammar/spelling/structure mistakes, and provide a clear correction. "
                    "2. Write a brief comment in English about what the student did well and what they should improve. "
                    "3. Show the full corrected letter (in bold or highlight the changes if possible). "
                    "Do NOT give a grade—just corrections and encouragement."
                )
                ai_message = (
                    f"{ai_prompt}\n\nStudent's letter/essay:\n{schreiben_text}"
                )

                with st.spinner("🧑‍🏫 Herr Felix is marking..."):
                    try:
                        client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                        response = client.chat.completions.create(
                            model="gpt-4o",
                            messages=[{"role": "system", "content": ai_message}]
                        )
                        ai_feedback = response.choices[0].message.content.strip()
                    except Exception as e:
                        ai_feedback = f"Error: {str(e)}"

                st.success("📝 **Feedback from Herr Felix:**")
                st.markdown(ai_feedback)
                st.session_state["schreiben_usage"][schreiben_usage_key] += 1
