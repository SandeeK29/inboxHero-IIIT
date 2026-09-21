# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Configuration Loader for Project inboxHero
Handles environment variables, LLM provider selection (Gemini / Ollama), and system paths.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Check for .env in project dir, then parent dir
env_path = BASE_DIR / ".env"
parent_env_path = BASE_DIR.parent / ".env"

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
elif parent_env_path.exists():
    load_dotenv(dotenv_path=parent_env_path)
else:
    load_dotenv()

# LLM Configuration (Configured for Ollama)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# System Paths
DATA_DIR = BASE_DIR / "data"
INBOX_FILE = DATA_DIR / "inbox.json"
OUTBOX_DIR = BASE_DIR / "outbox"
PREFS_FILE = BASE_DIR / "prefs.json"
DECISIONS_FILE = BASE_DIR / "decisions.json"
TRACE_FILE = BASE_DIR / "trace.jsonl"
DASHBOARD_FILE = BASE_DIR / "dashboard.html"
DASHBOARD_JSON_FILE = BASE_DIR / "dashboard.json"
DRAFTS_FILE = BASE_DIR / "drafts.json"  # Persisted draft cache — avoids re-running LLM on every dashboard refresh

# Ensure output directories exist
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
