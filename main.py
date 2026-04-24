from fastapi import FastAPI, WebSocket
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
# WEBSOCKET CLIENTS
# ======================
clients = set()

# ======================
# CACHE
# ======================
cache = {}
CACHE_TTL = 120  # 2 minutes (important for API saving)

# ======================
# DATA FETCH
# ======================
def fetch_prices(symbol: str):
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


def get_prices(symbol):
    now = time()

    if symbol in cache and now - cache[symbol]["time"] < CACHE_TTL:
        return cache[symbol]["data"]

    data = fetch_prices(symbol)

    cache[symbol] = {"data": data, "time": now}
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


def atr(high, low, close):
    trs = []

    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)

    return sum(trs[-14:]) / 14

# ======================
# PROCESS SYMBOL
# ======================
def process(symbol):
    data = get_prices(symbol)

    if not data:
        return None

    closes, highs, lows = data

    ema10 = ema(closes, 10)
    ema20 = ema(closes, 20)

    signal = "BUY" if ema10[-1] > ema20[-1] else "SELL" if ema10[-1] < ema20[-1] else "HOLD"

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
# WEBSOCKET
# ======================
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)

    try:
        while True:
            await asyncio.sleep(10)
    except:
        clients.remove(websocket)


async def broadcast(data):
    dead = []

    for ws in clients:
        try:
            await ws.send_json(data)
        except:
            dead.append(ws)

    for d in dead:
        clients.remove(d)


# ======================
# SMART LOOP (LOW API USAGE)
# ======================
last_data = {}

async def loop():
    global last_data

    while True:
        data = {
            "EURUSD": process("EUR/USD"),
            "GOLD": process("XAU/USD")
        }

        if data != last_data:
            last_data = data
            await broadcast(data)

        await asyncio.sleep(120)  # 2 minutes


@app.on_event("startup")
async def start():
    asyncio.create_task(loop())


# ======================
# ROOT
# ======================
@app.get("/")
def home():
    return {"status": "running"}
