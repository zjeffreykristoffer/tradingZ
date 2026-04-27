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
    allow_origins=["https://trading-z.vercel.app"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ======================
# CONFIG
# ======================
API_KEY = os.getenv("TWELVE_DATA_KEY")

TIMEFRAME = "15min"
HTF_TIMEFRAME = "1h"

SYNC_INTERVAL = 900
CACHE_TTL = 300

# ======================
# SYMBOL CONFIG
# pip          → smallest meaningful price unit for this instrument
# sl_mult      → ATR multiplier for stop-loss  (wider = safer stop)
# tp_mult      → ATR multiplier for take-profit
# min_atr_pips → floor: SL is always at least this many pips wide
# ======================
SYMBOL_CONFIG = {
    "DEFAULT": {"pip": 0.0001, "sl_mult": 1.5,  "tp_mult": 2.5,  "min_atr_pips": 5},
    "JPY":     {"pip": 0.01,   "sl_mult": 1.5,  "tp_mult": 2.5,  "min_atr_pips": 5},
    "XAU":     {"pip": 0.1,    "sl_mult": 1.8,  "tp_mult": 3.0,  "min_atr_pips": 20},
}


def get_symbol_config(symbol: str):
    if "XAU" in symbol:
        return SYMBOL_CONFIG["XAU"]
    if "JPY" in symbol:
        return SYMBOL_CONFIG["JPY"]
    return SYMBOL_CONFIG["DEFAULT"]


# ======================
# CACHE
# ======================
cache = {}


def get_prices(symbol, interval):
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

    except Exception as e:
        print(e)
        return None


# ======================
# INDICATORS
# ======================
def ema(data, period):
    if len(data) < period:
        return data[:]
    k = 2 / (period + 1)
    out = [data[0]]
    for p in data[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def rsi(data, period=14):
    if len(data) < period + 1:
        return [50.0] * len(data)

    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsis = []

    for i in range(period, len(data)):
        rs = avg_gain / (avg_loss + 1e-9)
        rsis.append(100 - (100 / (1 + rs)))
        if i < len(data) - 1:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    return [50.0] * period + rsis


def atr(high, low, close, period=14):
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)

    if not trs:
        return 0.0
    if len(trs) < period:
        return sum(trs) / len(trs)

    smoothed = sum(trs[:period]) / period
    for tr in trs[period:]:
        smoothed = (smoothed * (period - 1) + tr) / period
    return smoothed


def bollinger(data, period=20):
    window = data[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    return mean + 2 * std, mean, mean - 2 * std


def macd(data, fast=12, slow=26, signal_period=9):
    """Returns (macd_line[-1], signal_line[-1], histogram[-1], histogram[-2])."""
    ema_fast    = ema(data, fast)
    ema_slow    = ema(data, slow)
    macd_line   = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal_period)
    hist_now    = macd_line[-1] - signal_line[-1]
    hist_prev   = macd_line[-2] - signal_line[-2]
    return macd_line[-1], signal_line[-1], hist_now, hist_prev


# ======================
# PROCESS
# ======================
def process(symbol):
    data = get_prices(symbol, TIMEFRAME)
    htf  = get_prices(symbol, HTF_TIMEFRAME)

    if not data or not htf:
        return {"symbol": symbol, "signal": "NO DATA"}

    closes, highs, lows = data
    htf_closes, htf_highs, htf_lows = htf

    cfg   = get_symbol_config(symbol)
    price = closes[-2]   # last confirmed (closed) candle

    # ── LTF indicators ────────────────────────────────────────────────────────
    ema50_vals  = ema(closes, 50)
    ema200_vals = ema(closes, 200)
    rsi_vals    = rsi(closes)
    atr_val     = atr(highs, lows, closes)
    upper, mid, lower = bollinger(closes)
    _, _, macd_hist, macd_hist_prev = macd(closes)

    ltf_trend = 1 if ema50_vals[-2] > ema200_vals[-2] else -1
    ltf_rsi   = rsi_vals[-2]

    # ── HTF indicators ────────────────────────────────────────────────────────
    htf_ema50  = ema(htf_closes, 50)
    htf_ema200 = ema(htf_closes, 200)
    htf_rsi_v  = rsi(htf_closes)
    htf_atr    = atr(htf_highs, htf_lows, htf_closes)

    htf_trend   = 1 if htf_ema50[-2] > htf_ema200[-2] else -1
    htf_rsi_val = htf_rsi_v[-2]

    trend = ltf_trend  # primary directional bias

    # ── Bollinger position (0 = lower band, 1 = upper band) ──────────────────
    band_range = (upper - lower) if upper != lower else 1e-9
    bb_pos = (price - lower) / band_range

    # ── Confidence scoring ────────────────────────────────────────────────────
    confidence = 50

    # 1. LTF trend (±15)
    confidence += trend * 15

    # 2. HTF trend alignment — heavy weight (±20)
    if ltf_trend == htf_trend:
        confidence += 20
    else:
        confidence -= 20   # counter-trend signals punished hard

    # 3. RSI — context-aware: reward entries in the right zone, penalise extremes
    if trend == 1:  # looking for buys
        if 40 <= ltf_rsi <= 60:
            confidence += 12   # healthy momentum, not extended
        elif ltf_rsi < 40:
            confidence += 6    # potential bounce
        elif ltf_rsi > 70:
            confidence -= 15   # overbought — avoid chasing
        elif ltf_rsi > 60:
            confidence -= 5    # getting stretched
    else:  # looking for sells
        if 40 <= ltf_rsi <= 60:
            confidence += 12
        elif ltf_rsi > 60:
            confidence += 6
        elif ltf_rsi < 30:
            confidence -= 15   # oversold — avoid chasing shorts
        elif ltf_rsi < 40:
            confidence -= 5

    # 4. HTF RSI confirmation (±6)
    if trend == 1 and htf_rsi_val > 50:
        confidence += 6
    elif trend == -1 and htf_rsi_val < 50:
        confidence += 6
    else:
        confidence -= 6

    # 5. MACD histogram polarity & momentum direction (±8 each)
    if macd_hist > 0:
        confidence += 8 if trend == 1 else -8
    else:
        confidence += 8 if trend == -1 else -8

    if (macd_hist > macd_hist_prev and trend == 1) or \
       (macd_hist < macd_hist_prev and trend == -1):
        confidence += 8    # momentum accelerating in trend direction
    else:
        confidence -= 5    # momentum fading

    # 6. Bollinger Band position (±8)
    if trend == 1:
        if bb_pos < 0.35:
            confidence += 8   # buying near lower band — good value
        elif bb_pos > 0.75:
            confidence -= 8   # buying near upper band — extended
    else:
        if bb_pos > 0.65:
            confidence += 8   # selling near upper band
        elif bb_pos < 0.25:
            confidence -= 8   # selling near lower band — extended

    confidence = max(0, min(100, confidence))

    # ── Signal label ──────────────────────────────────────────────────────────
    if confidence >= 78:
        signal = "STRONG BUY"  if trend == 1 else "STRONG SELL"
    elif confidence >= 65:
        signal = "BUY"          if trend == 1 else "SELL"
    elif confidence >= 55:
        signal = "WEAK BUY"    if trend == 1 else "WEAK SELL"
    else:
        signal = "NO TRADE"

    # ── ATR-based SL / TP ─────────────────────────────────────────────────────
    # Use the larger of LTF ATR and 40% of HTF ATR so the stop breathes
    # properly. Then enforce the pip floor from SYMBOL_CONFIG.
    effective_atr = max(atr_val, htf_atr * 0.4)
    min_distance  = cfg["min_atr_pips"] * cfg["pip"]
    effective_atr = max(effective_atr, min_distance)

    sl = tp = rr = None
    if "BUY" in signal:
        sl = price - effective_atr * cfg["sl_mult"]
        tp = price + effective_atr * cfg["tp_mult"]
    elif "SELL" in signal:
        sl = price + effective_atr * cfg["sl_mult"]
        tp = price - effective_atr * cfg["tp_mult"]

    if sl is not None and sl != price:
        risk   = abs(price - sl)
        reward = abs(tp - price)
        rr     = round(reward / risk, 2)

    return {
        "symbol":      symbol,
        "signal":      signal,
        "confidence":  round(confidence, 2),
        "trend":       "BULLISH" if trend == 1 else "BEARISH",
        "htf_trend":   "BULLISH" if htf_trend == 1 else "BEARISH",
        "entry":       round(price, 5),
        "stop_loss":   round(sl, 5) if sl is not None else None,
        "take_profit": round(tp, 5) if tp is not None else None,
        "risk_reward": rr,
        "rsi":         round(ltf_rsi, 2),
        "htf_rsi":     round(htf_rsi_val, 2),
        "atr":         round(atr_val, 5),
        "macd_hist":   round(macd_hist, 6),
        "ema50":       round(ema50_vals[-2], 5),
        "ema200":      round(ema200_vals[-2], 5),
    }


# ======================
# API
# ======================
@app.get("/dashboard/all")
def dashboard():
    now = datetime.now(timezone.utc)
    return {
        "data": {
            "NZDUSD": process("NZD/USD"),
            "GOLD":   process("XAU/USD"),
        },
        "meta": {
            "last_fetch": now.isoformat(),
            "next_sync":  SYNC_INTERVAL,
        },
    }
