import pathlib
import textwrap

import streamlit as st

st.set_page_config(page_title="Xenom IT Systems Proposal", page_icon="🖋️", layout="centered")

logo_path = pathlib.Path(__file__).resolve().parents[1] / "ChatGPT Image Dec 9, 2025, 10_21_14 AM.png"

st.title("🖋️ Proposal Letter for Xenom IT Systems")
st.caption("A concise overview of our software solutions and contact details.")

if logo_path.exists():
    st.image(str(logo_path), caption="Xenom IT Systems", use_column_width=True)

st.markdown("""
**Xenom IT Solutions**  
Smart, simple software for churches, businesses, and schools.
""")

st.divider()

st.header("Who We Are")
st.write(
    "Xenom IT Solutions is a Ghana-based software company building practical digital tools "
    "that solve real problems in church administration, business inventory & sales, and German language learning. "
    "We are the creators of Apzla, Sedifex, and Falowen."
)

st.divider()

st.header("Our Solutions")

col1, col2 = st.columns(2, gap="large")
with col1:
    st.subheader("1. Apzla – For Churches")
    st.write(
        textwrap.dedent(
            """
            A simple digital system to help churches stay organised and connected.
            Apzla helps you:
            • Keep proper member and visitor records
            • Track attendance for services and events
            • Support departments and ministries with accurate data
            • Share announcements and reminders more efficiently

            For churches and ministries that want to move from paper & scattered WhatsApp chats to one organised system.
            """
        ).strip()
    )

with col2:
    st.subheader("2. Sedifex – For Businesses")
    st.write(
        textwrap.dedent(
            """
            An inventory and sales system for all kinds of businesses and consultancies running a point of sale with customer relationship management.
            Sedifex helps you:
            • Track stock and inventory in real time
            • Record sales and transactions
            • Manage customers and contacts (basic CRM)
            • See simple reports to guide decisions

            For shops, pharmacies, small supermarkets, service businesses, and any organisation that needs clear stock and customer records.
            """
        ).strip()
    )

st.subheader("3. Falowen – For German Learning")
st.write(
    textwrap.dedent(
        """
        A digital platform for German learning and exam preparation, designed to work with schools, training centres, and private tutors.
        Falowen helps you:
        • Support students preparing for Goethe and other exams
        • Provide structured practice for vocabulary, grammar, and speaking
        • Offer a digital extension of your classroom teaching

        For schools and language centres that want a modern tool to support their German programmes.
        """
    ).strip()
)

st.divider()

st.header("Demo & Contact")

contact_col1, contact_col2 = st.columns(2, gap="large")
with contact_col1:
    st.subheader("Apzla (churches) & Sedifex (businesses)")
    st.write(
        """
        Email: sedifexbiz@gmail.com  
        Phone / WhatsApp: +233 59 505 4266  
        Website: [www.sedifex.com](https://www.sedifex.com)
        """
    )

with contact_col2:
    st.subheader("Falowen (German learning & schools)")
    st.write(
        """
        Email: learngermanghana@gmail.com  
        Phone / WhatsApp: +233 20 570 6589  
        Websites: [www.falowen.app](https://www.falowen.app)  
        [www.learngermanghana.com](https://www.learngermanghana.com)
        """
    )

st.info(
    "Choose the solution that fits you and contact us for a demo or meeting."
)
