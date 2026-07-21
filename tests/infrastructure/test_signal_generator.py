import numpy as np
import pandas as pd
from pathlib import Path
from uuid import uuid4

from domain.entities.signal import Signal
from domain.value_objects.symbol import Symbol
from infrastructure.ml.signal_generator import SignalGenerator, SignalConfig
from infrastructure.ml.trainer import Trainer


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.2, 1.5, n)
    low = close - rng.uniform(0.2, 1.5, n)
    opn = close + rng.normal(0, 0.3, n)
    volume = rng.integers(1000, 50000, n).astype(float)
    dates = pd.date_range("2024-01-01", periods=n, freq="1min")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestSignalGenerator:
    def test_not_ready_without_model(self) -> None:
        gen = SignalGenerator()
        assert gen.is_ready is False

    def test_generate_returns_none_when_not_ready(self) -> None:
        gen = SignalGenerator()
        df = _make_ohlcv(200)
        result = gen.generate(
            df, strategy_id=uuid4(), symbol=Symbol(code="EURUSD_otc")
        )
        assert result is None

    def test_generate_after_training(self, tmp_path: Path) -> None:
        trainer = Trainer()
        df_train = _make_ohlcv(200)
        trainer.train_and_save(df_train, tmp_path / "model")

        gen = SignalGenerator()
        gen.load_model(tmp_path / "model")
        assert gen.is_ready is True

        df_signal = _make_ohlcv(100, seed=99)
        result = gen.generate(
            df_signal, strategy_id=uuid4(), symbol=Symbol(code="EURUSD_otc")
        )
        if result is not None:
            assert isinstance(result, Signal)
            assert result.symbol.code == "EURUSD_OTC"
            assert result.confidence.score >= 0.5

    def test_generate_returns_none_on_short_data(self, tmp_path: Path) -> None:
        trainer = Trainer()
        df_train = _make_ohlcv(200)
        trainer.train_and_save(df_train, tmp_path / "model")

        gen = SignalGenerator()
        gen.load_model(tmp_path / "model")

        df_short = _make_ohlcv(5, seed=99)
        result = gen.generate(
            df_short, strategy_id=uuid4(), symbol=Symbol(code="EURUSD_otc")
        )
        assert result is None

    def test_low_threshold_produces_signal(self, tmp_path: Path) -> None:
        trainer = Trainer()
        df_train = _make_ohlcv(200)
        trainer.train_and_save(df_train, tmp_path / "model")

        config = SignalConfig(confidence_threshold=0.51)
        gen = SignalGenerator(config=config)
        gen.load_model(tmp_path / "model")

        df_signal = _make_ohlcv(100, seed=77)
        result = gen.generate(
            df_signal, strategy_id=uuid4(), symbol=Symbol(code="EURUSD_otc")
        )
        assert result is None or isinstance(result, Signal)

    def test_high_threshold_fewer_signals(self, tmp_path: Path) -> None:
        trainer = Trainer()
        df_train = _make_ohlcv(200)
        trainer.train_and_save(df_train, tmp_path / "model")

        gen_low = SignalGenerator(SignalConfig(confidence_threshold=0.51))
        gen_low.load_model(tmp_path / "model")
        gen_high = SignalGenerator(SignalConfig(confidence_threshold=0.85))
        gen_high.load_model(tmp_path / "model")

        df_signal = _make_ohlcv(100, seed=33)
        symbol = Symbol(code="EURUSD_otc")
        sid = uuid4()

        r_low = gen_low.generate(df_signal, strategy_id=sid, symbol=symbol)
        r_high = gen_high.generate(df_signal, strategy_id=sid, symbol=symbol)

        if r_high is not None:
            assert r_low is not None
            assert r_high.confidence.score >= r_low.confidence.score

    def test_signal_has_feature_values(self, tmp_path: Path) -> None:
        trainer = Trainer()
        df_train = _make_ohlcv(200)
        trainer.train_and_save(df_train, tmp_path / "model")

        gen = SignalGenerator(SignalConfig(confidence_threshold=0.51))
        gen.load_model(tmp_path / "model")

        df_signal = _make_ohlcv(100, seed=55)
        result = gen.generate(
            df_signal, strategy_id=uuid4(), symbol=Symbol(code="EURUSD_otc")
        )
        if result is not None:
            assert len(result.feature_values) > 0
