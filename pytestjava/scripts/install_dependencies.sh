#!/bin/bash
# API Test Framework - Dependency Installation Script

echo "🚀 Installing API Test Framework dependencies..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 is not installed. Please install pip3."
    exit 1
fi

# Install Python dependencies
echo "📦 Installing Python packages..."
pip3 install -r requirements.txt

# Install Allure command line tool
echo "📊 Installing Allure command line tool..."

# For Windows (using scoop)
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    if command -v scoop &> /dev/null; then
        scoop install allure
    else
        echo "⚠️  Scoop not found. Please install Allure manually:"
        echo "   Download from: https://github.com/allure-framework/allure2/releases"
    fi
# For macOS (using homebrew)
elif [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew &> /dev/null; then
        brew install allure
    else
        echo "⚠️  Homebrew not found. Please install Allure manually:"
        echo "   brew install allure"
    fi
# For Linux (using package manager)
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Try different package managers
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install allure
    elif command -v yum &> /dev/null; then
        sudo yum install allure
    elif command -v dnf &> /dev/null; then
        sudo dnf install allure
    else
        echo "⚠️  Package manager not found. Please install Allure manually:"
        echo "   See: https://docs.qameta.io/allure/#_installing_a_commandline"
    fi
else
    echo "⚠️  Unsupported OS. Please install Allure manually."
fi

echo "✅ Dependencies installed successfully!"
echo ""
echo "📝 Next steps:"
echo "   1. Copy .env.example to .env and configure your settings"
echo "   2. Set up your WeChat Work webhook key in .env"
echo "   3. Run: python run_tests.py --help to see available options"