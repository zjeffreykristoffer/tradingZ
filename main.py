from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

# Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# 🔑 PUT YOUR API KEY HERE
# =========================
API_KEY = "6dc5d1c5200546a697bebfb1672702ac"

# =========================
# MARKET DATA FUNCTION
# =========================
def get_prices(symbol: str):
    url = (
        f"https://api.twelvedata.com/time_series"
        f"?symbol={symbol}&interval=5min&outputsize=30&apikey={API_KEY}"
    )

    try:
        response = requests.get(url, timeout=10).json()

        if "values" not in response:
            return None

        # Convert to float list (closing prices)
        closes = [float(item["close"]) for item in response["values"]]
        closes.reverse()  # oldest → newest

        return closes

    except Exception:
        return None


# =========================
# SIMPLE EMA FUNCTION
# =========================
def ema(data, period):
    k = 2 / (period + 1)
    values = [data[0]]

    for price in data[1:]:
        values.append(price * k + values[-1] * (1 - k))

    return values[-1]


# =========================
# SIGNAL ENGINE
# =========================
def generate_signal(symbol: str):

    prices = get_prices(symbol)

    if not prices or len(prices) < 20:
        return {"error": "No market data available"}

    ema10 = ema(prices[-20:], 10)
    ema20 = ema(prices[-20:], 20)

    entry = prices[-1]

    # Signal logic
    if ema10 > ema20:
        signal = "BUY"
    elif ema10 < ema20:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "symbol": symbol,
        "signal": signal,
        "entry": entry,
        "stop_loss": round(entry * 0.99, 5),
        "take_profit": round(entry * 1.02, 5),
        "ema_10": round(ema10, 5),
        "ema_20": round(ema20, 5),
    }


# =========================
# ROUTES
# =========================
@app.get("/")
def home():
    return {"message": "Trading API is running"}

@app.get("/signal/forex")
def forex_signal():
    return generate_signal("EUR/USD")

@app.get("/signal/gold")
def gold_signal():
    return generate_signal("XAU/USD")
