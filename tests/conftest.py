"""Shared pytest configuration for all tests."""
import sys
import os

# Ensure the project root is on sys.path so `src.*` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
