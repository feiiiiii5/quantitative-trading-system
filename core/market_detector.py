import re


class MarketDetector:
    A_SHARE_PREFIXES = {"0", "1", "2", "3", "4", "5", "6", "8", "9"}
    HK_PREFIXES = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}
    US_PATTERN = re.compile(r"^[A-Z]{1,5}$")
    US_9DIGIT_PATTERN = re.compile(r"^[A-Z]{1,4}\.?[A-Z]?$")

    MARKET_CONFIG = {
        "A": {
            "name": "A股",
            "currency": "CNY",
            "exchange": "SSE/SZSE",
            "trading_hours": "09:30-11:30,13:00-15:00",
            "badge_color": "#ff4757",
        },
        "HK": {
            "name": "港股",
            "currency": "HKD",
            "exchange": "HKEX",
            "trading_hours": "09:30-12:00,13:00-16:00",
            "badge_color": "#ffa502",
        },
        "US": {
            "name": "美股",
            "currency": "USD",
            "exchange": "NYSE/NASDAQ",
            "trading_hours": "21:30-04:00(ET)",
            "badge_color": "#00d4aa",
        },
    }

    HK_INDEX_CODES = {"HSI", "HSTECH", "HSCEI", "HSCI", "HSMBI", "HSHKCI"}

    @classmethod
    def detect(cls, symbol: str) -> str:
        s = symbol.strip().upper()
        if s in cls.HK_INDEX_CODES:
            return "HK"
        if s.endswith(".HK") or s.endswith(".HKEX"):
            return "HK"
        clean = re.sub(r"[^A-Za-z0-9.]", "", s)
        if re.match(r"^[A-Z]", clean):
            if cls.US_PATTERN.match(clean.split(".")[0]) or cls.US_9DIGIT_PATTERN.match(clean):
                return "US"
        digits = re.sub(r"[^0-9]", "", symbol)
        if len(digits) == 6 and digits[0] in cls.A_SHARE_PREFIXES:
            return "A"
        if len(digits) <= 5 and digits and digits[0] in cls.HK_PREFIXES:
            if not cls.US_PATTERN.match(s) and not cls.US_9DIGIT_PATTERN.match(s):
                return "HK"
        if cls.US_PATTERN.match(s) or cls.US_9DIGIT_PATTERN.match(s):
            return "US"
        return "A"

    @classmethod
    def get_config(cls, symbol: str) -> dict:
        market = cls.detect(symbol)
        return {"market": market, **cls.MARKET_CONFIG[market]}

    @classmethod
    def normalize_symbol(cls, symbol: str) -> str:
        s = symbol.strip()
        market = cls.detect(s)
        if market == "HK":
            digits = re.sub(r"[^0-9]", "", s)
            return digits.zfill(5)
        if market == "US":
            return s.upper().split(".")[0]
        return re.sub(r"[^0-9]", "", s)
