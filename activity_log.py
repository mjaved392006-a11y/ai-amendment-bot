"""
activity_log.py
---------------
Lightweight activity log used by app.py to display a live "what is the AI
doing right now?" feed in the Streamlit sidebar.

video_qc.py knows nothing about Streamlit. It just emits stage/message pairs
through the `progress` callback. This module consumes those events and
renders them in a sidebar container.

Usage from app.py:

    from activity_log import ActivityLog, render_sidebar

    log = ActivityLog.get()                    # singleton-ish, session_state backed
    placeholder = st.sidebar.container()
    render_sidebar(log, placeholder)           # initial render

    def progress(stage, message):
        log.emit(stage, message)
        render_sidebar(log, placeholder)       # re-render on each event

Usage from video_qc.py:

    from activity_log import pretty_name as _pretty
    progress(stage, message)                   # unchanged — callback abstraction
"""

from datetime import datetime
from typing import List, Dict, Optional


# ---------------------------------------------------------------------------
# Stage taxonomy — controls icon + level shown in the sidebar.
# ---------------------------------------------------------------------------

# Stage prefixes and their display icon + severity. Order matters for prefix
# match: the first matching prefix wins.
STAGE_STYLES = [
    # (prefix, icon, level)
    ("audio_extract_done",  "✅", "ok"),
    ("audio_extract",       "⏳", "info"),
    ("audio_warning",       "⚠️", "warn"),
    ("transcribe_done",     "✅", "ok"),
    ("transcribe",          "⏳", "info"),
    ("glossary_done",       "✅", "ok"),
    ("glossary",            "⏳", "info"),
    ("frames_done",         "✅", "ok"),
    ("frames",              "⏳", "info"),
    ("checks",              "🤖", "info"),
    ("check_started",       "▶️", "info"),
    ("check_done",          "✅", "ok"),
    ("check_err",           "❌", "err"),
    ("dedupe_done",         "✅", "ok"),
    ("dedupe",              "🧹", "info"),
    ("done",                "🏁", "ok"),
]

LEVEL_COLORS = {
    "ok":   "#4caf50",
    "info": "#9aa0a6",
    "warn": "#ffa500",
    "err":  "#ff4b4b",
}


def _stage_style(stage: str):
    for prefix, icon, level in STAGE_STYLES:
        if stage == prefix or stage.startswith(prefix):
            return icon, level
    return "•", "info"


# ---------------------------------------------------------------------------
# Pretty-name helper used by video_qc.py to label checkers consistently.
# ---------------------------------------------------------------------------

def pretty_name(checker_or_name) -> str:
    """Turn a checker function or raw string into a human-readable label."""
    name = getattr(checker_or_name, "__name__", str(checker_or_name))
    return (
        name.replace("check_", "")
        .replace("generate_", "")
        .replace("_", " ")
        .title()
    )


# ---------------------------------------------------------------------------
# ActivityLog — a tiny session_state-backed event store.
# ---------------------------------------------------------------------------

class ActivityLog:
    """In-memory + session_state-backed log of (timestamp, stage, message) entries."""

    _SESSION_KEY = "activity_log_entries"
    _START_KEY = "activity_log_started_at"

    def __init__(self, store: Optional[Dict] = None):
        # `store` is expected to be st.session_state in the Streamlit app.
        # Pass None for a standalone in-memory log (e.g. tests).
        self._store = store if store is not None else {}
        self._store.setdefault(self._SESSION_KEY, [])

    @classmethod
    def get(cls, store=None) -> "ActivityLog":
        """Convenience constructor returning a log bound to st.session_state."""
        if store is None:
            try:
                import streamlit as st
                store = st.session_state
            except Exception:
                store = {}
        return cls(store)

    @property
    def entries(self) -> List[Dict]:
        return self._store.get(self._SESSION_KEY, [])

    def reset(self):
        self._store[self._SESSION_KEY] = []
        self._store[self._START_KEY] = time_now_seconds()

    def started_at(self) -> Optional[float]:
        return self._store.get(self._START_KEY)

    def emit(self, stage: str, message: str):
        icon, level = _stage_style(stage)
        elapsed = None
        started = self.started_at()
        if started is not None:
            elapsed = max(0, time_now_seconds() - started)

        entry = {
            "stage": stage,
            "message": message,
            "icon": icon,
            "level": level,
            "ts": datetime.now().strftime("%H:%M:%S"),
            "elapsed": elapsed,
        }
        self._store[self._SESSION_KEY].append(entry)


def time_now_seconds() -> float:
    """Indirection so tests can monkeypatch."""
    import time as _time
    return _time.time()


# ---------------------------------------------------------------------------
# Streamlit sidebar renderer — only imported lazily when called.
# ---------------------------------------------------------------------------

def render_sidebar(log: ActivityLog, placeholder, max_visible: int = 40, title: str = "🤖 AI Activity"):
    """
    Render the activity log inside a Streamlit container/placeholder.

    Call this once on initial render, and again after every log.emit() to push
    the latest entries to the sidebar live.

    Parameters
    ----------
    log : ActivityLog
    placeholder : a Streamlit container or placeholder (e.g. st.sidebar.empty()
                  or st.sidebar.container())
    max_visible : how many recent entries to show (oldest are scrolled off).
    title : section header text.
    """
    entries = log.entries[-max_visible:]

    # Build markdown body so the whole panel updates atomically.
    body_lines = [f"**{title}**"]
    if not entries:
        body_lines.append("_Idle. Click 'Analyze Video' to begin._")
    else:
        for e in entries:
            color = LEVEL_COLORS.get(e["level"], "#9aa0a6")
            ts = e["ts"]
            elapsed = f" · {int(e['elapsed'])}s" if e.get("elapsed") is not None else ""
            line = (
                f"<div style='font-size:0.82rem; line-height:1.35; "
                f"margin-bottom:2px; color:{color};'>"
                f"<span style='opacity:0.7'>{ts}{elapsed}</span> "
                f"{e['icon']} {e['message']}"
                f"</div>"
            )
            body_lines.append(line)

    # Use unsafe_allow_html so the colored entries render properly.
    placeholder.markdown(
        "\n\n".join(body_lines) if not entries else
        body_lines[0] + "\n\n" + "".join(body_lines[1:]),
        unsafe_allow_html=True,
    )


def attach_progress_callback(log: ActivityLog, placeholder, max_visible: int = 40):
    """
    Returns a `progress(stage, message)` callable suitable for passing to
    run_video_qc(). Each invocation appends an entry to `log` and re-renders
    `placeholder` so the user sees activity stream in live.
    """
    def progress(stage: str, message: str):
        log.emit(stage, message)
        render_sidebar(log, placeholder, max_visible=max_visible)
    return progress
