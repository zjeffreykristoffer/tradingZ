def get_signal():
    try:
        import yfinance as yf

        data = yf.download("GC=F", period="1d", interval="5m", progress=False)

        # Safety check
        if data is None or data.empty:
            return {"error": "Market data unavailable"}

        # Indicators
        data["EMA_10"] = data["Close"].ewm(span=10).mean()
        data["EMA_20"] = data["Close"].ewm(span=20).mean()

        # FORCE single row + single values (IMPORTANT FIX)
        latest = data.tail(1).iloc[0]

        close = float(latest["Close"])
        ema10 = float(latest["EMA_10"])
        ema20 = float(latest["EMA_20"])

        # Signal logic
        if ema10 > ema20:
            signal = "BUY"
        elif ema10 < ema20:
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "signal": signal,
            "entry": close,
            "stop_loss": close * 0.99,
            "take_profit": close * 1.02,
            "ema_10": ema10,
            "ema_20": ema20
        }

    except Exception as e:
        return {"error": str(e)}
