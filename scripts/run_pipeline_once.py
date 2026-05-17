"""パイプラインを手動で1回実行するスクリプト"""
import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

sys.path.insert(0, ".")

from app.pipeline.runner import run_daily_pipeline


async def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    stats = await run_daily_pipeline(target_date)
    print(f"\n=== 結果 ===")
    print(f"  日付:     {stats['date']}")
    print(f"  検知数:   {stats['dips_detected']}")
    print(f"  分析完了: {stats['dips_analyzed']}")


if __name__ == "__main__":
    asyncio.run(main())
