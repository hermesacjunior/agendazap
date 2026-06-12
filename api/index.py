from pathlib import Path
import os
import sys


APP_DIR = Path(__file__).resolve().parents[1] / "agendazap"

os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))

# Keep Vercel preview/prod from crashing before the real PostgreSQL env is set.
# Production data must use DATABASE_URL from the provider.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/agendazap.db")

from app.main import app  # noqa: E402
