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

send_text(f"🔒 <b>EXTREME TIGHT Scan {datetime.utcnow().strftime('%H:%M UTC')}</b>\nFilter: 3% of 60d low + RSI<28")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def is_hammer(o,h,l,c):
    b=abs(c-o); 
    if b==0 or h==l: return False
    lower=min(o,c)-l; upper=h-max(o,c)
    return lower > b*2.2 and upper < b*0.35 and (h-l) > b*2.5

def is_doji(o,h,l,c):
    if h==l: return False
    return abs(c-o)/(h-l) < 0.12 and (h-l) > 0

def scan_extreme(df):
    if len(df)<100: return None
    df=df.iloc[:-1].copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    df['vol_ma20']=df['v'].rolling(20).mean()
    
    # Only check last 3 days
    for end in range(len(df)-1, len(df)-4, -1):
        for ws in [2,3,4]:
            s=end-ws+1; w=df.iloc[s:end+1]
            low=w['l'].min(); low60=df.iloc[end-60:end]['l'].min(); low90=df.iloc[end-90:end]['l'].min()
            curr=df.iloc[end]['c']; ema20=df.iloc[end]['ema20']
            rsi_now=df['rsi'].iloc[end]; rsi_min=w['rsi'].min()
            vol_now=df.iloc[end]['v']; vol_ma=df.iloc[end]['vol_ma20']
            
            # EXTREME 1: Within 3% of 60-day low (absolute bottom)
            if low > low60*1.03: continue
            # EXTREME 2: Within 5% of 90-day low
            if low > low90*1.05: continue
            # EXTREME 3: Price still within 3% of pattern low (hasn't pumped)
            if curr > low*1.03: continue
            # EXTREME 4: RSI extremely oversold
            if rsi_now > 30: continue
            if rsi_min > 28: continue
            # EXTREME 5: Need STRONG hammer/doji - at least 2
            hammers = sum(1 for _,r in w.iterrows() if is_hammer(r['o'],r['h'],r['l'],r['c']) or is_doji(r['o'],r['h'],r['l'],r['c']))
            if hammers < 2: continue
            # EXTREME 6: Price far below EMA20 (capitulation) - at least 5% below
            if curr > ema20*0.97: continue
            # EXTREME 7: Volume confirmation - last candle volume > 1.2x avg (buyers coming)
            if vol_now < vol_ma*0.8: continue
            # EXTREME 8: Must have green close today vs yesterday (reversal started)
            if df.iloc[end]['c'] <= df.iloc[end-1]['c']: continue
            # EXTREME 9: Last candle must be bullish (close > open)
            if df.iloc[end]['c'] <= df.iloc[end]['o']: continue
            
            sl=low*0.98; risk=curr-sl
            if risk<=0 or risk/curr > 0.08: continue # risk must be <8%
            
            return {'s':s,'e':end,'ws':ws,'low':low,'curr':curr,'sl':sl,'tp':curr+risk*4.0,'df':df,'rsi':rsi_now,'low60':low60,'ema20':ema20}
    return None

def chart(res,sym,exn):
    df=res['df'].tail(100)
    fig,(ax,ax2)=plt.subplots(2,1,figsize=(12,6),gridspec_kw={'height_ratios':[3,1]})
    for idx,row in df.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=4)
    ax.plot(df.index,df['ema20'],color='#5b4cff',lw=1.2)
    ax.axvspan(res['s'],res['e'],color='gold',alpha=0.35)
    ax.axhline(res['sl'],color='red',ls='--',lw=1.5); ax.axhline(res['tp'],color='green',ls='-',lw=1.5)
    ax.set_title(f"{sym} FUTURES {exn} {res['ws']}c RSI{res['rsi']:.1f} {res['curr']/res['low60']*100-100:.1f}% above 60d low",fontsize=11)
    ax.grid(alpha=0.2)
    # RSI panel
    ax2.plot(df.index,df['rsi'],color='orange',lw=1.2); ax2.axhline(30,color='red',ls='--'); ax2.axhline(70,color='green',ls='--')
    ax2.set_ylim(0,100); ax2.grid(alpha=0.2)
    return fig

BLACKLIST = {'BTC','ETH','BNB','SOL','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH',
             'SPCX','SPX','STOCK','NVDA','AAPL','TSLA','PEPE','SHIB','UNI','TRX','ETC','ATOM','XLM'}

EXS = [
    ('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BINANCE', ccxt.binance, {'enableRateLimit': True, 'options': {'defaultType': 'future'}}),
]

total=0; scanned=0; sent=set()
for exn, cls, opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and (m.get('type') in ['future','swap'] or ':USDT' in m['symbol'])]
        syms=syms[:600]
        send_text(f"📊 {exn}: {len(syms)}")
        for sym in syms:
            clean=sym.split('/')[0].split(':')[0]
            if any(b in clean.upper() for b in BLACKLIST): continue
            if 'STOCK' in sym.upper(): continue
            if clean in sent: continue
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1d',limit=120)
                if len(ohlcv)<100: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                scanned+=1
                res=scan_extreme(df)
                if res:
                    sent.add(clean)
                    fig=chart(res,clean,exn)
                    pct_from_low = (res['curr']/res['low60']-1)*100
                    cap=f"💎 <b>EXTREME BOTTOM {clean} FUTURES {exn}</b>\n{res['ws']} candles RSI {res['rsi']:.1f}\nPrice {res['curr']:.6f} ({pct_from_low:+.1f}% from 60d low)\nSL {res['sl']:.6f} (-2%)\nTP {res['tp']:.6f} (4:1 RR)\nEMA20 {res['ema20']:.6f}\nFilter: 3% of 60d low, RSI<30, 2x hammer, below EMA"
                    send_photo(fig,cap); total+=1
                    time.sleep(0.8)
            except: continue
    except Exception as e:
        send_text(f"⚠️ {exn} {str(e)[:80]}"); continue

send_text(f"✅ <b>EXTREME Done</b>\nScanned {scanned} FUTURES\nFound {total} 💎\nCriteria: 3% of 60d low, RSI<30, <3% from low, 2x hammer, below EMA, bullish reversal")
