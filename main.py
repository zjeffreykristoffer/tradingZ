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
    allow_origins=[
        "https://trading-z.vercel.app",
    ],
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

SYNC_INTERVAL = 900  # 15 minutes (aligned with candle)

CACHE_TTL = 300
CACHE_MAX_ENTRIES = 50

# ======================
# TRADE FILTER CONFIG
# ======================
def get_min_pip_move(symbol: str):
    if "XAU" in symbol:
        return 50  # gold
    return 10  # forex


def get_pip_value(symbol: str):
    if "JPY" in symbol:
        return 0.01
    elif "XAU" in symbol:
        return 0.1
    return 0.0001


def estimate_spread(pip_value: float):
    return pip_value * 1.5  # realistic default spread


# ======================
# CACHE
# ======================
cache = {}


def _evict_cache():
    if len(cache) >= CACHE_MAX_ENTRIES:
        oldest = sorted(cache.items(), key=lambda x: x[1]["time"])
        for key, _ in oldest[:10]:
            del cache[key]


# ======================
# DATA FETCH
# ======================
def fetch_prices(symbol: str, interval: str):
    try:
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={symbol}&interval={interval}&outputsize=300&apikey={API_KEY}"
        )
        with httpx.Client(timeout=10) as client:
            r = client.get(url).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]][::-1]
        highs = [float(x["high"]) for x in r["values"]][::-1]
        lows = [float(x["low"]) for x in r["values"]][::-1]

        return closes, highs, lows

    except Exception as e:
        print(f"[fetch_prices] Error fetching {symbol}: {e}")
        return None


def get_prices(symbol: str, interval: str):
    key = f"{symbol}_{interval}"
    now = time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"]

    data = fetch_prices(symbol, interval)

    if data:
        _evict_cache()
        cache[key] = {"data": data, "time": now}

    return data


# ======================
# INDICATORS
# ======================
def ema(data: list, period: int) -> list:
    k = 2 / (period + 1)
    out = [data[0]]
    for p in data[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def rsi(data: list, period: int = 14) -> list:
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


def atr(high: list, low: list, close: list, period: int = 14) -> float:
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)

    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0

    smoothed = sum(trs[:period]) / period
    for tr in trs[period:]:
        smoothed = (smoothed * (period - 1) + tr) / period

    return smoothed


def bollinger(data: list, period: int = 20):
    if len(data) < period:
        return (data[-1], data[-1], data[-1])
    window = data[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    return (mean + 2 * std, mean, mean - 2 * std)


# ======================
# SCORING ENGINE (IMPROVED)
# ======================
def score_trade(closes, highs, lows):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_vals = rsi(closes)
    vol = atr(highs, lows, closes)

    price = closes[-2]  # CLOSED CANDLE
    upper, mid, lower = bollinger(closes)
    rsi_val = rsi_vals[-2]

    score_long = 0
    score_short = 0

    # Trend (reduced dominance)
    if ema50[-2] > ema200[-2]:
        score_long += 25
    else:
        score_short += 25

    # RSI
    if rsi_val < 30:
        score_long += 25
    elif rsi_val > 70:
        score_short += 25
    elif rsi_val < 40:
        score_long += 10
    elif rsi_val > 60:
        score_short += 10

    # Bollinger + RSI combo
    if price <= lower and rsi_val < 35:
        score_long += 20
    elif price >= upper and rsi_val > 65:
        score_short += 20

    return score_long, score_short, vol, price


# ======================
# PROCESS
# ======================
def process(symbol: str):
    data = get_prices(symbol, TIMEFRAME)
    htf_data = get_prices(symbol, HTF_TIMEFRAME)

    if not data or not htf_data:
        return {"symbol": symbol, "signal": "NO_DATA"}

    closes, highs, lows = data
    htf_closes, _, _ = htf_data

    if len(closes) < 60 or len(htf_closes) < 200:
        return {"symbol": symbol, "signal": "INSUFFICIENT_DATA"}

    long_score, short_score, vol, price = score_trade(closes, highs, lows)

    # Higher TF trend
    htf_ema50 = ema(htf_closes, 50)
    htf_ema200 = ema(htf_closes, 200)
    higher_tf = "LONG" if htf_ema50[-2] > htf_ema200[-2] else "SHORT"

    direction = "LONG" if long_score > short_score else "SHORT"
    gap = abs(long_score - short_score)
    dominant = max(long_score, short_score)

    signal = "NO TRADE"

    if dominant >= 60 and gap >= 10:
        if dominant >= 80:
            signal = "STRONG BUY" if direction == "LONG" else "STRONG SELL"
        else:
            signal = "BUY" if direction == "LONG" else "SELL"

    # ======================
    # SL / TP (STRUCTURE + ATR)
    # ======================
    entry = price

    if "BUY" in signal:
        sl = min(lows[-5:])
        risk = entry - sl
        tp = entry + risk * 2
    elif "SELL" in signal:
        sl = max(highs[-5:])
        risk = sl - entry
        tp = entry - risk * 2
    else:
        sl = tp = None

    # ======================
    # FILTERS
    # ======================
    pip_value = get_pip_value(symbol)
    min_move = get_min_pip_move(symbol)

    spread = estimate_spread(pip_value)
    projected_pips = abs(tp - entry) / pip_value if tp else 0

    if signal != "NO TRADE":
        if projected_pips < min_move:
            signal = "NO TRADE"
        elif vol < pip_value * 5:
            signal = "NO TRADE"
        elif spread > pip_value * 3:
            signal = "NO TRADE"
        elif ("BUY" in signal and higher_tf != "LONG") or \
             ("SELL" in signal and higher_tf != "SHORT"):
            signal = "NO TRADE"

    return {
        "symbol": symbol,
        "signal": signal,
        "long_score": long_score,
        "short_score": short_score,
        "gap": gap,
        "entry": round(entry, 5),
        "stop_loss": round(sl, 5) if sl else None,
        "take_profit": round(tp, 5) if tp else None,
        "rsi": None,
        "atr": round(vol, 5),
    }


# ======================
# API
# ======================
@app.get("/dashboard/all")
def dashboard_all():
    now = datetime.now(timezone.utc)

    return {
        "data": {
            "NZDUSD": process("NZD/USD"),
            "GOLD": process("XAU/USD")
        },
        "meta": {
            "last_fetch": now.isoformat(),
            "next_sync": SYNC_INTERVAL
        }
    }


@app.get("/")
def home():
    return {
        "status": "running",
        "model": "improved institutional hybrid",
        "timeframe": "15m + 1H confirmation",
        "notes": "closed candle, real HTF, structure SL/TP, volatility & spread filters",
    }
