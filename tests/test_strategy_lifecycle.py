import pytest
from unittest.mock import MagicMock

from core.strategy_lifecycle import (
    DeviationAlert,
    LiveMonitor,
    PaperTradingSandbox,
    PaperTradingSession,
    PromotionCriteria,
    PromotionResult,
    StrategyConfig,
    StrategyLifecycleManager,
    StrategyState,
    StrategyVersion,
    _VALID_TRANSITIONS,
)


def _make_mock_db() -> MagicMock:
    mock_db = MagicMock()
    mock_tx = MagicMock()
    mock_db.transaction.return_value.__enter__ = MagicMock(return_value=mock_tx)
    mock_db.transaction.return_value.__exit__ = MagicMock(return_value=False)
    return mock_db


def _make_manager() -> StrategyLifecycleManager:
    return StrategyLifecycleManager(db=_make_mock_db())


def _make_config(**overrides) -> StrategyConfig:
    defaults = {
        "name": "test_strategy",
        "version": "1.0",
    }
    defaults.update(overrides)
    return StrategyConfig(**defaults)


def _register_and_advance(
    manager: StrategyLifecycleManager,
    config: StrategyConfig | None = None,
    target_state: StrategyState = StrategyState.BACKTEST_PASSED,
) -> str:
    cfg = config or _make_config()
    vid = manager.register_strategy(cfg)
    if target_state == StrategyState.RESEARCH:
        return vid
    transitions = [
        (StrategyState.RESEARCH, StrategyState.BACKTEST_PASSED),
        (StrategyState.BACKTEST_PASSED, StrategyState.PAPER_TRADING),
        (StrategyState.PAPER_TRADING, StrategyState.PILOT),
        (StrategyState.PILOT, StrategyState.LIVE),
    ]
    for from_s, to_s in transitions:
        if from_s == target_state:
            break
        manager.update_state(vid, to_s)
        if to_s == target_state:
            break
    return vid


class TestStrategyState:

    def test_strategy_state_values(self) -> None:
        expected = {
            "RESEARCH": "research",
            "BACKTEST_PASSED": "backtest_passed",
            "PAPER_TRADING": "paper_trading",
            "PILOT": "pilot",
            "LIVE": "live",
            "ARCHIVED": "archived",
        }
        for name, value in expected.items():
            assert StrategyState[name].value == value

    def test_valid_transitions_research(self) -> None:
        allowed = _VALID_TRANSITIONS[StrategyState.RESEARCH]
        assert allowed == {StrategyState.BACKTEST_PASSED, StrategyState.ARCHIVED}

    def test_valid_transitions_archived(self) -> None:
        allowed = _VALID_TRANSITIONS[StrategyState.ARCHIVED]
        assert allowed == set()


class TestDataclasses:

    def test_promotion_criteria_defaults(self) -> None:
        pc = PromotionCriteria()
        assert pc.sharpe_threshold == 1.5
        assert pc.min_positive_months == 3
        assert pc.max_drawdown == 0.15

    def test_strategy_config_defaults(self) -> None:
        cfg = StrategyConfig(name="s", version="1")
        assert cfg.parameters == {}
        assert cfg.risk_limits == {}
        assert cfg.universe == {}
        assert cfg.schedule == {}

    def test_promotion_result_fields(self) -> None:
        pr = PromotionResult(
            from_state=StrategyState.RESEARCH,
            to_state=StrategyState.BACKTEST_PASSED,
            approved=True,
            reason="All criteria met",
            metrics_snapshot={"sharpe": 1.0},
        )
        assert pr.from_state == StrategyState.RESEARCH
        assert pr.to_state == StrategyState.BACKTEST_PASSED
        assert pr.approved is True
        assert pr.reason == "All criteria met"
        assert pr.metrics_snapshot == {"sharpe": 1.0}

    def test_deviation_alert_fields(self) -> None:
        da = DeviationAlert(
            metric_name="sharpe",
            live_value=0.8,
            backtest_value=1.5,
            deviation=0.7,
            threshold=0.5,
            severity="warning",
        )
        assert da.metric_name == "sharpe"
        assert da.live_value == 0.8
        assert da.backtest_value == 1.5
        assert da.deviation == 0.7
        assert da.threshold == 0.5
        assert da.severity == "warning"


class TestStrategyLifecycleManagerRegister:

    def test_lifecycle_manager_register_strategy(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        assert isinstance(vid, str)
        assert len(vid) > 0
        strategies = manager.list_strategies()
        assert any(sv.version_id == vid for sv in strategies)

    def test_lifecycle_manager_register_strategy_state(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        sv = manager.get_strategy(vid)
        assert sv is not None
        assert sv.state == StrategyState.RESEARCH


class TestStrategyLifecycleManagerUpdateState:

    def test_lifecycle_manager_update_state_valid(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        result = manager.update_state(vid, StrategyState.BACKTEST_PASSED)
        assert result is True

    def test_lifecycle_manager_update_state_invalid(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        result = manager.update_state(vid, StrategyState.LIVE)
        assert result is False

    def test_lifecycle_manager_update_state_not_found(self) -> None:
        manager = _make_manager()
        result = manager.update_state("nonexistent", StrategyState.BACKTEST_PASSED)
        assert result is False


class TestStrategyLifecycleManagerGetList:

    def test_lifecycle_manager_get_strategy(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        sv = manager.get_strategy(vid)
        assert isinstance(sv, StrategyVersion)
        assert sv.version_id == vid

    def test_lifecycle_manager_get_strategy_not_found(self) -> None:
        manager = _make_manager()
        assert manager.get_strategy("nonexistent") is None

    def test_lifecycle_manager_list_strategies_all(self) -> None:
        manager = _make_manager()
        manager.register_strategy(_make_config(name="a", version="1"))
        manager.register_strategy(_make_config(name="b", version="1"))
        assert len(manager.list_strategies()) == 2

    def test_lifecycle_manager_list_strategies_by_state(self) -> None:
        manager = _make_manager()
        vid_a = manager.register_strategy(_make_config(name="a", version="1"))
        manager.register_strategy(_make_config(name="b", version="1"))
        manager.update_state(vid_a, StrategyState.BACKTEST_PASSED)
        research_list = manager.list_strategies(state=StrategyState.RESEARCH)
        bt_list = manager.list_strategies(state=StrategyState.BACKTEST_PASSED)
        assert len(research_list) == 1
        assert len(bt_list) == 1


class TestStrategyLifecycleManagerMetrics:

    def test_lifecycle_manager_record_metrics(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        manager.record_metrics(vid, {"sharpe": 1.2, "max_drawdown": 0.08})
        sv = manager.get_strategy(vid)
        assert sv is not None
        assert sv.metrics["sharpe"] == 1.2
        assert sv.metrics["max_drawdown"] == 0.08

    def test_lifecycle_manager_record_metrics_not_found(self) -> None:
        manager = _make_manager()
        manager.record_metrics("nonexistent", {"sharpe": 1.0})


class TestCheckPromotionEligibility:

    def test_check_promotion_eligibility_research_meets_criteria(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        manager.record_metrics(vid, {"sharpe": 0.5})
        result = manager.check_promotion_eligibility(vid)
        assert result.approved is True
        assert result.to_state == StrategyState.BACKTEST_PASSED

    def test_check_promotion_eligibility_research_fails_sharpe(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        manager.record_metrics(vid, {"sharpe": -0.1})
        result = manager.check_promotion_eligibility(vid)
        assert result.approved is False

    def test_check_promotion_eligibility_archived(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        manager.update_state(vid, StrategyState.ARCHIVED)
        result = manager.check_promotion_eligibility(vid)
        assert result.approved is False
        assert "Archived" in result.reason

    def test_check_promotion_eligibility_live(self) -> None:
        manager = _make_manager()
        vid = _register_and_advance(manager, target_state=StrategyState.LIVE)
        result = manager.check_promotion_eligibility(vid)
        assert result.approved is False
        assert "already LIVE" in result.reason

    def test_check_promotion_eligibility_paper_to_pilot(self) -> None:
        manager = _make_manager()
        vid = _register_and_advance(manager, target_state=StrategyState.PAPER_TRADING)
        manager.record_metrics(vid, {"sharpe": 1.6, "consecutive_positive_months": 3})
        result = manager.check_promotion_eligibility(vid)
        assert result.approved is True
        assert result.to_state == StrategyState.PILOT

    def test_check_promotion_eligibility_pilot_to_live(self) -> None:
        manager = _make_manager()
        vid = _register_and_advance(manager, target_state=StrategyState.PILOT)
        manager.record_metrics(vid, {
            "sharpe": 1.6,
            "max_drawdown": 0.10,
            "consecutive_positive_months": 4,
        })
        result = manager.check_promotion_eligibility(vid)
        assert result.approved is True
        assert result.to_state == StrategyState.LIVE


class TestPromote:

    def test_promote_approved(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        manager.record_metrics(vid, {"sharpe": 0.5})
        result = manager.promote(vid)
        assert result.approved is True
        sv = manager.get_strategy(vid)
        assert sv is not None
        assert sv.state == StrategyState.BACKTEST_PASSED

    def test_promote_denied(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        manager.record_metrics(vid, {"sharpe": -1.0})
        result = manager.promote(vid)
        assert result.approved is False
        sv = manager.get_strategy(vid)
        assert sv is not None
        assert sv.state == StrategyState.RESEARCH


class TestCompareVersions:

    def test_compare_versions(self) -> None:
        manager = _make_manager()
        vid_a = manager.register_strategy(_make_config(name="a", version="1"))
        vid_b = manager.register_strategy(_make_config(name="b", version="1"))
        manager.record_metrics(vid_a, {"sharpe": 1.0, "max_drawdown": 0.10})
        manager.record_metrics(vid_b, {"sharpe": 1.5, "max_drawdown": 0.08})
        result = manager.compare_versions(vid_a, vid_b)
        assert "metric_deltas" in result
        assert result["metric_deltas"]["sharpe"]["delta"] == pytest.approx(0.5)
        assert result["metric_deltas"]["max_drawdown"]["delta"] == pytest.approx(-0.02)

    def test_compare_versions_not_found(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        result = manager.compare_versions(vid, "nonexistent")
        assert "error" in result


class TestPaperTradingSandbox:

    def test_paper_trading_start(self) -> None:
        manager = _make_manager()
        vid = _register_and_advance(manager, target_state=StrategyState.BACKTEST_PASSED)
        sandbox = PaperTradingSandbox(manager)
        session_id = sandbox.start(vid, initial_capital=100_000.0)
        assert isinstance(session_id, str)
        assert session_id.startswith("pt_")

    def test_paper_trading_start_wrong_state(self) -> None:
        manager = _make_manager()
        vid = manager.register_strategy(_make_config())
        sandbox = PaperTradingSandbox(manager)
        with pytest.raises(ValueError, match="BACKTEST_PASSED or PAPER_TRADING"):
            sandbox.start(vid, initial_capital=100_000.0)

    def test_paper_trading_start_not_found(self) -> None:
        manager = _make_manager()
        sandbox = PaperTradingSandbox(manager)
        with pytest.raises(ValueError, match="not found"):
            sandbox.start("nonexistent", initial_capital=100_000.0)

    def test_paper_trading_stop(self) -> None:
        manager = _make_manager()
        vid = _register_and_advance(manager, target_state=StrategyState.BACKTEST_PASSED)
        sandbox = PaperTradingSandbox(manager)
        session_id = sandbox.start(vid, initial_capital=100_000.0)
        result = sandbox.stop(session_id)
        assert "pnl" in result
        assert "return_pct" in result
        assert "total_trades" in result

    def test_paper_trading_stop_not_found(self) -> None:
        manager = _make_manager()
        sandbox = PaperTradingSandbox(manager)
        with pytest.raises(ValueError, match="not found"):
            sandbox.stop("nonexistent")

    def test_paper_trading_get_session(self) -> None:
        manager = _make_manager()
        vid = _register_and_advance(manager, target_state=StrategyState.BACKTEST_PASSED)
        sandbox = PaperTradingSandbox(manager)
        session_id = sandbox.start(vid, initial_capital=100_000.0)
        session = sandbox.get_session(session_id)
        assert isinstance(session, PaperTradingSession)
        assert session.session_id == session_id


class TestLiveMonitor:

    def test_live_monitor_no_deviation(self) -> None:
        monitor = LiveMonitor()
        alerts = monitor.check_deviation(
            "v1",
            {"sharpe": 1.5, "max_drawdown": 0.10, "win_rate": 0.55},
            {"sharpe": 1.5, "max_drawdown": 0.10, "win_rate": 0.55},
        )
        assert alerts == []

    def test_live_monitor_sharpe_deviation_warning(self) -> None:
        monitor = LiveMonitor()
        alerts = monitor.check_deviation(
            "v1",
            {"sharpe": 0.9},
            {"sharpe": 1.5},
        )
        assert len(alerts) == 1
        assert alerts[0].metric_name == "sharpe"
        assert alerts[0].severity == "warning"

    def test_live_monitor_sharpe_deviation_critical(self) -> None:
        monitor = LiveMonitor()
        alerts = monitor.check_deviation(
            "v1",
            {"sharpe": 0.3},
            {"sharpe": 1.5},
        )
        assert len(alerts) == 1
        assert alerts[0].metric_name == "sharpe"
        assert alerts[0].severity == "critical"

    def test_live_monitor_drawdown_deviation(self) -> None:
        monitor = LiveMonitor()
        alerts = monitor.check_deviation(
            "v1",
            {"max_drawdown": 0.20},
            {"max_drawdown": 0.10},
        )
        assert len(alerts) == 1
        assert alerts[0].metric_name == "max_drawdown"

    def test_live_monitor_win_rate_deviation(self) -> None:
        monitor = LiveMonitor()
        alerts = monitor.check_deviation(
            "v1",
            {"win_rate": 0.40},
            {"win_rate": 0.55},
        )
        assert len(alerts) == 1
        assert alerts[0].metric_name == "win_rate"

    def test_live_monitor_multiple_deviations(self) -> None:
        monitor = LiveMonitor()
        alerts = monitor.check_deviation(
            "v1",
            {"sharpe": 0.8, "max_drawdown": 0.25, "win_rate": 0.35},
            {"sharpe": 1.5, "max_drawdown": 0.10, "win_rate": 0.55},
        )
        assert len(alerts) == 3
        names = {a.metric_name for a in alerts}
        assert names == {"sharpe", "max_drawdown", "win_rate"}
