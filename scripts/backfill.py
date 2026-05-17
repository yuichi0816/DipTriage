"""過去の特定日付のデータを取得してパイプラインを実行するスクリプト。
検証例: uv run scripts/backfill.py 2024-07-19  (CrowdStrike 急落日)
"""
import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

sys.path.insert(0, ".")

from app.pipeline.runner import run_daily_pipeline


async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run scripts/backfill.py YYYY-MM-DD [YYYY-MM-DD ...]")
        sys.exit(1)

    dates = sys.argv[1:]
    for date in dates:
        print(f"\n--- Backfilling {date} ---")
        stats = await run_daily_pipeline(date)
        print(f"  検知: {stats['dips_detected']}, 分析: {stats['dips_analyzed']}")


if __name__ == "__main__":
    asyncio.run(main())
