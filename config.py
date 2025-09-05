import os
from pathlib import Path

# --- Logging Configuration ---
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO").upper()
THIRD_PARTY_LOGGING_LEVEL = os.getenv("THIRD_PARTY_LOGGING_LEVEL", "WARNING").upper()

# --- File Path Configuration ---
SYSTEM_AGENTS_FILE = Path(os.getenv("SYSTEM_AGENTS_FILE", "system_agents.py"))
KNOWLEDGE_FILE = Path(os.getenv("KNOWLEDGE_FILE", "knowledge.md"))
INPUT_FILE = Path(os.getenv("INPUT_FILE", "input.md"))

# --- Git Configuration ---
GIT_COMMIT_USER_NAME = os.getenv("GIT_COMMIT_USER_NAME", "AdaptiveAgentSystem")
GIT_COMMIT_USER_EMAIL = os.getenv("GIT_COMMIT_USER_EMAIL", "agent@example.com")

# --- Process Configuration ---
MAX_CHILD_RESTARTS = int(os.getenv("MAX_CHILD_RESTARTS", 3))
CHILD_PROCESS_TIMEOUT_SECONDS = int(os.getenv("CHILD_PROCESS_TIMEOUT_SECONDS", 300))
