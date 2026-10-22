"""Hugging Face Space entry point: makes src/ importable, loads .env if present, starts the UI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()   # no .env on the Space; the Space's secrets are already environment variables

from alikable.app import main  # noqa: E402

main()
