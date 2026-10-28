import ccxt, pandas as pd, requests, os, io, time
import matplotlib.pyplot as plt
from datetime import datetime

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
        print(msg)
    except: pass

def send_photo(fig, cap):
    try:
        buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=130,bbox_inches='tight')
        buf.seek(0); plt.close(fig)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"},
            files={"photo":buf}, timeout=25)
    except Exception as e: print(e)

send_text(f"🚀 <b>TIGHT FUTURES Scan {datetime.utcnow().strftime('%H:%M UTC')}</b>\nExcluding BTC ETH BNB SOL + stocks...")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def is_doji(o,h,l,c): return (h-l)>0 and abs(c-o)/(h-l)<0.25
def is_hammer(o,h,l,c): 
    b=abs(c-o)
    if b==0 or (h-l)==0: return False
    lower=min(o,c)-l; upper=h-max(o,c)
    return lower > b*1.8 and upper < b*0.5

def scan_tight(df):
    if len(df)<80: return None
    df=df.iloc[:-1].copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    for end in range(len(df)-1, len(df)-6, -1):
        for ws in [2,3,4,5]:
            s=end-ws+1; w=df.iloc[s:end+1]
            low=w['l'].min(); low60=df.iloc[max(0,end-60):end]['l'].min(); low90=df.iloc[max(0,end-90):end]['l'].min()
            curr=df.iloc[end]['c']
            if low > low60*1.08: continue
            if low > low90*1.12: continue
            if curr > low*1.06: continue
            if df['rsi'].iloc[end] > 38: continue
            if w['rsi'].min() > 32: continue
            if sum(1 for _,r in w.iterrows() if is_hammer(r['o'],r['h'],r['l'],r['c']) or is_doji(r['o'],r['h'],r['l'],r['c'])) < 1: continue
            if (w['c'] > w['o']).sum() < 1: continue
            if curr <= w['c'].min(): continue
            sl=low*0.97; risk=curr-sl
            if risk<=0: continue
            return {'s':s,'e':end,'ws':ws,'low':low,'curr':curr,'sl':sl,'tp':curr+risk*3.0,'df':df,'rsi':df['rsi'].iloc[end],'low60':low60}
    return None

def chart(res,sym,exn):
    df=res['df'].tail(90)
    fig,ax=plt.subplots(figsize=(11,4.5))
    for idx,row in df.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=3.5)
    ax.plot(df.index,res['df']['ema20'].tail(90),color='#5b4cff',lw=1.2)
    ax.axvspan(res['s'],res['e'],color='lightgreen',alpha=0.25)
    ax.axhline(res['sl'],color='red',ls='--'); ax.axhline(res['tp'],color='green')
    ax.set_title(f"{sym} FUTURES {exn} {res['ws']}c RSI{res['rsi']:.1f}"); ax.grid(alpha=0.2)
    return fig

BLACKLIST = {'BTC','ETH','BNB','SOL','XRP','ETHFI','BTCDOM','SOLV','XRPBULL','XRPBEAR',
             'SPCX','SPX','STOCK','NVDA','AAPL','TSLA','MSFT','GOOGL','AMZN','META',
             'ADA','DOGE','SHIB','AVAX','DOT','LINK','LTC','BCH','TRX','UNI','ATOM','ETC'}

EXS = [
    ('BINANCE', ccxt.binance, {'enableRateLimit': True, 'options': {'defaultType': 'future'}}),
    ('BINANCE-PERP', ccxt.binanceusdm, {'enableRateLimit': True}),
    ('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
]

total=0; scanned=0; sent_symbols=set()
for exn, cls, opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and (m.get('type') in ['future','swap'] or ':USDT' in m['symbol'])]
        if not syms: syms=[s for s in ex.markets if 'USDT' in s]
        syms=syms[:500]
        send_text(f"📊 {exn}: {len(syms)} pairs")
        for sym in syms:
            clean=sym.split('/')[0].split(':')[0]
            # FILTER MEGA + STOCK
            if any(b in clean.upper() for b in BLACKLIST): continue
            if 'STOCK' in sym.upper() or 'SPX' in clean.upper(): continue
            if clean in sent_symbols: continue
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1d',limit=100)
                if len(ohlcv)<80: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                scanned+=1
                res=scan_tight(df)
                if res:
                    sent_symbols.add(clean)
                    fig=chart(res,clean,exn)
                    cap=f"🔥 <b>{clean} FUTURES {exn}</b> {res['ws']}c RSI{res['rsi']:.1f}\nPrice {res['curr']:.6f} SL {res['sl']:.6f} TP {res['tp']:.6f}\nTIGHT BOTTOM"
                    send_photo(fig,cap); total+=1
                    time.sleep(0.7)
            except: continue
    except Exception as e:
        send_text(f"⚠️ {exn} {str(e)[:100]}"); continue

send_text(f"✅ <b>Done</b> Scanned {scanned} Found {total}\nExcluded: BTC ETH BNB SOL XRP + STOCKS")
