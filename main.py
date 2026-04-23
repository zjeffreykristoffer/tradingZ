from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

# ======================
# CORS (frontend access)
# ======================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================
# API KEY
# ======================
API_KEY = "YOUR_TWELVEDATA_API_KEY"

# ======================
# GET MARKET DATA
# ======================
def get_prices(symbol: str):
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
# EMA FUNCTION
# ======================
def ema(data, period):
    k = 2 / (period + 1)
    values = [data[0]]

    for price in data[1:]:
        values.append(price * k + values[-1] * (1 - k))

    return values[-1]


# ======================
# SIMPLE ATR (volatility)
# ======================
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
# SIGNAL ENGINE
# ======================
def generate_signal(symbol: str):

    data = get_prices(symbol)

    if not data:
        return {"error": "No market data available"}

    closes, highs, lows = data

    if len(closes) < 20:
        return {"error": "Not enough data"}

    ema10 = ema(closes[-20:], 10)
    ema20 = ema(closes[-20:], 20)

    entry = closes[-1]

    # ======================
    # SIGNAL LOGIC
    # ======================
    if ema10 > ema20:
        signal = "BUY"
    elif ema10 < ema20:
        signal = "SELL"
    else:
        signal = "HOLD"

    # ======================
    # ATR-BASED RISK
    # ======================
    volatility = atr(highs, lows, closes)

    if signal == "BUY":
        stop_loss = entry - (volatility * 1.5)
        take_profit = entry + (volatility * 2)

    elif signal == "SELL":
        stop_loss = entry + (volatility * 1.5)
        take_profit = entry - (volatility * 2)

    else:
        stop_loss = None
        take_profit = None

    return {
        "symbol": symbol,
        "signal": signal,
        "entry": entry,
        "stop_loss": round(stop_loss, 5) if stop_loss else None,
        "take_profit": round(take_profit, 5) if take_profit else None,
        "ema_10": round(ema10, 5),
        "ema_20": round(ema20, 5),
        "atr": round(volatility, 5)
    }


# ======================
# ROUTES
# ======================
@app.get("/")
def home():
    return {"message": "Trading API running"}

@app.get("/signal/forex")
def forex():
    return generate_signal("EUR/USD")

@app.get("/signal/gold")
def gold():
    return generate_signal("XAU/USD")
