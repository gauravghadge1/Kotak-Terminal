#!/usr/bin/env python
"""
Kotak Trading Terminal - Entry Point

Run this script to start the trading terminal.
"""

import os
import sys

# Add terminal directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    print("Note: python-dotenv not installed. Using system environment variables.")

from terminal.app import run_terminal

if __name__ == '__main__':
    run_terminal()
