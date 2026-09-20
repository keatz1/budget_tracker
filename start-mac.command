#!/bin/bash
# Double-click this file to start the budget app on a Mac.
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed."
  echo "Opening the download page. Install it, open it once, then double-click this file again."
  open "https://www.docker.com/products/docker-desktop/"
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but not running. Starting it..."
  open -a Docker
  echo "Waiting for Docker to start (this can take a minute)..."
  until docker info >/dev/null 2>&1; do sleep 2; done
fi

if [ ! -f .env ]; then
  echo "BT_SECRET_KEY=$(openssl rand -hex 32)" > .env
  echo "BT_PORT=8000" >> .env
fi

echo "Starting the budget app. The first time takes a few minutes..."
docker compose up -d --build || { read -n 1 -s -r -p "Something went wrong. Press any key to close."; exit 1; }

echo "Waiting for it to come up..."
for i in $(seq 1 60); do
  if curl -fs http://localhost:8000/health >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "Opening http://localhost:8000"
open "http://localhost:8000"
echo
echo "The app keeps running in the background, even after you close this window."
echo "To stop it, double-click stop-mac.command."
sleep 3
