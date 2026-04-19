#!/bin/bash
REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO/server"

if [ ! -d ".venv" ]; then
    echo "Run ./setup.sh first"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "Copy server/.env.example to server/.env and fill in your API keys first"
    exit 1
fi

exec .venv/bin/python main.py
