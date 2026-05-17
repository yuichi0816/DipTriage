from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data" / "diptriage.db"))
DATABASE_URL: str = f"sqlite+aiosqlite:///{DB_PATH}"

THRESHOLD_DIP_PCT: float = float(os.getenv("THRESHOLD_DIP_PCT", "-5.0"))
MACRO_FILTER_PCT: float = float(os.getenv("MACRO_FILTER_PCT", "-2.0"))

OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL_INTERVIEW: str = os.getenv("OLLAMA_MODEL_INTERVIEW", "qwen3:30b")
OLLAMA_MODEL_DIAGNOSIS: str = os.getenv("OLLAMA_MODEL_DIAGNOSIS", "qwen3:30b")

PIPELINE_HOUR: int = int(os.getenv("PIPELINE_HOUR", "7"))
PIPELINE_MINUTE: int = int(os.getenv("PIPELINE_MINUTE", "0"))

SP500_SYMBOLS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NIKKEI225_SYMBOLS_URL = "https://en.wikipedia.org/wiki/Nikkei_225"

INDEX_SYMBOLS = {
    "US": "^GSPC",
    "JP": "^N225",
}
