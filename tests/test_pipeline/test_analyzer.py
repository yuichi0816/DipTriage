"""純粋関数のユニットテスト（DB・ネットワーク不要）"""
import pytest
from app.pipeline.analyzer import (
    calculate_beta,
    calculate_volume_ratio,
    calculate_volatility,
    score_idiosyncratic,
)


class TestCalculateVolumeRatio:
    def test_normal(self):
        # 今日 400、過去20日平均 100 → 4.0
        volumes = [400.0] + [100.0] * 20
        assert calculate_volume_ratio(volumes) == pytest.approx(4.0)

    def test_today_none_returns_none(self):
        volumes = [None] + [100.0] * 20
        assert calculate_volume_ratio(volumes) is None

    def test_today_zero_returns_none(self):
        volumes = [0.0] + [100.0] * 20
        assert calculate_volume_ratio(volumes) is None

    def test_empty_returns_none(self):
        assert calculate_volume_ratio([]) is None

    def test_insufficient_history_returns_none(self):
        assert calculate_volume_ratio([100.0]) is None

    def test_nones_in_history_are_excluded(self):
        # 歴史データに None が混入しても正しく計算する
        volumes = [200.0, 100.0, None, 100.0, None, 100.0] + [100.0] * 15
        assert calculate_volume_ratio(volumes) == pytest.approx(2.0)

    def test_window_limits_historical_average(self):
        # window=3 の場合、直近3件だけで平均を計算する
        volumes = [300.0, 100.0, 200.0, 300.0, 999.0]  # 999 は window 外
        result = calculate_volume_ratio(volumes, window=3)
        # 平均 = (100+200+300)/3 = 200, ratio = 300/200 = 1.5
        assert result == pytest.approx(1.5)


class TestCalculateVolatility:
    def test_normal(self):
        import numpy as np
        prices = [100.0 * (1 + 0.01 * i) for i in range(260)]
        closes = prices[::-1]  # 新しい順
        sigma, dev = calculate_volatility(closes, -5.0)
        assert sigma is not None and sigma > 0
        assert dev is not None and dev > 0

    def test_insufficient_data_returns_none(self):
        sigma, dev = calculate_volatility([100.0] * 10, -5.0)
        assert sigma is None and dev is None


class TestCalculateBeta:
    def test_perfect_correlation_beta_one(self):
        import numpy as np
        prices = [100.0 * (1.01 ** i) for i in range(260)]
        # 株価と市場が完全に同じ動き → beta ≈ 1.0
        beta = calculate_beta(prices[::-1], prices[::-1])
        assert beta == pytest.approx(1.0, abs=1e-6)

    def test_insufficient_data_returns_none(self):
        assert calculate_beta([100.0] * 10, [100.0] * 10) is None

    def test_zero_variance_market_returns_none(self):
        stock = [100.0] * 260
        market = [200.0] * 260
        assert calculate_beta(stock[::-1], market[::-1]) is None


class TestScoreIdiosyncratic:
    def test_highly_idiosyncratic(self):
        # セクター超過下落 -10%, 相関 0.1, beta 0.3 → スコア高い
        is_idio, score = score_idiosyncratic(-10.0, 0.1, 0.3)
        assert is_idio == 1
        assert score is not None and score >= 0.4

    def test_sector_driven(self):
        # セクター超過下落なし、相関 0.95, beta 1.5 → スコア低い
        is_idio, score = score_idiosyncratic(0.0, 0.95, 1.5)
        assert is_idio == 0

    def test_all_none_returns_none(self):
        is_idio, score = score_idiosyncratic(None, None, None)
        assert is_idio is None and score is None

    def test_beta_contributes_to_score(self):
        # beta のみ提供 → スコアが None にならない
        is_idio, score = score_idiosyncratic(None, None, 0.0)
        assert score is not None
        assert score == pytest.approx(1.0)  # beta=0 → 1 - 0/2 = 1.0

    def test_high_beta_reduces_idiosyncratic_score(self):
        # beta が高いほど market-driven → スコアが下がる
        _, score_low_beta = score_idiosyncratic(None, None, 0.0)
        _, score_high_beta = score_idiosyncratic(None, None, 2.0)
        assert score_low_beta > score_high_beta
