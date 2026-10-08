from dataclasses import dataclass, field
from typing import Optional, List
import pandas as pd
import ta
from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, EMA_FAST, EMA_SLOW,
    BUY_STOP_LOSS_PCT, BUY_TARGET_PCT,
    SELL_STOP_LOSS_PCT, SELL_TARGET_PCT,
    ATR_PERIOD, ATR_MULTIPLIER,
    FIB_EXTENSION, MIN_RR,
)


@dataclass
class SignalResult:
    signal: str          # BUY / SELL / NEUTRAL
    strength: str        # STRONG / MEDIUM / WEAK / NEUTRAL
    entry_price: float
    stop_loss: float
    target_price: float
    indicators: List[str] = field(default_factory=list)
    error: Optional[str] = None


def analyze(df: pd.DataFrame) -> SignalResult:
    """
    Run technical analysis on OHLCV DataFrame and return a SignalResult.
    Requires at least 51 rows (for EMA50).
    """
    if df is None or len(df) < 51:
        return SignalResult(
            signal="NEUTRAL", strength="NEUTRAL",
            entry_price=0, stop_loss=0, target_price=0,
            error="Not enough data (need 51+ bars)",
        )

    df = df.copy()
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    open_ = df["open"]

    # --- Compute indicators ---
    rsi      = ta.momentum.RSIIndicator(close, window=RSI_PERIOD).rsi()
    macd_obj = ta.trend.MACD(close, window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL)
    macd_line        = macd_obj.macd()
    macd_signal_line = macd_obj.macd_signal()
    bb       = ta.volatility.BollingerBands(close, window=BB_PERIOD, window_dev=BB_STD)
    bb_lower = bb.bollinger_lband()
    bb_upper = bb.bollinger_hband()
    ema_fast = ta.trend.EMAIndicator(close, window=EMA_FAST).ema_indicator()
    ema_slow = ta.trend.EMAIndicator(close, window=EMA_SLOW).ema_indicator()
    atr      = ta.volatility.AverageTrueRange(high, low, close, window=ATR_PERIOD).average_true_range()

    last_close = float(close.iloc[-1])

    votes_buy  = 0
    votes_sell = 0
    indicator_lines = []

    # --- RSI ---
    rsi_val = _safe_last(rsi)
    if rsi_val is not None:
        if rsi_val < RSI_OVERSOLD:
            votes_buy += 1
            indicator_lines.append(f"✅ RSI({RSI_PERIOD}) = {rsi_val:.1f} (Oversold → BUY)")
        elif rsi_val > RSI_OVERBOUGHT:
            votes_sell += 1
            indicator_lines.append(f"🔴 RSI({RSI_PERIOD}) = {rsi_val:.1f} (Overbought → SELL)")
        else:
            indicator_lines.append(f"⬜ RSI({RSI_PERIOD}) = {rsi_val:.1f} (Neutral)")

    # --- MACD ---
    macd_val = _safe_last(macd_line)
    macd_sig = _safe_last(macd_signal_line)
    if macd_val is not None and macd_sig is not None:
        if macd_val > macd_sig:
            votes_buy += 1
            indicator_lines.append("✅ MACD: bullish crossover → BUY")
        else:
            votes_sell += 1
            indicator_lines.append("🔴 MACD: bearish crossover → SELL")

    # --- Bollinger Bands ---
    bb_l = _safe_last(bb_lower)
    bb_u = _safe_last(bb_upper)
    if bb_l is not None and bb_u is not None:
        if last_close < bb_l:
            votes_buy += 1
            indicator_lines.append("✅ Price below Lower BB → BUY")
        elif last_close > bb_u:
            votes_sell += 1
            indicator_lines.append("🔴 Price above Upper BB → SELL")
        else:
            indicator_lines.append("⬜ Price within Bollinger Bands (Neutral)")

    # --- EMA crossover ---
    ema_f = _safe_last(ema_fast)
    ema_s = _safe_last(ema_slow)
    if ema_f is not None and ema_s is not None:
        if ema_f > ema_s:
            votes_buy += 1
            indicator_lines.append(f"✅ EMA{EMA_FAST} > EMA{EMA_SLOW} (Golden Cross → BUY)")
        else:
            votes_sell += 1
            indicator_lines.append(f"🔴 EMA{EMA_FAST} < EMA{EMA_SLOW} (Death Cross → SELL)")

    # --- Candlestick patterns ---
    candle_signal, candle_label = _detect_candle_pattern(open_, high, low, close)
    if candle_signal == "BUY":
        votes_buy += 1
        indicator_lines.append(f"✅ Candle: {candle_label} → BUY")
    elif candle_signal == "SELL":
        votes_sell += 1
        indicator_lines.append(f"🔴 Candle: {candle_label} → SELL")
    else:
        indicator_lines.append(f"⬜ Candle: No pattern (Neutral)")

    # --- Determine signal ---
    if votes_buy > votes_sell:
        signal = "BUY"
        count  = votes_buy
    elif votes_sell > votes_buy:
        signal = "SELL"
        count  = votes_sell
    elif votes_buy > 0 and ema_s is not None:
        # Tiebreaker: price position relative to EMA50 decides trend direction
        if last_close > float(ema_s):
            signal = "BUY"
            count  = votes_buy
            indicator_lines.append("⚖️ Tiebreaker: price above EMA50 → BUY")
        else:
            signal = "SELL"
            count  = votes_sell
            indicator_lines.append("⚖️ Tiebreaker: price below EMA50 → SELL")
    else:
        signal = "NEUTRAL"
        count  = 0

    if signal == "NEUTRAL":
        strength = "NEUTRAL"
    elif count >= 4:
        strength = "STRONG"
    elif count >= 3:
        strength = "MEDIUM"
    else:
        strength = "WEAK"

    # --- ATR stop loss ---
    atr_val = _safe_last(atr)

    # --- Swing high / low (last 20 bars) ---
    swing_window = 20
    swing_high = float(high.iloc[-swing_window:].max())
    swing_low  = float(low.iloc[-swing_window:].min())
    swing_move = swing_high - swing_low

    # --- Fibonacci extension targets ---
    # BUY:  project above swing_high using 0.618 × move (Fib 1.618 extension)
    # SELL: project below swing_low  using 0.618 × move
    fib_target_buy  = swing_high + FIB_EXTENSION * swing_move
    fib_target_sell = swing_low  - FIB_EXTENSION * swing_move

    # --- Entry / exit prices ---
    if signal == "BUY":
        # ATR stop loss — adapts to each stock's volatility
        if atr_val:
            stop_loss = round(last_close - ATR_MULTIPLIER * atr_val, 2)
        else:
            stop_loss = round(last_close * BUY_STOP_LOSS_PCT, 2)  # fallback

        # Target: average of all valid sources above entry (BB upper, swing high, Fib extension)
        candidates = [
            bb_u            if bb_u            and bb_u            > last_close else None,
            swing_high      if swing_high      > last_close                     else None,
            fib_target_buy  if fib_target_buy  > last_close                     else None,
        ]
        valid = [v for v in candidates if v is not None]
        if valid:
            target = round(sum(valid) / len(valid), 2)
        else:
            target = round(last_close * BUY_TARGET_PCT, 2)  # fallback

    elif signal == "SELL":
        # ATR stop loss
        if atr_val:
            stop_loss = round(last_close + ATR_MULTIPLIER * atr_val, 2)
        else:
            stop_loss = round(last_close * SELL_STOP_LOSS_PCT, 2)  # fallback

        # Target: average of all valid sources below entry (BB lower, swing low, Fib extension)
        candidates = [
            bb_l             if bb_l             and bb_l             < last_close else None,
            swing_low        if swing_low        < last_close                      else None,
            fib_target_sell  if fib_target_sell  < last_close                      else None,
        ]
        valid = [v for v in candidates if v is not None]
        if valid:
            target = round(sum(valid) / len(valid), 2)
        else:
            target = round(last_close * SELL_TARGET_PCT, 2)  # fallback

    else:
        stop_loss = last_close
        target    = last_close

    # --- Annotate ATR and Fibonacci in indicators ---
    if atr_val:
        indicator_lines.append(f"📏 ATR({ATR_PERIOD}) = {_fmt_price(atr_val)} → stop {ATR_MULTIPLIER}× away")
    if signal in ("BUY", "SELL"):
        fib_t = fib_target_buy if signal == "BUY" else fib_target_sell
        indicator_lines.append(
            f"📐 Fib 1.618 extension = {_fmt_price(fib_t)} "
            f"(swing {_fmt_price(swing_low)} → {_fmt_price(swing_high)})"
        )

    # --- R:R filter — veto weak setups ---
    rr = None
    if signal == "BUY" and (last_close - stop_loss) > 0:
        rr = (target - last_close) / (last_close - stop_loss)
    elif signal == "SELL" and (stop_loss - last_close) > 0:
        rr = (last_close - target) / (stop_loss - last_close)

    if rr is not None:
        indicator_lines.append(f"⚖️ R:R = {rr:.2f} (min {MIN_RR})")
        if rr < MIN_RR:
            indicator_lines.append(f"🚫 R:R {rr:.2f} below minimum {MIN_RR} — signal vetoed")
            signal   = "NEUTRAL"
            strength = "NEUTRAL"

    return SignalResult(
        signal=signal,
        strength=strength,
        entry_price=last_close,
        stop_loss=stop_loss,
        target_price=target,
        indicators=indicator_lines,
    )


# ---------------------------------------------------------------------------
# Candlestick pattern detection
# ---------------------------------------------------------------------------

def _detect_candle_pattern(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> tuple:
    """
    Detect the most recent candlestick pattern.
    Returns (signal, label) where signal is 'BUY', 'SELL', or 'NEUTRAL'.
    Priority: 3-candle patterns first, then 2-candle, then single-candle.
    """
    if len(close) < 3:
        return "NEUTRAL", None

    # Last 3 candles
    o1, o2, o3 = float(open_.iloc[-3]), float(open_.iloc[-2]), float(open_.iloc[-1])
    h1, h2, h3 = float(high.iloc[-3]),  float(high.iloc[-2]),  float(high.iloc[-1])
    l1, l2, l3 = float(low.iloc[-3]),   float(low.iloc[-2]),   float(low.iloc[-1])
    c1, c2, c3 = float(close.iloc[-3]), float(close.iloc[-2]), float(close.iloc[-1])

    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    body3 = abs(c3 - o3)
    avg_body = (body1 + body2 + body3) / 3 or 1  # avoid div/0

    # --- Morning Star (BUY) ---
    # Candle 1: large bearish | Candle 2: small body (indecision) | Candle 3: large bullish closing above midpoint of C1
    if (
        c1 < o1 and body1 > avg_body              # C1 large bearish
        and body2 < avg_body * 0.5                 # C2 small (star)
        and c3 > o3 and body3 > avg_body           # C3 large bullish
        and c3 > (o1 + c1) / 2                     # C3 closes above midpoint of C1
    ):
        return "BUY", "Morning Star"

    # --- Evening Star (SELL) ---
    # Candle 1: large bullish | Candle 2: small body | Candle 3: large bearish closing below midpoint of C1
    if (
        c1 > o1 and body1 > avg_body              # C1 large bullish
        and body2 < avg_body * 0.5                 # C2 small (star)
        and c3 < o3 and body3 > avg_body           # C3 large bearish
        and c3 < (o1 + c1) / 2                     # C3 closes below midpoint of C1
    ):
        return "SELL", "Evening Star"

    # --- Bullish Engulfing (BUY) ---
    # C2 bearish, C3 bullish and fully engulfs C2 body
    if (
        c2 < o2                      # C2 bearish
        and c3 > o3                  # C3 bullish
        and o3 <= c2                 # C3 opens at or below C2 close
        and c3 >= o2                 # C3 closes at or above C2 open
    ):
        return "BUY", "Bullish Engulfing"

    # --- Bearish Engulfing (SELL) ---
    # C2 bullish, C3 bearish and fully engulfs C2 body
    if (
        c2 > o2                      # C2 bullish
        and c3 < o3                  # C3 bearish
        and o3 >= c2                 # C3 opens at or above C2 close
        and c3 <= o2                 # C3 closes at or below C2 open
    ):
        return "SELL", "Bearish Engulfing"

    # --- Hammer (BUY) — single candle ---
    # Small body at top, lower shadow >= 2x body, tiny upper shadow
    range3 = h3 - l3 or 1
    upper_shadow3 = h3 - max(o3, c3)
    lower_shadow3 = min(o3, c3) - l3
    if (
        body3 <= range3 * 0.3                      # small body
        and lower_shadow3 >= body3 * 2             # long lower shadow
        and upper_shadow3 <= body3 * 0.5           # tiny upper shadow
    ):
        return "BUY", "Hammer"

    # --- Shooting Star (SELL) — single candle ---
    # Small body at bottom, upper shadow >= 2x body, tiny lower shadow
    if (
        body3 <= range3 * 0.3                      # small body
        and upper_shadow3 >= body3 * 2             # long upper shadow
        and lower_shadow3 <= body3 * 0.5           # tiny lower shadow
    ):
        return "SELL", "Shooting Star"

    return "NEUTRAL", None


def _fmt_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    elif value >= 1:
        return f"{value:,.2f}"
    else:
        return f"{value:.6f}"


def _safe_last(series: pd.Series) -> Optional[float]:
    try:
        val = series.iloc[-1]
        return None if pd.isna(val) else float(val)
    except (IndexError, TypeError):
        return None
