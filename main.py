import os
import math
from time import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ======================
# CORS
# ======================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://trading-z.vercel.app"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ======================
# CONFIG
# ======================
API_KEY = os.getenv("TWELVE_DATA_KEY")

TIMEFRAME = "15min"
HTF_TIMEFRAME = "1h"

SYNC_INTERVAL = 900
CACHE_TTL = 300

# ======================
# SYMBOL CONFIG
# ======================
SYMBOL_CONFIG = {
    "DEFAULT": {"pip": 0.0001, "atr_multiplier_sl": 1.2, "atr_multiplier_tp": 2.0, "min_atr_pips": 2},
    "JPY": {"pip": 0.01, "atr_multiplier_sl": 1.2, "atr_multiplier_tp": 2.0, "min_atr_pips": 2},
    "XAU": {"pip": 0.1, "atr_multiplier_sl": 1.5, "atr_multiplier_tp": 2.5, "min_atr_pips": 15},
}


def get_symbol_config(symbol: str):
    if "XAU" in symbol:
        return SYMBOL_CONFIG["XAU"]
    if "JPY" in symbol:
        return SYMBOL_CONFIG["JPY"]
    return SYMBOL_CONFIG["DEFAULT"]


# ======================
# CACHE
# ======================
cache = {}


def get_prices(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"]

    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=300&apikey={API_KEY}"
        r = httpx.get(url, timeout=10).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]][::-1]
        highs = [float(x["high"]) for x in r["values"]][::-1]
        lows = [float(x["low"]) for x in r["values"]][::-1]

        cache[key] = {"data": (closes, highs, lows), "time": now}
        return closes, highs, lows

    except Exception as e:
        print(e)
        return None


# ======================
# INDICATORS
# ======================
def ema(data, period):
    k = 2 / (period + 1)
    out = [data[0]]
    for p in data[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def rsi(data, period=14):
    if len(data) < period + 1:
        return [50] * len(data)

    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsis = []

    for i in range(period, len(data)):
        rs = avg_gain / (avg_loss + 1e-9)
        rsis.append(100 - (100 / (1 + rs)))

        if i < len(data) - 1:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    return [50] * period + rsis


def atr(high, low, close, period=14):
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)

    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0

    smoothed = sum(trs[:period]) / period
    for tr in trs[period:]:
        smoothed = (smoothed * (period - 1) + tr) / period

    return smoothed


def bollinger(data, period=20):
    window = data[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    return mean + 2 * std, mean, mean - 2 * std


# ======================
# SIGNAL ENGINE
# ======================
def score_trade(closes, highs, lows):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_vals = rsi(closes)
    vol = atr(highs, lows, closes)

    price = closes[-2]
    upper, mid, lower = bollinger(closes)
    rsi_val = rsi_vals[-2]

    trend = 1 if ema50[-2] > ema200[-2] else -1

    # RSI bias
    if rsi_val < 30:
        rsi_bias = 1
    elif rsi_val > 70:
        rsi_bias = -1
    elif rsi_val < 45:
        rsi_bias = 0.5
    elif rsi_val > 55:
        rsi_bias = -0.5
    else:
        rsi_bias = 0

    # Bollinger bias
    band_range = upper - lower if upper != lower else 1
    pos = (price - lower) / band_range

    if pos < 0.3:
        bb_bias = 1
    elif pos > 0.7:
        bb_bias = -1
    else:
        bb_bias = 0

    return {
        "trend": trend,
        "rsi_bias": rsi_bias,
        "bb_bias": bb_bias,
        "rsi": rsi_val,
        "ema50": ema50[-2],
        "ema200": ema200[-2],
        "price": price,
        "atr": vol,
    }


# ======================
# PROCESS
# ======================
def process(symbol):
    data = get_prices(symbol, TIMEFRAME)
    htf = get_prices(symbol, HTF_TIMEFRAME)

    if not data or not htf:
        return {"symbol": symbol, "signal": "NO DATA"}

    closes, highs, lows = data
    htf_closes, _, _ = htf

    d = score_trade(closes, highs, lows)

    trend = d["trend"]

    # CONFIDENCE
    confidence = 50
    confidence += trend * 20
    confidence += d["rsi_bias"] * 15
    confidence += d["bb_bias"] * 15

    # HTF influence
    htf_ema50 = ema(htf_closes, 50)
    htf_ema200 = ema(htf_closes, 200)
    htf_trend = 1 if htf_ema50[-2] > htf_ema200[-2] else -1

    confidence += 10 if trend == htf_trend else -10

    confidence = max(0, min(100, confidence))

    # SIGNAL
    if confidence >= 75:
        signal = "STRONG BUY" if trend == 1 else "STRONG SELL"
    elif confidence >= 60:
        signal = "BUY" if trend == 1 else "SELL"
    elif confidence >= 50:
        signal = "WEAK BUY" if trend == 1 else "WEAK SELL"
    else:
        signal = "NO TRADE"

    trend_label = "BULLISH" if trend == 1 else "BEARISH"

    # SL/TP
    cfg = get_symbol_config(symbol)
    entry = d["price"]

    if "BUY" in signal:
        sl = min(lows[-5:])
        risk = entry - sl
        tp = entry + risk * cfg["atr_multiplier_tp"]
    elif "SELL" in signal:
        sl = max(highs[-5:])
        risk = sl - entry
        tp = entry - risk * cfg["atr_multiplier_tp"]
    else:
        sl = tp = None

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": round(confidence, 2),
        "trend": trend_label,
        "entry": round(entry, 5),
        "stop_loss": round(sl, 5) if sl else None,
        "take_profit": round(tp, 5) if tp else None,
        "rsi": round(d["rsi"], 2),
        "atr": round(d["atr"], 5),
        "ema50": round(d["ema50"], 5),
        "ema200": round(d["ema200"], 5),
    }


# ======================
# API
# ======================
@app.get("/dashboard/all")
def dashboard():
    now = datetime.now(timezone.utc)

    return {
        "data": {
            "NZDUSD": process("NZD/USD"),
            "GOLD": process("XAU/USD"),
        },
        "meta": {
            "last_fetch": now.isoformat(),
            "next_sync": SYNC_INTERVAL,
        },
    }
