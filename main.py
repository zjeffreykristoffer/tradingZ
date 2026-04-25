from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests, numpy as np, os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("6dc5d1c5200546a697bebfb1672702ac")

# ======================
# STATE (in-memory)
# ======================
account = {"balance": 1000.0, "risk": 0.02}
trades = []

# ======================
# FETCH DATA
# ======================
def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=15min&outputsize=200&apikey={API_KEY}"
    r = requests.get(url, timeout=10).json()

    if "values" not in r:
        return None

    closes = [float(x["close"]) for x in r["values"]][::-1]
    highs = [float(x["high"]) for x in r["values"]][::-1]
    lows = [float(x["low"]) for x in r["values"]][::-1]

    return closes, highs, lows

# ======================
# INDICATORS
# ======================
def ema(d,p):
    k=2/(p+1); out=[d[0]]
    for x in d[1:]: out.append(x*k+out[-1]*(1-k))
    return out

def rsi(d,p=14):
    deltas=np.diff(d)
    gains=np.where(deltas>0,deltas,0)
    losses=np.where(deltas<0,-deltas,0)
    ag,al=np.mean(gains[:p]),np.mean(losses[:p])
    rsis=[50]*p
    for i in range(p,len(gains)):
        ag=(ag*(p-1)+gains[i])/p
        al=(al*(p-1)+losses[i])/p
        rs=ag/(al+1e-9)
        rsis.append(100-(100/(1+rs)))
    return rsis

def atr(h,l,c,p=14):
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return np.mean(trs[-p:])

# ======================
# SIGNAL
# ======================
def signal(closes, highs, lows):
    e50=ema(closes,50)[-1]
    e200=ema(closes,200)[-1]
    r=rsi(closes)[-1]
    a=atr(highs,lows,closes)
    price=closes[-1]

    long=0; short=0

    if e50>e200: long+=1
    else: short+=1

    if r<40: long+=1
    elif r>60: short+=1

    if long>short: s="BUY"
    elif short>long: s="SELL"
    else: s="NONE"

    return s, price, a

# ======================
# TRADE ENGINE
# ======================
def open_trade(sig, price, atr):
    risk_amt = account["balance"] * account["risk"]

    if sig=="BUY":
        sl = price - atr*1.5
        tp = price + atr*3
    elif sig=="SELL":
        sl = price + atr*1.5
        tp = price - atr*3
    else:
        return None

    size = risk_amt / abs(price - sl)

    t={
        "signal":sig,
        "entry":price,
        "tp":tp,
        "sl":sl,
        "size":size,
        "open":True
    }
    trades.append(t)
    return t

def update(price):
    for t in trades:
        if not t["open"]: continue

        if t["signal"]=="BUY":
            if price>=t["tp"]:
                account["balance"] += (t["tp"]-t["entry"])*t["size"]
                t["open"]=False
            elif price<=t["sl"]:
                account["balance"] -= (t["entry"]-t["sl"])*t["size"]
                t["open"]=False

        if t["signal"]=="SELL":
            if price<=t["tp"]:
                account["balance"] += (t["entry"]-t["tp"])*t["size"]
                t["open"]=False
            elif price>=t["sl"]:
                account["balance"] -= (t["sl"]-t["entry"])*t["size"]
                t["open"]=False

# ======================
# API
# ======================
@app.get("/")
def home():
    return {"status":"running"}

@app.get("/trade/{symbol}")
def trade(symbol:str):
    data=fetch(symbol)
    if not data:
        return {"error":"no data"}

    c,h,l=data
    sig,price,atr_val = signal(c,h,l)

    update(price)

    t=None
    if sig!="NONE":
        t=open_trade(sig,price,atr_val)

    closed=[x for x in trades if not x["open"]]
    wins=len([x for x in closed if (x["signal"]=="BUY" and x["tp"]>x["entry"]) or (x["signal"]=="SELL" and x["tp"]<x["entry"])])
    losses=len(closed)-wins
    wr=(wins/(wins+losses))*100 if (wins+losses)>0 else 0

    return {
        "balance":round(account["balance"],2),
        "signal":sig,
        "price":round(price,2),
        "trade":t,
        "wins":wins,
        "losses":losses,
        "winrate":round(wr,2)
    }
