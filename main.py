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

TIMEFRAME_MINUTES = 15   # minutes per LTF candle — used in holding-time maths

SYNC_INTERVAL  = 300
CACHE_TTL      = 300   # align with SYNC_INTERVAL so prices never refresh mid-window

# Tracks the last time a real data sync occurred so the frontend
# receives the *remaining* countdown, not always the full interval.
last_sync_time: float = 0.0
cached_results: dict  = {}   # holds last computed signals until next sync

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
# Sources: LTF EMA 20, Price vs EMA50 10, HTF EMA 20, RSI 15, MACD 10, Bollinger 10 → total 85
# MACD crossover bonus (+5) can push a side above 85 but confidence is capped at 100%.
MAX_SCORE = 85.0

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


def macd(data: list) -> tuple[float, float]:
    """
    Returns (histogram, macd_line).
    Returning both values allows the caller to detect crossovers by comparing
    the current histogram sign against the previous bar's histogram sign.
    """
    ema12      = ema(data, 12)
    ema26      = ema(data, 26)
    macd_line  = [a - b for a, b in zip(ema12, ema26)]
    signal     = ema(macd_line, 9)
    hist       = macd_line[-1] - signal[-1]
    return hist, macd_line[-1]

# ======================
# HOLDING TIME ESTIMATOR
# ======================
# Methodology
# -----------
# The ATR (Average True Range) measures how far price moves on a *single candle*
# on average. If the distance from entry to TP is D and the ATR per bar is V, the
# naive estimate is D/V bars. Converting to minutes: bars × TIMEFRAME_MINUTES.
#
# Real markets don't trend in a straight line, so we apply empirical multipliers:
#   - Optimistic  : 0.7 × naïve  (strong trend, almost every bar moves toward TP)
#   - Base        : 1.8 × naïve  (typical drift / pullbacks along the way)
#   - Pessimistic : 4.0 × naïve  (choppy market, lots of consolidation)
#
# Rounding to the nearest 15 minutes keeps the numbers clean.

_HOLD_OPT  = 0.7
_HOLD_BASE = 1.8
_HOLD_PESS = 4.0
_ROUND_MIN = 15   # snap estimates to 15-minute grid


def _snap(minutes: float) -> int:
    """Round to the nearest TIMEFRAME_MINUTES grid, minimum 1 interval."""
    snapped = round(minutes / _ROUND_MIN) * _ROUND_MIN
    return max(snapped, _ROUND_MIN)


def estimate_holding_time(
    entry: float,
    take_profit: float,
    atr_per_bar: float,
    timeframe_minutes: int = TIMEFRAME_MINUTES,
) -> dict:
    """
    Return optimistic / base / pessimistic holding-time estimates in minutes.

    Returns None values when a valid TP / ATR is not available.
    """
    if take_profit is None or atr_per_bar <= 0:
        return {"holding_time_opt": None, "holding_time_base": None, "holding_time_pess": None}

    tp_distance  = abs(take_profit - entry)
    naive_bars   = tp_distance / atr_per_bar          # expected bars to TP
    naive_mins   = naive_bars * timeframe_minutes

    return {
        "holding_time_opt":  _snap(naive_mins * _HOLD_OPT),
        "holding_time_base": _snap(naive_mins * _HOLD_BASE),
        "holding_time_pess": _snap(naive_mins * _HOLD_PESS),
    }

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

    Tier thresholds (tuned for MAX_SCORE = 85):
      STRONG  — dominant ≥ 70 and gap ≥ 18  (clear, decisive trend)
      BUY/SELL — dominant ≥ 55 and gap ≥ 10 (moderate conviction)
      WEAK    — dominant ≥ 48 and gap ≥ 6   (marginal, use caution)
      NO TRADE — anything below
    """
    dominant  = max(long_score, short_score)
    gap       = abs(long_score - short_score)
    direction = "BUY" if long_score > short_score else "SELL"

    confidence = round((dominant / MAX_SCORE) * 100, 1)

    if dominant >= 70 and gap >= 18:
        signal = f"STRONG {direction}"
    elif dominant >= 55 and gap >= 10:
        signal = direction
    elif dominant >= 48 and gap >= 6:
        signal = f"WEAK {direction}"
    else:
        signal = "NO TRADE"

    return signal, confidence

# ======================
# PROCESS SYMBOL
# ======================
def process(symbol: str) -> dict:
    data = get_prices(symbol, TIMEFRAME)
    htf  = get_prices(symbol, HTF_TIMEFRAME)

    if not data or not htf:
        return {
            "symbol":              symbol,
            "recommendation":      "NO DATA",
            "confidence":          0.0,
            "entry":               None,
            "stop_loss":           None,
            "take_profit":         None,
            "lot_size":            None,
            "risk_usd":            None,
            "holding_time_opt":    None,
            "holding_time_base":   None,
            "holding_time_pess":   None,
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
    upper, mid, lower = bollinger(closes)
    macd_hist, macd_line_val = macd(closes)

    # MACD crossover: compare current histogram sign vs previous completed bar.
    # A sign flip on the histogram means the MACD line just crossed the signal line.
    prev_macd_hist, _ = macd(closes[:-1])
    macd_crossed = (macd_hist > 0) != (prev_macd_hist > 0)

    htf_ema50  = ema(htf_closes, 50)
    htf_ema200 = ema(htf_closes, 200)

    # ── Trend context flags ────────────────────────────────
    ltf_uptrend = ema50_vals[-2] > ema200_vals[-2]
    htf_uptrend = htf_ema50[-2]  > htf_ema200[-2]

    # ── Scoring ──────────────────────────────────────────────
    long_score = short_score = 0

    # 1. LTF EMA trend (20 pts)
    #    Is the 50 EMA above the 200 EMA on the traded timeframe?
    if ltf_uptrend:
        long_score  += 20
    else:
        short_score += 20

    # 2. Price position vs EMA50 (10 pts)
    #    Is price on the correct side of the trend line right now?
    if price > ema50_vals[-2]:
        long_score  += 10
    else:
        short_score += 10

    # 3. HTF EMA trend (20 pts)
    #    Higher-timeframe bias. Boosted from the original 10 pts because
    #    trading against the HTF trend is the most common cause of false signals.
    if htf_uptrend:
        long_score  += 20
    else:
        short_score += 20

    # 4. RSI (15 pts)
    #    Standard oversold / overbought levels (30/70) with a graduated
    #    mid-zone. The old 45/60 thresholds were too tight and added noise.
    if r < 35:
        long_score  += 15          # deeply oversold — strong buy pressure
    elif r < 45:
        long_score  += 10          # recovering from oversold
    elif r <= 55:
        long_score  += 5           # neutral — no strong conviction either way
        short_score += 5
    elif r <= 65:
        short_score += 10          # weakening from overbought
    else:
        short_score += 15          # deeply overbought — strong sell pressure

    # 5. MACD histogram + crossover bonus (10 pts + 5 bonus)
    #    Base points for histogram direction; bonus awarded on a fresh
    #    signal-line crossover, which is a higher-conviction entry trigger.
    if macd_hist > 0:
        long_score  += 10
        if macd_crossed:
            long_score  += 5       # fresh bullish crossover
    else:
        short_score += 10
        if macd_crossed:
            short_score += 5       # fresh bearish crossover

    # 6. Bollinger Bands — trend-aware (10 pts)
    #    The old logic (price < mid → always long) contradicted the EMA trend
    #    in downtrends. The new logic scores relative to the trend direction:
    #
    #    Uptrend  : near lower band = dip-buy entry (10 pts)
    #               above midline  = trend continuation (7 pts)
    #               otherwise      = weak lean (3 pts)
    #    Downtrend: near upper band = rally-sell entry (10 pts)
    #               below midline  = trend continuation (7 pts)
    #               otherwise      = weak lean (3 pts)
    band_range = upper - lower
    near_lower = price < (lower + band_range * 0.25)
    near_upper = price > (upper - band_range * 0.25)

    if ltf_uptrend:
        if near_lower:
            long_score  += 10
        elif price > mid:
            long_score  += 7
        else:
            long_score  += 3
    else:
        if near_upper:
            short_score += 10
        elif price < mid:
            short_score += 7
        else:
            short_score += 3

    # ── HTF conflict filter ────────────────────────────────
    # When LTF and HTF trends disagree, cap any non-weak signal down to WEAK
    # and reduce confidence by 25%. Avoid trading against the higher timeframe.
    htf_ltf_agree = (ltf_uptrend == htf_uptrend)

    signal, confidence = build_signal(long_score, short_score)

    if not htf_ltf_agree and signal in ("STRONG BUY", "BUY", "STRONG SELL", "SELL"):
        signal     = "WEAK " + ("BUY" if "BUY" in signal else "SELL")
        confidence = round(confidence * 0.75, 1)

    # ── SL / TP ──────────────────────────────────────────────
    effective_atr = max(vol, cfg["min_atr_pips"] * cfg["pip"])
    sl = tp = None

    if "BUY" in signal:
        sl = round(price - effective_atr * cfg["sl_mult"], 5)
        tp = round(price + effective_atr * cfg["tp_mult"], 5)
    elif "SELL" in signal:
        sl = round(price + effective_atr * cfg["sl_mult"], 5)
        tp = round(price - effective_atr * cfg["tp_mult"], 5)

    # ── Lot size ─────────────────────────────────────────────
    risk_usd = get_risk_usd()
    lot_size = calculate_lot_size(risk_usd, price, sl, cfg) if sl is not None else None

    # ── Holding time ─────────────────────────────────────────
    hold = estimate_holding_time(price, tp, effective_atr)

    return {
        "symbol":            symbol,
        "recommendation":    signal,
        "confidence":        confidence,
        "entry":             round(price, 5),
        "stop_loss":         sl,
        "take_profit":       tp,
        "lot_size":          lot_size,
        "risk_usd":          risk_usd,
        "holding_time_opt":  hold["holding_time_opt"],
        "holding_time_base": hold["holding_time_base"],
        "holding_time_pess": hold["holding_time_pess"],
    }

# ======================
# API
# ======================
SYMBOLS = {
    "NZDUSD": "NZD/USD",
    "EURUSD": "EUR/USD",
    "GOLD":   "XAU/USD",
}

@app.get("/dashboard/all")
def dashboard():
    global last_sync_time, cached_results

    now       = time()
    elapsed   = now - last_sync_time
    remaining = int(max(0, SYNC_INTERVAL - elapsed))

    # Only recompute signals when the 15-minute window has elapsed or on
    # first load. Any page refresh in between returns the same cached signals
    # so the recommendation never changes mid-window.
    if elapsed >= SYNC_INTERVAL or last_sync_time == 0.0:
        cached_results = {key: process(sym) for key, sym in SYMBOLS.items()}
        last_sync_time = now
        remaining      = SYNC_INTERVAL

    return {
        "assets": cached_results,
        "meta": {
            "last_fetch": datetime.fromtimestamp(last_sync_time, tz=timezone.utc).isoformat(),
            "next_sync":  remaining,
        },
    }
