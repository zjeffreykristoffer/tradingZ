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
# TRADE TRACKING
# ======================
trade_log = []
stats = {"wins": 0, "losses": 0, "total": 0}

# ======================
# SYMBOL CONFIG
# ======================
SYMBOL_CONFIG = {
    "DEFAULT": {"pip": 0.0001, "sl_mult": 1.5, "tp_mult": 2.2, "min_atr_pips": 5},
    "JPY":     {"pip": 0.01,   "sl_mult": 1.5, "tp_mult": 2.2, "min_atr_pips": 5},
    "XAU":     {"pip": 0.1,    "sl_mult": 1.8, "tp_mult": 2.5, "min_atr_pips": 20},
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
        highs  = [float(x["high"]) for x in r["values"]][::-1]
        lows   = [float(x["low"]) for x in r["values"]][::-1]

        cache[key] = {"data": (closes, highs, lows), "time": now}
        return closes, highs, lows

    except:
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

    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / len(trs)

def bollinger(data, period=20):
    window = data[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    return mean + 2 * std, mean, mean - 2 * std

def macd(data):
    ema12 = ema(data, 12)
    ema26 = ema(data, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal = ema(macd_line, 9)
    return macd_line[-1] - signal[-1]

# ======================
# TRADE LOGIC
# ======================
def log_trade(symbol, signal, entry, sl, tp):
    if "TRADE" in signal or sl is None:
        return

    trade_log.append({
        "symbol": symbol,
        "direction": "BUY" if "BUY" in signal else "SELL",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "status": "OPEN"
    })

def update_trades():
    for trade in trade_log:
        if trade["status"] != "OPEN":
            continue

        data = get_prices(trade["symbol"], TIMEFRAME)
        if not data:
            continue

        _, highs, lows = data

        for h, l in zip(highs[-3:], lows[-3:]):
            if trade["direction"] == "BUY":
                if l <= trade["sl"]:
                    trade["status"] = "LOSS"
                    stats["losses"] += 1
                    stats["total"] += 1
                    break
                if h >= trade["tp"]:
                    trade["status"] = "WIN"
                    stats["wins"] += 1
                    stats["total"] += 1
                    break
            else:
                if h >= trade["sl"]:
                    trade["status"] = "LOSS"
                    stats["losses"] += 1
                    stats["total"] += 1
                    break
                if l <= trade["tp"]:
                    trade["status"] = "WIN"
                    stats["wins"] += 1
                    stats["total"] += 1
                    break

# ======================
# PROCESS
# ======================
def process(symbol):
    data = get_prices(symbol, TIMEFRAME)
    htf  = get_prices(symbol, HTF_TIMEFRAME)

    if not data or not htf:
        return {"symbol": symbol, "signal": "NO DATA"}

    closes, highs, lows = data
    htf_closes, _, _ = htf

    price = closes[-2]
    cfg = get_symbol_config(symbol)

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    r = rsi(closes)[-2]
    vol = atr(highs, lows, closes)
    upper, mid, lower = bollinger(closes)
    macd_hist = macd(closes)

    htf_ema50 = ema(htf_closes, 50)
    htf_ema200 = ema(htf_closes, 200)

    long_score = 0
    short_score = 0

    if ema50[-2] > ema200[-2]:
        long_score += 25
    else:
        short_score += 25

    if htf_ema50[-2] > htf_ema200[-2]:
        long_score += 10
    else:
        short_score += 10

    if 45 <= r <= 60:
        long_score += 10
        short_score += 10
    elif r < 45:
        long_score += 15
    else:
        short_score += 15

    if macd_hist > 0:
        long_score += 8
    else:
        short_score += 8

    if price < mid:
        long_score += 10
    else:
        short_score += 10

    dominant = max(long_score, short_score)
    gap = abs(long_score - short_score)

    signal = "NO TRADE"
    direction = "BUY" if long_score > short_score else "SELL"

    if dominant >= 50 and gap >= 8:
        if dominant >= 75:
            signal = f"STRONG {direction}"
        elif dominant >= 60:
            signal = direction
        else:
            signal = f"WEAK {direction}"

    effective_atr = max(vol, cfg["min_atr_pips"] * cfg["pip"])

    sl = tp = rr = None

    if "BUY" in signal:
        sl = price - effective_atr * cfg["sl_mult"]
        tp = price + effective_atr * cfg["tp_mult"]
    elif "SELL" in signal:
        sl = price + effective_atr * cfg["sl_mult"]
        tp = price - effective_atr * cfg["tp_mult"]

    if sl:
        risk = abs(price - sl)
        reward = abs(tp - price)
        rr = round(reward / risk, 2)

    log_trade(symbol, signal, price, sl, tp)

    return {
        "symbol": symbol,
        "signal": signal,
        "entry": price,
        "stop_loss": round(sl, 5) if sl else None,
        "take_profit": round(tp, 5) if tp else None,
        "risk_reward": rr,
        "rsi": round(r, 2),
        "atr": round(vol, 5),
        "ema50": ema50[-2],
        "ema200": ema200[-2],
    }

# ======================
# API
# ======================
@app.get("/dashboard/all")
def dashboard():
    update_trades()

    winrate = round((stats["wins"] / stats["total"]) * 100, 2) if stats["total"] else 0

    return {
        "data": {
            "NZDUSD": process("NZD/USD"),
            "GOLD": process("XAU/USD"),
        },
        "stats": {
            "wins": stats["wins"],
            "losses": stats["losses"],
            "total": stats["total"],
            "winrate": winrate
        },
        "trades": trade_log[-10:],
        "meta": {
            "last_fetch": datetime.now(timezone.utc).isoformat(),
            "next_sync": SYNC_INTERVAL
        }
    }
