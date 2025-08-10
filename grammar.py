
Skip to content
Navigation Menu
learngermanghana
linguaspark

Code
Issues
Pull requests 3
Actions
Projects
Wiki
Security
Insights

    Settings

    linguaspark

/
in
main

Indent mode
Indent size
Line wrap mode
Editing lingua.py file contents
Selection deleted
4704
4705
4706
4707
4708
4709
4710
4711
4712
4713
4714
4715
4716
4717
4718
4719
4720
4721
4722
4723
4724
4725
4726
4727
4728
4729
4730
4731
4732
4733
4734
4735
4736
4737
4738
4739
4740
4741
4742
4743
4744
4745
4746
4747
4748
4749
4750
4751
4752
4753
4754
4755
4756
4757
4758
4759
4760
4761
4762
4763
4764
4765
4766
4767
4768
4769
4770
4771
4772
4773
4774
4775
4776
4777
4778
4779
4780
4781
4782
            def render_announcement(row, is_pinned=False):
                ts_label = _fmt_dt_label(row.get("__dt"))
                st.markdown(
                    (
                        f"<div style='padding:10px 12px; background:{'#fff7ed' if is_pinned else '#f8fafc'}; "
                        f"border:1px solid #e5e7eb; border-radius:8px; margin:8px 0;'>"
                        f"{'📌 <b>Pinned</b> • ' if is_pinned else ''}"
                        f"<b>Teacher</b> "
                        f"<span style='color:#888;'>{ts_label} GMT</span><br>"
                        f"{row.get('Announcement','')}"
                        f"</div>"
                    ),
                    unsafe_allow_html=True,
                )

                # Replies (Firestore)
                ann_id = row.get("__id")
                replies = get_replies(class_name, ann_id)

                if replies:
                    for r in replies:
                        when = ""
                        ts = r.get("timestamp")
                        try:
                            when = ts.strftime("%d %b %H:%M") + " UTC"
                        except Exception:
                            when = ""
                        st.markdown(
                            f"<div style='margin-left:20px; color:#444;'>↳ <b>{r.get('student_name','')}</b> "
                            f"<span style='color:#bbb;'>{when}</span><br>"
                            f"{r.get('text','')}</div>",
                            unsafe_allow_html=True,
                        )

                with st.expander("Reply"):
                    reply_text = st.text_area(
                        f"Reply to {ann_id}",
                        key=f"reply_{ann_id}",
                        height=90,
                        placeholder="Write your reply…"
                    )
                    if st.button("Send Reply", key=f"reply_btn_{ann_id}") and reply_text.strip():
                        post_reply(class_name, ann_id, student_code, student_name, reply_text)
                        st.success("Reply sent!")
                        st.rerun()

            # Render lists
            for _, row in pinned_df.iterrows():
                render_announcement(row, is_pinned=True)
            for _, row in latest_df.iterrows():
                render_announcement(row, is_pinned=False)
#







#Myresults
def linkify_html(text):
    """Escape HTML and convert URLs in plain text to anchor tags."""
    s = "" if text is None or (isinstance(text, float) and pd.isna(text)) else str(text)
    s = html_stdlib.escape(s)  # <-- use stdlib html, not the component
    s = re.sub(r'(https?://[^\s<]+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)
    return s


def _clean_link(val) -> str:
    """Return a clean string or '' if empty/NaN/common placeholders."""
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    s = str(val).strip()
    if s.lower() in {"", "nan", "none", "null", "0"}:
        return ""
    return s

Use Control + Shift + m to toggle the tab key moving focus. Alternatively, use esc then tab to move to the next interactive element on the page.
Editing linguaspark/lingua.py at main · learngermanghana/linguaspark
