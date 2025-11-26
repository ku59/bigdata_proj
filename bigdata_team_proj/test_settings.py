# test_settings.py

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.append(str(SRC))

from utils.settings import settings


print("DART_API_KEY =", settings.DART_API_KEY)
