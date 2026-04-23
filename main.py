from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd

app = FastAPI()

# ✅ Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "Trading API is running"}

def get_signal():
    try:
        # Fetch market data
        data = yf.download("EURUSD=X", period="1d", interval="5m", progress=False)

        # ✅ Safety checks (VERY IMPORTANT)
        if data is None or data.empty or len(data) < 20:
            return {"error": "Market data unavailable"}

        # Compute indicators
        data["EMA_10"] = data["Close"].ewm(span=10).mean()
        data["EMA_20"] = data["Close"].ewm(span=20).mean()

        # ✅ Get ONLY last row (fixes Series error completely)
        latest = data.iloc[-1]

        close = float(latest["Close"])
        ema10 = float(latest["EMA_10"])
        ema20 = float(latest["EMA_20"])

        # Trading logic (safe scalar comparisons)
        if ema10 > ema20:
            signal = "BUY"
        elif ema10 < ema20:
            signal = "SELL"
        else:
            signal = "HOLD"

        # Risk levels (simple MVP logic)
        stop_loss = close * 0.99
        take_profit = close * 1.02

        return {
            "signal": signal,
            "entry": close,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "ema_10": ema10,
            "ema_20": ema20
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/signal")
def signal():
    return get_signal()
