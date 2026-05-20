import os
import signal
import time
import traceback

from job_store import (
    claim_next_job,
    content_type_from_video_path,
    download_video_to_temp,
    mark_done,
    mark_failed,
    reset_stale_jobs,
    update_job_progress,
    upload_result,
)
from video_qc import run_video_qc


POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "5"))
MAX_FRAMES = int(os.getenv("WORKER_MAX_FRAMES", "16"))

# How often (in seconds) to run the stale-job recovery sweep
STALE_RESET_INTERVAL = int(os.getenv("WORKER_STALE_RESET_INTERVAL", "300"))  # 5 min

# Path the Docker HEALTHCHECK monitors — worker touches this on every loop
_HEARTBEAT_FILE = "/tmp/worker_alive"

# Graceful-shutdown flag — set to True by the SIGTERM handler
_shutdown_requested = False


def _handle_sigterm(signum, frame):
    """Ask the main loop to exit cleanly after the current job finishes."""
    global _shutdown_requested
    _shutdown_requested = True
    print("SIGTERM received — finishing current job then shutting down", flush=True)


def _touch_heartbeat():
    """Update the mtime of the heartbeat file so the Docker HEALTHCHECK passes."""
    try:
        with open(_HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def _progress(job_id: str):
    """Return a progress callback that logs to stdout and writes to Supabase."""
    def emit(stage: str, message: str):
        print(f"[job={job_id}] {stage}: {message}", flush=True)
        # Best-effort — never let a progress update crash the worker
        update_job_progress(job_id, f"{stage}: {message}")
    return emit


def process_job(job: dict):
    job_id = job["id"]
    video_path = job["video_path"]
    # Prefer the content_type column; fall back to decoding the storage path
    content_type = job.get("content_type") or content_type_from_video_path(video_path)
    local_video = None

    print(f"[job={job_id}] claimed video_path={video_path} content_type={content_type}", flush=True)

    try:
        local_video = download_video_to_temp(video_path)
        result = run_video_qc(
            local_video,
            progress=_progress(job_id),
            max_frames=MAX_FRAMES,
            content_type=content_type,
        )
        result_path = upload_result(job_id, result)
        mark_done(job_id, result_path)
        print(f"[job={job_id}] done result_path={result_path}", flush=True)
    except Exception as exc:
        error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        mark_failed(job_id, error)
        print(f"[job={job_id}] failed {error}", flush=True)
        traceback.print_exc()
    finally:
        if local_video and os.path.exists(local_video):
            try:
                os.remove(local_video)
            except OSError:
                pass


def main():
    print("AI Amendment Bot worker started", flush=True)

    # Register SIGTERM handler for graceful Docker/Render/Fly shutdown
    signal.signal(signal.SIGTERM, _handle_sigterm)

    # On startup: recycle any jobs left stuck in 'processing' from a previous crash
    try:
        recycled = reset_stale_jobs(stale_after_minutes=30)
        if recycled:
            print(f"Recycled {recycled} stale job(s) back to queued", flush=True)
    except Exception as e:
        print(f"Warning: stale-job reset failed: {e}", flush=True)

    last_stale_reset = time.time()

    while not _shutdown_requested:
        # Touch heartbeat so the Docker HEALTHCHECK knows the worker is alive
        _touch_heartbeat()

        # Periodic stale-job sweep (in case a worker crashes while this one is running)
        if time.time() - last_stale_reset >= STALE_RESET_INTERVAL:
            try:
                recycled = reset_stale_jobs(stale_after_minutes=30)
                if recycled:
                    print(f"Periodic sweep: recycled {recycled} stale job(s)", flush=True)
            except Exception as e:
                print(f"Warning: periodic stale-job reset failed: {e}", flush=True)
            last_stale_reset = time.time()

        job = claim_next_job()
        if job:
            process_job(job)
        else:
            time.sleep(POLL_SECONDS)

    print("Worker shut down cleanly.", flush=True)


if __name__ == "__main__":
    main()
