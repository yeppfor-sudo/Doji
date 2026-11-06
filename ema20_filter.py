import os
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

EMA_LEN = 20
ATR_LEN = 14

def ema(series: pd.Series, length: int = EMA_LEN) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def atr(df: pd.DataFrame, length: int = ATR_LEN) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()

def check_1d_ema20(df, level, direction, breakout_lookback=10, zone_tol=0.003, max_ext_atr=2.0, slope_bars=3, sl_buffer_atr=0.25):
    if df is None or len(df) < max(EMA_LEN, ATR_LEN) + breakout_lookback + 2:
        return None
    d = df.copy()
    for c in ["open","high","low","close"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["open","high","low","close"])
    if len(d) < 30:
        return None
    d["ema20"] = ema(d["close"])
    d["atr"] = atr(d)
    last = d.iloc[-1]
    a = last["atr"]
    e = last["ema20"]
    if pd.isna(a) or pd.isna(e) or a <= 0:
        return None
    slope = e - d["ema20"].iloc[-1 - slope_bars]
    if abs(last["close"] - e) > max_ext_atr * a:
        return None
    window = d.iloc[-(breakout_lookback + 1):-1]
    if direction == "long":
        if slope < 0:
            return None
        bo = window[(window["close"] > level) & (window["close"] > window["ema20"])]
        if bo.empty:
            return None
        zone_top = max(level, e)
        touched = last["low"] <= zone_top * (1 + zone_tol)
        held = last["close"] > zone_top
        if not (touched and held):
            return None
        sl = min(last["low"], e) - sl_buffer_atr * a
        return {"direction":"long","level":float(level),"ema20":float(e),"close":float(last["close"]),"sl":float(sl),"atr":float(a)}
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
        return {"direction":"short","level":float(level),"ema20":float(e),"close":float(last["close"]),"sl":float(sl),"atr":float(a)}
    return None

def build_daily_summary(results, date_str):
    if not results:
        return f"1D breakout-retest (EMA20 confirmed) - {date_str}\nNo pairs passed today."
    longs = [r for r in results if r["direction"]=="long"]
    shorts = [r for r in results if r["direction"]=="short"]
    def line(r):
        return f"{r['pair']}  close {r['close']:.6g}  level {r['level']:.6g}  EMA20 {r['ema20']:.6g}  SL {r['sl']:.6g}"
    parts = [f"1D breakout-retest (EMA20 confirmed) - {date_str}"]
    if longs:
        parts.append(f"\nLONG ({len(longs)})")
        parts += [line(r) for r in longs]
    if shorts:
        parts.append(f"\nSHORT ({len(shorts)})")
        parts += [line(r) for r in shorts]
    return "\n".join(parts)

def _tg_creds():
    token = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing BOT_TOKEN / CHAT_ID environment variables")
    return token, chat_id

def send_telegram_message(text: str):
    token, chat_id = _tg_creds()
    for i in range(0, len(text), 4000):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": text[i:i+4000]}, timeout=20)
        r.raise_for_status()

def render_chart(df, pair, hit, path, n_bars=70):
    d = df.copy()
    for c in ["open","high","low","close"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["ema20"] = ema(d["close"])
    d = d.iloc[-n_bars:].reset_index(drop=True)
    if "time" in d.columns:
        try:
            labels = pd.to_datetime(d["time"]).dt.strftime("%m-%d").tolist()
        except Exception:
            labels = [str(x) for x in range(len(d))]
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
    ax.axvspan(last_x - 0.5, last_x + 0.5, color="#ffffff", alpha=0.08)
    ax.set_title(f"{pair}  1D  {hit['direction'].upper()} retest  (EMA20 confirmed)", color="white", fontsize=12)
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

def send_telegram_photo(path, caption=""):
    token, chat_id = _tg_creds()
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id": chat_id, "caption": caption[:1000]}, files={"photo": f}, timeout=40)
    r.raise_for_status()

def send_daily_report(results, date_str, max_charts=10, out_dir="charts"):
    # FIX: Silent when 0 pass - no more "No pairs passed" spam
    if not results:
        print(f"{date_str}: 0 passed - Telegram skipped (silent)")
        return
    send_telegram_message(build_daily_summary(results, date_str))
    os.makedirs(out_dir, exist_ok=True)
    for r in results[:max_charts]:
        path = os.path.join(out_dir, f"{r['pair']}_1d.png")
        render_chart(r["df"], r["pair"], r, path)
        cap = f"{r['pair']} {r['direction'].upper()}\nclose {r['close']:.6g} | level {r['level']:.6g} | EMA20 {r['ema20']:.6g} | SL {r['sl']:.6g}"
        send_telegram_photo(path, cap)
