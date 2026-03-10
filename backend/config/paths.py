"""Path management for the Kaiwu backend."""
from pathlib import Path

# Project root directory (kaiwu/backend)
ROOT_DIR = Path(__file__).resolve().parent.parent

# Configuration directory
CONFIG_DIR = ROOT_DIR / "config"

# Data directory for runtime data
DATA_DIR = ROOT_DIR / "data"

# Logs directory
LOGS_DIR = DATA_DIR / "logs"

# Skills directory
SKILLS_DIR = ROOT_DIR / "skills"

# Built-in tools directory
TOOLS_DIR = ROOT_DIR / "tools" / "builtin"
