import ccxt, pandas as pd, requests, os, io, json, time
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")
MEMORY_FILE="accumulation_memory.json"

# ALL BLOCKS
BLOCK_STOCKS = {'TLT','TLH','IEF','SHY','INDA','EWJ','EWA','EWZ','KWEB','QQQ','SPY','DIA','IWM','EWW','EWC','MCHI','INDY','STRC','OURA','SPX','SPX500','NAS100','DJI','US30','UK100','GER40','RKLB','NVDA','AAPL','TSLA','MSFT','STOCK','ETF','OIL','GOLD','SILVER','XAU','XAG','XAUT','PAXG','KAU','KAG','TRY','EUR','GBP','JPY','AUD','CAD','CHF','NZD','USDC','BUSD','FDUSD','TUSD','DAI','USDE','USDP','GUSD','PYUSD','EURI','EURC'}

BLOCK_MEGA = {'BTC','ETH','SOL','BNB','TRX','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH','XLM','ETC','HBAR','APT','NEAR','UNI','FIL','ARB','OP','ATOM','MATIC','POL','TON','SHIB','PEPE','CRO','LEO','OKB','BGB','SUI','LDO','RNDR','TAO','FET','WIF','ENA','JUP','SEI','TIA','ONDO','W','PYTH','STRK','JTO','ENS','ETC'}

BLOCK_ALL = BLOCK_STOCKS | BLOCK_MEGA

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
        print(msg)
    except: pass

def send_photo(fig, cap):
    try:
        buf=io.BytesIO()
        fig.savefig(buf,format='png',dpi=150,bbox_inches='tight')
        buf.seek(0); plt.close(fig)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"}, files={"photo":buf}, timeout=30)
    except Exception as e: print(f"Photo error {e}")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()

def is_valid_crypto(sym):
    if not sym.endswith('USDT:USDT'): return False
    base = sym.split('/')[0].upper()
    if base in BLOCK_ALL: return False
    if any(x in base for x in ['XAU','PAXG','GOLD','XAG']): return False
    if len(base) < 2 or len(base) > 8: return False
    if any(c.isdigit() for c in base): return False
    if not base.isalpha(): return False
    return True

def detect_accumulation_days(df_1d):
    if len(df_1d) < 35: return False, 0, ""
    df_1d['ema20']=ema(df_1d['c'],20)
    df_1d['range']=(df_1d['h']-df_1d['l'])/df_1d['c']
    last = df_1d.iloc[-1]
    last_4 = df_1d.iloc[-5:-1]
    tight_days = (last_4['range'] < 0.013).sum()
    avg_range = last_4['range'].mean()
    if avg_range < 0.0015 or avg_range > 0.016: return False, 0, ""
    low_30 = df_1d['l'].iloc[-30:].min()
    near_bottom = last['c'] <= low_30 * 1.30
    below_ema = last['c'] < last['ema20'] * 1.03
    if tight_days >= 2 and near_bottom and below_ema:
        return True, tight_days+1, f"Tight {tight_days+1}d {avg_range*100:.2f}%"
    return False, 0, ""

def detect_12h_breakout(df_12h):
    if len(df_12h) < 40: return False, ""
    df_12h['ema20']=ema(df_12h['c'],20)
    df_12h['ema6']=ema(df_12h['c'],6)
    df_12h['ema12']=ema(df_12h['c'],12)
    last = df_12h.iloc[-1]; prev = df_12h.iloc[-2]
    body = abs(last['c']-last['o']); range_c = last['h']-last['l']
    solid = body / range_c > 0.60 if range_c>0 else False
    green = last['c'] > last['o']
    breakout = last['c'] > last['ema20'] and prev['c'] <= last['ema20']*1.005
    above_all = last['c'] > last['ema6'] and last['c'] > last['ema12']
    vol_ok = last['v'] > df_12h['v'].iloc[-20:].mean() * 0.8
    if breakout and solid and green and above_all and vol_ok:
        return True, f"12H SOLID Breakout EMA20 {last['ema20']:.6f} Close {last['c']:.6f} Body {body/range_c*100:.0f}%"
    return False, ""

def chart_accumulation(df_1d, df_12h, base, exn, days, reason_break):
    fig, (ax1, ax2) = plt.subplots(2,1,figsize=(12,7), gridspec_kw={'height_ratios':[2,1]})
    d1 = df_1d.tail(60)
    for idx,row in d1.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax1.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax1.plot([idx,idx],[row['o'],row['c']],color=col,lw=3)
    ax1.plot(d1.index, ema(d1['c'],20), color='#5b4cff', lw=1.2, label='EMA20')
    ax1.axvspan(d1.index[-days-1], d1.index[-1], color='lightgreen', alpha=0.25)
    ax1.set_title(f"{base} USDT PERP {exn} - {days}d Accumulation at Bottom", fontweight='bold')
    ax1.legend(); ax1.grid(alpha=0.2)
    d12 = df_12h.tail(40)
    for idx,row in d12.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax2.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax2.plot([idx,idx],[row['o'],row['c']],color=col,lw=3)
    ax2.plot(d12.index, ema(d12['c'],20), color='#5b4cff', lw=1.5, label='EMA20 12H')
    ax2.plot(d12.index, ema(d12['c'],6), color='orange', lw=0.8, label='EMA6')
    ax2.plot(d12.index, ema(d12['c'],12), color='blue', lw=0.8, label='EMA12')
    ax2.set_title(f"12H Breakout: {reason_break}", fontsize=10)
    ax2.legend(); ax2.grid(alpha=0.2)
    plt.tight_layout()
    return fig

def chart_acc_only(df_1d, base, exn, days):
    d1 = df_1d.tail(50)
    fig, ax = plt.subplots(figsize=(11,4))
    for idx,row in d1.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=3)
    ax.plot(d1.index, ema(d1['c'],20), color='#5b4cff', lw=1.2, label='EMA20')
    ax.axvspan(d1.index[-days-1], d1.index[-1], color='lightgreen', alpha=0.3)
    ax.set_title(f"{base} USDT PERP {exn} - {days}d Tight Accumulation SAVED")
    ax.legend(); ax.grid(alpha=0.2)
    return fig

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            data=json.loads(open(MEMORY_FILE).read())
            cutoff = datetime.utcnow() - timedelta(days=8)
            cleaned = {}
            for k,v in data.items():
                b = v.get('base',k).upper()
                if datetime.fromisoformat(v['first_seen']) > cutoff and b not in BLOCK_ALL:
                    if 'XAU' not in b and 'PAXG' not in b:
                        cleaned[b]=v
            return cleaned
        except: pass
    return {}

def save_memory(mem):
    try: open(MEMORY_FILE,'w').write(json.dumps(mem, indent=2))
    except: pass

# MAIN
send_text(f"🚀 <b>FINAL BOT 12H - NO MEGA NO GOLD {datetime.utcnow().strftime('%H:%M UTC')}</b>")

EXS = [
    ('BINANCE', ccxt.binanceusdm, {'enableRateLimit': True}),
    ('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BYBIT', ccxt.bybit, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('KUCOIN', ccxt.kucoin, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
]

memory = load_memory()
send_text(f"🧠 Memory: {len(memory)} unique small caps watching")
seen_bases = set(memory.keys())
new_today = 0; breakouts = 0; scanned = 0

for exn, cls, opts in EXS:
    try:
        ex = cls(opts); ex.load_markets()
        syms = [s for s in ex.markets if is_valid_crypto(s)]
        send_text(f"📊 {exn}: {len(syms)} USDT PERP (mega+gold removed)")
        for sym in syms:
            base = sym.split('/')[0].upper()
            if base in memory:
                try:
                    df_12h = pd.DataFrame(ex.fetch_ohlcv(sym,'12h',limit=50), columns=['t','o','h','l','c','v'])
                    is_break, reason = detect_12h_breakout(df_12h)
                    if is_break:
                        df_1d = pd.DataFrame(ex.fetch_ohlcv(sym,'1d',limit=80), columns=['t','o','h','l','c','v'])
                        fig = chart_accumulation(df_1d, df_12h, base, exn, memory[base]['days'], reason)
                        cap = f"🚀 <b>BREAKOUT 12H {base} {exn}</b>\n{reason}\nAccumulated {memory[base]['days']}d since {memory[base]['first_seen'][:10]}\nPrice {df_12h.iloc[-1]['c']:.6f}\n🔥 Deleted from memory"
                        send_photo(fig, cap)
                        del memory[base]; breakouts+=1; save_memory(memory)
                        time.sleep(0.6)
                except: continue
                continue
            if base in seen_bases: continue
            try:
                df_1d = pd.DataFrame(ex.fetch_ohlcv(sym,'1d',limit=45), columns=['t','o','h','l','c','v'])
                is_acc, days_acc, reason_acc = detect_accumulation_days(df_1d)
                scanned+=1
                if is_acc:
                    low_30 = df_1d['l'].iloc[-30:].min()
                    memory[base] = {"symbol": sym, "base": base, "exchange": exn, "days": days_acc, "reason": reason_acc, "first_seen": datetime.utcnow().isoformat(), "price_at_save": float(df_1d.iloc[-1]['c']), "low_30": float(low_30)}
                    seen_bases.add(base); new_today+=1
                    if new_today <= 12:
                        fig = chart_acc_only(df_1d, base, exn, days_acc)
                        cap = f"📦 <b>SAVED {base} {exn}</b>\n{reason_acc}\nEMA20 {ema(df_1d['c'],20).iloc[-1]:.6f} Price {df_1d.iloc[-1]['c']:.6f}\nWatching 12H EMA20 breakout"
                        send_photo(fig, cap)
                        time.sleep(0.5)
                    save_memory(memory)
            except: continue
    except Exception as e:
        send_text(f"⚠️ {exn} {str(e)[:100]}")
        continue

save_memory(memory)
send_text(f"✅ <b>DONE FINAL</b> Scanned {scanned} New {new_today} Breakouts 12H {breakouts}\n🧠 Total {len(memory)} unique small caps only - No BTC SOL BNB TRX XAUT PAXG")
