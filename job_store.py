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

import boto3
from supabase import create_client

# Tracks whether we've already pushed the CORS policy this process lifetime.
_r2_cors_configured = False


BUCKET_DEFAULT = "amendment-bot-files"
R2_BUCKET_DEFAULT = "ai-amendment-videos"
DIRECT_UPLOAD_EXPIRY_SECONDS = 60 * 60

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


def r2_bucket_name() -> str:
    return _secret("R2_BUCKET", R2_BUCKET_DEFAULT)


def _r2_client():
    access_key_id = _secret("R2_ACCESS_KEY_ID")
    secret_access_key = _secret("R2_SECRET_ACCESS_KEY")
    endpoint = _secret("R2_ENDPOINT")
    if not access_key_id or not secret_access_key or not endpoint:
        raise RuntimeError(
            "Missing R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, or R2_ENDPOINT."
        )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def _ensure_r2_cors() -> None:
    """
    Push a CORS policy to the R2 bucket so browsers can PUT directly from
    any origin (e.g. *.streamlit.app).  Only runs once per process lifetime.
    """
    global _r2_cors_configured
    if _r2_cors_configured:
        return
    try:
        _r2_client().put_bucket_cors(
            Bucket=r2_bucket_name(),
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": ["*"],
                        "AllowedMethods": ["PUT", "GET", "HEAD"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["ETag"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )
        _r2_cors_configured = True
    except Exception as exc:
        # Non-fatal — CORS may already be set in the Cloudflare dashboard.
        # Mark as configured anyway so we don't retry (and spam logs) on
        # every subsequent ticket creation.
        print(f"[R2] WARNING: could not set CORS policy via API: {exc}", flush=True)
        print("[R2] Assuming CORS is already configured in the dashboard.", flush=True)
        _r2_cors_configured = True


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


def _insert_analysis_job(job_id: str, video_path: str, content_type: str) -> dict[str, Any]:
    payload = {
        "id": job_id,
        "status": "queued",
        "video_path": video_path,
        # Store content_type directly so the worker does not have to decode it
        # from the object path if the slug mapping changes.
        "content_type": content_type,
    }
    response = _client().table("jobs").insert(payload).execute()
    rows = response.data or []
    return rows[0] if rows else payload


def create_direct_upload_ticket(content_type: str) -> dict[str, str]:
    # Ensure the bucket has a CORS policy before handing a presigned URL to
    # the browser.  This is idempotent and cached after the first call.
    _ensure_r2_cors()

    job_id = str(uuid.uuid4())
    content_slug = _content_slug(content_type)
    video_path = f"uploads/{job_id}/{content_slug}/direct_upload.mp4"
    signed_url = _r2_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": r2_bucket_name(),
            "Key": video_path,
            # Signing Content-Type makes CORS preflight and the actual PUT
            # consistent — the browser must send the same value in both.
            "ContentType": "video/mp4",
        },
        ExpiresIn=DIRECT_UPLOAD_EXPIRY_SECONDS,
    )
    return {
        "job_id": job_id,
        "video_path": video_path,
        "signed_url": signed_url,
        "content_type": content_type,
    }


def submit_uploaded_analysis_job(job_id: str, video_path: str, content_type: str) -> dict[str, Any]:
    if not job_id or not video_path:
        raise ValueError("Direct upload job_id and video_path are required.")
    return _insert_analysis_job(job_id, video_path, content_type)


def submit_analysis_job(video_bytes: bytes, filename: str, content_type: str) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    safe_name = _safe_filename(filename)
    content_slug = _content_slug(content_type)
    video_path = f"uploads/{job_id}/{content_slug}/{safe_name}"

    _r2_client().put_object(
        Bucket=r2_bucket_name(),
        Key=video_path,
        Body=video_bytes,
        ContentType="video/mp4",
    )

    return _insert_analysis_job(job_id, video_path, content_type)


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
    suffix = Path(video_path).suffix or ".mp4"
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    _r2_client().download_file(r2_bucket_name(), video_path, temp_path)
    return temp_path


def _ensure_result_bucket() -> None:
    """
    Create the result-storage bucket if it doesn't already exist.
    Non-public — access is via the service-role key only.
    Safe to call repeatedly (list_buckets is cheap).
    """
    client = _client()
    bname = bucket_name()
    try:
        existing = [b["name"] for b in (client.storage.list_buckets() or [])]
        if bname not in existing:
            client.storage.create_bucket(bname, options={"public": False})
            print(f"[Storage] Created bucket '{bname}'.", flush=True)
    except Exception as exc:
        # Non-fatal — bucket may already exist or list permission may be absent.
        print(f"[Storage] WARNING: could not ensure bucket '{bname}': {exc}", flush=True)


def upload_result(job_id: str, result: dict[str, Any]) -> str:
    _ensure_result_bucket()
    result_path = f"results/{job_id}/result.json"
    data = json.dumps(result, ensure_ascii=False).encode("utf-8")
    client = _client()
    bname = bucket_name()

    # Try upsert=True (boolean); fall back to remove+upload for older supabase-py
    # builds that ignore or reject the flag.
    try:
        client.storage.from_(bname).upload(
            result_path,
            data,
            file_options={
                "content-type": "application/json",
                "upsert": True,
            },
        )
    except Exception as first_exc:
        try:
            client.storage.from_(bname).remove([result_path])
        except Exception:
            pass
        try:
            client.storage.from_(bname).upload(
                result_path,
                data,
                file_options={"content-type": "application/json"},
            )
        except Exception as second_exc:
            raise RuntimeError(
                f"Failed to upload result to Supabase Storage "
                f"(bucket='{bname}', path='{result_path}'). "
                f"First attempt: {first_exc}. Second attempt: {second_exc}."
            ) from second_exc

    return result_path


def download_result(result_path: str) -> dict[str, Any]:
    try:
        data = _client().storage.from_(bucket_name()).download(result_path)
    except Exception as exc:
        raise RuntimeError(
            f"Could not download QC result from Supabase Storage "
            f"(bucket='{bucket_name()}', path='{result_path}'). "
            f"Ensure the bucket exists and the service-role key has storage access. "
            f"Original error: {exc}"
        ) from exc
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
        .update({"status": "queued", "started_at": None})
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
