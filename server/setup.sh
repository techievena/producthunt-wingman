#!/bin/bash

# ProductHunt Wingman Setup Script
# This script creates a fresh virtual environment and installs dependencies to avoid conflicts.

set -e

echo "🚀 Setting up ProductHunt Wingman..."

# 1. Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# 2. Activate venv
echo "🔗 Activating virtual environment..."
source .venv/bin/activate

# 3. Upgrade pip
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# 4. Install dependencies
echo "📥 Installing requirements..."
pip install -r requirements.txt

# 5. Install Playwright browsers
echo "🌐 Installing Playwright browsers..."
playwright install chromium

echo ""
echo "✅ Setup complete!"
echo "To run the wingman:"
echo "1. source .venv/bin/activate"
echo "2. python main.py"
