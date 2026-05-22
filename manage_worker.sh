#!/bin/bash
# ============================================================
# AI Amendment Bot — Worker Management Helper
# Usage: bash manage_worker.sh [start|stop|restart|logs|status|update]
# ============================================================

CONTAINER="amendment-bot-worker"
IMAGE="amendment-bot-worker:latest"
REPO_DIR="/home/ec2-user/ai-amendment-bot"
ENV_FILE="$REPO_DIR/.env"

case "$1" in
  start)
    echo "Starting worker..."
    docker run -d \
        --name $CONTAINER \
        --restart always \
        --env-file $ENV_FILE \
        $IMAGE
    echo "Worker started."
    ;;

  stop)
    echo "Stopping worker..."
    docker stop $CONTAINER && docker rm $CONTAINER
    echo "Worker stopped."
    ;;

  restart)
    echo "Restarting worker..."
    docker restart $CONTAINER
    echo "Worker restarted."
    ;;

  logs)
    docker logs -f --tail=100 $CONTAINER
    ;;

  status)
    echo "--- Container status ---"
    docker ps -a --filter name=$CONTAINER
    echo ""
    echo "--- Last 20 log lines ---"
    docker logs --tail=20 $CONTAINER 2>&1
    ;;

  update)
    echo "Pulling latest code and rebuilding..."
    cd $REPO_DIR
    git pull origin main
    docker build -f Dockerfile.worker -t $IMAGE .
    docker stop $CONTAINER 2>/dev/null || true
    docker rm $CONTAINER 2>/dev/null || true
    docker run -d \
        --name $CONTAINER \
        --restart always \
        --env-file $ENV_FILE \
        $IMAGE
    echo "Worker updated and restarted."
    ;;

  *)
    echo "Usage: bash manage_worker.sh [start|stop|restart|logs|status|update]"
    echo ""
    echo "  start    — start the worker container"
    echo "  stop     — stop and remove the container"
    echo "  restart  — restart the container"
    echo "  logs     — tail live logs"
    echo "  status   — show container status + last 20 log lines"
    echo "  update   — pull latest code, rebuild image, restart"
    ;;
esac
