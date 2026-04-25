import os
import math
from time import time

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ======================
# CORS
# ======================
# Replace the Vercel URL below with your actual frontend URL once deployed.
# Keep "http://localhost:3000" only if you ever test locally.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://trading-z.vercel.app",  # <-- replace with your real Vercel URL
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ======================
# CONFIG
# ======================
# Set TWELVE_DATA_KEY in:
#   - GitHub: Settings → Secrets and variables → Actions → New repository secret
#   - Render:  Environment tab → Add Environment Variable
API_KEY = os.getenv("TWELVE_DATA_KEY")

# ======================
# CACHE
# ======================
cache = {}
CACHE_TTL = 120
CACHE_MAX_ENTRIES = 50


def _evict_cache():
    """Remove the 10 oldest entries when cache exceeds max size."""
    if len(cache) >= CACHE_MAX_ENTRIES:
        oldest = sorted(cache.items(), key=lambda x: x[1]["time"])
        for key, _ in oldest[:10]:
            del cache[key]


# ======================
# DATA FETCH
# ======================
def fetch_prices(symbol: str):
    try:
        # outputsize=300 ensures a stable EMA-200 (needs 250+ candles minimum)
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={symbol}&interval=15min&outputsize=300&apikey={API_KEY}"
        )
        with httpx.Client(timeout=10) as client:
            r = client.get(url).json()

        if "values" not in r:
            return None

        closes = [float(x["close"]) for x in r["values"]][::-1]
        highs  = [float(x["high"])  for x in r["values"]][::-1]
        lows   = [float(x["low"])   for x in r["values"]][::-1]

        return closes, highs, lows

    except Exception as e:
        print(f"[fetch_prices] Error fetching {symbol}: {e}")
        return None


def get_prices(symbol: str):
    now = time()

    if symbol in cache and now - cache[symbol]["time"] < CACHE_TTL:
        return cache[symbol]["data"]

    data = fetch_prices(symbol)

    if data:
        _evict_cache()
        cache[symbol] = {"data": data, "time": now}

    return data


# ======================
# INDICATORS
# ======================
def ema(data: list, period: int) -> list:
    k = 2 / (period + 1)
    out = [data[0]]
    for p in data[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def rsi(data: list, period: int = 14) -> list:
    if len(data) < period + 1:
        return [50] * len(data)

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

    return [50] * period + rsis


def atr(high: list, low: list, close: list, period: int = 14) -> float:
    """Wilder's smoothed ATR — more stable than a simple average."""
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        trs.append(tr)

    if not trs:
        return 0.0
    if len(trs) < period:
        return sum(trs) / len(trs)

    # Seed with simple average, then apply Wilder's smoothing
    smoothed = sum(trs[:period]) / period
    for tr in trs[period:]:
        smoothed = (smoothed * (period - 1) + tr) / period

    return smoothed


def bollinger(data: list, period: int = 20):
    if len(data) < period:
        return (data[-1], data[-1], data[-1])
    window = data[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    return (mean + 2 * std, mean, mean - 2 * std)


# ======================
# VOLATILITY HELPERS
# ======================
def directional_vol_score(
    closes: list, highs: list, lows: list, period: int = 14
) -> tuple:
    """
    Measures directional conviction via candle body-to-range ratios.
    Strong-bodied bull candles → long pts.
    Strong-bodied bear candles → short pts.
    Returns (long_pts, short_pts), max 10 pts each.
    """
    recent_c = closes[-period:]
    recent_h = highs[-period:]
    recent_l = lows[-period:]

    bull_vol = 0.0
    bear_vol = 0.0

    for i in range(1, len(recent_c)):
        body = abs(recent_c[i] - recent_c[i - 1])
        candle_range = recent_h[i] - recent_l[i]
        conviction = body / candle_range if candle_range > 1e-9 else 0

        if recent_c[i] > recent_c[i - 1]:
            bull_vol += conviction
        else:
            bear_vol += conviction

    total = bull_vol + bear_vol
    if total == 0:
        return 0, 0

    bull_ratio = bull_vol / total  # 0.5=balanced, >0.6=bullish momentum

    if bull_ratio >= 0.65:
        return 10, 0
    elif bull_ratio >= 0.55:
        return 5, 0
    elif bull_ratio <= 0.35:
        return 0, 10
    elif bull_ratio <= 0.45:
        return 0, 5
    return 0, 0  # 0.45–0.55: balanced, no edge


def atr_slope_score(
    highs: list, lows: list, closes: list,
    period: int = 14, lookback: int = 3
) -> tuple:
    """
    Compares current ATR to ATR from `lookback` bars ago.
    Expanding vol in price direction  = conviction   (+5 pts).
    Contracting vol                   = exhaustion   (+3 pts other side).
    Returns (long_pts, short_pts), max 5 pts each.
    """
    if len(closes) < period + lookback + 2:
        return 0, 0

    current_atr = atr(highs, lows, closes, period)
    prior_atr   = atr(highs[:-lookback], lows[:-lookback], closes[:-lookback], period)

    if prior_atr == 0:
        return 0, 0

    atr_change = (current_atr - prior_atr) / prior_atr
    price_up   = closes[-1] > closes[-(lookback + 1)]

    if atr_change > 0.15:
        # Expanding volatility — reward the direction price is moving
        return (5, 0) if price_up else (0, 5)
    elif atr_change < -0.15:
        # Contracting volatility — slight exhaustion lean against current move
        return (0, 3) if price_up else (3, 0)

    return 0, 0  # Stable volatility — no directional edge


# ======================
# SCORING ENGINE
# ======================
def score_trade(closes: list, highs: list, lows: list) -> tuple:
    ema50    = ema(closes, 50)
    ema200   = ema(closes, 200)
    rsi_vals = rsi(closes)
    vol      = atr(highs, lows, closes)

    price = closes[-1]
    upper, mid, lower = bollinger(closes)
    rsi_val = rsi_vals[-1]

    score_long  = 0
    score_short = 0

    # ── TREND (35 pts) ──────────────────────────────────────────────────────
    # EMA50 > EMA200 = bullish structure; below = bearish
    if ema50[-1] > ema200[-1]:
        score_long += 35
    else:
        score_short += 35

    # ── RSI (25 pts) ────────────────────────────────────────────────────────
    # Standard Wilder levels: <30 oversold, >70 overbought, 40–60 neutral
    if rsi_val < 30:
        score_long += 25        # Deeply oversold — strong long signal
    elif rsi_val > 70:
        score_short += 25       # Deeply overbought — strong short signal
    elif rsi_val < 40:
        score_long += 12        # Mildly oversold — partial long signal
    elif rsi_val > 60:
        score_short += 12       # Mildly overbought — partial short signal
    # 40–60: neutral — no points, no artificial inflation

    # ── BOLLINGER BANDS (25 pts) ─────────────────────────────────────────────
    # Position ratio: 0.0 = at lower band, 0.5 = midline, 1.0 = at upper band
    band_range = upper - lower
    if band_range > 0:
        position = (price - lower) / band_range

        if price <= lower:
            score_long += 25    # At/below lower band — strong mean-reversion long
        elif price >= upper:
            score_short += 25   # At/above upper band — strong mean-reversion short
        elif position < 0.35:
            score_long += 15    # Price in lower zone
        elif position > 0.65:
            score_short += 15   # Price in upper zone
        # 0.35–0.65: midline zone — no edge, no points

    # ── VOLATILITY (15 pts) ──────────────────────────────────────────────────
    # Candle body conviction (max 10 pts) + ATR slope (max 5 pts)
    # Hard cap at 15 preserves the 100-pt scoring scale
    long_body,  short_body  = directional_vol_score(closes, highs, lows)
    long_slope, short_slope = atr_slope_score(highs, lows, closes)

    score_long  += min(long_body  + long_slope,  15)
    score_short += min(short_body + short_slope, 15)

    return score_long, score_short, ema50, ema200, rsi_val, vol, price, mid


# ======================
# PROCESS (SMART ENGINE)
# ======================
def process(symbol: str) -> dict:
    data = get_prices(symbol)

    if not data:
        return {"symbol": symbol, "signal": "NO_DATA"}

    closes, highs, lows = data

    if len(closes) < 60:
        return {"symbol": symbol, "signal": "INSUFFICIENT_DATA"}

    long_score, short_score, ema50, ema200, rsi_val, vol, price, mid = score_trade(
        closes, highs, lows
    )

    # ── SMART DECISION ENGINE ────────────────────────────────────────────────
    dominant_score = max(long_score, short_score)
    direction      = "LONG" if long_score > short_score else "SHORT"
    gap            = abs(long_score - short_score)

    signal = "NO TRADE"

    if dominant_score >= 50 and gap >= 10:
        if dominant_score >= 85:
            signal = "STRONG BUY"  if direction == "LONG" else "STRONG SELL"
        elif dominant_score >= 70:
            signal = "BUY"         if direction == "LONG" else "SELL"
        else:
            signal = "WEAK BUY"    if direction == "LONG" else "WEAK SELL"

    # ── RISK MANAGEMENT ──────────────────────────────────────────────────────
    # SL: 1.5× ATR  |  TP: 3.0× ATR  →  R:R = 1:2 (break-even at ~33% win rate)
    entry = price

    if "BUY" in signal:
        sl = entry - vol * 1.5
        tp = entry + vol * 3.0
    elif "SELL" in signal:
        sl = entry + vol * 1.5
        tp = entry - vol * 3.0
    else:
        sl = None
        tp = None

    return {
        "symbol":      symbol,
        "signal":      signal,
        "long_score":  long_score,
        "short_score": short_score,
        "gap":         gap,
        "entry":       round(entry, 5),
        "stop_loss":   round(sl, 5) if sl is not None else None,
        "take_profit": round(tp, 5) if tp is not None else None,
        "rsi":         round(rsi_val, 2),
        "atr":         round(vol, 5),
        "ema50":       round(ema50[-1], 5),
        "ema200":      round(ema200[-1], 5),
    }


# ======================
# API
# ======================
@app.get("/dashboard/all")
def dashboard_all():
    return {
        "EURUSD": process("EUR/USD"),
        # "GBPUSD": process("GBP/USD"),
        # "USDCAD": process("USD/CAD"),
        "NZDUSD": process("NZD/USD"),
        "GOLD": process("XAU/USD")
    }


@app.get("/")
def home():
    return {
        "status":    "running",
        "model":     "institutional hybrid scoring system",
        "timeframe": "15m",
        "strategy":  "trend + momentum + volatility with conflict resolution",
    }
