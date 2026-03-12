import streamlit as st
import pandas as pd
import tempfile

from video_qc import run_video_qc

st.set_page_config(page_title="AI Amendment Bot — QC Board", layout="wide")

st.markdown("### Koochester")
st.title("AI Amendment Bot — QC Board")

st.caption("Upload a video → generate transcript → run QC on spoken content.")

uploaded = st.file_uploader("Upload video", type=["mp4", "mov", "mkv", "mpeg4"])

if uploaded:
    with tempfile.NamedTemporaryFile(delete=False, suffix="." + uploaded.name.split(".")[-1]) as tmp:
        tmp.write(uploaded.getbuffer())
        video_path = tmp.name

    if st.button("Analyze Video"):
        with st.spinner("Transcribing and analyzing video..."):
            rows = run_video_qc(video_path)

        if not rows:
            st.success("No issues found ✅")
        else:
            df = pd.DataFrame(rows)

            st.subheader("QC Board")
            st.dataframe(df, use_container_width=True, height=520)

            st.download_button(
                "Download Report (CSV)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="video_qc_report.csv",
                mime="text/csv"
            )
else:
    st.info("Upload a video to start.")