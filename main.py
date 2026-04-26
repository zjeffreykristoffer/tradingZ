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

# ======================
# TRADE FILTER CONFIG
# ======================
MIN_PIP_MOVE = 3
MIN_ATR = 0.0005
MAX_SPREAD = 0.0002
SYNC_INTERVAL = 120

# ======================
# CACHE
# ======================
cache = {}
CACHE_TTL = 120
CACHE_MAX_ENTRIES = 50


def _evict_cache():
    if len(cache) >= CACHE_MAX_ENTRIES:
        oldest = sorted(cache.items(), key=lambda x: x[1]["time"])
        for key, _ in oldest[:10]:
            del cache[key]


# ======================
# DATA FETCH
# ======================
def fetch_prices(symbol: str):
    try:
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={symbol}&interval=15min&outputsize=300&apikey={API_KEY}"
        )
        with httpx.Client(timeout=10) as client:
            r = client.get(url).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]][::-1]
        highs  = [float(x["high"])  for x in r["values"]][::-1]
        lows   = [float(x["low"])   for x in r["values"]][::-1]

        return closes, highs, lows

    except Exception as e:
        print(f"[fetch_prices] Error fetching {symbol}: {e}")
        return None


def get_prices(symbol: str):
    now = time()

    if symbol in cache and now - cache[symbol]["time"] < CACHE_TTL:
        return cache[symbol]["data"]

    data = fetch_prices(symbol)

    if data:
        _evict_cache()
        cache[symbol] = {"data": data, "time": now}

    return data


# ======================
# HELPERS (NEW)
# ======================
def get_pip_value(symbol: str):
    if "JPY" in symbol:
        return 0.01
    elif "XAU" in symbol:
        return 0.1
    return 0.0001


def estimate_spread(highs: list, lows: list):
    return (highs[-1] - lows[-1]) * 0.1


def higher_tf_trend(closes: list):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    return "LONG" if ema50[-1] > ema200[-1] else "SHORT"


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

    if not trs:
        return 0.0
    if len(trs) < period:
        return sum(trs) / len(trs)

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
# SCORING ENGINE (UNCHANGED)
# ======================
def score_trade(closes: list, highs: list, lows: list) -> tuple:
    ema50    = ema(closes, 50)
    ema200   = ema(closes, 200)
    rsi_vals = rsi(closes)
    vol      = atr(highs, lows, closes)

    price = closes[-1]
    upper, mid, lower = bollinger(closes)
    rsi_val = rsi_vals[-1]

    score_long  = 0
    score_short = 0

    if ema50[-1] > ema200[-1]:
        score_long += 35
    else:
        score_short += 35

    if rsi_val < 30:
        score_long += 25
    elif rsi_val > 70:
        score_short += 25
    elif rsi_val < 40:
        score_long += 12
    elif rsi_val > 60:
        score_short += 12

    band_range = upper - lower
    if band_range > 0:
        position = (price - lower) / band_range

        if price <= lower:
            score_long += 25
        elif price >= upper:
            score_short += 25
        elif position < 0.35:
            score_long += 15
        elif position > 0.65:
            score_short += 15

    return score_long, score_short, ema50, ema200, rsi_val, vol, price, mid


# ======================
# PROCESS (UPDATED WITH FILTERS)
# ======================
def process(symbol: str) -> dict:
    data = get_prices(symbol)

    if not data:
        return {"symbol": symbol, "signal": "NO_DATA"}

    closes, highs, lows = data

    if len(closes) < 60:
        return {"symbol": symbol, "signal": "INSUFFICIENT_DATA"}

    long_score, short_score, ema50, ema200, rsi_val, vol, price, mid = score_trade(
        closes, highs, lows
    )

    dominant_score = max(long_score, short_score)
    direction      = "LONG" if long_score > short_score else "SHORT"
    gap            = abs(long_score - short_score)

    signal = "NO TRADE"

    if dominant_score >= 50 and gap >= 10:
        if dominant_score >= 85:
            signal = "STRONG BUY" if direction == "LONG" else "STRONG SELL"
        elif dominant_score >= 70:
            signal = "BUY" if direction == "LONG" else "SELL"
        else:
            signal = "WEAK BUY" if direction == "LONG" else "WEAK SELL"

    entry = price

    if "BUY" in signal:
        sl = entry - vol * 1.5
        tp = entry + vol * 3.0
    elif "SELL" in signal:
        sl = entry + vol * 1.5
        tp = entry - vol * 3.0
    else:
        sl = None
        tp = None

    # ======================
    # FILTERS (NEW)
    # ======================
    pip_value = get_pip_value(symbol)
    projected_move = abs(tp - entry) if tp else 0
    projected_pips = projected_move / pip_value if pip_value else 0
    spread = estimate_spread(highs, lows)
    higher_tf = higher_tf_trend(closes)

    if signal != "NO TRADE":
        if projected_pips < MIN_PIP_MOVE:
            signal = "NO TRADE"
        elif vol < MIN_ATR:
            signal = "NO TRADE"
        elif spread >= MAX_SPREAD:
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
        "rsi": round(rsi_val, 2),
        "atr": round(vol, 5),
        "ema50": round(ema50[-1], 5),
        "ema200": round(ema200[-1], 5),
    }


# ======================
# API (UPDATED RESPONSE)
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
        "model": "institutional hybrid scoring system",
        "timeframe": "15m",
        "strategy": "trend + momentum + volatility with conflict resolution",
    }
