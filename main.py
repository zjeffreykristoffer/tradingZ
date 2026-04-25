from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from time import time
import math
import numpy as np

app = FastAPI()

# ======================
# CORS
# ======================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = "6dc5d1c5200546a697bebfb1672702ac"

# ======================
# CACHE
# ======================
cache = {}
CACHE_TTL = 120


# ======================
# DATA FETCH
# ======================
def fetch_prices(symbol: str, interval="15min"):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=500&apikey={API_KEY}"
        r = requests.get(url, timeout=10).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]][::-1]
        highs = [float(x["high"]) for x in r["values"]][::-1]
        lows = [float(x["low"]) for x in r["values"]][::-1]

        return closes, highs, lows

    except:
        return None


def get_prices(symbol, interval="15min"):
    now = time()
    key = f"{symbol}_{interval}"

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"]

    data = fetch_prices(symbol, interval)

    if data:
        cache[key] = {"data": data, "time": now}

    return data


# ======================
# INDICATORS (FIXED)
# ======================

def ema(data, period):
    if len(data) < period:
        return data

    k = 2 / (period + 1)
    out = [data[0]]

    for price in data[1:]:
        out.append(price * k + out[-1] * (1 - k))

    return out


def rsi(data, period=14):
    if len(data) <= period:
        return [50] * len(data)

    deltas = np.diff(data)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    rsis = [50] * period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        rs = avg_gain / (avg_loss + 1e-9)
        rsis.append(100 - (100 / (1 + rs)))

    return rsis


def atr(high, low, close, period=14):
    trs = []

    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)

    if len(trs) < period:
        return np.mean(trs)

    atr_val = np.mean(trs[:period])

    for i in range(period, len(trs)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period

    return atr_val


def bollinger(data, period=20):
    if len(data) < period:
        return data[-1], data[-1], data[-1]

    window = data[-period:]
    mean = np.mean(window)
    std = np.std(window)

    upper = mean + 2 * std
    lower = mean - 2 * std

    return upper, mean, lower


# ======================
# SAFE PROBABILITY
# ======================
def safe_prob(long_score, short_score):
    total = long_score + short_score
    if total == 0:
        return 0.5, 0.5

    return long_score / total, short_score / total


# ======================
# SCORING ENGINE (FIXED)
# ======================
def score_trade(closes, highs, lows):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_vals = rsi(closes)
    atr_val = atr(highs, lows, closes)

    price = closes[-1]
    upper, mid, lower = bollinger(closes)
    rsi_val = rsi_vals[-1]

    score_long = 0
    score_short = 0

    # TREND
    if ema50[-1] > ema200[-1]:
        score_long += 35
    else:
        score_short += 35

    # RSI (clean logic)
    if rsi_val < 40:
        score_long += 25
    elif rsi_val > 60:
        score_short += 25
    else:
        score_long += 10
        score_short += 10

    # Bollinger (fixed structure)
    if price < lower:
        score_long += 30
    elif price > upper:
        score_short += 30
    elif price <= mid:
        score_long += 10
    else:
        score_short += 10

    return score_long, score_short, ema50, ema200, rsi_val, atr_val, price, mid


# ======================
# MULTI-TIMEFRAME ENGINE
# ======================
def process(symbol, intervals=["15min", "1h", "4h", "1day"]):

    weights = {
        "15min": 0.2,
        "1h": 0.3,
        "4h": 0.25,
        "1day": 0.25
    }

    combined_long = 0
    combined_short = 0
    results = {}

    for interval in intervals:
        data = get_prices(symbol, interval)
        if not data:
            continue

        closes, highs, lows = data

        if len(closes) < 60:
            continue

        long_score, short_score, ema50, ema200, rsi_val, atr_val, price, mid = score_trade(
            closes, highs, lows
        )

        prob_long, prob_short = safe_prob(long_score, short_score)

        combined_long += prob_long * weights[interval]
        combined_short += prob_short * weights[interval]

        results[interval] = {
            "signal": "LONG" if prob_long > prob_short else "SHORT",
            "rsi": round(rsi_val, 2),
            "ema50": ema50[-1],
            "ema200": ema200[-1],
            "atr": round(atr_val, 5)
        }

    confidence_gap = abs(combined_long - combined_short)

    final_signal = "NO TRADE"

    # FINAL DECISION RULE (statistically safe)
    if confidence_gap > 0.20 and max(combined_long, combined_short) > 0.55:
        final_signal = "BUY" if combined_long > combined_short else "SELL"

    return {
        "symbol": symbol,
        "final_signal": final_signal,
        "prob_long": round(combined_long * 100, 2),
        "prob_short": round(combined_short * 100, 2),
        "confidence_gap": round(confidence_gap, 3),
        "timeframes": results
    }


# ======================
# API ENDPOINT
# ======================
@app.get("/process/{symbol}")
def process_route(symbol: str):
    return process(symbol)


@app.get("/")
def home():
    return {
        "status": "running",
        "model": "fixed multi-timeframe probabilistic trading engine",
        "logic": "EMA + RSI + BB + ATR with regime-filter style scoring",
        "timeframe": "15m / 1h / 4h / 1D"
    }
