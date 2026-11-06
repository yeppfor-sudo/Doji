"""
ema20_filter.py - EMA20 confirmation filter + daily Telegram summary
for a 1d breakout-retest scanner.

Drop this file next to your scanner and call it AFTER your wedge/breakout
detection has produced a candidate (pair, direction, broken level).

Input candles: pandas DataFrame, oldest -> newest, columns:
    open, high, low, close   (volume optional)
Pass CLOSED candles only (drop the still-forming candle first).
"""

import os
import requests
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # headless (GitHub Actions)
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

EMA_LEN = 20
ATR_LEN = 14


def ema(series: pd.Series, length: int = EMA_LEN) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def atr(df: pd.DataFrame, length: int = ATR_LEN) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def check_1d_ema20(
    df: pd.DataFrame,
    level: float,
    direction: str,            # "long" or "short"
    breakout_lookback: int = 10,
    zone_tol: float = 0.003,   # 0.3% tolerance for "touching" the zone
    max_ext_atr: float = 2.0,  # skip if close is too far from EMA20
    slope_bars: int = 3,
    sl_buffer_atr: float = 0.25,
):
    """
    Returns a dict with entry/SL info if the setup passes, else None.
    The last row of df is the retest candle (previous closed candle).
    """
    if len(df) < max(EMA_LEN, ATR_LEN) + breakout_lookback + 2:
        return None

    d = df.copy()
    d["ema20"] = ema(d["close"])
    d["atr"] = atr(d)

    last = d.iloc[-1]
    a = last["atr"]
    e = last["ema20"]
    if pd.isna(a) or pd.isna(e) or a <= 0:
        return None

    # EMA20 slope: flat or with the trade direction
    slope = e - d["ema20"].iloc[-1 - slope_bars]
    # Extension filter: skip entries far from EMA20
    if abs(last["close"] - e) > max_ext_atr * a:
        return None

    window = d.iloc[-(breakout_lookback + 1):-1]  # candles before retest

    if direction == "long":
        if slope < 0:
            return None
        # breakout candle: closed above level AND above its EMA20
        bo = window[(window["close"] > level) & (window["close"] > window["ema20"])]
        if bo.empty:
            return None
        zone_top = max(level, e)
        touched = last["low"] <= zone_top * (1 + zone_tol)
        held = last["close"] > zone_top
        if not (touched and held):
            return None
        sl = min(last["low"], e) - sl_buffer_atr * a
        return {
            "direction": "long",
            "level": level,
            "ema20": float(e),
            "close": float(last["close"]),
            "sl": float(sl),
            "atr": float(a),
        }

    if direction == "short":
        if slope > 0:
            return None
        bo = window[(window["close"] < level) & (window["close"] < window["ema20"])]
        if bo.empty:
            return None
        zone_bot = min(level, e)
        touched = last["high"] >= zone_bot * (1 - zone_tol)
        held = last["close"] < zone_bot
        if not (touched and held):
            return None
        sl = max(last["high"], e) + sl_buffer_atr * a
        return {
            "direction": "short",
            "level": level,
            "ema20": float(e),
            "close": float(last["close"]),
            "sl": float(sl),
            "atr": float(a),
        }

    return None


def build_daily_summary(results: list, date_str: str) -> str:
    """results: list of dicts, each with 'pair' plus the check_1d_ema20 fields."""
    if not results:
        return f"1D breakout-retest (EMA20 confirmed) - {date_str}\nNo pairs passed today."

    longs = [r for r in results if r["direction"] == "long"]
    shorts = [r for r in results if r["direction"] == "short"]

    def line(r):
        return (
            f"{r['pair']}  close {r['close']:.6g}  level {r['level']:.6g}  "
            f"EMA20 {r['ema20']:.6g}  SL {r['sl']:.6g}"
        )

    parts = [f"1D breakout-retest (EMA20 confirmed) - {date_str}"]
    if longs:
        parts.append("\nLONG (" + str(len(longs)) + ")")
        parts += [line(r) for r in longs]
    if shorts:
        parts.append("\nSHORT (" + str(len(shorts)) + ")")
        parts += [line(r) for r in shorts]
    return "\n".join(parts)


def send_telegram_message(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    # Telegram limit is 4096 chars per message: split if needed
    for i in range(0, len(text), 4000):
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text[i:i + 4000]},
            timeout=20,
        )
        r.raise_for_status()



def render_chart(df: pd.DataFrame, pair: str, hit: dict, path: str, n_bars: int = 70) -> str:
    """
    Render a 1d candlestick chart (built from the same candles the scanner
    just fetched) with EMA20, the broken level, the retest candle and the SL.
    """
    d = df.copy()
    d["ema20"] = ema(d["close"])
    d = d.iloc[-n_bars:].reset_index(drop=True)
    if "time" in df.columns:
        labels = pd.to_datetime(df["time"].iloc[-n_bars:]).dt.strftime("%m-%d").tolist()
    else:
        labels = [str(x) for x in range(len(d))]

    up, down = "#26a69a", "#ef5350"
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=130)
    fig.patch.set_facecolor("#131722")
    ax.set_facecolor("#131722")

    for x, r in d.iterrows():
        color = up if r["close"] >= r["open"] else down
        ax.plot([x, x], [r["low"], r["high"]], color=color, linewidth=1)
        lo, hi = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.35, lo), 0.7, max(hi - lo, 1e-12), color=color))

    ax.plot(d.index, d["ema20"], color="#f5a623", linewidth=1.5, label="EMA20")
    ax.axhline(hit["level"], color="#4fc3f7", linestyle="--", linewidth=1.2, label="Broken level")
    ax.axhline(hit["sl"], color="#ef5350", linestyle=":", linewidth=1.2, label="SL")

    last_x = len(d) - 1
    ax.axvspan(last_x - 0.5, last_x + 0.5, color="#ffffff", alpha=0.08)  # retest candle

    ax.set_title(
        f"{pair}  1D  {hit['direction'].upper()} retest  (EMA20 confirmed)",
        color="white", fontsize=12,
    )
    step = max(len(d) // 8, 1)
    ax.set_xticks(range(0, len(d), step))
    ax.set_xticklabels(labels[::step], color="#b2b5be", fontsize=8)
    ax.tick_params(axis="y", colors="#b2b5be", labelsize=8)
    ax.yaxis.tick_right()
    ax.grid(color="#2a2e39", linewidth=0.5)
    for sp in ax.spines.values():
        sp.set_color("#2a2e39")
    ax.legend(facecolor="#131722", edgecolor="#2a2e39", labelcolor="white", fontsize=8, loc="upper left")
    ax.set_xlim(-1, len(d) + 1)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def send_telegram_photo(path: str, caption: str = ""):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    with open(path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"photo": f},
            timeout=40,
        )
    r.raise_for_status()


def send_daily_report(results: list, date_str: str, max_charts: int = 10, out_dir: str = "charts"):
    """
    Sends the one-message summary, then one chart photo per passing pair
    (each result must include 'pair', 'df' and the check_1d_ema20 fields).
    """
    send_telegram_message(build_daily_summary(results, date_str))
    os.makedirs(out_dir, exist_ok=True)
    for r in results[:max_charts]:
        path = os.path.join(out_dir, f"{r['pair']}_1d.png")
        render_chart(r["df"], r["pair"], r, path)
        cap = (
            f"{r['pair']} {r['direction'].upper()}\n"
            f"close {r['close']:.6g} | level {r['level']:.6g} | "
            f"EMA20 {r['ema20']:.6g} | SL {r['sl']:.6g}"
        )
        send_telegram_photo(path, cap)


# ---------------------------------------------------------------------------
# How to wire it into your scanner (1d only):
#
#   results = []
#   for pair in pairs:
#       df = fetch_closed_candles(pair, "1d")        # your existing function
#       cand = your_wedge_breakout_retest(df)        # your existing detection
#       if not cand:
#           continue
#       hit = check_1d_ema20(df, cand["level"], cand["direction"])
#       if hit:
#           results.append({"pair": pair, "df": df, **hit})
#
#   send_daily_report(results, today_str)
#
# requirements: pandas, requests, matplotlib
# ---------------------------------------------------------------------------
