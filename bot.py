import ccxt, pandas as pd, requests, os, io, json
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")
WATCHLIST_FILE = "bottom_ready.json"  # باٹم تیار لسٹ

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
        print(msg)
    except: pass

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE,'r') as f: return json.load(f)
        except: return {}
    return {}

def save_watchlist(wl):
    with open(WATCHLIST_FILE,'w') as f: json.dump(wl,f,indent=2)

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

# Stage 1: باٹم تیار ہے (کراس کے بغیر بھی)
def is_bottom_ready(df):
    if len(df)<90: return None
    df=df.copy()
    df['ema20']=ema(df['c'],20); df['ema50']=ema(df['c'],50); df['rsi']=rsi(df['c'],14)
    df['vol_ma20']=df['v'].rolling(20).mean()
    
    for ws in [4,5,6]:
        s=len(df)-ws-1; e=len(df)-1
        if s<0: continue
        w=df.iloc[s:e+1]
        low_acc=w['l'].min(); high_acc=w['h'].max()
        if (high_acc-low_acc)/low_acc > 0.08: continue  # ٹائٹ
        
        low7=df.iloc[-8:-1]['l'].min()
        low90=df.iloc[-91:-1]['l'].min()
        curr=df.iloc[-1]['c']
        
        if low_acc > low7*1.08: continue
        if low_acc > low90*1.18: continue
        if curr > low_acc*1.25: continue  # ابھی لو کے قریب
        if df['rsi'].iloc[-1] > 62 or df['rsi'].iloc[-1] < 25: continue
        # ڈاؤن ٹرینڈ کے بعد
        if df['c'].iloc[-20] < df['c'].iloc[-40]*0.85:  # پہلے گرا ہوا ہے
            return {'low':low_acc,'high':high_acc,'ws':ws,'low7':low7,'rsi':df['rsi'].iloc[-1]}
    return None

# Stage 2: آج کراس + گرین کلوز ٹچ ہوا؟
def is_breakout_now(df, bottom_info):
    df=df.copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    df['vol_ma20']=df['v'].rolling(20).mean()
    last=df.iloc[-1]; prev=df.iloc[-2]
    
    cross = prev['c'] <= prev['ema20']*1.01 and last['c'] > last['ema20']
    bullish = last['c'] > last['o']
    touch = last['c'] >= bottom_info['high']*0.992  # اکومولیشن ہائی کو ٹچ کلوز
    
    if cross and bullish and touch:
        sl=bottom_info['low']*0.965; risk=last['c']-sl
        if risk>0 and risk/last['c']<0.10:
            return {'curr':last['c'],'sl':sl,'tp1':last['c']+risk*1.8,'tp2':last['c']+risk*3.2,'vol':last['v']/last['vol_ma20'],'df':df}
    return None

def chart_bottom(res,sym,exn,breakout=False):
    df=res['df'].tail(80) if 'df' in res else res.get('df',None)
    if df is None: return None
    fig,ax=plt.subplots(figsize=(12,5))
    for i in range(len(df)-1):
        r=df.iloc[i]; col='#00b26a' if r['c']>=r['o'] else '#ff3b30'
        ax.plot([df.index[i],df.index[i]],[r['l'],r['h']],color=col,lw=1)
        ax.plot([df.index[i],df.index[i]],[r['o'],r['c']],color=col,lw=3.5)
    last=df.iloc[-1]; li=df.index[-1]
    color='lime' if breakout else 'orange'
    ax.plot([li,li],[last['l'],last['h']],color=color,lw=3,ls='--')
    ax.plot([li,li],[last['o'],last['c']],color=color,lw=7)
    ax.scatter(li, last['c'], color='gold', s=400, edgecolor='black', zorder=7, marker='*')
    ax.plot(df.index, df['ema20'].tail(80), color='#5b4cff', lw=1.8, label='EMA20')
    title = f"{sym} BREAKOUT NOW {exn}" if breakout else f"{sym} BOTTOM READY {exn} - Watch Next 10 Days"
    ax.set_title(title, fontsize=11, color='green' if breakout else 'blue', fontweight='bold')
    ax.legend(fontsize=7); ax.grid(alpha=0.2)
    return fig

# Main
watchlist = load_watchlist()
# پرانی entry 10 دن بعد delete
now=datetime.utcnow()
watchlist = {k:v for k,v in watchlist.items() if (now - datetime.strptime(v['date'],"%Y-%m-%d")).days < 10}

BLACKLIST={'BTC','ETH','BNB','SOL','XRP','BTCDOM','SPX','STOCK'}
EXS=[('MEXC',ccxt.mexc,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('OKX',ccxt.okx,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('GATE',ccxt.gate,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('BITGET',ccxt.bitget,{'enableRateLimit':True,'options':{'defaultType':'swap'}})]

# Step 1: Watchlist کے جو پہلے سے ہیں ان میں breakout چیک کرو
breakouts=[]
for pair_key, info in list(watchlist.items()):
    try:
        clean, exn = pair_key.split('_')
        # ex fetch
        for en, cls, opts in EXS:
            if en!=exn: continue
            ex=cls(opts); ex.load_markets()
            syms=[m['symbol'] for m in ex.markets.values() if clean in m['symbol'] and 'USDT' in m['symbol']]
            if not syms: continue
            ohlcv=ex.fetch_ohlcv(syms[0],'1d',limit=110)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            res=is_breakout_now(df, info)
            if res:
                res['low7']=info['low7']; res['high']=info['high']; res['ws']=info['ws']
                breakouts.append((clean,exn,res))
                del watchlist[pair_key]  # breakout ہو گیا تو لسٹ سے نکال دو
    except: continue

send_text(f"📊 Watchlist {len(watchlist)} bottoms ready, Breakouts today {len(breakouts)}")

# Breakouts بھیجو
for clean,exn,res in breakouts[:10]:
    fig=chart_bottom(res,clean,exn,breakout=True)
    if fig is None: continue
    cap=f"🚀 <b>{clean} BREAKOUT NOW {exn}</b>\nBottom Ready تھا، آج Cross+Close Touch ہوا\nEntry {res['curr']:.6f} SL {res['sl']:.6f} TP {res['tp1']:.6f}/{res['tp2']:.6f}\nVol {res['vol']:.1f}x - Next 10 Days Watchlist سے نکلا"
    buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=140,bbox_inches='tight'); buf.seek(0); plt.close(fig)
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"}, files={"photo":buf}, timeout=25)

# Step 2: نئے bottom ready ڈھونڈو
new_bottoms=0
for exn,cls,opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and (m.get('type') in ['future','swap'] or ':USDT' in m['symbol'])][:400]
        for sym in syms:
            clean=sym.split('/')[0].split(':')[0]
            key=f"{clean}_{exn}"
            if key in watchlist: continue
            if any(b in clean.upper() for b in BLACKLIST): continue
            if 'STOCK' in sym.upper(): continue
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1d',limit=110)
                if len(ohlcv)<90: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                res=is_bottom_ready(df)
                if res:
                    res['date']=datetime.utcnow().strftime("%Y-%m-%d")
                    res['symbol']=sym
                    watchlist[key]=res
                    new_bottoms+=1
            except: continue
    except: continue

save_watchlist(watchlist)
send_text(f"✅ Done: Breakouts {len(breakouts)} sent\nNew bottom ready {new_bottoms} added\nTotal watchlist {len(watchlist)} (10 دن تک scan ہوگا)\nآج جو باٹم تیار ہے وہ کل کراس کرے گا تو Alert آئے گا")
