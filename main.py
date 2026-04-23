from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = "6dc5d1c5200546a697bebfb1672702ac"

@app.get("/")
def home():
    return {"message": "Trading API running"}

def get_price(symbol="EUR/USD"):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=30&apikey={API_KEY}"

    r = requests.get(url).json()

    if "values" not in r:
        return None

    closes = [float(x["close"]) for x in r["values"]]
    return closes

def get_signal():
    try:
        closes = get_price("EUR/USD")

        if not closes or len(closes) < 10:
            return {"error": "No market data"}

        # Simple EMA logic
        def ema(data, period):
            k = 2 / (period + 1)
            ema_values = []
            ema_values.append(data[0])

            for price in data[1:]:
                ema_values.append(price * k + ema_values[-1] * (1 - k))

            return ema_values[-1]

        ema10 = ema(closes, 10)
        ema20 = ema(closes, 20)

        entry = closes[-1]

        if ema10 > ema20:
            signal = "BUY"
        elif ema10 < ema20:
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "signal": signal,
            "entry": entry,
            "stop_loss": entry * 0.99,
            "take_profit": entry * 1.02
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/signal")
def signal():
    return get_signal()
