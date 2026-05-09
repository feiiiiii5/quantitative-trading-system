import numpy as np
import pandas as pd
import pytest

from core.duckdb_analytics import _validate_identifier, _validate_path


class TestValidateIdentifier:
    def test_validate_identifier_valid(self) -> None:
        for name in ("close", "open_price", "_private", "A1"):
            _validate_identifier(name)

    def test_validate_identifier_rejects_semicolon(self) -> None:
        with pytest.raises(ValueError):
            _validate_identifier("col; DROP TABLE")

    def test_validate_identifier_rejects_space(self) -> None:
        with pytest.raises(ValueError):
            _validate_identifier("col name")

    def test_validate_identifier_rejects_hyphen(self) -> None:
        with pytest.raises(ValueError):
            _validate_identifier("col-name")

    def test_validate_identifier_rejects_starts_digit(self) -> None:
        with pytest.raises(ValueError):
            _validate_identifier("1col")

    def test_validate_identifier_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            _validate_identifier("")

    def test_validate_identifier_rejects_sql_injection(self) -> None:
        with pytest.raises(ValueError):
            _validate_identifier("col'); DROP TABLE--")


class TestValidatePath:
    def test_validate_path_valid(self) -> None:
        _validate_path("data/file.parquet")

    def test_validate_path_rejects_parent_traversal(self) -> None:
        with pytest.raises(ValueError):
            _validate_path("../etc/passwd")

    def test_validate_path_rejects_absolute(self) -> None:
        with pytest.raises(ValueError):
            _validate_path("/etc/passwd")

    def test_validate_path_rejects_double_dot_middle(self) -> None:
        with pytest.raises(ValueError):
            _validate_path("data/../etc/passwd")


class TestDuckDBAnalyticsSecurity:
    @pytest.fixture()
    def analytics(self) -> None:
        duckdb = pytest.importorskip("duckdb")
        from core.duckdb_analytics import DuckDBAnalytics
        inst = DuckDBAnalytics()
        yield inst
        inst.close()

    def test_correlation_matrix_rejects_malicious_column(self, analytics: None) -> None:
        dates = pd.date_range("2024-01-01", periods=30)
        df = pd.DataFrame({
            "date": dates,
            "col'); DROP TABLE--": np.random.randn(30) + 100,
        })
        with pytest.raises(ValueError):
            analytics.correlation_matrix(df)

    def test_rolling_correlation_rejects_malicious_symbol(self, analytics: None) -> None:
        dates = pd.date_range("2024-01-01", periods=30)
        df = pd.DataFrame({
            "date": dates,
            "A": np.random.randn(30) + 100,
            "B": np.random.randn(30) + 100,
        })
        with pytest.raises(ValueError):
            analytics.rolling_correlation("; DROP TABLE--", "B", df)

    def test_rolling_correlation_rejects_window_lt_2(self, analytics: None) -> None:
        dates = pd.date_range("2024-01-01", periods=30)
        df = pd.DataFrame({
            "date": dates,
            "A": np.random.randn(30) + 100,
            "B": np.random.randn(30) + 100,
        })
        with pytest.raises(ValueError):
            analytics.rolling_correlation("A", "B", df, window=1)
