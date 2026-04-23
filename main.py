from fastapi import FastAPI
import yfinance as yf
import pandas as pd

app = FastAPI()

def get_signal():
    try:
        data = yf.download("XAUUSD=X", period="1d", interval="5m")

        # ✅ Check if empty BEFORE using it
        if data is None or data.empty or len(data) < 20:
            return {"error": "Market data unavailable"}

        data['EMA_10'] = data['Close'].ewm(span=10).mean()
        data['EMA_20'] = data['Close'].ewm(span=20).mean()

        latest = data.iloc[-1]

if latest['EMA_10'] > latest['EMA_20']:
    signal = "BUY"
elif latest['EMA_10'] < latest['EMA_20']:
    signal = "SELL"
else:
    signal = "HOLD"

        entry = float(latest['Close'])

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
