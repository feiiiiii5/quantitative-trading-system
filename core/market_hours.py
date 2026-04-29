import logging
from datetime import date, datetime, time, timedelta
import pytz

logger = logging.getLogger(__name__)

_A_MORNING_OPEN = time(9, 30)
_A_MORNING_CLOSE = time(11, 30)
_A_AFTERNOON_OPEN = time(13, 0)
_A_AFTERNOON_CLOSE = time(15, 0)

_HK_MORNING_OPEN = time(9, 30)
_HK_MORNING_CLOSE = time(12, 0)
_HK_AFTERNOON_OPEN = time(13, 0)
_HK_AFTERNOON_CLOSE = time(16, 0)

_US_PRE_OPEN = time(9, 30)
_US_OPEN = time(9, 30)
_US_CLOSE = time(16, 0)
_US_ET = "US/Eastern"

_A_HOLIDAYS_2024 = {
    date(2024, 1, 1), date(2024, 2, 9), date(2024, 2, 10),
    date(2024, 2, 12), date(2024, 2, 13), date(2024, 2, 14),
    date(2024, 2, 15), date(2024, 2, 16), date(2024, 4, 4),
    date(2024, 4, 5), date(2024, 5, 1), date(2024, 5, 2),
    date(2024, 5, 3), date(2024, 6, 10), date(2024, 9, 16),
    date(2024, 9, 17), date(2024, 10, 1), date(2024, 10, 2),
    date(2024, 10, 3), date(2024, 10, 4), date(2024, 10, 7),
    date(2024, 12, 30), date(2024, 12, 31),
}
_A_HOLIDAYS_2025 = {
    date(2025, 1, 1), date(2025, 1, 28), date(2025, 1, 29),
    date(2025, 1, 30), date(2025, 1, 31), date(2025, 2, 3),
    date(2025, 2, 4), date(2025, 4, 4), date(2025, 5, 1),
    date(2025, 5, 2), date(2025, 5, 5), date(2025, 5, 31),
    date(2025, 6, 2), date(2025, 10, 1), date(2025, 10, 2),
    date(2025, 10, 3), date(2025, 10, 6), date(2025, 10, 7),
    date(2025, 10, 8), date(2025, 12, 31),
}
_A_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17),
    date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20),
    date(2026, 4, 6), date(2026, 5, 1), date(2026, 5, 4),
    date(2026, 6, 19), date(2026, 10, 1), date(2026, 10, 2),
    date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
    date(2026, 12, 31),
}
A_HOLIDAYS = _A_HOLIDAYS_2024 | _A_HOLIDAYS_2025 | _A_HOLIDAYS_2026

_HK_HOLIDAYS_2024 = {
    date(2024, 1, 1), date(2024, 2, 10), date(2024, 2, 12),
    date(2024, 2, 13), date(2024, 3, 29), date(2024, 3, 30),
    date(2024, 4, 1), date(2024, 4, 4), date(2024, 5, 1),
    date(2024, 5, 15), date(2024, 6, 10), date(2024, 7, 1),
    date(2024, 9, 18), date(2024, 10, 1), date(2024, 10, 11),
    date(2024, 12, 25), date(2024, 12, 26),
}
_HK_HOLIDAYS_2025 = {
    date(2025, 1, 1), date(2025, 1, 29), date(2025, 1, 30),
    date(2025, 1, 31), date(2025, 4, 4), date(2025, 4, 18),
    date(2025, 4, 19), date(2025, 5, 1), date(2025, 5, 5),
    date(2025, 6, 2), date(2025, 7, 1), date(2025, 10, 1),
    date(2025, 10, 7), date(2025, 12, 25), date(2025, 12, 26),
}
_HK_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 4, 3), date(2026, 4, 6),
    date(2026, 5, 1), date(2026, 5, 25), date(2026, 7, 1),
    date(2026, 10, 1), date(2026, 10, 22), date(2026, 12, 25),
    date(2026, 12, 26),
}
HK_HOLIDAYS = _HK_HOLIDAYS_2024 | _HK_HOLIDAYS_2025 | _HK_HOLIDAYS_2026

_US_HOLIDAYS_2024 = {
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19),
    date(2024, 3, 29), date(2024, 5, 27), date(2024, 6, 19),
    date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28),
    date(2024, 11, 29), date(2024, 12, 24), date(2024, 12, 25),
}
_US_HOLIDAYS_2025 = {
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 11, 28), date(2025, 12, 24), date(2025, 12, 25),
}
_US_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 11, 27), date(2026, 12, 24), date(2026, 12, 25),
}
US_HOLIDAYS = _US_HOLIDAYS_2024 | _US_HOLIDAYS_2025 | _US_HOLIDAYS_2026


class MarketHours:
    @staticmethod
    def get_market_status(market: str) -> dict:
        if market == "A":
            return MarketHours._a_status()
        elif market == "HK":
            return MarketHours._hk_status()
        elif market == "US":
            return MarketHours._us_status()
        return {"is_open": False, "session": "unknown", "next_open": None}

    @staticmethod
    def _a_status() -> dict:
        now = datetime.now(pytz.timezone("Asia/Shanghai"))
        today = now.date()
        weekday = today.weekday()

        if weekday >= 5 or today in A_HOLIDAYS:
            next_open = MarketHours._a_next_open(now)
            return {
                "is_open": False,
                "session": "closed",
                "reason": "weekend" if weekday >= 5 else "holiday",
                "next_open": next_open,
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": "Asia/Shanghai",
            }

        t = now.time()
        if _A_MORNING_OPEN <= t < _A_MORNING_CLOSE:
            session = "morning"
        elif _A_AFTERNOON_OPEN <= t < _A_AFTERNOON_CLOSE:
            session = "afternoon"
        elif _A_MORNING_CLOSE <= t < _A_AFTERNOON_OPEN:
            session = "lunch_break"
        elif t < _A_MORNING_OPEN:
            session = "pre_market"
        else:
            next_open = MarketHours._a_next_open(now)
            return {
                "is_open": False,
                "session": "closed",
                "reason": "after_hours",
                "next_open": next_open,
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": "Asia/Shanghai",
            }

        is_open = session in ("morning", "afternoon")
        return {
            "is_open": is_open,
            "session": session,
            "reason": None if is_open else "lunch_break",
            "next_open": None,
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "Asia/Shanghai",
        }

    @staticmethod
    def _a_next_open(now: datetime) -> str:
        d = now.date()
        for i in range(1, 15):
            candidate = d + timedelta(days=i)
            if candidate.weekday() < 5 and candidate not in A_HOLIDAYS:
                return datetime.combine(candidate, _A_MORNING_OPEN).strftime("%Y-%m-%d %H:%M")
        return ""

    @staticmethod
    def _hk_status() -> dict:
        now = datetime.now(pytz.timezone("Asia/Hong_Kong"))
        today = now.date()
        weekday = today.weekday()

        if weekday >= 5 or today in HK_HOLIDAYS:
            next_open = MarketHours._hk_next_open(now)
            return {
                "is_open": False,
                "session": "closed",
                "reason": "weekend" if weekday >= 5 else "holiday",
                "next_open": next_open,
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": "Asia/Hong_Kong",
            }

        t = now.time()
        if _HK_MORNING_OPEN <= t < _HK_MORNING_CLOSE:
            session = "morning"
        elif _HK_AFTERNOON_OPEN <= t < _HK_AFTERNOON_CLOSE:
            session = "afternoon"
        elif _HK_MORNING_CLOSE <= t < _HK_AFTERNOON_OPEN:
            session = "lunch_break"
        elif t < _HK_MORNING_OPEN:
            session = "pre_market"
        else:
            next_open = MarketHours._hk_next_open(now)
            return {
                "is_open": False,
                "session": "closed",
                "reason": "after_hours",
                "next_open": next_open,
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": "Asia/Hong_Kong",
            }

        is_open = session in ("morning", "afternoon")
        return {
            "is_open": is_open,
            "session": session,
            "reason": None if is_open else "lunch_break",
            "next_open": None,
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "Asia/Hong_Kong",
        }

    @staticmethod
    def _hk_next_open(now: datetime) -> str:
        d = now.date()
        for i in range(1, 15):
            candidate = d + timedelta(days=i)
            if candidate.weekday() < 5 and candidate not in HK_HOLIDAYS:
                return datetime.combine(candidate, _HK_MORNING_OPEN).strftime("%Y-%m-%d %H:%M")
        return ""

    @staticmethod
    def _us_status() -> dict:
        et = pytz.timezone(_US_ET)
        now = datetime.now(et)
        today = now.date()
        weekday = today.weekday()

        if weekday >= 5 or today in US_HOLIDAYS:
            next_open = MarketHours._us_next_open(now)
            return {
                "is_open": False,
                "session": "closed",
                "reason": "weekend" if weekday >= 5 else "holiday",
                "next_open": next_open,
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": _US_ET,
            }

        t = now.time()
        if t < _US_OPEN:
            session = "pre_market"
        elif _US_OPEN <= t < _US_CLOSE:
            session = "regular"
        else:
            session = "after_hours"

        is_open = session == "regular"
        return {
            "is_open": is_open,
            "session": session,
            "reason": None if is_open else ("pre_market" if session == "pre_market" else "after_hours"),
            "next_open": None if is_open else MarketHours._us_next_open(now),
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": _US_ET,
        }

    @staticmethod
    def _us_next_open(now: datetime) -> str:
        d = now.date()
        for i in range(1, 15):
            candidate = d + timedelta(days=i)
            if candidate.weekday() < 5 and candidate not in US_HOLIDAYS:
                return datetime.combine(candidate, _US_OPEN).strftime("%Y-%m-%d %H:%M")
        return ""

    @staticmethod
    def get_refresh_interval(market: str) -> int:
        status = MarketHours.get_market_status(market)
        if status.get("is_open"):
            return 1
        return 30

    @staticmethod
    def should_fetch_realtime(market: str) -> bool:
        status = MarketHours.get_market_status(market)
        return status.get("is_open", False)
