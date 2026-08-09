"""Phase 00 smoke tests: empty skeleton imports cleanly."""


def test_version():
    import quant

    assert isinstance(quant.__version__, str)


def test_subpackages_importable():
    from quant.backtest import costs, engine, execution, metrics
    from quant.candles import aggregation
    from quant.data import dhan, instruments, validation
    from quant.indicators import angle, ema
    from quant.research import parameter_search, walk_forward
    from quant.strategies import ema_9_15

    assert all(
        m.__name__
        for m in (
            costs,
            engine,
            execution,
            metrics,
            aggregation,
            dhan,
            instruments,
            validation,
            angle,
            ema,
            parameter_search,
            walk_forward,
            ema_9_15,
        )
    )
