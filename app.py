import json
import os
import tempfile
import time

import pandas as pd
import streamlit as st

from activity_log import ActivityLog, attach_progress_callback, render_sidebar
from export_utils import build_report_docx_bytes
from job_store import download_result, get_job, submit_analysis_job
from video_qc import run_qc_checks_only
from google_drive import download_drive_video, is_drive_url, GDOWN_AVAILABLE


st.set_page_config(page_title="AI Amendment Bot — QC Board", layout="wide")

st.markdown(
    """
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@900&display=swap" rel="stylesheet">
    <div style="line-height:1.1; margin-bottom: 4px;">
        <a href="https://koocester.com/" target="_blank" style="text-decoration:none;">
            <span style="font-family:'Montserrat',sans-serif; font-size:2rem; font-weight:900; color:#ffffff; letter-spacing:-1px;">koocester</span><br>
            <span style="font-family:'Montserrat',sans-serif; font-size:2rem; font-weight:900; color:#e8192c; letter-spacing:-1px;">group</span>
        </a>
    </div>
    """,
    unsafe_allow_html=True,
)
st.title("AI Amendment Bot — QC Board")
st.info(
    "**what this bot does** — upload a video and the ai will review it across "
    "five areas: story clarity, information clarity, visuals, audio, and a full qc board "
    "with specific issues flagged by timestamp and severity. "
    "use the sidebar to tell the ai what kind of content it is so the review is more accurate.",
    icon="ℹ️",
)


# ---------- Sidebar: channel context, filters, reset ----------
with st.sidebar:
    st.header("Settings")
    st.caption("Tell the bot what kind of video this is so it applies the right Koocester SOP rules.")

    content_type = st.selectbox(
        "Content type",
        options=["Business & Wealth", "Homes", "Autos", "Foodie", "General"],
        index=["Business & Wealth", "Homes", "Autos", "Foodie", "General"].index(
            st.session_state.get("content_type", "General")
        ),
        help="Sets which Koocester title card, subtitle, and brand rules to check against.",
    )
    st.caption("this controls which SOP rules the bot checks — title card format, colours, and brand elements vary by content type.")
    st.session_state["content_type"] = content_type

    severity_filter = st.multiselect(
        "QC severity filter",
        ["High", "Medium", "Low"],
        default=st.session_state.get("severity_filter", ["High", "Medium", "Low"]),
        help="Filter the QC board below.",
    )
    st.caption("use this to show only the issues that matter most. high = must fix, medium = good to fix, low = minor.")
    st.session_state["severity_filter"] = severity_filter

    st.divider()
    if st.button("Reset analysis", use_container_width=True):
        for key in (
            "qc_result", "video_path", "video_bytes", "video_mime",
            "uploaded_name", "activity_log_entries", "activity_log_started_at",
            "edited_transcript_text", "analysis_job_id", "analysis_job_started_at",
            "analysis_job_status",
        ):
            st.session_state.pop(key, None)
        st.rerun()

    st.divider()
    # Live AI activity feed — populated by activity_log module.
    activity_log = ActivityLog.get()
    activity_placeholder = st.empty()
    render_sidebar(activity_log, activity_placeholder)


# ---------- Helpers ----------
SEVERITY_COLORS = {
    "High": ("#ff4b4b", "white"),
    "Medium": ("#ffa500", "black"),
    "Low": ("#4caf50", "white"),
}


def color_severity(val):
    bg_fg = SEVERITY_COLORS.get(val)
    if not bg_fg:
        return ""
    bg, fg = bg_fg
    return f"background-color: {bg}; color: {fg};"


def score_emoji(score):
    try:
        s = int(score)
    except Exception:
        return ""
    if s >= 5:
        return "🟢"
    if s == 4:
        return "🟢"
    if s == 3:
        return "🟡"
    if s == 2:
        return "🟠"
    return "🔴"


def _mmss_to_seconds(value):
    """Convert 'MM:SS' (or seconds) to int seconds. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s or s.upper() == "N/A":
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                mm, ss = parts
                return int(mm) * 60 + int(ss)
            if len(parts) == 3:
                hh, mm, ss = parts
                return int(hh) * 3600 + int(mm) * 60 + int(ss)
        except ValueError:
            return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _transcript_context_for_timestamp(segment_data, target_ts, window=1):
    """Return a list of nearby segments around the target timestamp."""
    if not segment_data:
        return []
    target_sec = _mmss_to_seconds(target_ts)
    if target_sec is None:
        return []

    indexed = []
    for i, seg in enumerate(segment_data):
        if not isinstance(seg, dict):
            continue
        seg_sec = _mmss_to_seconds(seg.get("start"))
        if seg_sec is None:
            continue
        indexed.append((i, seg_sec, seg))

    if not indexed:
        return []

    # Pick the closest segment to the target.
    closest_idx = min(range(len(indexed)), key=lambda j: abs(indexed[j][1] - target_sec))
    lo = max(0, closest_idx - window)
    hi = min(len(indexed), closest_idx + window + 1)
    return [indexed[j][2] for j in range(lo, hi)]


def _persist_uploaded_video(uploaded):
    """Save uploaded bytes to a temp file ONCE per upload, store path in session_state."""
    if st.session_state.get("uploaded_name") == uploaded.name and st.session_state.get("video_path"):
        return st.session_state["video_path"]

    # Clean up any prior temp file before replacing.
    prior = st.session_state.get("video_path")
    if prior and os.path.exists(prior):
        try:
            os.remove(prior)
        except OSError:
            pass

    suffix = "." + uploaded.name.split(".")[-1] if "." in uploaded.name else ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.getbuffer())
        path = tmp.name

    st.session_state["uploaded_name"] = uploaded.name
    st.session_state["video_path"] = path
    st.session_state["video_bytes"] = uploaded.getbuffer().tobytes()
    st.session_state["video_mime"] = uploaded.type or "video/mp4"
    # New upload invalidates any prior result.
    st.session_state.pop("qc_result", None)
    st.session_state.pop("edited_transcript_text", None)
    st.session_state.pop("analysis_job_id", None)
    st.session_state.pop("analysis_job_started_at", None)
    st.session_state.pop("analysis_job_status", None)
    return path


# ---------- Upload ----------
tab_upload, tab_drive = st.tabs(["📁 Upload file", "☁️ Google Drive link"])

# --- Tab 1: direct file upload ---
with tab_upload:
    uploaded = st.file_uploader("Upload video", type=["mp4", "mov", "mkv", "mpeg4"])

    if uploaded:
        video_path = _persist_uploaded_video(uploaded)

        size_mb = len(st.session_state["video_bytes"]) / (1024 * 1024)

        preview_col, info_col = st.columns([2, 1])
        with preview_col:
            st.video(st.session_state["video_bytes"])
        with info_col:
            st.metric("File size", f"{size_mb:.1f} MB")
            st.write(f"**File name:** {uploaded.name}")
            if size_mb > 200:
                st.warning(
                    "Large file — transcription and analysis may take several minutes "
                    "and cost more API credits."
                )

# --- Tab 2: Google Drive link ---
with tab_drive:
    st.caption(
        "paste a google drive share link below. "
        "the file must be set to **'anyone with the link can view'** in google drive — "
        "private links won't work. to check: open the file in drive → share → change to 'anyone with the link'."
    )

    drive_url = st.text_input(
        "Google Drive link",
        placeholder="https://drive.google.com/file/d/abc123.../view?usp=sharing",
        key="drive_url_input",
    )

    drive_load_clicked = st.button(
        "Load from Drive",
        disabled=not drive_url.strip(),
        key="drive_load_btn",
    )

    if drive_load_clicked and drive_url.strip():
        if not GDOWN_AVAILABLE:
            st.error("gdown is not installed. Run: pip install gdown")
        elif not is_drive_url(drive_url.strip()):
            st.error("That doesn't look like a Google Drive link. Make sure you're pasting the full share URL.")
        else:
            with st.spinner("Downloading from Google Drive..."):
                try:
                    drive_path = download_drive_video(drive_url.strip())
                    # Store in session state the same way the uploader does
                    with open(drive_path, "rb") as f:
                        drive_bytes = f.read()
                    st.session_state["uploaded_name"] = f"drive_{drive_url[-20:].replace('/', '_')}.mp4"
                    st.session_state["video_path"] = drive_path
                    st.session_state["video_bytes"] = drive_bytes
                    st.session_state["video_mime"] = "video/mp4"
                    st.session_state.pop("qc_result", None)
                    st.session_state.pop("edited_transcript_text", None)
                    st.session_state.pop("analysis_job_id", None)
                    st.session_state.pop("analysis_job_started_at", None)
                    st.session_state.pop("analysis_job_status", None)
                    st.success("Video loaded from Google Drive.")
                except RuntimeError as e:
                    st.error(str(e))

    # Show preview if a Drive video was loaded
    if st.session_state.get("video_bytes") and st.session_state.get("uploaded_name", "").startswith("drive_"):
        size_mb = len(st.session_state["video_bytes"]) / (1024 * 1024)
        prev_col, info_col = st.columns([2, 1])
        with prev_col:
            st.video(st.session_state["video_bytes"])
        with info_col:
            st.metric("File size", f"{size_mb:.1f} MB")

# --- Shared: show Analyze button if any video is ready ---
video_ready = bool(st.session_state.get("video_path") and st.session_state.get("video_bytes"))

if video_ready:

    analyze_clicked = st.button(
        "Analyze Video",
        type="primary",
        disabled=bool(st.session_state.get("qc_result") or st.session_state.get("analysis_job_id")),
        help="Submit the video to the background QC worker. Use 'Reset analysis' in the sidebar to re-run.",
    )

    if analyze_clicked:
        try:
            activity_log.reset()
            activity_log.emit("job_submit", "Uploading video and creating background analysis job...")
            render_sidebar(activity_log, activity_placeholder)
            job = submit_analysis_job(
                st.session_state["video_bytes"],
                st.session_state.get("uploaded_name", "video.mp4"),
                st.session_state.get("content_type", "General"),
            )
            st.session_state["analysis_job_id"] = job["id"]
            st.session_state["analysis_job_started_at"] = time.time()
            st.session_state["analysis_job_status"] = job.get("status", "queued")
            st.session_state.pop("edited_transcript_text", None)
        except Exception as exc:
            st.error(
                "Could not submit analysis job. Check Supabase secrets, bucket name, "
                "and storage/table permissions."
            )
            st.exception(exc)
            st.stop()
        st.rerun()

    job_id = st.session_state.get("analysis_job_id")
    if job_id and not st.session_state.get("qc_result"):
        started_at = st.session_state.get("analysis_job_started_at") or time.time()
        elapsed = int(time.time() - started_at)

        try:
            job = get_job(job_id)
        except Exception as exc:
            st.error("Could not check analysis job status.")
            st.exception(exc)
            job = None

        if job:
            status = job.get("status", "queued")
            st.session_state["analysis_job_status"] = status

            if status == "done" and job.get("result_path"):
                with st.spinner("Loading completed QC report..."):
                    result = download_result(job["result_path"])
                st.session_state["qc_result"] = result
                st.session_state.pop("analysis_job_id", None)
                st.session_state.pop("analysis_job_status", None)
                st.success("Analysis complete")
                st.rerun()

            elif status == "failed":
                st.error("Analysis failed in the background worker.")
                if job.get("error"):
                    st.code(job["error"])
                if st.button("Clear failed job", key="clear_failed_job"):
                    st.session_state.pop("analysis_job_id", None)
                    st.session_state.pop("analysis_job_started_at", None)
                    st.session_state.pop("analysis_job_status", None)
                    st.rerun()

            else:
                worker_progress = job.get("progress", "")
                if status == "queued":
                    progress_text = "Queued for analysis..."
                    bar_value = 0.15
                else:
                    # Show the latest stage message from the worker if available
                    stage_label = worker_progress.split(": ", 1)[-1] if worker_progress else ""
                    progress_text = f"Worker is analyzing your video... {stage_label}".rstrip()
                    bar_value = 0.65

                st.progress(
                    bar_value,
                    text=f"{progress_text}  •  {elapsed}s elapsed",
                )
                if worker_progress:
                    st.caption(f"Last worker update: {worker_progress}")
                st.caption(f"Job ID: {job_id}")
                time.sleep(5)
                st.rerun()


# ---------- Render results from session_state (so widget interactions don't re-run analysis) ----------
result = st.session_state.get("qc_result")

if result:
    summary = result.get("summary") or {}
    info = result.get("info") or {}
    story_clarity = result.get("story_clarity") or {}
    visual = result.get("visual") or {}
    audio = result.get("audio") or {}
    rows = result.get("rows") or []
    transcript = result.get("transcript") or ""
    segment_data = result.get("segment_data") or []
    frames = result.get("frames") or []
    audio_warning = result.get("audio_warning")

    # ----- Audio quality warning (shown up top so users see it first) -----
    if audio_warning:
        msg = "  \n".join(f"• {m}" for m in audio_warning.get("messages", []))
        if audio_warning.get("severity") == "high":
            st.error(f"**Audio quality alert** — transcription accuracy may suffer.\n\n{msg}")
        else:
            st.warning(f"**Audio quality notice**\n\n{msg}")

    # ----- Export buttons -----
    docx_bytes = build_report_docx_bytes(result)

    json_payload = json.dumps(
        {
            "summary": summary,
            "info": info,
            "visual": visual,
            "audio": audio,
            "rows": rows,
            "transcript": transcript,
        },
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")

    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8") if rows else b""

    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        st.download_button(
            "⬇️ DOCX report",
            data=docx_bytes,
            file_name="ai_qc_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            "⬇️ CSV (QC rows)",
            data=csv_bytes,
            file_name="video_qc_report.csv",
            mime="text/csv",
            disabled=not rows,
            use_container_width=True,
        )
    with dl3:
        st.download_button(
            "⬇️ JSON (full result)",
            data=json_payload,
            file_name="video_qc_report.json",
            mime="application/json",
            use_container_width=True,
        )

    st.success("Analysis complete")

    # ----- Score row with emoji color cues -----
    col1, col2, col3, col4, col5 = st.columns(5)
    story_score = story_clarity.get("score", 3)
    info_score = info.get("score", 3)
    visual_score = visual.get("score", 3)
    audio_score = audio.get("score", 3)

    col1.metric("Story Clarity", f"{score_emoji(story_score)} {story_score}/5")
    col2.metric("Info Clarity", f"{score_emoji(info_score)} {info_score}/5")
    col3.metric("Visuals", f"{score_emoji(visual_score)} {visual_score}/5")
    col4.metric("Audio", f"{score_emoji(audio_score)} {audio_score}/5")
    col5.metric("Predicted Retention", summary.get("retention", "Medium"))

    # ----- Overall review -----
    st.subheader("Overall Review")
    st.write(summary.get("overall_review", "No overall review generated."))

    suggestions = summary.get("suggestions", [])
    if suggestions:
        st.subheader("Top Suggestions")
        for item in suggestions:
            st.write(f"- {item}")

    # ----- Story Clarity -----
    st.subheader("Story Clarity")
    st.write(story_clarity.get("summary", "No story clarity summary generated."))

    sc_strengths = story_clarity.get("strengths", [])
    sc_improvements = story_clarity.get("improvements", [])

    if sc_strengths:
        st.write("**Strengths**")
        for item in sc_strengths:
            st.write(f"- {item}")

    if sc_improvements:
        st.write("**Suggested Improvements**")
        for item in sc_improvements:
            st.write(f"- {item}")

    # ----- QC Board -----
    st.subheader("QC Board")
    if rows:
        df = pd.DataFrame(rows)

        preferred_order = [
            "Timestamp",
            "Type",
            "Location",
            "Snippet",
            "Issue",
            "Suggestion",
            "Severity",
        ]
        df = df[[c for c in preferred_order if c in df.columns]]

        active_filters = st.session_state.get("severity_filter") or list(SEVERITY_COLORS.keys())
        if "Severity" in df.columns and active_filters:
            df = df[df["Severity"].isin(active_filters)]

        if df.empty:
            st.info("No QC rows match the selected severity filter.")
        else:
            styled_df = df.style.map(
                color_severity,
                subset=["Severity"] if "Severity" in df.columns else [],
            )
            st.dataframe(styled_df, use_container_width=True, height=520)

            # ----- Issue cards: transcript context + jump-to-timestamp -----
            st.markdown("#### Issue details")
            st.caption(
                "Click an issue to expand it. 'Jump to' loads the video at "
                "that moment in the player below."
            )

            visible_rows = df.to_dict(orient="records")
            for i, row in enumerate(visible_rows):
                ts = row.get("Timestamp", "N/A")
                sev = row.get("Severity", "Medium")
                sev_emoji = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}.get(sev, "⚪")
                header = (
                    f"{sev_emoji} [{ts}] **{row.get('Type', '')}** — "
                    f"{row.get('Issue', '')[:80]}"
                )
                with st.expander(header, expanded=False):
                    st.markdown(f"**Severity:** {sev}")
                    st.markdown(f"**Location:** {row.get('Location', '—')}")
                    st.markdown(f"**Timestamp:** {ts}")
                    snippet = row.get("Snippet", "")
                    if snippet:
                        st.markdown(f"**Snippet:** _{snippet}_")
                    st.markdown(f"**Issue:** {row.get('Issue', '')}")
                    st.markdown(f"**Suggestion:** {row.get('Suggestion', '')}")

                    # Surrounding transcript context
                    context_segs = _transcript_context_for_timestamp(
                        segment_data, ts, window=1
                    )
                    if context_segs:
                        st.markdown("**Transcript context:**")
                        for seg in context_segs:
                            seg_start = seg.get("start", "N/A")
                            seg_text = (seg.get("text", "") or "").strip()
                            st.markdown(f"`[{seg_start}]` {seg_text}")

                    # Jump-to-timestamp button
                    target_sec = _mmss_to_seconds(ts)
                    if target_sec is not None:
                        if st.button(
                            f"▶ Jump to {ts}",
                            key=f"jump_{i}_{ts}",
                            use_container_width=False,
                        ):
                            st.session_state["jump_to_time"] = target_sec
                            st.rerun()

            # ----- Inline jump-to playback -----
            jump_to = st.session_state.get("jump_to_time")
            if jump_to is not None and st.session_state.get("video_bytes"):
                st.markdown("#### Playback at issue timestamp")
                st.video(
                    st.session_state["video_bytes"],
                    start_time=int(jump_to),
                )
                if st.button("Clear playback", key="clear_jump"):
                    st.session_state.pop("jump_to_time", None)
                    st.rerun()
    else:
        st.info("No QC rows returned.")

    # ----- Information clarity + visuals (two columns) -----
    left, right = st.columns(2)

    with left:
        st.subheader("Information Clarity")
        st.write(info.get("summary", "No information clarity summary generated."))

        strengths = info.get("strengths", [])
        improvements = info.get("improvements", [])

        if strengths:
            st.write("**Strengths**")
            for item in strengths:
                st.write(f"- {item}")

        if improvements:
            st.write("**Suggested Improvements**")
            for item in improvements:
                st.write(f"- {item}")

    with right:
        st.subheader("Visual Review")
        st.write(visual.get("summary", "No visual review generated."))

        if visual.get("strengths"):
            st.write("**Strengths**")
            for item in visual["strengths"]:
                st.write(f"- {item}")

        if visual.get("issues"):
            st.write("**Issues**")
            for item in visual["issues"]:
                st.write(f"- {item}")

        if visual.get("suggestions"):
            st.write("**Suggestions**")
            for item in visual["suggestions"]:
                st.write(f"- {item}")

        # Frame thumbnails
        if frames:
            with st.expander("Sampled frames", expanded=False):
                cols = st.columns(min(4, len(frames)))
                for i, frame in enumerate(frames):
                    b64 = frame.get("base64")
                    ts = frame.get("timestamp", "N/A")
                    if not b64:
                        continue
                    cols[i % len(cols)].image(
                        f"data:image/jpeg;base64,{b64}",
                        caption=f"t={ts}",
                        use_container_width=True,
                    )
        elif visual.get("frame_timestamps"):
            st.caption("Sampled frames: " + ", ".join(visual["frame_timestamps"]))

    # ----- Audio review -----
    st.subheader("Audio Review")
    st.write(audio.get("summary", "No audio review generated."))

    audio_left, audio_right = st.columns(2)

    with audio_left:
        if audio.get("strengths"):
            st.write("**Strengths**")
            for item in audio["strengths"]:
                st.write(f"- {item}")

        if audio.get("issues"):
            st.write("**Issues**")
            for item in audio["issues"]:
                st.write(f"- {item}")

    with audio_right:
        if audio.get("suggestions"):
            st.write("**Suggestions**")
            for item in audio["suggestions"]:
                st.write(f"- {item}")

        if audio.get("timestamp_notes"):
            st.write("**Timestamp Notes**")
            for item in audio["timestamp_notes"]:
                st.write(f"- {item}")

    # ----- Transcript with timestamps -----
    with st.expander("Transcript with timestamps", expanded=False):
        if segment_data:
            for seg in segment_data:
                start = seg.get("start", "N/A")
                text = seg.get("text", "").strip()
                if text:
                    st.markdown(f"**[{start}]** {text}")
        else:
            st.write(transcript or "_No transcript available._")

    # ----- Correct transcript & Re-Analyse -----
    st.divider()
    st.subheader("✏️ Correct transcript & re-analyse")
    st.caption(
        "spotted a transcription mistake? fix it below and click **re-analyse** — "
        "all QC checks will re-run with the corrected text. "
        "transcription won't re-run, so this is much faster than a full analysis. "
        "example: change 'one door two door' → 'one dog two dog'."
    )

    edited_transcript = st.text_area(
        "Transcript",
        value=st.session_state.get("edited_transcript_text", transcript),
        height=220,
        key="transcript_editor",
        placeholder="Your transcript will appear here after analysis...",
    )

    reanalyse_clicked = st.button(
        "🔄 Re-Analyse",
        type="primary",
        disabled=not bool(result.get("audio_base64")),
        help="Re-run all QC checks with the corrected transcript above.",
    )

    if reanalyse_clicked:
        st.session_state["edited_transcript_text"] = edited_transcript
        stored_frames = result.get("frames") or []
        stored_audio_b64 = result.get("audio_base64") or ""
        stored_glossary = result.get("glossary") or []
        stored_segment_data = result.get("segment_data") or []
        stored_video_path = st.session_state.get("video_path") or ""
        stored_end_frames = result.get("end_frames") or []
        stored_dense_cta_frames = result.get("dense_cta_frames") or []

        ra_progress_bar = st.progress(0.0, text="Re-analysing...")
        ra_start = time.time()

        ra_stage_progress = {
            "checks": 0.05,
            "dedupe": 0.90,
            "done": 1.00,
        }

        activity_log.reset()
        sidebar_progress_ra = attach_progress_callback(activity_log, activity_placeholder)

        def ra_progress(stage, message):
            sidebar_progress_ra(stage, message)
            pct = ra_stage_progress.get(stage, 0.0)
            elapsed = int(time.time() - ra_start)
            ra_progress_bar.progress(
                min(pct, 1.0),
                text=f"Re-analysing... {int(pct * 100)}%  •  {elapsed}s elapsed",
            )

        try:
            with st.status("Re-analysing with corrected transcript...", expanded=True) as ra_status:
                ra_result = run_qc_checks_only(
                    transcript=edited_transcript,
                    frames=stored_frames,
                    audio_base64=stored_audio_b64,
                    segment_data=stored_segment_data,
                    video_path=stored_video_path,
                    glossary=stored_glossary,
                    progress=ra_progress,
                    content_type=st.session_state.get("content_type", "General"),
                    dense_cta_frames=stored_dense_cta_frames,
                    end_frames=stored_end_frames,
                )
                ra_status.update(label="Re-analysis complete", state="complete", expanded=False)

            ra_progress_bar.progress(
                1.0,
                text=f"✅ Re-analysis complete  •  {int(time.time() - ra_start)}s",
            )

            # Merge new results back — preserve frames, audio_base64,
            # audio_warning, segment_data, glossary from the original run.
            updated_result = dict(result)
            updated_result.update(ra_result)
            updated_result["transcript"] = edited_transcript
            st.session_state["qc_result"] = updated_result
            st.rerun()
        except Exception as exc:
            ra_progress_bar.progress(1.0, text="❌ Re-analysis failed")
            st.error("Re-analysis failed.")
            st.exception(exc)

elif not video_ready:
    st.info("Upload a video or load one from Google Drive to start.")
# end of app.py
