#!/bin/bash
cd "$(dirname "$0")"
docker compose stop
echo "Stopped. Your data is safe in the data folder. Double-click start-mac.command to start again."
sleep 3
