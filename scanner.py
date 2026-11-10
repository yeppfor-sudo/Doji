import os, io, json, time
import matplotlib
matplotlib.use("Agg")
import requests, numpy as np, pandas as pd, mplfinance as mpf
from concurrent.futures import ThreadPoolExecutor

# ================= SETTINGS =================
TIMEFRAMES = ["4h", "8h", "12h", "1d", "3d", "1w"]
LOOKBACK_DOWN = 30
MIN_DOWN_PCT  = 0.70
BIG_BODY_X    = 1.5
MAX_ABOVE_EMA = 0.12
MAX_CHARTS    = 40
WORKERS       = 8
SENT_FILE     = "sent.json"
KEEP_DAYS     = 30
MIN_GRADE     = "A"      # send only this grade or better: "A", "B" or "C"
# ============================================

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT  = os.environ["TELEGRAM_CHAT_ID"]

BASE = "https://contract.mexc.com/api/v1/contract"
NATIVE = {"4h": ("Hour4", 14400), "8h": ("Hour8", 28800),
          "1d": ("Day1", 86400), "1w": ("Week1", 604800)}
RESAMPLE = {"12h": ("4h", "12h"), "3d": ("1d", "3D")}
SEC = {"4h":14400,"8h":28800,"12h":43200,"1d":86400,"3d":259200,"1w":604800}

TF_WEIGHT = {"4h": 5, "8h": 6, "12h": 7, "1d": 8, "3d": 9, "1w": 10}
GRADE_RANK = {"C": 1, "B": 2, "A": 3}

# ---- non-crypto blocklist (stocks, ETFs, commodities, forex, indices) ----
BLOCK = {
    # stocks
    "TSLA","AAPL","NVDA","MSFT","AMZN","GOOGL","GOOG","META","COIN","MSTR","HOOD",
    "CRCL","PLTR","AMD","NFLX","INTC","BABA","UBER","PYPL","SHOP","NIO","TSM",
    "ORCL","SMCI","AVGO","JPM","WMT","COST","PFE","MCD","NKE","XOM","RIVN",
    "LCID","SOFI","RDDT","DJT","CVNA","BIDU","JD","PDD","ADBE","CRM","QCOM",
    "MRVL","ASML","LLY","UNH","HD","BAC","WFC","GS","CSCO","IBM","SNAP","ABNB",
    "MARA","RIOT","CLSK","IREN","BMNR","SBET","FIG","FIGR","GLXY","BULL","CRWV",
    # ETFs / funds
    "SPY","QQQ","IWM","DIA","ARKK","GLD","SLV","USO","TLT","VOO","IVV","IBIT",
    "ETHA","FBTC","GBTC","BITO",
    # metals / commodities
    "XAU","XAG","GOLD","SILVER","PAXG","XAUT","XPT","XPD","PLATINUM","PALLADIUM",
    "COPPER","XCU","OIL","USOIL","UKOIL","BRENT","WTI","NGAS","NATGAS","WHEAT",
    "CORN","SOYBEAN","COFFEE","SUGAR","COCOA","COTTON",
    # forex / indices
    "EUR","GBP","JPY","AUD","CAD","CHF","NZD","CNH","DXY",
    "SPX","SPX500","NAS100","NDX","US30","US500","US100","DAX","HSI","NIKKEI","FTSE",
}
NON_CRYPTO_WORDS = ("stock", "equity", "equities", "etf", "commodit", "forex",
                    "metal", "tradfi", "traditional", "precious")

def is_non_crypto(c):
    base = str(c.get("baseCoin", "")).upper()
    if base in BLOCK:
        return True
    # defensive: check any category-style fields MEXC may return
    blob = " ".join(str(c.get(k, "")) for k in
                    ("conceptPlate", "conceptPlateId", "conceptPlateEn")).lower()
    return any(w in blob for w in NON_CRYPTO_WORDS)

# ---------------- Telegram ----------------
def tg_text(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": text}, timeout=30)
    except Exception as e:
        print("tg_text error", e)

def tg_photo(buf, caption):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                          data={"chat_id": TG_CHAT, "caption": caption[:1000]},
                          files={"photo": ("chart.png", buf, "image/png")}, timeout=60)
        if not r.ok:
            print("tg_photo error", r.text)
    except Exception as e:
        print("tg_photo error", e)

# ---------------- Data ----------------
def get_symbols():
    r = requests.get(f"{BASE}/detail", timeout=20).json()["data"]
    out, skipped = [], []
    for c in r:
        if c.get("quoteCoin") == "USDT" and c.get("state") == 0:
            if is_non_crypto(c):
                skipped.append(c["symbol"])
            else:
                out.append(c["symbol"])
    print(f"Skipped {len(skipped)} non-crypto pairs: {sorted(skipped)}")
    return out

def klines(symbol, tf, n=200):
    iv, sec = NATIVE[tf]
    end = int(time.time()); start = end - sec * n
    for _ in range(3):
        try:
            d = requests.get(f"{BASE}/kline/{symbol}",
                             params={"interval": iv, "start": start, "end": end},
                             timeout=20).json()
            if d.get("success") and d["data"]["time"]:
                d = d["data"]
                df = pd.DataFrame({"Open": d["open"], "High": d["high"], "Low": d["low"],
                                   "Close": d["close"], "Volume": d["vol"]},
                                  index=pd.to_datetime(d["time"], unit="s"))
                return df.astype(float)
        except Exception:
            time.sleep(0.5)
    return None

def get_df(symbol, tf):
    if tf in NATIVE:
        return klines(symbol, tf)
    src, rule = RESAMPLE[tf]
    df = klines(symbol, src, 400 if tf == "12h" else 300)
    if df is None: return None
    return df.resample(rule).agg({"Open":"first","High":"max","Low":"min",
                                  "Close":"last","Volume":"sum"}).dropna()

def add_ema(df):
    for p in (6, 12, 20):
        df[f"E{p}"] = df["Close"].ewm(span=p, adjust=False).mean()
    return df

# ---------------- Score + Grade ----------------
def calc_score(tf, stacked, below, body_x, ext, vr, fresh):
    # downtrend quality (max 25): 70% -> 0 pts, 100% -> 12.5 pts each
    s = max(0.0, (stacked - MIN_DOWN_PCT) / (1 - MIN_DOWN_PCT)) * 12.5
    s += max(0.0, (below - MIN_DOWN_PCT) / (1 - MIN_DOWN_PCT)) * 12.5
    # trigger candle body (max 25): 1.5x -> 0 pts, 3x or more -> 25 pts
    s += min(max((body_x - BIG_BODY_X) / (3.0 - BIG_BODY_X), 0.0), 1.0) * 25
    # closeness to EMA20 (max 20)
    ep = ext * 100
    s += 20 if ep <= 3 else 12 if ep <= 6 else 5
    # volume vs last 20 candles (max 15)
    s += 15 if vr >= 2 else 10 if vr >= 1.5 else 5 if vr >= 1.2 else 0
    # timeframe weight (max 10)
    s += TF_WEIGHT.get(tf, 5)
    # fresh cross (max 5)
    s += 5 if fresh else 0
    return round(s, 1)

def grade(score):
    return "A" if score >= 70 else ("B" if score >= 55 else "C")

# ---------------- Pattern ----------------
def check(df, tf):
    if df is None or len(df) < 60: return None
    df = add_ema(df.copy())
    closed = df.iloc[:-1] if df.index[-1].timestamp() + SEC[tf] > time.time() else df
    if len(closed) < 50: return None
    c = closed.iloc[-1]; p = closed.iloc[-2]
    hist = closed.iloc[-(LOOKBACK_DOWN+1):-1]

    stacked = ((hist.E6 < hist.E12) & (hist.E12 < hist.E20)).mean()
    below   = (hist.Close < hist.E20).mean()
    falling = hist.E20.iloc[-1] < hist.E20.iloc[0]
    if not (stacked >= MIN_DOWN_PCT and below >= MIN_DOWN_PCT and falling): return None

    body = abs(c.Close - c.Open)
    avg_body = (closed.Close - closed.Open).abs().iloc[-21:-1].mean()
    if not (c.Close > c.Open and body >= BIG_BODY_X * avg_body): return None
    if not (c.Close > c.E6 and c.Close > c.E12 and c.Close > c.E20): return None
    if not (p.Close < p.E20 or c.Open <= c.E20): return None

    ext = c.Close / c.E20 - 1
    if ext > MAX_ABOVE_EMA: return None

    vol_avg = float(closed.Volume.iloc[-21:-1].mean())
    vr = float(c.Volume / vol_avg) if vol_avg > 0 else 0.0
    fresh = bool(p.Close < p.E20)
    body_x = float(body / avg_body)
    score = calc_score(tf, float(stacked), float(below), body_x, float(ext), vr, fresh)

    return {"tf": tf, "close": float(c.Close), "above_EMA20_%": round(float(ext)*100, 2),
            "body_x": round(body_x, 2), "vol_x": round(vr, 2),
            "score": score, "grade": grade(score),
            "candle_time": closed.index[-1]}

def scan_one(args):
    sym, tf = args
    try:
        df = get_df(sym, tf)
        r = check(df, tf)
        if r:
            r["symbol"] = sym
            r["df"] = df
        return r
    except Exception:
        return None

# ---------------- Chart ----------------
def chart_buf(r):
    df = add_ema(r["df"].copy()).tail(70)
    ap = [mpf.make_addplot(df["E6"],  color="#e58fd0", width=1),
          mpf.make_addplot(df["E12"], color="#ff9f2e", width=1),
          mpf.make_addplot(df["E20"], color="#7c4dff", width=1.2)]
    mc = mpf.make_marketcolors(up="#16a672", down="#f0435a", edge="inherit", wick="inherit")
    st = mpf.make_mpf_style(marketcolors=mc, gridstyle=":", facecolor="white")
    buf = io.BytesIO()
    mpf.plot(df, type="candle", style=st, addplot=ap, figsize=(9, 5),
             title=(f"{r['symbol']}  {r['tf']}  Grade {r['grade']} ({r['score']:.0f}/100)  "
                    f"+{r['above_EMA20_%']}% vs EMA20"),
             savefig=dict(fname=buf, format="png", dpi=110))
    buf.seek(0)
    return buf

# ---------------- Dedup state ----------------
def load_sent():
    try:
        with open(SENT_FILE) as f:
            d = json.load(f)
    except Exception:
        d = {}
    cutoff = time.time() - KEEP_DAYS * 86400
    return {k: v for k, v in d.items() if v > cutoff}

def save_sent(d):
    with open(SENT_FILE, "w") as f:
        json.dump(d, f)

# ---------------- Main ----------------
def main():
    sent = load_sent()
    symbols = get_symbols()
    print(f"Scanning {len(symbols)} crypto symbols x {len(TIMEFRAMES)} timeframes")
    jobs = [(s, tf) for s in symbols for tf in TIMEFRAMES]
    with ThreadPoolExecutor(WORKERS) as ex:
        results = [r for r in ex.map(scan_one, jobs) if r]

    # only setups not already alerted (same pair + tf + trigger candle)
    new = []
    for r in results:
        key = f"{r['symbol']}|{r['tf']}|{r['candle_time']}"
        if key not in sent:
            r["key"] = key
            new.append(r)

    # grade filter (default: Grade A only)
    before = len(new)
    new = [r for r in new if GRADE_RANK[r["grade"]] >= GRADE_RANK[MIN_GRADE]]
    print(f"Found {len(results)} setups, {before} new, {len(new)} grade {MIN_GRADE}+")
    if not new:
        save_sent(sent)
        return

    new.sort(key=lambda x: (-x["score"], -x["body_x"]))
    lines = [f"{r['symbol']} | {r['tf']} | Grade {r['grade']} ({r['score']:.0f}) | "
             f"+{r['above_EMA20_%']}% | body {r['body_x']}x" for r in new]
    tg_text(f"🟢 {len(new)} new Grade {MIN_GRADE}+ setups:\n\n" + "\n".join(lines[:60]))

    for r in new[:MAX_CHARTS]:
        try:
            cap = (f"{r['symbol']}  {r['tf']}  |  Grade {r['grade']} ({r['score']:.0f}/100)\n"
                   f"Close: {r['close']}\n"
                   f"+{r['above_EMA20_%']}% vs EMA20 | body {r['body_x']}x | vol {r['vol_x']}x")
            tg_photo(chart_buf(r), cap)
            time.sleep(1)
        except Exception as e:
            print("chart error", r["symbol"], e)

    now = time.time()
    for r in new:
        sent[r["key"]] = now
    save_sent(sent)

if __name__ == "__main__":
    main()
