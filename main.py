from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
# CACHE SYSTEM
# ======================
cache = {}
CACHE_TTL = 60  # seconds

# ======================
# FETCH DATA
# ======================
def fetch_prices(symbol: str):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=50&apikey={API_KEY}"

    try:
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

    except:
        return None

# ======================
# CACHED WRAPPER
# ======================
def get_prices(symbol: str):
    now = time()

    if symbol in cache:
        if now - cache[symbol]["time"] < CACHE_TTL:
            return cache[symbol]["data"]

    data = fetch_prices(symbol)

    cache[symbol] = {
        "data": data,
        "time": now
    }

    return data

# ======================
# INDICATORS
# ======================
def ema(data, period):
    k = 2 / (period + 1)
    values = [data[0]]

    for price in data[1:]:
        values.append(price * k + values[-1] * (1 - k))

    return values

def atr(high, low, close, period=14):
    trs = []

    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)

    return sum(trs[-period:]) / period

# ======================
# MAIN DASHBOARD ENDPOINT
# ======================
@app.get("/dashboard/forex")
def dashboard():
    data = get_prices("EUR/USD")

    if not data:
        return {"error": "No data"}

    closes, highs, lows = data

    if len(closes) < 20:
        return {"error": "Not enough data"}

    ema10_series = ema(closes, 10)
    ema20_series = ema(closes, 20)

    ema10 = ema10_series[-1]
    ema20 = ema20_series[-1]

    signal = "BUY" if ema10 > ema20 else "SELL" if ema10 < ema20 else "HOLD"

    volatility = atr(highs, lows, closes)
    entry = closes[-1]

    if signal == "BUY":
        sl = entry - (volatility * 1.5)
        tp = entry + (volatility * 2)
    elif signal == "SELL":
        sl = entry + (volatility * 1.5)
        tp = entry - (volatility * 2)
    else:
        sl = None
        tp = None

    return {
        "symbol": "EUR/USD",
        "prices": closes,
        "ema10": ema10_series,
        "ema20": ema20_series,
        "signal": signal,
        "entry": entry,
        "stop_loss": round(sl, 5) if sl else None,
        "take_profit": round(tp, 5) if tp else None,
        "atr": round(volatility, 5)
    }

@app.get("/")
def home():
    return {"message": "Trading API running"}
