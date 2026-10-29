import ccxt, pandas as pd, requests, os, io, json, time
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")
MEMORY_FILE="accumulation_memory.json"

# BLOCKS - No stocks, commodities, gold, mega
BLOCK_STOCKS = {'TLT','TLH','IEF','SHY','INDA','EWJ','EWA','EWZ','KWEB','QQQ','SPY','DIA','IWM','EWW','EWC','MCHI','INDY','STRC','OURA','SPX','SPX500','NAS100','DJI','US30','UK100','GER40','RKLB','NVDA','AAPL','TSLA','MSFT','STOCK','ETF','OIL','SILVER','GOLD','XAU','XAG','XAUT','PAXG','KAU','TRY','EUR','GBP','JPY','AUD','CAD','CHF','NZD','USDC','BUSD','FDUSD','TUSD','DAI','USDE','USDP','GUSD','PYUSD','EURI','EURC','XLU','XLP','XLE','XLF','XLB','XLI','XLY','XLK','XLV','GLD','SLV','GDX','GDXJ','COPX','LIT','URA'}
BLOCK_MEGA = {'BTC','ETH','SOL','BNB','TRX','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH','XLM','ETC','HBAR','APT','NEAR','UNI','FIL','ARB','OP','ATOM','MATIC','POL','TON','SHIB','PEPE','CRO','LEO','OKB','BGB','SUI','LDO','RNDR','TAO','FET','WIF','ENA','JUP','SEI','TIA','ONDO','W','PYTH','STRK','JTO','ENS'}
BLOCK_COMMODITY = {'LEAD','COPPER','NICKEL','ZINC','TIN','ALUM','ALUMINIUM','ALUMINUM','CORN','SOY','WHEAT','COTTON','SUGAR','COFFEE','COCOA','GAS'}
BLOCK_ALL = BLOCK_STOCKS | BLOCK_MEGA | BLOCK_COMMODITY

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
        print(msg)
    except: pass

def send_photo(fig, cap):
    try:
        buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=150,bbox_inches='tight')
        buf.seek(0); plt.close(fig)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"}, files={"photo":buf}, timeout=30)
    except Exception as e: print(f"Photo {e}")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def is_doji(o,h,l,c): return (h-l)>0 and abs(c-o)/(h-l)<0.35
def is_hammer(o,h,l,c): b=abs(c-o); return b>0 and (min(o,c)-l)>b*1.2

def is_valid_crypto(sym):
    if not sym.endswith('USDT:USDT') and ':USDT' not in sym and 'USDT' not in sym: return False
    base = sym.split('/')[0].split(':')[0].upper()
    if 'STOCK' in base: return False
    if base in BLOCK_ALL: return False
    if any(x in base for x in ['XAU','PAXG','GOLD','XAG','LEAD','COPPER','NICKEL','ZINC','TIN','GLD','SLV','ALUM']): return False
    if len(base) < 2 or len(base) > 6: return False
    if any(c.isdigit() for c in base): return False
    if not base.isalpha(): return False
    return True

# YOUR REVERSAL SCAN LOGIC
def scan_reversal(df):
    if len(df)<70: return None
    df=df.iloc[:-1].copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    for end in range(len(df)-1, len(df)-11, -1):
        for ws in [2,3,4,5,6,7,8]:
            s=end-ws+1; w=df.iloc[s:end+1]
            low=w['l'].min(); low60=df.iloc[max(0,end-60):end]['l'].min()
            if low>low60*1.25: continue
            if (w['c']>w['o']).sum()<1: continue
            if sum(is_doji(r['o'],r['h'],r['l'],r['c']) or is_hammer(r['o'],r['h'],r['l'],r['c']) for _,r in w.iterrows())<1: continue
            if w['rsi'].min()>52 and df['rsi'].iloc[end]>58: continue
            curr=df.iloc[end]['c']; sl=low*0.96; risk=curr-sl
            if risk<=0: continue
            return {'s':s,'e':end,'ws':ws,'curr':curr,'sl':sl,'tp':curr+risk*2.8,'df':df,'rsi':df['rsi'].iloc[end], 'low':low}
    return None

# 12H SOLID BREAKOUT
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

def chart_saved(res, sym, exn, df_full):
    df=res['df'].tail(60)
    fig,ax=plt.subplots(figsize=(11,4))
    for idx,row in df.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=3)
    ax.plot(df.index, df['ema20'].tail(60), color='#5b4cff', lw=1.2, label='EMA20')
    ax.axvspan(res['s'], res['e'], color='lightgreen', alpha=0.3)
    ax.set_title(f"{sym} FUTURES {exn} - {res['ws']}c Reversal SAVED RSI{res['rsi']:.1f}", fontweight='bold')
    ax.legend(); ax.grid(alpha=0.2)
    return fig

def chart_breakout(df_1d, df_12h, base, exn, saved_info, reason_break):
    fig, (ax1, ax2) = plt.subplots(2,1,figsize=(12,7), gridspec_kw={'height_ratios':[2,1]})
    d1 = df_1d.tail(60)
    for idx,row in d1.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax1.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax1.plot([idx,idx],[row['o'],row['c']],color=col,lw=3)
    ax1.plot(d1.index, ema(d1['c'],20), color='#5b4cff', lw=1.2, label='EMA20')
    ax1.axvspan(d1.index[-saved_info['ws']-1], d1.index[-1], color='lightgreen', alpha=0.25)
    ax1.set_title(f"{base} FUTURES {exn} - SAVED {saved_info['days']}d ago Now BREAKOUT", fontweight='bold')
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

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            data=json.loads(open(MEMORY_FILE).read())
            cutoff = datetime.utcnow() - timedelta(days=8)
            cleaned = {}
            for k,v in data.items():
                b = v.get('base',k).upper()
                if datetime.fromisoformat(v['first_seen']) > cutoff and b not in BLOCK_ALL and 'STOCK' not in b and 'LEAD' not in b and 'GLD' not in b:
                    cleaned[b]=v
            return cleaned
        except: pass
    return {}

def save_memory(mem):
    try: open(MEMORY_FILE,'w').write(json.dumps(mem, indent=2))
    except: pass

# MAIN
send_text(f"🚀 <b>FUTURES MEMORY BOT 12H {datetime.utcnow().strftime('%H:%M UTC')}</b>")

EXS = [
    ('BINANCE', ccxt.binanceusdm, {'enableRateLimit': True}),
    ('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BYBIT', ccxt.bybit, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
]

memory = load_memory()
send_text(f"🧠 Memory: {len(memory)} coins watching for 12H breakout")
seen_bases = set(memory.keys())
new_today = 0; breakouts = 0; scanned = 0

for exn, cls, opts in EXS:
    try:
        ex = cls(opts); ex.load_markets()
        syms = [s for s in ex.markets if is_valid_crypto(s)]
        send_text(f"📊 {exn}: {len(syms)} USDT PERP (filtered)")
        
        for sym in syms:
            base = sym.split('/')[0].split(':')[0].upper()
            if base in memory:
                try:
                    df_12h = pd.DataFrame(ex.fetch_ohlcv(sym,'12h',limit=50), columns=['t','o','h','l','c','v'])
                    is_break, reason = detect_12h_breakout(df_12h)
                    if is_break:
                        df_1d = pd.DataFrame(ex.fetch_ohlcv(sym,'1d',limit=80), columns=['t','o','h','l','c','v'])
                        fig = chart_breakout(df_1d, df_12h, base, exn, memory[base], reason)
                        cap = f"🚀 <b>BREAKOUT 12H EMA20 {base} {exn}</b>\n{reason}\nSaved {memory[base]['first_seen'][:10]} {memory[base]['ws']}c reversal\nPrice {df_12h.iloc[-1]['c']:.6f} SL {memory[base]['sl']:.6f} TP {memory[base]['tp']:.6f}\n🔥 Deleted from memory"
                        send_photo(fig, cap)
                        del memory[base]; breakouts+=1; save_memory(memory)
                        time.sleep(0.6)
                except: continue
                continue
            
            if base in seen_bases: continue
            
            try:
                ohlcv = ex.fetch_ohlcv(sym,'1d',limit=90)
                if len(ohlcv)<70: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                res=scan_reversal(df)
                scanned+=1
                if res:
                    memory[base] = {
                        "symbol": sym, "base": base, "exchange": exn,
                        "ws": res['ws'], "rsi": res['rsi'], "sl": float(res['sl']), "tp": float(res['tp']),
                        "curr": float(res['curr']), "low": float(res['low']),
                        "first_seen": datetime.utcnow().isoformat(),
                        "days": 0
                    }
                    seen_bases.add(base); new_today+=1
                    if new_today <= 15:
                        fig = chart_saved(res, base, exn, df)
                        cap = f"📦 <b>SAVED {base} FUTURES {exn}</b> {res['ws']}c RSI{res['rsi']:.1f}\nPrice {res['curr']:.6f} SL {res['sl']:.6f} TP {res['tp']:.6f}\nWatching 12H EMA20 solid breakout"
                        send_photo(fig, cap)
                        time.sleep(0.5)
                    save_memory(memory)
            except: continue
    except Exception as e:
        send_text(f"⚠️ {exn} {str(e)[:100]}")
        continue

save_memory(memory)
send_text(f"✅ <b>DONE</b> Scanned {scanned} New Saved {new_today} Breakouts 12H {breakouts}\n🧠 Total {len(memory)} unique coins in memory until breakout")
