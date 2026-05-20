import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except Exception:
    st = None

from supabase import create_client


BUCKET_DEFAULT = "amendment-bot-files"

CONTENT_TYPE_BY_SLUG = {
    "business-wealth": "Business & Wealth",
    "homes": "Homes",
    "autos": "Autos",
    "foodie": "Foodie",
    "general": "General",
}


def _secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    if st is not None:
        try:
            value = st.secrets.get(name, default)
            return str(value) if value else default
        except Exception:
            pass
    return default


def _client():
    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def bucket_name() -> str:
    return _secret("SUPABASE_BUCKET", BUCKET_DEFAULT)


def _safe_filename(name: str) -> str:
    name = Path(name or "video.mp4").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "video.mp4"


def _content_slug(content_type: str) -> str:
    slug = str(content_type or "General").lower().replace("&", "")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "general"


def content_type_from_video_path(video_path: str) -> str:
    parts = str(video_path or "").split("/")
    if len(parts) >= 3 and parts[0] == "uploads":
        return CONTENT_TYPE_BY_SLUG.get(parts[2], "General")
    return "General"


def submit_analysis_job(video_bytes: bytes, filename: str, content_type: str) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    safe_name = _safe_filename(filename)
    content_slug = _content_slug(content_type)
    video_path = f"uploads/{job_id}/{content_slug}/{safe_name}"

    client = _client()
    client.storage.from_(bucket_name()).upload(
        video_path,
        video_bytes,
        file_options={
            "content-type": "video/mp4",
            "upsert": "true",
        },
    )

    payload = {
        "id": job_id,
        "status": "queued",
        "video_path": video_path,
        # Store content_type directly so the worker doesn't have to decode it
        # from the storage path (which is fragile if the slug mapping changes).
        "content_type": content_type,
    }
    response = client.table("jobs").insert(payload).execute()
    rows = response.data or []
    return rows[0] if rows else payload


def get_job(job_id: str) -> dict[str, Any] | None:
    response = (
        _client()
        .table("jobs")
        .select("*")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def claim_next_job() -> dict[str, Any] | None:
    client = _client()
    queued = (
        client.table("jobs")
        .select("*")
        .eq("status", "queued")
        .order("created_at")
        .limit(1)
        .execute()
    )
    rows = queued.data or []
    if not rows:
        return None

    job = rows[0]
    claimed = (
        client.table("jobs")
        .update({"status": "processing", "started_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", job["id"])
        .eq("status", "queued")
        .execute()
    )
    claimed_rows = claimed.data or []
    return claimed_rows[0] if claimed_rows else None


def download_video_to_temp(video_path: str) -> str:
    data = _client().storage.from_(bucket_name()).download(video_path)
    suffix = Path(video_path).suffix or ".mp4"
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(temp_path, "wb") as f:
        f.write(data)
    return temp_path


def upload_result(job_id: str, result: dict[str, Any]) -> str:
    result_path = f"results/{job_id}/result.json"
    data = json.dumps(result, ensure_ascii=False).encode("utf-8")
    _client().storage.from_(bucket_name()).upload(
        result_path,
        data,
        file_options={
            "content-type": "application/json",
            "upsert": "true",
        },
    )
    return result_path


def download_result(result_path: str) -> dict[str, Any]:
    data = _client().storage.from_(bucket_name()).download(result_path)
    if isinstance(data, bytes):
        text = data.decode("utf-8")
    else:
        text = str(data)
    return json.loads(text)


def update_job_progress(job_id: str, progress_message: str):
    """Write a short progress note to the job row so the frontend can show it."""
    try:
        (
            _client()
            .table("jobs")
            .update({"progress": str(progress_message)[:500]})
            .eq("id", job_id)
            .execute()
        )
    except Exception:
        pass  # Never let a progress update crash the worker


def reset_stale_jobs(stale_after_minutes: int = 30) -> int:
    """
    Reset jobs stuck in 'processing' back to 'queued'.

    This happens when a worker crashes mid-job and the job is never marked
    done/failed. Any job that has been 'processing' for longer than
    stale_after_minutes is assumed dead and recycled.

    Returns the number of jobs reset.

    NOTE: You also need these columns in the Supabase jobs table:
        content_type  text
        progress      text
    Run this SQL in the Supabase SQL editor:
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS content_type text DEFAULT 'General';
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress text DEFAULT '';
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)).isoformat()
    response = (
        _client()
        .table("jobs")
        .update({"status": "queued", "started_at": None, "progress": ""})
        .eq("status", "processing")
        .lt("started_at", cutoff)
        .execute()
    )
    return len(response.data or [])


def mark_done(job_id: str, result_path: str):
    return (
        _client()
        .table("jobs")
        .update({
            "status": "done",
            "result_path": result_path,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", job_id)
        .execute()
    )


def mark_failed(job_id: str, error: str):
    return (
        _client()
        .table("jobs")
        .update({
            "status": "failed",
            "error": str(error)[:2000],
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", job_id)
        .execute()
    )
