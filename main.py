from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import requests
from time import time

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
CACHE_TTL = 120  # 2 minutes

# ======================
# FETCH DATA
# ======================
def fetch_prices(symbol: str):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=50&apikey={API_KEY}"
        r = requests.get(url, timeout=10).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]]
        highs = [float(x["high"]) for x in r["values"]]
        lows = [float(x["low"]) for x in r["values"]]

        closes.reverse()
        highs.reverse()
        lows.reverse()

        return closes, highs, lows

    except Exception as e:
        print("Fetch error:", e)
        return None


def get_prices(symbol):
    now = time()

    if symbol in cache:
        if now - cache[symbol]["time"] < CACHE_TTL:
            return cache[symbol]["data"]

    data = fetch_prices(symbol)

    # only cache valid data
    if data:
        cache[symbol] = {"data": data, "time": now}

    return data

# ======================
# INDICATORS
# ======================
def ema(data, period):
    if not data:
        return []

    k = 2 / (period + 1)
    values = [data[0]]

    for price in data[1:]:
        values.append(price * k + values[-1] * (1 - k))

    return values


def atr(high, low, close):
    trs = []

    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)

    if len(trs) < 14:
        return sum(trs) / max(len(trs), 1)

    return sum(trs[-14:]) / 14

# ======================
# PROCESS SYMBOL (SAFE)
# ======================
def process(symbol):
    data = get_prices(symbol)

    if not data:
        return {
            "symbol": symbol,
            "prices": [],
            "ema10": [],
            "ema20": [],
            "signal": "NO_DATA",
            "entry": 0,
            "stop_loss": None,
            "take_profit": None,
            "atr": 0
        }

    closes, highs, lows = data

    ema10 = ema(closes, 10)
    ema20 = ema(closes, 20)

    signal = (
        "BUY" if ema10[-1] > ema20[-1]
        else "SELL" if ema10[-1] < ema20[-1]
        else "HOLD"
    )

    vol = atr(highs, lows, closes)
    entry = closes[-1]

    if signal == "BUY":
        sl = entry - vol * 1.5
        tp = entry + vol * 2
    elif signal == "SELL":
        sl = entry + vol * 1.5
        tp = entry - vol * 2
    else:
        sl = None
        tp = None

    return {
        "symbol": symbol,
        "prices": closes,
        "ema10": ema10,
        "ema20": ema20,
        "signal": signal,
        "entry": entry,
        "stop_loss": round(sl, 5) if sl else None,
        "take_profit": round(tp, 5) if tp else None,
        "atr": round(vol, 5)
    }

# ======================
# DASHBOARD API (FRONTEND USES THIS)
# ======================
@app.get("/dashboard/all")
def dashboard_all():
    return {
        "EURUSD": process("EUR/USD"),
        "GOLD": process("XAU/USD")
    }

# ======================
# ROOT
# ======================
@app.get("/")
def home():
    return {"status": "running"}
