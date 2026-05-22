#!/bin/bash
# ============================================================
# AI Amendment Bot — EC2 Worker Setup Script
# Run this inside your EC2 Instance Connect terminal
# Amazon Linux 2023
# ============================================================

set -e

echo "============================================"
echo "  AI Amendment Bot — EC2 Worker Setup"
echo "============================================"

# ---------- 1. Install Docker ----------
echo ""
echo "[1/6] Installing Docker..."
dnf update -y
dnf install -y docker git
systemctl start docker
systemctl enable docker
echo "Docker installed and started."

# ---------- 2. Clone the repo ----------
echo ""
echo "[2/6] Cloning repo..."
cd /home/ec2-user
if [ -d "ai-amendment-bot" ]; then
    echo "Repo already exists — pulling latest..."
    cd ai-amendment-bot
    git pull origin main
    cd /home/ec2-user
else
    git clone https://github.com/Chapman1121/ai-amendment-bot.git
fi
echo "Repo ready."

# ---------- 3. Write environment variables ----------
echo ""
echo "[3/6] Writing .env file..."
cat > /home/ec2-user/ai-amendment-bot/.env << 'EOF'
OPENAI_API_KEY=PASTE_YOUR_KEY_HERE
SUPABASE_URL=https://bnzjxsfqblwsjtzqlvts.supabase.co
SUPABASE_SERVICE_ROLE_KEY=PASTE_YOUR_KEY_HERE
SUPABASE_BUCKET=amendment-bot-files
WORKER_POLL_SECONDS=5
WORKER_MAX_FRAMES=16
WORKER_STALE_RESET_INTERVAL=300
EOF
chmod 600 /home/ec2-user/ai-amendment-bot/.env
echo ".env file written."

# ---------- 4. Build Docker image ----------
echo ""
echo "[4/6] Building Docker image (this takes a few minutes)..."
cd /home/ec2-user/ai-amendment-bot
docker build -f Dockerfile.worker -t amendment-bot-worker:latest .
echo "Image built."

# ---------- 5. Stop any existing container ----------
echo ""
echo "[5/6] Stopping any existing worker container..."
docker stop amendment-bot-worker 2>/dev/null || true
docker rm amendment-bot-worker 2>/dev/null || true

# ---------- 6. Run the worker ----------
echo ""
echo "[6/6] Starting worker container..."
docker run -d \
    --name amendment-bot-worker \
    --restart always \
    --env-file /home/ec2-user/ai-amendment-bot/.env \
    amendment-bot-worker:latest

echo ""
echo "============================================"
echo "  Worker is running!"
echo "  Check logs:  docker logs -f amendment-bot-worker"
echo "  Check status: docker ps"
echo "============================================"
