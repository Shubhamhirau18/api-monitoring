#!/usr/bin/env python3
"""
Main entry point for the BrightEdge API Monitoring System.
This script can be run directly to start the monitoring system.
"""

import sys
import os
from pathlib import Path

# Add src directory to Python path
current_dir = Path(__file__).parent
src_dir = current_dir / "src"
sys.path.insert(0, str(src_dir))

# Import and run the main application
from main import main

if __name__ == "__main__":
    sys.exit(main()) 