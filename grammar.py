def schreiben_trainer_tab():
    """Schreiben Trainer interface with feedback, PDF export, WhatsApp link, and stats."""
    st.header("✍️ Schreiben Trainer")
    # Initialize usage counter
    student_code = st.session_state.student_code
    student_name = st.session_state.student_name
    today_str = str(date.today())
    usage_key = f"{student_code}_schreiben_{today_str}"
    if "schreiben_usage" not in st.session_state:
        st.session_state.schreiben_usage = {}
    st.session_state.schreiben_usage.setdefault(usage_key, 0)

    # Initialize or connect to writing feedback DB
    conn = sqlite3.connect(VOCAB_DB, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS schreiben_feedback (
            student_code TEXT,
            date TEXT,
            level TEXT,
            score INTEGER,
            strengths TEXT,
            weaknesses TEXT
        )"""
    )
    conn.commit()

    # Show latest feedback stats
    with st.expander("📈 Your Writing Progress", expanded=True):
        c.execute(
            "SELECT date, level, score, strengths, weaknesses"
            " FROM schreiben_feedback WHERE student_code=?"
            " ORDER BY date DESC LIMIT 1",
            (student_code,),
        )
        row = c.fetchone()
        if row:
            st.markdown(
                f"**Last Attempt:** {row[0]}  \n"
                f"**Level:** {row[1]}  \n"
                f"**Score:** {row[2]} / 25  \n"
                f"**Strengths:** {row[3] or '–'}  \n"
                f"**Needs Improvement:** {row[4] or '–'}"
            )
        else:
            st.write("_No submissions yet. Your progress will appear here!_\n")

    st.info(
        f"Today's Schreiben submissions: {st.session_state.schreiben_usage[usage_key]}/{SCHREIBEN_DAILY_LIMIT}"
    )

    # Level selection
    schreiben_level = st.selectbox(
        "Select your level:",
        ["A1", "A2", "B1", "B2", "C1"],
        key="schreiben_level_select"
    )

    # Check usage limit
    if st.session_state.schreiben_usage[usage_key] >= SCHREIBEN_DAILY_LIMIT:
        st.warning("You've reached today's Schreiben submission limit. Please come back tomorrow!")
        return

    # Text input
    schreiben_text = st.text_area(
        "**Paste your letter or essay below.** Herr Felix will mark it as a real Goethe examiner and give you feedback.",
        height=250,
        key=f"schreiben_text_{schreiben_level}"
    )

    if st.button("Check My Writing"):
        if not schreiben_text.strip():
            st.warning("Please write something before submitting.")
        else:
            # Build the AI prompt
            ai_prompt = (
                f"You are Herr Felix, a strict but supportive Goethe examiner. "
                f"The student has submitted a {schreiben_level} German letter or essay. "
                "Talk as the tutor in English to explain mistakes. Use 'you' for the student to sound direct. "
                "Read the full text. Mark and correct grammar/spelling/structure mistakes, and provide a clear correction. "
                "Write a brief comment in English about what the student did well and what they should improve. "
                "Give a score out of 25 marks, with reasoning (grammar, spelling, vocab, structure). "
                "Show strengths, weaknesses, suggested phrases, vocabulary, conjunctions for next time. Also check if letter matches their level. "
                "If score is above 17, say they have passed and can submit to tutor. If below, tell them to improve."
            )
            ai_message = f"{ai_prompt}\n\nStudent's letter/essay:\n{schreiben_text}"

            with st.spinner("🧑‍🏫 Herr Felix is marking..."):
                try:
                    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "system", "content": ai_message}]
                    )
                    ai_feedback = response.choices[0].message.content.strip()
                except Exception as e:
                    st.error(f"Error: {e}")
                    return

            # Display feedback
            st.success("📝 **Feedback from Herr Felix:**")
            st.markdown(ai_feedback)

            # PDF download
            pdf_bytes = generate_pdf(
                student=student_name,
                level=schreiben_level,
                original=schreiben_text,
                feedback=ai_feedback
            )
            st.download_button(
                label="⬇️ Download Feedback as PDF", 
                data=pdf_bytes,
                file_name=f"Schreiben_Feedback_{schreiben_level}_{date.today()}.pdf",
                mime="application/pdf"
            )

            # WhatsApp link
            assignment_msg = (
                f"Hallo Herr Felix! Hier ist mein Schreiben für die Korrektur ({schreiben_level}):\n\n"
                f"{schreiben_text}\n\n---\nFeedback: {ai_feedback[:600]}..."
            )
            whatsapp_url = (
                "https://api.whatsapp.com/send"
                f"?phone=233205706589&text={assignment_msg.replace(' ', '%20').replace('\\n', '%0A')}"
            )
            st.markdown(
                f'<a href="{whatsapp_url}" target="_blank" '
                'style="font-size:1.15rem;background:#1ad03f;padding:9px 18px;'
                'border-radius:10px;text-decoration:none;color:white;">'
                '📲 Send Assignment via WhatsApp</a>',
                unsafe_allow_html=True
            )

            # Save feedback to DB
            import re
            score = None
            m = re.search(r"Score[: ]*([0-9]+)", ai_feedback)
            if m:
                score = int(m.group(1))
            strengths = weaknesses = ""
            if "Strengths:" in ai_feedback:
                strengths = ai_feedback.split("Strengths:")[1].split("\n")[0].strip()
            if "Weaknesses:" in ai_feedback:
                weaknesses = ai_feedback.split("Weaknesses:")[1].split("\n")[0].strip()
            if score is not None:
                c.execute(
                    "INSERT INTO schreiben_feedback (student_code, date, level, score, strengths, weaknesses) VALUES (?,?,?,?,?,?)",
                    (student_code, today_str, schreiben_level, score, strengths, weaknesses)
                )
                conn.commit()

            # Increment usage
            st.session_state.schreiben_usage[usage_key] += 1
