"""ASGI entrypoint shared by Uvicorn, Docker and Vercel."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ofi.api import app as app  # noqa: E402
