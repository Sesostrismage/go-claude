"""Configuration for Go Teacher.

Paths are resolved relative to the project root (the folder containing
go_teacher.py), so the project works no matter where it's cloned to. Only
change these if your katago/ folder or model filenames differ from the
defaults set up by the SETUP instructions in go_teacher.py.
"""

import os

# Root of the project (the folder containing go_teacher.py), regardless of
# which module this constant is imported from.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KATAGO_EXE = os.path.join(PROJECT_ROOT, "katago", "katago.exe")  # path to katago.exe
MAIN_MODEL = os.path.join(
    PROJECT_ROOT, "katago", "kata1-b18c384nbt-latest.bin.gz"
)  # main network
HUMAN_MODEL = os.path.join(
    PROJECT_ROOT, "katago", "b18c384nbt-humanv0.bin.gz"
)  # human-style network
ANTHROPIC_API_KEY = (
    ""  # leave "" - key is read from env var or .env file (see coach.py)
)

# Coach models selectable from the UI (label -> API model string).
COACH_MODELS = {
    "Sonnet": "claude-sonnet-5",
    "Opus": "claude-opus-4-8",
    "Haiku": "claude-haiku-4-5-20251001",
}
DEFAULT_COACH_MODEL = COACH_MODELS["Sonnet"]

PORT = 8123
ANALYSIS_VISITS = 150  # visits per analysis query (higher = stronger/slower)

# Big-mistake detection. A move is flagged when it loses at least this many
# points versus KataGo's best move (by board size - a few points matter more
# on a small board) OR drops the mover's winrate by at least MISTAKE_WINRATE.
# Because ANALYSIS_VISITS is shallow enough for a point or two of noise, a
# suspected mistake is re-analysed at MISTAKE_CONFIRM_VISITS before being
# flagged; the deeper analysis replaces the stored one.
MISTAKE_POINTS_BY_SIZE = {9: 3.0, 13: 3.5, 19: 4.0}
MISTAKE_WINRATE = 0.12
MISTAKE_CONFIRM_VISITS = 600
