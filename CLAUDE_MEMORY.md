# AI Amendment Bot — Project Memory
> Claude: READ THIS FILE AT THE START OF EVERY SESSION before doing anything else.

---

## Who is the user?
- **Name:** mj (mjaved392006@gmail.com)
- **Vibe:** casual, fast-paced, prefers short replies, types informally

---

## What is this project?
An **AI-powered video QC (Quality Control) bot** for Koocester Group.
- Users upload a video → the bot reviews it across story clarity, information clarity, visuals, audio, and a full QC board with timestamped issues and severity ratings.
- Built with **Streamlit** (frontend), **Supabase** (job queue + file storage), and **OpenAI** (AI analysis).

---

## Why the current architecture?
Originally everything ran inside Streamlit — but multiple users couldn't run the bot simultaneously without it crashing. 

**Solution:** Worker-queue architecture:
1. **Streamlit app** — users submit jobs (upload video → job queued in Supabase)
2. **Supabase** — stores job queue (`jobs` table) + video/result files (Storage bucket)
3. **AWS EC2 worker** — polls Supabase queue, processes videos, writes results back

**Goal: support 10 concurrent users without crashing.**

---

## Tech Stack
| Layer | Technology |
|---|---|
| Frontend | Streamlit (hosted on Streamlit Cloud) |
| Job queue + storage | Supabase |
| AI | OpenAI (GPT for analysis, Whisper for transcription) |
| Worker server | AWS EC2 (Amazon Linux 2023) |
| Worker runtime | Docker container |

---

## Credentials (DO NOT COMMIT TO GIT)
> Actual keys live in Streamlit Cloud secrets and in the `.env` file on EC2.
> Never paste real key values here — this file is tracked by git.
```
OPENAI_API_KEY=<stored in Streamlit secrets + EC2 .env>
SUPABASE_URL=https://bnzjxsfqblwsjtzqlvts.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<stored in Streamlit secrets + EC2 .env>
SUPABASE_BUCKET=amendment-bot-files
```

---

## AWS EC2 Instance
| Field | Value |
|---|---|
| Instance name | amendment-bot |
| Instance ID | i-00af04d221b0a71ee |
| Public IP | 43.217.73.81 |
| Private IP | 172.31.35.251 |
| OS | Amazon Linux 2023 |
| SSH key | `pem key/ai-amendment-worker-key.pem` (in this folder) |
| Login user | root (or ec2-user) |
| Access method | EC2 Instance Connect (browser) OR SSH with pem key |

---

## GitHub Repo
`https://github.com/Chapman1121/ai-amendment-bot.git`

---

## Key Files
| File | Purpose |
|---|---|
| `app.py` | Streamlit frontend — job submission + results display |
| `worker.py` | EC2 worker — polls Supabase queue and processes jobs |
| `job_store.py` | Supabase job queue helpers (submit, claim, mark done/failed) |
| `video_qc.py` | Core QC logic — runs all checks on a video |
| `connection.py` | OpenAI API helpers (text, vision, audio) |
| `Dockerfile.worker` | Docker image for the EC2 worker |
| `setup_ec2.sh` | One-time EC2 setup script (install Docker, clone repo, run worker) |
| `manage_worker.sh` | Helper: start/stop/restart/logs/update worker |

---

## Current Status (last updated: 2026-05-22)
- [x] Streamlit frontend built
- [x] Supabase job queue + storage set up
- [x] Worker code written (`worker.py`, `job_store.py`)
- [x] Dockerfile.worker ready
- [x] EC2 instance launched (Amazon Linux 2023, IP: 43.217.73.81)
- [x] Docker installed, repo cloned, .env written, worker container running on EC2
- [x] Supabase jobs table has `content_type` and `progress` columns added
- [x] Worker starts cleanly with no errors — polling for jobs
- [x] Upload limit raised to 500MB (`.streamlit/config.toml` + `app.py`)
- [x] `job_store.py` fix: removed `progress` from `reset_stale_jobs` update (was causing schema cache warning)
- [x] End-to-end test passed ✅
- [ ] **NEXT:** Push `manage_worker.sh` and `setup_ec2.sh` to GitHub

---

## What we were doing last session
- Full deployment to EC2 complete and working
- Upload limit raised to 500MB
- End-to-end test passed
- EC2 is t3.micro (1GB RAM, 2 vCPU) — monitor for memory issues, upgrade to t3.small (~$15/mo) if needed
- GitHub repo is PUBLIC — EC2 pulls without credentials. Keep it public for now.
- `manage_worker.sh` is in the local workspace folder but NOT yet on GitHub

## Worker Commands (run on EC2)
```bash
docker logs -f amendment-bot-worker                          # live logs
docker ps                                                     # check container is running
cd /home/ec2-user/ai-amendment-bot && git pull origin main   # pull latest code
docker build -f Dockerfile.worker -t amendment-bot-worker:latest . && docker stop amendment-bot-worker && docker rm amendment-bot-worker && docker run -d --name amendment-bot-worker --restart always --env-file .env amendment-bot-worker:latest   # rebuild + restart
```

---

## Supabase DB Schema (jobs table)
```sql
-- Required columns (run in Supabase SQL editor if missing):
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS content_type text DEFAULT 'General';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress text DEFAULT '';
```

---

## Notes
- mj uses AWS and Supabase under **different email accounts** — don't assume one email covers both
- EC2 Instance Connect is the preferred way to access EC2 (browser-based, no local SSH needed)
- The `.pem` key is stored in the `pem key/` subfolder of this workspace
