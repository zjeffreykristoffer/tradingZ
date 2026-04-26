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
    allow_origins=["*"],
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
# TRADE STORE
# ======================
TRADE_HISTORY = []
MAX_HISTORY = 500

# ======================
# SYMBOL CONFIG
# ======================
SYMBOL_CONFIG = {
    "DEFAULT": {"pip": 0.0001, "atr_multiplier_tp": 2.0},
    "JPY": {"pip": 0.01, "atr_multiplier_tp": 2.0},
    "XAU": {"pip": 0.1, "atr_multiplier_tp": 2.5},
}


def get_symbol_config(symbol):
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

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=300&apikey={API_KEY}"
    r = httpx.get(url, timeout=10).json()

    if "values" not in r:
        return None

    closes = [float(x["close"]) for x in r["values"]][::-1]
    highs = [float(x["high"]) for x in r["values"]][::-1]
    lows = [float(x["low"]) for x in r["values"]][::-1]

    cache[key] = {"data": (closes, highs, lows), "time": now}
    return closes, highs, lows


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

    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / len(trs)


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
    high = highs[-2]
    low = lows[-2]

    upper, mid, lower = bollinger(closes)
    rsi_val = rsi_vals[-2]

    trend = 1 if ema50[-2] > ema200[-2] else -1

    # RSI bias
    if rsi_val < 30:
        rsi_bias = 1
    elif rsi_val > 70:
        rsi_bias = -1
    else:
        rsi_bias = 0

    # BB bias
    pos = (price - lower) / (upper - lower) if upper != lower else 0.5
    bb_bias = 1 if pos < 0.3 else (-1 if pos > 0.7 else 0)

    return {
        "trend": trend,
        "rsi_bias": rsi_bias,
        "bb_bias": bb_bias,
        "rsi": rsi_val,
        "ema50": ema50[-2],
        "ema200": ema200[-2],
        "price": price,
        "high": high,
        "low": low,
        "atr": vol,
    }


# ======================
# TRADE LOGIC
# ======================
def log_trade(symbol, signal, entry, sl, tp):
    if "BUY" not in signal and "SELL" not in signal:
        return

    TRADE_HISTORY.append({
        "symbol": symbol,
        "signal": signal,
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "status": "OPEN",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


def evaluate_trades(symbol, high, low):
    for t in TRADE_HISTORY:
        if t["symbol"] != symbol or t["status"] != "OPEN":
            continue

        if "BUY" in t["signal"]:
            if high >= t["take_profit"]:
                t["status"] = "WIN"
            elif low <= t["stop_loss"]:
                t["status"] = "LOSS"

        elif "SELL" in t["signal"]:
            if low <= t["take_profit"]:
                t["status"] = "WIN"
            elif high >= t["stop_loss"]:
                t["status"] = "LOSS"


# ======================
# PROCESS
# ======================
def process(symbol):
    data = get_prices(symbol, TIMEFRAME)
    if not data:
        return {"symbol": symbol, "signal": "NO DATA"}

    closes, highs, lows = data

    d = score_trade(closes, highs, lows)

    # Evaluate existing trades
    evaluate_trades(symbol, d["high"], d["low"])

    trend = d["trend"]

    confidence = 50 + trend * 20 + d["rsi_bias"] * 15 + d["bb_bias"] * 15
    confidence = max(0, min(100, confidence))

    if confidence >= 75:
        signal = "STRONG BUY" if trend == 1 else "STRONG SELL"
    elif confidence >= 60:
        signal = "BUY" if trend == 1 else "SELL"
    elif confidence >= 50:
        signal = "WEAK BUY" if trend == 1 else "WEAK SELL"
    else:
        signal = "NO TRADE"

    entry = d["price"]

    if "BUY" in signal:
        sl = min(lows[-5:])
        tp = entry + (entry - sl) * 2
    elif "SELL" in signal:
        sl = max(highs[-5:])
        tp = entry - (sl - entry) * 2
    else:
        sl = tp = None

    # Log trade AFTER evaluation
    log_trade(symbol, signal, entry, sl, tp)

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": round(confidence, 2),
        "trend": "BULLISH" if trend == 1 else "BEARISH",
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


@app.get("/history")
def history(start: str = None, end: str = None):
    data = TRADE_HISTORY

    if start:
        data = [t for t in data if t["timestamp"] >= start]
    if end:
        data = [t for t in data if t["timestamp"] <= end]

    return {"data": data}
