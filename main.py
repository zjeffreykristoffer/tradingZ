import os
import math
from time import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ======================
# CORS
# ======================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ======================
# CONFIG
# ======================
API_KEY = os.getenv("TWELVE_DATA_KEY")

TIMEFRAME     = "15min"
HTF_TIMEFRAME = "1h"

SYNC_INTERVAL = 900
CACHE_TTL     = 300

# ======================
# RISK MODEL
# Use RISK_MODE="fixed" for a flat dollar amount, or "percent" for % of balance.
# ======================
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "10000"))   # USD
RISK_MODE       = os.getenv("RISK_MODE", "percent")               # "fixed" | "percent"
RISK_AMOUNT     = float(os.getenv("RISK_AMOUNT", "100"))          # used when RISK_MODE=fixed
RISK_PERCENT    = float(os.getenv("RISK_PERCENT", "1.0"))         # used when RISK_MODE=percent (e.g. 1 = 1%)

def get_risk_usd() -> float:
    """Return the dollar amount risked per trade."""
    if RISK_MODE == "percent":
        return round(ACCOUNT_BALANCE * RISK_PERCENT / 100, 2)
    return RISK_AMOUNT

# ======================
# SYMBOL CONFIG
# pip        – minimum price increment used for SL/TP sizing
# pip_value  – USD value of 1 pip for 1 standard lot
#              NZDUSD : 100 000 units × 0.0001 = $10 / pip / lot
#              XAUUSD : 100 oz     × $0.10   = $10 / pip / lot
#              JPYUSD  : approx $9 at ¥110 – use 9.09 as a reasonable constant
# sl_mult / tp_mult – ATR multipliers for stop-loss and take-profit
# ======================
SYMBOL_CONFIG = {
    "DEFAULT": {"pip": 0.0001, "pip_value": 10.0, "sl_mult": 1.5, "tp_mult": 2.2, "min_atr_pips": 5},
    "JPY":     {"pip": 0.01,   "pip_value": 9.09, "sl_mult": 1.5, "tp_mult": 2.2, "min_atr_pips": 5},
    "XAU":     {"pip": 0.10,   "pip_value": 10.0, "sl_mult": 1.8, "tp_mult": 2.5, "min_atr_pips": 20},
}

# Maximum score achievable – used to normalise confidence.
# Sources: EMA trend 25, HTF trend 10, RSI 15, MACD 8, Bollinger 10 → total 68
MAX_SCORE = 68.0

def get_symbol_config(symbol: str) -> dict:
    if "XAU" in symbol:
        return SYMBOL_CONFIG["XAU"]
    if "JPY" in symbol:
        return SYMBOL_CONFIG["JPY"]
    return SYMBOL_CONFIG["DEFAULT"]

# ======================
# CACHE
# ======================
cache: dict = {}

def get_prices(symbol: str, interval: str):
    key = f"{symbol}_{interval}"
    now = time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"]

    try:
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={symbol}&interval={interval}&outputsize=300&apikey={API_KEY}"
        )
        r = httpx.get(url, timeout=10).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]][::-1]
        highs  = [float(x["high"])  for x in r["values"]][::-1]
        lows   = [float(x["low"])   for x in r["values"]][::-1]

        cache[key] = {"data": (closes, highs, lows), "time": now}
        return closes, highs, lows

    except Exception:
        return None

# ======================
# INDICATORS
# ======================
def ema(data: list, period: int) -> list:
    k   = 2 / (period + 1)
    out = [data[0]]
    for p in data[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def rsi(data: list, period: int = 14) -> list:
    if len(data) < period + 1:
        return [50.0] * len(data)

    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsis: list = []
    for i in range(period, len(data)):
        rs = avg_gain / (avg_loss + 1e-9)
        rsis.append(100 - (100 / (1 + rs)))
        if i < len(data) - 1:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    return [50.0] * period + rsis


def atr(high: list, low: list, close: list, period: int = 14) -> float:
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / max(len(trs), 1)


def bollinger(data: list, period: int = 20):
    window = data[-period:]
    mean   = sum(window) / period
    std    = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    return mean + 2 * std, mean, mean - 2 * std


def macd(data: list) -> float:
    ema12      = ema(data, 12)
    ema26      = ema(data, 26)
    macd_line  = [a - b for a, b in zip(ema12, ema26)]
    signal     = ema(macd_line, 9)
    return macd_line[-1] - signal[-1]

# ======================
# LOT SIZE CALCULATOR
# ======================
def calculate_lot_size(risk_usd: float, entry: float, sl: float, cfg: dict) -> float:
    """
    Lot Size = Risk ($) / (SL distance in pips × pip value per 1 lot)

    Returns lot size rounded to 2 decimal places.
    Returns 0.0 if SL distance is zero or negative.
    """
    sl_distance_price = abs(entry - sl)
    if sl_distance_price <= 0:
        return 0.0

    sl_distance_pips = sl_distance_price / cfg["pip"]
    lot_size         = risk_usd / (sl_distance_pips * cfg["pip_value"])
    return round(lot_size, 2)

# ======================
# SIGNAL BUILDER
# ======================
def build_signal(long_score: int, short_score: int) -> tuple[str, float]:
    """
    Returns (signal_label, confidence_percent).
    confidence = dominant_score / MAX_SCORE * 100
    """
    dominant  = max(long_score, short_score)
    gap       = abs(long_score - short_score)
    direction = "BUY" if long_score > short_score else "SELL"

    confidence = round((dominant / MAX_SCORE) * 100, 1)

    signal = "NO TRADE"
    if dominant >= 50 and gap >= 8:
        if dominant >= 60:
            signal = f"STRONG {direction}"
        elif dominant >= 50:
            signal = direction
        else:
            signal = f"WEAK {direction}"

    # Extra weak tier for marginal gaps
    if signal == "NO TRADE" and dominant >= 45 and gap >= 5:
        signal = f"WEAK {direction}"

    return signal, confidence

# ======================
# PROCESS SYMBOL
# ======================
def process(symbol: str) -> dict:
    data = get_prices(symbol, TIMEFRAME)
    htf  = get_prices(symbol, HTF_TIMEFRAME)

    if not data or not htf:
        return {
            "symbol":         symbol,
            "recommendation": "NO DATA",
            "confidence":     0.0,
            "entry":          None,
            "stop_loss":      None,
            "take_profit":    None,
            "lot_size":       None,
            "risk_usd":       None,
        }

    closes, highs, lows = data
    htf_closes, _, _    = htf

    price = closes[-2]
    cfg   = get_symbol_config(symbol)

    # ── Indicators ──────────────────────────────────────────
    ema50_vals  = ema(closes, 50)
    ema200_vals = ema(closes, 200)
    r           = rsi(closes)[-2]
    vol         = atr(highs, lows, closes)
    _upper, mid, _lower = bollinger(closes)
    macd_hist   = macd(closes)

    htf_ema50  = ema(htf_closes, 50)
    htf_ema200 = ema(htf_closes, 200)

    # ── Scoring ──────────────────────────────────────────────
    long_score = short_score = 0

    # LTF EMA trend (25 pts)
    if ema50_vals[-2] > ema200_vals[-2]:
        long_score  += 25
    else:
        short_score += 25

    # HTF EMA trend (10 pts)
    if htf_ema50[-2] > htf_ema200[-2]:
        long_score  += 10
    else:
        short_score += 10

    # RSI (15 pts)
    if 45 <= r <= 60:
        long_score  += 10
        short_score += 10
    elif r < 45:
        long_score  += 15
    else:
        short_score += 15

    # MACD histogram (8 pts)
    if macd_hist > 0:
        long_score  += 8
    else:
        short_score += 8

    # Bollinger mid (10 pts)
    if price < mid:
        long_score  += 10
    else:
        short_score += 10

    signal, confidence = build_signal(long_score, short_score)

    # ── SL / TP ──────────────────────────────────────────────
    effective_atr = max(vol, cfg["min_atr_pips"] * cfg["pip"])
    sl = tp = rr = None

    if "BUY" in signal:
        sl = round(price - effective_atr * cfg["sl_mult"], 5)
        tp = round(price + effective_atr * cfg["tp_mult"], 5)
    elif "SELL" in signal:
        sl = round(price + effective_atr * cfg["sl_mult"], 5)
        tp = round(price - effective_atr * cfg["tp_mult"], 5)

    # ── Lot size ─────────────────────────────────────────────
    risk_usd = get_risk_usd()
    lot_size = calculate_lot_size(risk_usd, price, sl, cfg) if sl is not None else None

    return {
        "symbol":         symbol,
        "recommendation": signal,
        "confidence":     confidence,
        "entry":          round(price, 5),
        "stop_loss":      sl,
        "take_profit":    tp,
        "lot_size":       lot_size,
        "risk_usd":       risk_usd,
    }

# ======================
# API
# ======================
SYMBOLS = {
    "NZDUSD": "NZD/USD",
    "GOLD":   "XAU/USD",
}

@app.get("/dashboard/all")
def dashboard():
    results = {key: process(sym) for key, sym in SYMBOLS.items()}

    return {
        "assets": results,
        "meta": {
            "last_fetch": datetime.now(timezone.utc).isoformat(),
            "next_sync":  SYNC_INTERVAL,
        },
    }
