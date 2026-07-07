"""5クラス分類タクソノミーの単一情報源（監査 5-3）。"""
from __future__ import annotations

VALID_CLASSES = {"accident", "incident", "structural", "macro", "unknown"}

CLASS_JP = {
    "accident": "事故型",
    "incident": "事件型",
    "structural": "構造型",
    "macro": "マクロ型",
    "unknown": "不明",
}

# ダッシュボードの分類順ソート用（None = 問診未実施）
CLASS_ORDER = {"accident": 0, "incident": 1, "structural": 2, "macro": 3, "unknown": 4, None: 5}


def normalize_class(value: object) -> str:
    """LLM が返した分類値を検証し、無効なら unknown に落とす（監査 1-2）。"""
    return value if isinstance(value, str) and value in VALID_CLASSES else "unknown"
