import numpy as np
import pandas as pd

from core.database import ThreadSafeLRU

_indicator_cache = ThreadSafeLRU(maxsize=200)


class TechnicalIndicators:

    @staticmethod
    def compute_all(df: pd.DataFrame, symbol: str = "", period: str = "daily") -> dict:
        if df is None or len(df) < 30:
            return {}

        cache_key = f"{symbol}:{period}"
        if df is not None and "date" in df.columns and len(df) > 0:
            last_date = str(df["date"].iloc[-1])[:10]
            cache_key = f"{symbol}:{period}:{last_date}"

        cached = _indicator_cache.get(cache_key)
        if cached is not None:
            return cached

        c = df["close"].values.astype(float)
        h = df["high"].values.astype(float)
        low_arr = df["low"].values.astype(float)
        v = df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(len(df))

        ma = TechnicalIndicators._ma(c)
        ema = TechnicalIndicators._ema(c)
        boll = TechnicalIndicators._boll(c)
        macd = TechnicalIndicators._macd(c)
        supertrend = TechnicalIndicators._supertrend(h, low_arr, c)
        ichimoku = TechnicalIndicators._ichimoku(h, low_arr, c)

        rsi = TechnicalIndicators._rsi(c)
        kdj = TechnicalIndicators._kdj(h, low_arr, c)
        cci = TechnicalIndicators._cci(h, low_arr, c)
        williams_r = TechnicalIndicators._williams_r(h, low_arr, c)
        roc = TechnicalIndicators._roc(c)

        vwap = TechnicalIndicators._vwap(h, low_arr, c, v)
        obv = TechnicalIndicators._obv(c, v)
        volume_ratio = TechnicalIndicators._volume_ratio(v)
        cmf = TechnicalIndicators._cmf(h, low_arr, c, v)

        atr = TechnicalIndicators._atr(h, low_arr, c)
        hist_vol = TechnicalIndicators._hist_vol(c)
        bb_position = TechnicalIndicators._bb_position(c, boll)

        trend_score = TechnicalIndicators._trend_score(
            ma, ema, macd, rsi, kdj, cci, supertrend, boll, bb_position
        )
        signal = TechnicalIndicators._signal(trend_score)

        result = {
            "ma": ma, "ema": ema, "boll": boll, "macd": macd,
            "supertrend": supertrend, "ichimoku": ichimoku,
            "rsi": rsi, "kdj": kdj, "cci": _last(cci),
            "williams_r": _last(williams_r), "roc": roc,
            "vwap": _last(vwap), "obv": _last(obv),
            "volume_ratio": _last(volume_ratio), "cmf": _last(cmf),
            "atr": _last(atr), "hist_vol": hist_vol,
            "bb_position": _last(bb_position),
            "trend_score": trend_score, "signal": signal,
        }

        _indicator_cache.set(cache_key, result, ttl=30)

        return result

    @staticmethod
    def _ma(c: np.ndarray) -> dict:
        result = {}
        for p in [5, 10, 20, 60, 120]:
            if len(c) >= p:
                vals = pd.Series(c).rolling(p).mean().values
                result[p] = _to_list(vals)
        return result

    @staticmethod
    def _ema(c: np.ndarray) -> dict:
        result = {}
        for p in [12, 26]:
            s = pd.Series(c)
            vals = s.ewm(span=p, adjust=False).mean().values
            result[p] = _to_list(vals)
        return result

    @staticmethod
    def _boll(c: np.ndarray, period: int = 20, nbdev: float = 2.0) -> dict:
        s = pd.Series(c)
        mid = s.rolling(period).mean()
        std = s.rolling(period).std()
        upper = mid + nbdev * std
        lower = mid - nbdev * std
        width = ((upper - lower) / mid * 100).values
        return {
            "upper": _to_list(upper.values),
            "mid": _to_list(mid.values),
            "lower": _to_list(lower.values),
            "width": _to_list(width),
        }

    @staticmethod
    def _macd(c: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
        s = pd.Series(c)
        ema_fast = s.ewm(span=fast, adjust=False).mean()
        ema_slow = s.ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        hist = (dif - dea) * 2
        return {
            "dif": _to_list(dif.values),
            "dea": _to_list(dea.values),
            "hist": _to_list(hist.values),
        }

    @staticmethod
    def _supertrend(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray,
                    period: int = 10, multiplier: float = 3.0) -> dict:
        tr = np.maximum(h - low_arr, np.maximum(np.abs(h - np.roll(c, 1)),
                                           np.abs(low_arr - np.roll(c, 1))))
        tr[0] = h[0] - low_arr[0]
        atr = pd.Series(tr).rolling(period).mean().values
        n = len(c)
        upper_band = np.zeros(n)
        lower_band = np.zeros(n)
        supertrend = np.zeros(n)
        direction = np.ones(n)

        hl2 = (h + low_arr) / 2
        upper_band = hl2 + multiplier * atr
        lower_band = hl2 - multiplier * atr

        for i in range(1, n):
            if np.isnan(atr[i]):
                supertrend[i] = np.nan
                continue
            if lower_band[i] > lower_band[i - 1] or c[i - 1] < lower_band[i - 1]:
                pass
            else:
                lower_band[i] = lower_band[i - 1]
            if upper_band[i] < upper_band[i - 1] or c[i - 1] > upper_band[i - 1]:
                pass
            else:
                upper_band[i] = upper_band[i - 1]
            if direction[i - 1] == 1:
                if c[i] < lower_band[i]:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]
                else:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
            else:
                if c[i] > upper_band[i]:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
                else:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]

        return {
            "value": _to_list(supertrend),
            "direction": _to_list(direction),
        }

    @staticmethod
    def _ichimoku(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray) -> dict:
        def _mid(high, low, period):
            roll_h = pd.Series(high).rolling(period, min_periods=period).max()
            roll_l = pd.Series(low).rolling(period, min_periods=period).min()
            return ((roll_h + roll_l) / 2).values

        tenkan = _mid(h, low_arr, 9)
        kijun = _mid(h, low_arr, 26)
        senkou_a = (tenkan + kijun) / 2
        senkou_b = _mid(h, low_arr, 52)
        return {
            "tenkan": _to_list(tenkan),
            "kijun": _to_list(kijun),
            "senkou_a": _to_list(senkou_a),
            "senkou_b": _to_list(senkou_b),
        }

    @staticmethod
    def _rsi(c: np.ndarray) -> dict:
        result = {}
        for p in [6, 12, 24]:
            delta = np.diff(c, prepend=c[0])
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = pd.Series(gain).ewm(alpha=1 / p, min_periods=p).mean().values
            avg_loss = pd.Series(loss).ewm(alpha=1 / p, min_periods=p).mean().values
            rs = np.where(avg_loss != 0, avg_gain / avg_loss, 100)
            rsi_vals = 100 - 100 / (1 + rs)
            result[p] = _to_list(rsi_vals)
        return result

    @staticmethod
    def _kdj(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray,
             n: int = 9, m1: int = 3, m2: int = 3) -> dict:
        hh = pd.Series(h).rolling(n).max().values
        ll = pd.Series(low_arr).rolling(n).min().values
        rsv = np.where(
            np.isfinite(hh) & np.isfinite(ll) & (hh != ll),
            (c - ll) / (hh - ll) * 100,
            50.0,
        )
        k = np.full(len(c), 50.0)
        d = np.full(len(c), 50.0)
        for i in range(1, len(c)):
            k[i] = (2 / m1) * k[i - 1] + (1 / m1) * rsv[i]
            d[i] = (2 / m2) * d[i - 1] + (1 / m2) * k[i]
        j = 3 * k - 2 * d
        return {"k": _to_list(k), "d": _to_list(d), "j": _to_list(j)}

    @staticmethod
    def _cci(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
        tp = (h + low_arr + c) / 3
        ma = pd.Series(tp).rolling(period).mean().values
        md = pd.Series(tp).rolling(period).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        ).values
        cci = np.where(np.isfinite(md) & (md != 0), (tp - ma) / (0.015 * md), 0)
        return cci

    @staticmethod
    def _williams_r(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
        hh = pd.Series(h).rolling(period).max().values
        ll = pd.Series(low_arr).rolling(period).min().values
        wr = np.where(np.isfinite(hh) & np.isfinite(ll) & (hh != ll), (hh - c) / (hh - ll) * -100, -50)
        return wr

    @staticmethod
    def _roc(c: np.ndarray) -> dict:
        result = {}
        for p in [3, 5, 10, 20]:
            vals = np.zeros(len(c))
            vals[p:] = (c[p:] - c[:-p]) / c[:-p] * 100
            result[p] = _to_list(vals)
        return result

    @staticmethod
    def _vwap(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray, v: np.ndarray) -> np.ndarray:
        tp = (h + low_arr + c) / 3
        cum_tp_v = np.cumsum(tp * v)
        cum_v = np.cumsum(v)
        return np.where(cum_v != 0, cum_tp_v / cum_v, c)

    @staticmethod
    def _obv(c: np.ndarray, v: np.ndarray) -> np.ndarray:
        direction = np.sign(np.diff(c, prepend=c[0]))
        obv = np.cumsum(direction * v)
        return obv

    @staticmethod
    def _volume_ratio(v: np.ndarray, period: int = 5) -> np.ndarray:
        avg = pd.Series(v).rolling(period).mean().values
        return np.where(avg != 0, v / avg, 1)

    @staticmethod
    def _cmf(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray, v: np.ndarray,
             period: int = 20) -> np.ndarray:
        clv = np.where((h - low_arr) != 0, ((c - low_arr) - (h - c)) / (h - low_arr), 0)
        mfv = clv * v
        cmf = pd.Series(mfv).rolling(period).sum() / pd.Series(v).rolling(period).sum()
        return cmf.values

    @staticmethod
    def _atr(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
        tr = np.maximum(h - low_arr, np.maximum(np.abs(h - np.roll(c, 1)),
                                           np.abs(low_arr - np.roll(c, 1))))
        tr[0] = h[0] - low_arr[0]
        return pd.Series(tr).ewm(alpha=1 / period, min_periods=period).mean().values

    @staticmethod
    def _hist_vol(c: np.ndarray) -> dict:
        log_ret = np.log(c[1:] / c[:-1])
        log_ret = np.insert(log_ret, 0, 0)
        result = {}
        for p in [10, 20, 60]:
            vol = pd.Series(log_ret).rolling(p).std().values * np.sqrt(252) * 100
            result[p] = _to_list(vol)
        return result

    @staticmethod
    def _bb_position(c: np.ndarray, boll: dict) -> np.ndarray:
        upper = np.array(boll["upper"])
        lower = np.array(boll["lower"])
        diff = upper - lower
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(diff != 0, (c - lower) / diff, 0.5)

    @staticmethod
    def _trend_score(ma, ema, macd, rsi, kdj, cci, supertrend, boll, bb_position) -> float:
        score = 0
        try:
            last_close_idx = -1
            if 5 in ma and 20 in ma:
                ma5_last = ma[5][last_close_idx]
                ma20_last = ma[20][last_close_idx]
                if not np.isnan(ma5_last) and not np.isnan(ma20_last):
                    score += 15 if ma5_last > ma20_last else -15
            if 10 in ma and 60 in ma:
                ma10_last = ma[10][last_close_idx]
                ma60_last = ma[60][last_close_idx]
                if not np.isnan(ma10_last) and not np.isnan(ma60_last):
                    score += 15 if ma10_last > ma60_last else -15
            if 12 in ema and 26 in ema:
                dif_last = macd["dif"][last_close_idx]
                dea_last = macd["dea"][last_close_idx]
                if not np.isnan(dif_last) and not np.isnan(dea_last):
                    score += 10 if dif_last > dea_last else -10
                    hist_last = macd["hist"][last_close_idx]
                    hist_prev = macd["hist"][-2] if len(macd["hist"]) > 1 else 0
                    if hist_last > hist_prev:
                        score += 5
                    else:
                        score -= 5
            for p in [6, 12, 24]:
                if p in rsi:
                    val = rsi[p][last_close_idx]
                    if not np.isnan(val):
                        if val > 70:
                            score -= 8
                        elif val > 50:
                            score += 5
                        elif val < 30:
                            score += 8
                        elif val < 50:
                            score -= 5
            k_last = kdj["k"][last_close_idx]
            d_last = kdj["d"][last_close_idx]
            if not np.isnan(k_last) and not np.isnan(d_last):
                if k_last > d_last:
                    score += 5
                else:
                    score -= 5
                if k_last > 80:
                    score -= 5
                elif k_last < 20:
                    score += 5
            cci_val = cci if isinstance(cci, (int, float)) else 0
            if cci_val > 100:
                score += 5
            elif cci_val < -100:
                score -= 5
            st_dir = supertrend.get("direction", [])
            if st_dir:
                score += 10 if st_dir[last_close_idx] == 1 else -10
            bb_pos = bb_position if isinstance(bb_position, (int, float)) else 0.5
            if bb_pos > 0.8:
                score -= 5
            elif bb_pos < 0.2:
                score += 5
        except (IndexError, KeyError, TypeError):
            pass
        return max(-100, min(100, score))

    @staticmethod
    def _signal(trend_score: float) -> str:
        if trend_score >= 50:
            return "strong_buy"
        elif trend_score >= 15:
            return "buy"
        elif trend_score <= -50:
            return "strong_sell"
        elif trend_score <= -15:
            return "sell"
        return "neutral"


def _to_list(arr) -> list:
    if isinstance(arr, np.ndarray):
        return np.nan_to_num(arr, nan=0).round(4).tolist()
    if isinstance(arr, pd.Series):
        return np.nan_to_num(arr.values, nan=0).round(4).tolist()
    return []


def _last(arr) -> float:
    try:
        if isinstance(arr, np.ndarray):
            val = arr[-1]
        elif isinstance(arr, list):
            val = arr[-1]
        else:
            return 0.0
        return round(float(val), 4) if not np.isnan(val) else 0.0
    except (IndexError, TypeError):
        return 0.0


class KLinePatternRecognizer:
    @staticmethod
    def recognize(df: pd.DataFrame) -> list[dict]:
        if df is None or len(df) < 5:
            return []
        result = []
        candles = df.reset_index(drop=True)
        n = len(candles)
        closes = candles["close"].astype(float).values
        slopes = np.zeros(n)
        lookback = 5
        for i in range(n):
            start = max(0, i - lookback)
            if i - start < 2:
                slopes[i] = 0.0
            else:
                x = np.arange(i - start)
                slopes[i] = float(np.polyfit(x, closes[start:i], 1)[0])
        for i in range(len(candles)):
            row = candles.iloc[i]
            open_price = float(row["open"])
            close_price = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            body = abs(close_price - open_price)
            upper = high - max(open_price, close_price)
            lower = min(open_price, close_price) - low
            trend = slopes[i]

            if body > 0 and lower > body * 2 and upper <= max(body * 0.3, 0.01):
                if trend < 0:
                    result.append({"index": i, "date": str(row["date"]), "pattern": "hammer", "label": "锤子线", "price": low})
                if trend > 0:
                    result.append({"index": i, "date": str(row["date"]), "pattern": "hanging_man", "label": "吊颈线", "price": high})

            if max(open_price, close_price) > 0 and body / max(open_price, close_price) < 0.0015:
                result.append({"index": i, "date": str(row["date"]), "pattern": "doji", "label": "十字星", "price": close_price})

            if i >= 1:
                prev = candles.iloc[i - 1]
                prev_open = float(prev["open"])
                prev_close = float(prev["close"])
                prev_body_high = max(prev_open, prev_close)
                prev_body_low = min(prev_open, prev_close)
                curr_body_high = max(open_price, close_price)
                curr_body_low = min(open_price, close_price)
                if curr_body_high <= prev_body_high and curr_body_low >= prev_body_low:
                    result.append({"index": i, "date": str(row["date"]), "pattern": "harami", "label": "孕线", "price": close_price})
                if curr_body_high >= prev_body_high and curr_body_low <= prev_body_low and np.sign(close_price - open_price) != np.sign(prev_close - prev_open):
                    result.append({"index": i, "date": str(row["date"]), "pattern": "engulfing", "label": "吞噬形态", "price": close_price})

            if i >= 2:
                a = candles.iloc[i - 2]
                b = candles.iloc[i - 1]
                c = row
                a_body = abs(float(a["close"]) - float(a["open"]))
                b_body = abs(float(b["close"]) - float(b["open"]))
                midpoint_a = (float(a["open"]) + float(a["close"])) / 2
                if float(a["close"]) < float(a["open"]) and b_body < a_body * 0.5 and float(c["close"]) > float(c["open"]) and float(c["close"]) > midpoint_a:
                    result.append({"index": i, "date": str(row["date"]), "pattern": "morning_star", "label": "早晨之星", "price": float(c["close"])})
                if float(a["close"]) > float(a["open"]) and b_body < a_body * 0.5 and float(c["close"]) < float(c["open"]) and float(c["close"]) < midpoint_a:
                    result.append({"index": i, "date": str(row["date"]), "pattern": "evening_star", "label": "黄昏之星", "price": float(c["close"])})
        return result

    @staticmethod
    def _trend(df: pd.DataFrame, index: int, lookback: int = 5) -> float:
        start = max(0, index - lookback)
        if index - start < 2:
            return 0.0
        closes = df.iloc[start:index]["close"].astype(float).values
        x = np.arange(len(closes))
        slope = np.polyfit(x, closes, 1)[0]
        return float(slope)


class IndicatorAnalysis:
    @staticmethod
    def ma_alignment(df: pd.DataFrame) -> dict:
        if df is None or len(df) < 60:
            return {"bullish": False, "bearish": False, "values": {}}
        closes = df["close"].astype(float)
        ma5 = closes.rolling(5).mean().iloc[-1]
        ma10 = closes.rolling(10).mean().iloc[-1]
        ma20 = closes.rolling(20).mean().iloc[-1]
        ma60 = closes.rolling(60).mean().iloc[-1]
        values = {"ma5": round(float(ma5), 4), "ma10": round(float(ma10), 4), "ma20": round(float(ma20), 4), "ma60": round(float(ma60), 4)}
        return {
            "bullish": ma5 > ma10 > ma20 > ma60,
            "bearish": ma5 < ma10 < ma20 < ma60,
            "values": values,
        }

    @staticmethod
    def boll_squeeze(df: pd.DataFrame) -> dict:
        if df is None or len(df) < 25:
            return {"warning": False, "points": []}
        closes = df["close"].astype(float)
        mid = closes.rolling(20).mean()
        std = closes.rolling(20).std()
        width = (std * 4 / mid.replace(0, np.nan)).fillna(0)
        shrink = width.diff().fillna(0) < 0
        warnings = []
        for i in range(24, len(df)):
            if shrink.iloc[i - 4:i + 1].all() and width.iloc[i] < width.iloc[max(i - 19, 0):i + 1].mean() * 0.6:
                warnings.append({"index": i, "date": str(df.iloc[i]["date"]), "width": round(float(width.iloc[i]), 4)})
        return {"warning": bool(warnings), "points": warnings}

    @staticmethod
    def volume_price_analysis(df: pd.DataFrame) -> dict:
        if df is None or len(df) < 20:
            return {}
        window = df.tail(20).copy()
        x = np.arange(len(window))
        volume = window["volume"].astype(float).values
        closes = window["close"].astype(float).values
        slope = float(np.polyfit(x, volume, 1)[0]) if len(volume) > 1 else 0
        volume_ratio = float(volume[-1] / max(np.mean(volume[-5:]), 1))
        price_ret = pd.Series(closes).pct_change().fillna(0)
        up_volume = volume[price_ret > 0].sum()
        down_volume = volume[price_ret <= 0].sum()
        obv = np.cumsum(np.sign(price_ret.values) * volume)
        obv_ma = pd.Series(obv).rolling(20).mean().bfill()
        obv_trend = float(obv_ma.iloc[-1] - obv_ma.iloc[0])
        if closes[-1] > closes[0] and volume_ratio > 1:
            conclusion = "量增价涨，强势信号"
            color = "green"
        elif closes[-1] < closes[0] and volume_ratio > 1:
            conclusion = "量增价跌，出货信号"
            color = "red"
        else:
            conclusion = "量价配合中性"
            color = "neutral"
        return {
            "volume_trend_slope": round(slope, 4),
            "volume_ratio": round(volume_ratio, 4),
            "volume_factor": round(float(up_volume / max(down_volume, 1)), 4),
            "obv_trend": round(obv_trend, 4),
            "conclusion": conclusion,
            "color": color,
        }

    @staticmethod
    def support_resistance(df: pd.DataFrame, lookback: int = 120) -> dict:
        if df is None or len(df) < 30:
            return {"supports": [], "resistances": []}
        recent = df.tail(lookback).copy()
        closes = recent["close"].astype(float)
        highs = recent["high"].astype(float)
        lows = recent["low"].astype(float)
        supports = sorted({round(float(v), 2) for v in [lows.min(), lows.quantile(0.1), closes.rolling(20).mean().iloc[-1], closes.rolling(60).mean().iloc[-1]] if np.isfinite(v)})
        resistances = sorted({round(float(v), 2) for v in [highs.max(), highs.quantile(0.9), np.ceil(closes.iloc[-1] / 10) * 10] if np.isfinite(v)})
        return {"supports": supports[:6], "resistances": resistances[:6]}

    @staticmethod
    def volatility_range(df: pd.DataFrame) -> dict:
        if df is None or len(df) < 25:
            return {}
        h = df["high"].astype(float).values
        low_arr = df["low"].astype(float).values
        c = df["close"].astype(float).values
        atr = TechnicalIndicators._atr(h, low_arr, c, period=14)
        atr20 = pd.Series(atr).rolling(20).mean().iloc[-1]
        last_close = float(c[-1])
        return {
            "atr20": round(float(atr20), 4) if np.isfinite(atr20) else 0,
            "predicted_low": round(last_close - float(atr20), 4) if np.isfinite(atr20) else round(last_close, 4),
            "predicted_high": round(last_close + float(atr20), 4) if np.isfinite(atr20) else round(last_close, 4),
            "note": "基于历史波动率的统计区间，不构成精确预测",
        }

    @staticmethod
    def vpvr(df: pd.DataFrame, bins: int = 24, lookback: int = 120) -> dict:
        if df is None or len(df) < 10:
            return {"bins": [], "point_of_control": 0}
        recent = df.tail(lookback).copy()
        low = float(recent["low"].min())
        high = float(recent["high"].max())
        if high <= low:
            return {"bins": [], "point_of_control": round(low, 4)}
        edges = np.linspace(low, high, bins + 1)
        labels = []
        volumes = []
        for i in range(bins):
            if i < bins - 1:
                mask = (recent["close"] >= edges[i]) & (recent["close"] < edges[i + 1])
            else:
                mask = (recent["close"] >= edges[i]) & (recent["close"] <= edges[i + 1])
            vol = float(recent.loc[mask, "volume"].astype(float).sum())
            labels.append(round(float((edges[i] + edges[i + 1]) / 2), 4))
            volumes.append(round(vol, 4))
        point_of_control = labels[int(np.argmax(volumes))] if volumes else 0
        return {"bins": [{"price": labels[i], "volume": volumes[i]} for i in range(len(labels))], "point_of_control": point_of_control}

    @staticmethod
    def trend_lines(df: pd.DataFrame, lookback: int = 120) -> dict:
        if df is None or len(df) < 20:
            return {"support_line": [], "resistance_line": []}
        recent = df.tail(lookback).reset_index(drop=True)
        lows = recent["low"].astype(float)
        highs = recent["high"].astype(float)
        x = np.arange(len(recent))
        low_idx = lows.nsmallest(min(5, len(lows))).index.values
        high_idx = highs.nlargest(min(5, len(highs))).index.values
        support_coef = np.polyfit(low_idx, lows.iloc[low_idx], 1) if len(low_idx) >= 2 else (0, float(lows.iloc[-1]))
        resist_coef = np.polyfit(high_idx, highs.iloc[high_idx], 1) if len(high_idx) >= 2 else (0, float(highs.iloc[-1]))
        support_line = (support_coef[0] * x + support_coef[1]).round(4).tolist()
        resistance_line = (resist_coef[0] * x + resist_coef[1]).round(4).tolist()
        return {"support_line": support_line, "resistance_line": resistance_line}

    @staticmethod
    def relative_strength(df: pd.DataFrame, benchmark_df: pd.DataFrame) -> dict:
        if df is None or benchmark_df is None or df.empty or benchmark_df.empty:
            return {"series": []}
        left = df[["date", "close"]].rename(columns={"close": "asset_close"})
        right = benchmark_df[["date", "close"]].rename(columns={"close": "benchmark_close"})
        merged = left.merge(right, on="date", how="inner")
        if merged.empty:
            return {"series": []}
        merged["asset_norm"] = merged["asset_close"] / merged["asset_close"].iloc[0] * 100
        merged["benchmark_norm"] = merged["benchmark_close"] / merged["benchmark_close"].iloc[0] * 100
        merged["relative"] = merged["asset_norm"] - merged["benchmark_norm"]
        return {
            "series": merged[["date", "asset_norm", "benchmark_norm", "relative"]].assign(date=lambda x: x["date"].astype(str)).to_dict("records"),
            "stronger_than_benchmark": float(merged["relative"].iloc[-1]) > 0,
        }

    @staticmethod
    def rsi_divergence(df: pd.DataFrame, period: int = 14) -> dict:
        if df is None or len(df) < 30:
            return {"top_divergence": [], "bottom_divergence": []}
        closes = df["close"].astype(float).values
        delta = np.diff(closes, prepend=closes[0])
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gains).ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = pd.Series(losses).ewm(alpha=1 / period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = (100 - 100 / (1 + rs)).fillna(50)
        top_divergence = []
        bottom_divergence = []
        for i in range(5, len(df)):
            price_window = closes[i - 5:i + 1]
            rsi_window = rsi.iloc[i - 5:i + 1].values
            if closes[i] >= np.max(price_window) and rsi.iloc[i] < np.max(rsi_window[:-1]):
                top_divergence.append({"index": i, "date": str(df.iloc[i]["date"]), "price": round(float(closes[i]), 4), "rsi": round(float(rsi.iloc[i]), 4)})
            if closes[i] <= np.min(price_window) and rsi.iloc[i] > np.min(rsi_window[:-1]):
                bottom_divergence.append({"index": i, "date": str(df.iloc[i]["date"]), "price": round(float(closes[i]), 4), "rsi": round(float(rsi.iloc[i]), 4)})
        return {"top_divergence": top_divergence, "bottom_divergence": bottom_divergence}


def calc_all_indicators(kline_data: list) -> dict:
    if not kline_data or len(kline_data) < 30:
        return {"error": "Insufficient data"}

    df = pd.DataFrame(kline_data)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    result = {}

    try:
        computed = TechnicalIndicators.compute_all(df)
        if computed:
            result.update(computed)
    except Exception:
        pass

    try:
        result["ma_alignment"] = IndicatorAnalysis.ma_alignment(df)
    except Exception:
        pass

    try:
        result["support_resistance"] = IndicatorAnalysis.support_resistance(df)
    except Exception:
        pass

    try:
        result["volatility"] = IndicatorAnalysis.volatility_range(df)
    except Exception:
        pass

    try:
        result["volume_price"] = IndicatorAnalysis.volume_price_analysis(df)
    except Exception:
        pass

    try:
        result["rsi_divergence"] = IndicatorAnalysis.rsi_divergence(df)
    except Exception:
        pass

    try:
        result["kline_patterns"] = KLinePatternRecognizer.recognize(df)
    except Exception:
        pass

    return result


def calc_factor_ic(factor_values, forward_returns, periods: list = None) -> dict:
    if periods is None:
        periods = [1, 5, 10]

    fv = np.array(factor_values, dtype=float)
    fr = np.array(forward_returns, dtype=float)

    result = {}
    for p in periods:
        if len(fv) < p + 2 or len(fr) < p + 2:
            result[p] = {"IC": 0.0, "ICIR": 0.0, "IC_positive_ratio": 0.0}
            continue

        n = min(len(fv), len(fr)) - p
        if n < 2:
            result[p] = {"IC": 0.0, "ICIR": 0.0, "IC_positive_ratio": 0.0}
            continue

        ic_list = []
        window = max(20, n // 4)
        for i in range(window, n, window):
            x = fv[i - window:i]
            y = fr[i - window + p:i + p]
            min_len = min(len(x), len(y))
            x = x[:min_len]
            y = y[:min_len]
            mask = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
            x_clean = x[mask]
            y_clean = y[mask]
            if len(x_clean) < 3:
                ic_list.append(0.0)
                continue
            try:
                from scipy.stats import pearsonr
                corr, _ = pearsonr(x_clean, y_clean)
                ic_list.append(float(corr) if np.isfinite(corr) else 0.0)
            except Exception:
                ic_list.append(0.0)

        if not ic_list:
            result[p] = {"IC": 0.0, "ICIR": 0.0, "IC_positive_ratio": 0.0}
            continue

        ic_arr = np.array(ic_list)
        mean_ic = float(np.mean(ic_arr))
        std_ic = float(np.std(ic_arr))
        icir = mean_ic / std_ic if std_ic > 0 else 0.0
        ic_pos_ratio = float(np.sum(ic_arr > 0) / len(ic_arr))

        result[p] = {
            "IC": round(mean_ic, 4),
            "ICIR": round(icir, 4),
            "IC_positive_ratio": round(ic_pos_ratio, 4),
        }

    return result


def calc_factor_turnover(factor_values_series) -> float:
    arr = np.array(factor_values_series, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 2:
        return 0.0

    turnover_list = []
    for i in range(1, arr.shape[0]):
        rank_t = np.argsort(np.argsort(arr[i - 1]))
        rank_t1 = np.argsort(np.argsort(arr[i]))
        mask = ~(np.isnan(arr[i - 1]) | np.isnan(arr[i]))
        if mask.sum() < 3:
            continue
        rank_t_clean = rank_t[mask]
        rank_t1_clean = rank_t1[mask]
        try:
            from scipy.stats import spearmanr
            corr, _ = spearmanr(rank_t_clean, rank_t1_clean)
            turnover_list.append(float(corr) if np.isfinite(corr) else 0.0)
        except Exception:
            continue

    if not turnover_list:
        return 0.0

    return round(float(np.mean(turnover_list)), 4)


def calc_atr(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - low_arr[0]
    for i in range(1, n):
        tr[i] = max(h[i] - low_arr[i], abs(h[i] - c[i - 1]), abs(low_arr[i] - c[i - 1]))
    return pd.Series(tr).ewm(alpha=1 / period, min_periods=period).mean().values


def calc_adx(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - low_arr[0]
    for i in range(1, n):
        tr[i] = max(h[i] - low_arr[i], abs(h[i] - c[i - 1]), abs(low_arr[i] - c[i - 1]))
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = h[i] - h[i - 1]
        down_move = low_arr[i - 1] - low_arr[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
    atr = pd.Series(tr).ewm(alpha=1 / period, min_periods=period).mean().values
    plus_di = np.where(atr > 0, pd.Series(plus_dm).ewm(alpha=1 / period, min_periods=period).mean().values / atr * 100, 0)
    minus_di = np.where(atr > 0, pd.Series(minus_dm).ewm(alpha=1 / period, min_periods=period).mean().values / atr * 100, 0)
    dx = np.where((plus_di + minus_di) > 0, np.abs(plus_di - minus_di) / (plus_di + minus_di) * 100, 0)
    adx = pd.Series(dx).ewm(alpha=1 / period, min_periods=period).mean().values
    return adx


def calc_chandelier_exit(h: np.ndarray, low_arr: np.ndarray, c: np.ndarray,
                          atr: np.ndarray, period: int = 22, mult: float = 3.0):
    n = len(c)
    long_stop = np.full(n, np.nan)
    short_stop = np.full(n, np.nan)
    for i in range(period, n):
        highest = np.max(h[i - period:i + 1])
        lowest = np.min(low_arr[i - period:i + 1])
        atr_val = atr[i] if not np.isnan(atr[i]) else 0
        long_stop[i] = highest - mult * atr_val
        short_stop[i] = lowest + mult * atr_val
        if i > period:
            if c[i - 1] > long_stop[i - 1]:
                long_stop[i] = max(long_stop[i], long_stop[i - 1])
            if c[i - 1] < short_stop[i - 1]:
                short_stop[i] = min(short_stop[i], short_stop[i - 1])
    return long_stop, short_stop


def calc_kelly_fraction(c: np.ndarray, lookback: int = 60, half_kelly: float = 0.5) -> float:
    if len(c) < lookback + 1:
        return 0.25
    returns = np.diff(c[-lookback - 1:]) / c[-lookback - 1:-1]
    returns = returns[np.isfinite(returns)]
    if len(returns) < 10:
        return 0.25
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    if len(wins) == 0 or len(losses) == 0:
        return 0.25
    win_rate = len(wins) / len(returns)
    avg_win = np.mean(wins)
    avg_loss = abs(np.mean(losses))
    if avg_loss == 0:
        return 0.25
    win_loss_ratio = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / win_loss_ratio
    kelly = max(0.05, min(0.5, kelly * half_kelly))
    return kelly
