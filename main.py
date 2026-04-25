from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from time import time
import math

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
def fetch_prices(symbol: str):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=15min&outputsize=100&apikey={API_KEY}"
        r = requests.get(url, timeout=10).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]][::-1]
        highs = [float(x["high"]) for x in r["values"]][::-1]
        lows = [float(x["low"]) for x in r["values"]][::-1]

        return closes, highs, lows

    except:
        return None


def get_prices(symbol):
    now = time()

    if symbol in cache and now - cache[symbol]["time"] < CACHE_TTL:
        return cache[symbol]["data"]

    data = fetch_prices(symbol)

    if data:
        cache[symbol] = {"data": data, "time": now}

    return data


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

    rsis = []
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

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
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)

    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / len(trs)


def bollinger(data, period=20):
    if len(data) < period:
        return (data[-1], data[-1], data[-1])

    window = data[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)

    return (mean + 2 * std, mean, mean - 2 * std)


# ======================
# SCORING ENGINE
# ======================
def score_trade(closes, highs, lows):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_vals = rsi(closes)
    vol = atr(highs, lows, closes)

    price = closes[-1]
    upper, mid, lower = bollinger(closes)
    rsi_val = rsi_vals[-1]

    score_long = 0
    score_short = 0

    # TREND (35 pts)
    if ema50[-1] > ema200[-1]:
        score_long += 35
    else:
        score_short += 35

    # RSI (25 pts)
    if 45 <= rsi_val <= 65:
        score_long += 15
        score_short += 15
    elif rsi_val > 65:
        score_short += 25
    elif rsi_val < 45:
        score_long += 25

    # BOLLINGER (25 pts)
    if price <= mid:
        score_long += 25
    if price >= mid:
        score_short += 25

    # VOLATILITY (15 pts)
    if vol > 0:
        score_long += 15
        score_short += 15

    return score_long, score_short, ema50, ema200, rsi_val, vol, price, mid


# ======================
# PROCESS (SMART ENGINE)
# ======================
def process(symbol):
    data = get_prices(symbol)

    if not data:
        return {"symbol": symbol, "signal": "NO_DATA"}

    closes, highs, lows = data

    if len(closes) < 60:
        return {"symbol": symbol, "signal": "INSUFFICIENT_DATA"}

    long_score, short_score, ema50, ema200, rsi_val, vol, price, mid = score_trade(
        closes, highs, lows
    )

    # ======================
    # SMART DECISION ENGINE
    # ======================
    dominant_score = max(long_score, short_score)
    direction = "LONG" if long_score > short_score else "SHORT"
    gap = abs(long_score - short_score)

    signal = "NO TRADE"

    if dominant_score >= 50 and gap >= 10:
        if dominant_score >= 85:
            signal = "STRONG BUY" if direction == "LONG" else "STRONG SELL"
        elif dominant_score >= 70:
            signal = "BUY" if direction == "LONG" else "SELL"
        else:
            signal = "WEAK BUY" if direction == "LONG" else "WEAK SELL"

    # ======================
    # RISK MANAGEMENT
    # ======================
    entry = price

    if "BUY" in signal:
        sl = entry - vol * 1.5
        tp = entry + vol * 2.2
    elif "SELL" in signal:
        sl = entry + vol * 1.5
        tp = entry - vol * 2.2
    else:
        sl = None
        tp = None

    return {
        "symbol": symbol,
        "signal": signal,
        "long_score": long_score,
        "short_score": short_score,
        "gap": gap,
        "entry": entry,
        "stop_loss": round(sl, 5) if sl else None,
        "take_profit": round(tp, 5) if tp else None,
        "rsi": round(rsi_val, 2),
        "atr": round(vol, 5),
        "ema50": ema50[-1],
        "ema200": ema200[-1]
    }


# ======================
# API
# ======================
@app.get("/dashboard/all")
def dashboard_all():
    return {
        #"EURUSD": process("EUR/USD"),
        #"GBPUSD": process("GBP/USD"),
        #"USDCAD": process("USD/CAD"),
        "GOLD": process("XAU/USD")
    }


@app.get("/")
def home():
    return {
        "status": "running",
        "model": "institutional hybrid scoring system",
        "timeframe": "15m",
        "strategy": "trend + momentum + volatility with conflict resolution"
    }
