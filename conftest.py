"""
conftest.py — root pytest configuration
Adds the project root to sys.path so all imports resolve correctly.
"""
import sys
import os

# Ensure project root is on path for all tests
sys.path.insert(0, os.path.dirname(__file__))
