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
        buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=150,bbox_inches='tight')
        buf.seek(0); plt.close(fig)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"},
            files={"photo":buf}, timeout=25)
    except Exception as e: print(e)

send_text(f"🔒 <b>ULTRA TIGHT {datetime.utcnow().strftime('%H:%M UTC')}</b>\nNo BTC ETH SOL + No Stocks")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def is_hammer(o,h,l,c):
    b=abs(c-o); 
    if b==0 or h==l: return False
    lower=min(o,c)-l; upper=h-max(o,c)
    return lower > b*2.5 and upper < b*0.3 and (h-l) > b*3

def is_doji(o,h,l,c):
    return h!=l and abs(c-o)/(h-l) < 0.10

def scan_ultra(df):
    if len(df)<100: return None
    df=df.iloc[:-1].copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    df['vol_ma']=df['v'].rolling(20).mean()
    
    for end in range(len(df)-1, len(df)-4, -1):
        for ws in [2,3]:
            s=end-ws+1; w=df.iloc[s:end+1]
            low=w['l'].min(); low60=df.iloc[end-60:end]['l'].min(); low90=df.iloc[end-90:end]['l'].min()
            curr=df.iloc[end]['c']; rsi_now=df['rsi'].iloc[end]
            if low > low60*1.025: continue  # 2.5% of 60d low - EXTREME
            if low > low90*1.04: continue   # 4% of 90d low
            if curr > low*1.025: continue   # hasn't pumped
            if rsi_now > 28: continue
            if w['rsi'].min() > 25: continue
            hammers = sum(1 for _,r in w.iterrows() if is_hammer(r['o'],r['h'],r['l'],r['c']) or is_doji(r['o'],r['h'],r['l'],r['c']))
            if hammers < 2: continue
            if curr > df.iloc[end]['ema20']*0.96: continue
            if df.iloc[end]['c'] <= df.iloc[end-1]['c']: continue
            if df.iloc[end]['c'] <= df.iloc[end]['o']: continue
            if df.iloc[end]['v'] < df.iloc[end]['vol_ma']*1.0: continue
            
            sl=low*0.985; risk=curr-sl
            if risk<=0 or risk/curr>0.05: continue
            return {'s':s,'e':end,'ws':ws,'low':low,'curr':curr,'sl':sl,'tp':curr+risk*4.5,'df':df,'rsi':rsi_now,'low60':low60}
    return None

def chart(res,sym,exn):
    df=res['df'].tail(100)
    fig,ax=plt.subplots(figsize=(12,5))
    for idx,row in df.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=4)
    ax.plot(df.index,df['ema20'],color='#5b4cff',lw=1)
    ax.axvspan(res['s'],res['e'],color='gold',alpha=0.4)
    ax.axhline(res['sl'],color='red',ls='--'); ax.axhline(res['tp'],color='green',lw=1.2)
    ax.set_title(f"{sym} FUTURES {exn} {res['ws']}c RSI{res['rsi']:.1f} {res['curr']/res['low60']*100-100:+.1f}% from 60d low")
    ax.grid(alpha=0.2)
    return fig

# EXTENDED BLACKLIST - no mega, no stocks, no ETFs
BLACKLIST = {
    'BTC','ETH','BNB','SOL','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH',
    'KWEB','QQQ','SPX','SPY','STOCK','NVDA','AAPL','TSLA','MSFT','GOOGL','AMZN','META','NFLX',
    'COIN','MSTR','HOOD','PLTR','NVO','LLY','SPCX','USTOCK','USSTOCK',
    'PEPE','SHIB','UNI','TRX','ETC','ATOM','XLM','HBAR','APT','FIL','ARB','OP'
}

# NO BINANCE - it always 451 from US GitHub
EXS = [
    ('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
]

total=0; scanned=0; sent=set()
for exn, cls, opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and (m.get('type') in ['future','swap'] or ':USDT' in m['symbol'])]
        syms=syms[:600]
        send_text(f"📊 {exn}: {len(syms)} FUTURES")
        for sym in syms:
            clean=sym.split('/')[0].split(':')[0].upper()
            if any(b in clean for b in BLACKLIST): continue
            if 'STOCK' in sym.upper() or 'SPX' in clean or 'KWEB' in clean or 'QQQ' in clean: continue
            if clean in sent: continue
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1d',limit=120)
                if len(ohlcv)<100: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                scanned+=1
                res=scan_ultra(df)
                if res:
                    sent.add(clean)
                    fig=chart(res,clean,exn)
                    cap=f"💎 <b>ULTRA BOTTOM {clean} FUTURES {exn}</b>\n{res['ws']}c RSI {res['rsi']:.1f}\nPrice {res['curr']:.6f}\nSL {res['sl']:.6f} TP {res['tp']:.6f}\n{(res['curr']/res['low60']-1)*100:+.1f}% from 60d low | 4.5:1 RR"
                    send_photo(fig,cap); total+=1
                    time.sleep(0.8)
            except: continue
    except Exception as e:
        send_text(f"⚠️ {exn} {str(e)[:80]}"); continue

send_text(f"✅ <b>ULTRA Done</b> Scanned {scanned} Found {total}\n2.5% of 60d low | RSI<28 | 2x hammer | No stocks/mega")
