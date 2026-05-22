# Commands Cheat Sheet
> Quick reference for GitHub, EC2, and VS Code

---

## GitHub (run in your project folder terminal)

```bash
# Push your changes to GitHub
git add .
git commit -m "describe what you changed"
git push origin main

# Pull latest changes from GitHub
git pull origin main

# Check what files you changed
git status

# See recent commit history
git log --oneline -10

# Undo last commit (keeps your changes)
git reset --soft HEAD~1
```

---

## EC2 Worker (run in EC2 Instance Connect terminal)

```bash
# Check if worker is running
docker ps

# View live logs
docker logs -f amendment-bot-worker

# View last 50 lines of logs
docker logs --tail=50 amendment-bot-worker

# Restart the worker
docker restart amendment-bot-worker

# Stop the worker
docker stop amendment-bot-worker

# Pull latest code from GitHub (after you push changes)
cd /home/ec2-user/ai-amendment-bot && git pull origin main

# Full update: pull code + rebuild image + restart worker
cd /home/ec2-user/ai-amendment-bot && git pull origin main && docker build -f Dockerfile.worker -t amendment-bot-worker:latest . && docker stop amendment-bot-worker && docker rm amendment-bot-worker && docker run -d --name amendment-bot-worker --restart always --env-file .env amendment-bot-worker:latest

# Check how much memory/CPU is being used
docker stats amendment-bot-worker

# Check disk space on EC2
df -h

# Check RAM usage
free -h
```

---

## VS Code

| Action | Shortcut |
|---|---|
| Open terminal | Ctrl + ` |
| Open file | Ctrl + P → type filename |
| Find in file | Ctrl + F |
| Find across all files | Ctrl + Shift + F |
| Save file | Ctrl + S |
| Save all files | Ctrl + K, S |
| Undo | Ctrl + Z |
| Redo | Ctrl + Y |
| Comment/uncomment line | Ctrl + / |
| Format document | Shift + Alt + F |
| Open Source Control (git) | Ctrl + Shift + G |

---

## Streamlit Cloud

- **Reboot app:** Go to your app → ⋮ menu → Reboot
- **View logs:** Go to your app → ⋮ menu → Logs  
- **Update secrets:** App → Settings → Secrets
- **Redeploy:** Just push to GitHub — Streamlit Cloud auto-deploys on every push to `main`

---

## Supabase Quick Links

- **View jobs table:** Table Editor → jobs
- **Run SQL:** SQL Editor → paste query → Run
- **Reload schema cache:** SQL Editor → `NOTIFY pgrst, 'reload schema';`
- **View storage files:** Storage → amendment-bot-files

---

## Workflow: Making Changes to the Bot

1. Edit code in VS Code
2. Test locally if possible
3. `git add . && git commit -m "what you changed" && git push origin main`
4. Streamlit Cloud auto-updates ✅
5. On EC2: run the full update command above to rebuild the worker ✅
