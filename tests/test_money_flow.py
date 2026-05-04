import pytest


class TestMoneyFlowPatterns:
    def test_insufficient_data_returns_unknown(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        result = analyzer.analyze_flow_pattern([])
        assert result["pattern"] == "insufficient_data"
        assert result["trend"] == "unknown"

    def test_two_points_insufficient(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [
            {"main_net_inflow": 100},
            {"main_net_inflow": -50},
        ]
        result = analyzer.analyze_flow_pattern(history)
        assert result["pattern"] == "insufficient_data"

    def test_continuous_inflow_pattern(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [
            {"main_net_inflow": 100},
            {"main_net_inflow": 200},
            {"main_net_inflow": 150},
        ]
        result = analyzer.analyze_flow_pattern(history)
        assert result["pattern"] == "continuous_inflow"
        assert result["trend"] == "bullish"
        assert result["total_main_net"] == 450.0
        assert result["avg_main_net"] == 150.0
        assert result["max_inflow"] == 200.0
        assert result["max_outflow"] == 100.0

    def test_continuous_outflow_pattern(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [
            {"main_net_inflow": -50},
            {"main_net_inflow": -100},
            {"main_net_inflow": -200},
        ]
        result = analyzer.analyze_flow_pattern(history)
        assert result["pattern"] == "continuous_outflow"
        assert result["trend"] == "bearish"

    def test_inflow_reversal_pattern(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [
            {"main_net_inflow": -50},
            {"main_net_inflow": -30},
            {"main_net_inflow": 100},
        ]
        result = analyzer.analyze_flow_pattern(history)
        assert result["pattern"] == "inflow_reversal"
        assert result["trend"] == "reversal_up"

    def test_outflow_reversal_pattern(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [
            {"main_net_inflow": 50},
            {"main_net_inflow": 30},
            {"main_net_inflow": -100},
        ]
        result = analyzer.analyze_flow_pattern(history)
        assert result["pattern"] == "outflow_reversal"
        assert result["trend"] == "reversal_down"

    def test_mixed_pattern(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [
            {"main_net_inflow": 100},
            {"main_net_inflow": -50},
            {"main_net_inflow": -30},
        ]
        result = analyzer.analyze_flow_pattern(history)
        assert result["pattern"] == "mixed"
        assert result["trend"] == "neutral"

    def test_missing_main_net_key_defaults_to_zero(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [{}, {}, {"main_net_inflow": 100}]
        result = analyzer.analyze_flow_pattern(history)
        assert result["pattern"] in ("mixed", "inflow_reversal")

    def test_large_history_with_mixed_signals(self):
        from core.money_flow import MoneyFlowAnalyzer

        analyzer = MoneyFlowAnalyzer()
        history = [
            {"main_net_inflow": 100},
            {"main_net_inflow": -50},
            {"main_net_inflow": -50},
        ]
        result = analyzer.analyze_flow_pattern(history)
        assert result["trend"] == "neutral"

    def test_singleton_getter(self):
        from core.money_flow import get_money_flow_analyzer

        a1 = get_money_flow_analyzer()
        a2 = get_money_flow_analyzer()
        assert a1 is a2
