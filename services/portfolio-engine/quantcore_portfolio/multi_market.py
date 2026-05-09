import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

import pytz

logger = logging.getLogger(__name__)


class Market(Enum):
    SSE = "SSE"
    SZSE = "SZSE"
    HKEX = "HKEX"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"


@dataclass(frozen=True)
class TradingHours:
    morning_open: str
    morning_close: str
    afternoon_open: str
    afternoon_close: str


@dataclass(frozen=True)
class MarketConfig:
    market: Market
    trading_hours: TradingHours
    currency: str
    settlement_days: int
    commission_rate: float
    tax_rate: float
    timezone: str
    holidays: frozenset[date]


_SSE_HOLIDAYS_2024: frozenset[date] = frozenset({
    date(2024, 1, 1), date(2024, 2, 9), date(2024, 2, 10),
    date(2024, 2, 12), date(2024, 2, 13), date(2024, 2, 14),
    date(2024, 2, 15), date(2024, 2, 16), date(2024, 4, 4),
    date(2024, 4, 5), date(2024, 5, 1), date(2024, 5, 2),
    date(2024, 5, 3), date(2024, 6, 10), date(2024, 9, 16),
    date(2024, 9, 17), date(2024, 10, 1), date(2024, 10, 2),
    date(2024, 10, 3), date(2024, 10, 4), date(2024, 10, 7),
    date(2024, 12, 30), date(2024, 12, 31),
})
_SSE_HOLIDAYS_2025: frozenset[date] = frozenset({
    date(2025, 1, 1), date(2025, 1, 28), date(2025, 1, 29),
    date(2025, 1, 30), date(2025, 1, 31), date(2025, 2, 3),
    date(2025, 2, 4), date(2025, 4, 4), date(2025, 5, 1),
    date(2025, 5, 2), date(2025, 5, 5), date(2025, 5, 31),
    date(2025, 6, 2), date(2025, 10, 1), date(2025, 10, 2),
    date(2025, 10, 3), date(2025, 10, 6), date(2025, 10, 7),
    date(2025, 10, 8), date(2025, 12, 31),
})
_SSE_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17),
    date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20),
    date(2026, 4, 6), date(2026, 5, 1), date(2026, 5, 4),
    date(2026, 6, 19), date(2026, 10, 1), date(2026, 10, 2),
    date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
    date(2026, 12, 31),
})

_HKEX_HOLIDAYS_2024: frozenset[date] = frozenset({
    date(2024, 1, 1), date(2024, 2, 10), date(2024, 2, 12),
    date(2024, 2, 13), date(2024, 3, 29), date(2024, 3, 30),
    date(2024, 4, 1), date(2024, 4, 4), date(2024, 5, 1),
    date(2024, 5, 15), date(2024, 6, 10), date(2024, 7, 1),
    date(2024, 9, 18), date(2024, 10, 1), date(2024, 10, 11),
    date(2024, 12, 25), date(2024, 12, 26),
})
_HKEX_HOLIDAYS_2025: frozenset[date] = frozenset({
    date(2025, 1, 1), date(2025, 1, 29), date(2025, 1, 30),
    date(2025, 1, 31), date(2025, 4, 4), date(2025, 4, 18),
    date(2025, 4, 19), date(2025, 5, 1), date(2025, 5, 5),
    date(2025, 6, 2), date(2025, 7, 1), date(2025, 10, 1),
    date(2025, 10, 7), date(2025, 12, 25), date(2025, 12, 26),
})
_HKEX_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 4, 3), date(2026, 4, 6),
    date(2026, 5, 1), date(2026, 5, 25), date(2026, 7, 1),
    date(2026, 10, 1), date(2026, 10, 22), date(2026, 12, 25),
    date(2026, 12, 26),
})

_US_HOLIDAYS_2024: frozenset[date] = frozenset({
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19),
    date(2024, 3, 29), date(2024, 5, 27), date(2024, 6, 19),
    date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28),
    date(2024, 11, 29), date(2024, 12, 24), date(2024, 12, 25),
})
_US_HOLIDAYS_2025: frozenset[date] = frozenset({
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 11, 28), date(2025, 12, 24), date(2025, 12, 25),
})
_US_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 11, 27), date(2026, 12, 24), date(2026, 12, 25),
})

_CN_HOLIDAYS = _SSE_HOLIDAYS_2024 | _SSE_HOLIDAYS_2025 | _SSE_HOLIDAYS_2026
_HK_HOLIDAYS = _HKEX_HOLIDAYS_2024 | _HKEX_HOLIDAYS_2025 | _HKEX_HOLIDAYS_2026
_US_HOLIDAYS = _US_HOLIDAYS_2024 | _US_HOLIDAYS_2025 | _US_HOLIDAYS_2026

_CN_TRADING_HOURS = TradingHours(
    morning_open="09:30", morning_close="11:30",
    afternoon_open="13:00", afternoon_close="15:00",
)
_HK_TRADING_HOURS = TradingHours(
    morning_open="09:30", morning_close="12:00",
    afternoon_open="13:00", afternoon_close="16:00",
)
_US_TRADING_HOURS = TradingHours(
    morning_open="09:30", morning_close="16:00",
    afternoon_open="09:30", afternoon_close="16:00",
)

_FX_RATES: dict[tuple[str, str], float] = {
    ("CNY", "HKD"): 1.08,
    ("HKD", "CNY"): 1.0 / 1.08,
    ("CNY", "USD"): 0.14,
    ("USD", "CNY"): 1.0 / 0.14,
    ("HKD", "USD"): 0.13,
    ("USD", "HKD"): 1.0 / 0.13,
}


class MultiMarketManager:
    def __init__(self) -> None:
        self._market_configs: dict[Market, MarketConfig] = {
            Market.SSE: MarketConfig(
                market=Market.SSE,
                trading_hours=_CN_TRADING_HOURS,
                currency="CNY",
                settlement_days=1,
                commission_rate=0.0003,
                tax_rate=0.001,
                timezone="Asia/Shanghai",
                holidays=_CN_HOLIDAYS,
            ),
            Market.SZSE: MarketConfig(
                market=Market.SZSE,
                trading_hours=_CN_TRADING_HOURS,
                currency="CNY",
                settlement_days=1,
                commission_rate=0.0003,
                tax_rate=0.001,
                timezone="Asia/Shanghai",
                holidays=_CN_HOLIDAYS,
            ),
            Market.HKEX: MarketConfig(
                market=Market.HKEX,
                trading_hours=_HK_TRADING_HOURS,
                currency="HKD",
                settlement_days=2,
                commission_rate=0.0005,
                tax_rate=0.0013,
                timezone="Asia/Hong_Kong",
                holidays=_HK_HOLIDAYS,
            ),
            Market.NYSE: MarketConfig(
                market=Market.NYSE,
                trading_hours=_US_TRADING_HOURS,
                currency="USD",
                settlement_days=1,
                commission_rate=0.0001,
                tax_rate=0.0,
                timezone="US/Eastern",
                holidays=_US_HOLIDAYS,
            ),
            Market.NASDAQ: MarketConfig(
                market=Market.NASDAQ,
                trading_hours=_US_TRADING_HOURS,
                currency="USD",
                settlement_days=1,
                commission_rate=0.0001,
                tax_rate=0.0,
                timezone="US/Eastern",
                holidays=_US_HOLIDAYS,
            ),
        }

    def get_market_config(self, market: Market) -> MarketConfig:
        config = self._market_configs.get(market)
        if config is None:
            raise ValueError(f"Unknown market: {market}")
        return config

    def convert_currency(
        self, amount: float, from_currency: str, to_currency: str
    ) -> float:
        if from_currency == to_currency:
            return amount
        rate = _FX_RATES.get((from_currency, to_currency))
        if rate is None:
            raise ValueError(
                f"No FX rate for {from_currency} -> {to_currency}"
            )
        return amount * rate

    def is_market_open(self, market: Market) -> bool:
        config = self.get_market_config(market)
        tz = pytz.timezone(config.timezone)
        now = datetime.now(tz)
        today = now.date()

        if today.weekday() >= 5 or today in config.holidays:
            return False

        current_time = now.time()
        hours = config.trading_hours
        morning_open = datetime.strptime(hours.morning_open, "%H:%M").time()
        morning_close = datetime.strptime(hours.morning_close, "%H:%M").time()
        afternoon_open = datetime.strptime(hours.afternoon_open, "%H:%M").time()
        afternoon_close = datetime.strptime(hours.afternoon_close, "%H:%M").time()

        in_morning = morning_open <= current_time < morning_close
        in_afternoon = afternoon_open <= current_time < afternoon_close
        return in_morning or in_afternoon

    def get_next_trading_day(self, market: Market, from_date: date) -> date:
        config = self.get_market_config(market)
        candidate = from_date + timedelta(days=1)
        for _ in range(30):
            if candidate.weekday() < 5 and candidate not in config.holidays:
                return candidate
            candidate += timedelta(days=1)
        raise ValueError(
            f"Could not find next trading day within 30 days for {market.value}"
        )

    def calculate_settlement_date(self, market: Market, trade_date: date) -> date:
        config = self.get_market_config(market)
        remaining = config.settlement_days
        candidate = trade_date
        while remaining > 0:
            candidate += timedelta(days=1)
            if candidate.weekday() < 5 and candidate not in config.holidays:
                remaining -= 1
        return candidate
