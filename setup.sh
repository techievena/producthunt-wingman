#!/bin/bash
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"

echo "Setting up PH Wingman..."

cd "$REPO/server"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

.venv/bin/pip install -r requirements.txt -q
.venv/bin/playwright install chromium

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "Created server/.env — fill in your API keys before running:"
    echo "  OPENAI_API_KEY (or ANTHROPIC_API_KEY)"
    echo "  LAUNCH_DATE"
    echo "  PH_LAUNCH_URL"
fi

echo ""
echo "Setup complete. Run ./start.sh to start the server."
