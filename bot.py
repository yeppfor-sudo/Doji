import ccxt, pandas as pd, requests, os, json, time
from datetime import datetime, timedelta

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")

# BLACKLIST - No stocks
BLACKLIST = {'EWJ','KWEB','RKLB','STOCK','NVDA','AAPL','QQQ','SPY','ETF','US30','NAS100','KWEB','EWJ','STOCK'}
MEMORY_FILE="accumulation_memory.json"

def t(m):
    try: 
        print(m)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
        data={"chat_id":CHAT_ID,"text":m,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=20)
    except Exception as e: print(f"Telegram error {e}")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()

def is_valid_crypto(sym):
    s=sym.upper()
    if any(x in s for x in BLACKLIST): return False
    if 'STOCK' in s or '/USDT:USDT' not in sym: return False
    if not sym.endswith('USDT:USDT'): return False
    # Only crypto - filter .S .P etc
    base=sym.split('/')[0]
    if len(base) > 12: return False
    return True

def detect_accumulation_days(df_1d):
    """Find days of accumulation - your CROSS pattern"""
    if len(df_1d) < 30: return False, 0, ""
    
    df_1d['ema20']=ema(df_1d['c'],20)
    df_1d['range']=(df_1d['h']-df_1d['l'])/df_1d['c']
    
    last = df_1d.iloc[-1]
    last_3 = df_1d.iloc[-4:-1]  # Last 3 days before today
    
    # 1. Days of tight accumulation - 3-4 days range <1.2%
    tight_days = (last_3['range'] < 0.012).sum()  # Tight
    avg_range = last_3['range'].mean()
    
    # 2. At bottom - near 30 day low
    low_30 = df_1d['l'].iloc[-30:].min()
    near_bottom = last['c'] <= low_30 * 1.25  # Within 25% of bottom
    
    # 3. Below EMA20 still - not yet breakout on daily
    below_ema = last['c'] < last['ema20'] * 1.02
    
    # 4. Volume dry - accumulation volume less than average
    vol_dry = last['v'] < df_1d['v'].iloc[-20:].mean() * 1.2
    
    if tight_days >= 2 and near_bottom and below_ema and avg_range < 0.015:
        days_count = tight_days + 1
        reason = f"Tight {days_count}d {avg_range*100:.2f}% near 30d low {low_30:.6f} now {last['c']:.6f}"
        return True, days_count, reason
    return False, 0, ""

def detect_8h_breakout(df_8h):
    """8H solid candle breakout EMA20 - your trigger"""
    if len(df_8h) < 30: return False, ""
    
    df_8h['ema20']=ema(df_8h['c'],20)
    df_8h['ema6']=ema(df_8h['c'],6)
    df_8h['ema12']=ema(df_8h['c'],12)
    
    last = df_8h.iloc[-1]
    prev = df_8h.iloc[-2]
    
    # Solid candle - body >60% of range, green, volume
    body = abs(last['c']-last['o'])
    range_c = last['h']-last['l']
    solid = body / range_c > 0.6 if range_c > 0 else False
    green = last['c'] > last['o']
    
    # Breakout EMA20 - close above EMA20, previous below or touching
    breakout = last['c'] > last['ema20'] and prev['c'] <= last['ema20']*1.005
    # Also above EMA6 and EMA12 like screenshot
    above_all = last['c'] > last['ema6'] and last['c'] > last['ema12']
    
    if breakout and solid and green and above_all:
        reason = f"8H SOLID Breakout EMA20 {last['ema20']:.6f} Close {last['c']:.6f} Body {body/range_c*100:.0f}%"
        return True, reason
    return False, ""

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try: 
            data=json.loads(open(MEMORY_FILE).read())
            # Clean old >7 days
            cutoff = datetime.utcnow() - timedelta(days=7)
            cleaned = {k:v for k,v in data.items() if datetime.fromisoformat(v['first_seen']) > cutoff}
            return cleaned
        except: pass
    return {}

def save_memory(mem):
    try: open(MEMORY_FILE,'w').write(json.dumps(mem, indent=2))
    except: pass

# MAIN
t(f"🔍 ACCUMULATION MEMORY BOT {datetime.utcnow().strftime('%H:%M UTC')} - All CEX Scan")

# Setup all CEX
exchanges = []
for ex_id in ['mexc','binance','bybit','okx','bitget','kucoin']:
    try:
        ex_class = getattr(ccxt, ex_id)
        ex = ex_class({'enableRateLimit': True})
        ex.options['defaultType']='swap'
        ex.load_markets()
        exchanges.append((ex_id, ex))
        t(f"✅ {ex_id} loaded {len(ex.markets)} markets")
    except Exception as e:
        t(f"⚠️ {ex_id} failed {str(e)[:100]}")

memory = load_memory()
t(f"🧠 Memory: {len(memory)} pairs already saved from previous days")

new_found_today = 0
breakouts_today = 0
scanned = 0
filtered = 0

for ex_id, ex in exchanges:
    try:
        perps = [s for s in ex.markets if ':USDT' in s and is_valid_crypto(s)][:600]  # Limit per CEX
        for sym in perps:
            clean_key = f"{sym}|{ex_id}"  # Avoid duplicate across CEX but keep exchange info
            
            # Skip if already in memory and not breakout yet
            if clean_key in memory and memory[clean_key].get('status') == 'watching':
                # Check 8H breakout for existing memory
                try:
                    df_8h = pd.DataFrame(ex.fetch_ohlcv(sym,'8h',limit=50), columns=['t','o','h','l','c','v'])
                    is_break, reason = detect_8h_breakout(df_8h)
                    if is_break:
                        base = sym.split('/')[0]
                        t(f"🚀 BREAKOUT ALERT! {base} on {ex_id.upper()}\n{reason}\nDays accumulated: {memory[clean_key]['days']} days\nFirst seen: {memory[clean_key]['first_seen'][:10]}\nChart: https://www.tradingview.com/symbols/{base}USDT/\n🔥 Deleting from memory - trade it now!")
                        del memory[clean_key]
                        breakouts_today += 1
                        save_memory(memory)
                        time.sleep(0.5)
                except: pass
                continue
            
            # New scan - 1D accumulation
            try:
                df_1d = pd.DataFrame(ex.fetch_ohlcv(sym,'1d',limit=35), columns=['t','o','h','l','c','v'])
                is_acc, days_acc, reason_acc = detect_accumulation_days(df_1d)
                
                if is_acc and clean_key not in memory:
                    base = sym.split('/')[0]
                    memory[clean_key] = {
                        "symbol": sym,
                        "base": base,
                        "exchange": ex_id,
                        "days": days_acc,
                        "reason": reason_acc,
                        "first_seen": datetime.utcnow().isoformat(),
                        "status": "watching",
                        "price_at_save": float(df_1d.iloc[-1]['c'])
                    }
                    new_found_today += 1
                    if new_found_today <= 10:  # Alert first 10 to avoid spam
                        t(f"📦 SAVED {base} {ex_id.upper()} - {reason_acc}\nEMA20 {df_1d.iloc[-1]['ema20']:.6f} Now {df_1d.iloc[-1]['c']:.6f}\nWatching for 8H EMA20 breakout")
                    save_memory(memory)
                
                scanned += 1
                if scanned % 200 == 0:
                    time.sleep(1)
            except Exception as e:
                continue
    except Exception as e:
        t(f"Error {ex_id} {str(e)[:100]}")
        continue

# Final report
total_watching = len(memory)
save_memory(memory)

report = f"""
✅ SCAN COMPLETE All CEX

📊 Today:
New accumulation saved: {new_found_today}
Breakouts 8H EMA20: {breakouts_today}
Total scanned: {scanned}
Filtered stocks: {filtered}

🧠 MEMORY:
Total watching: {total_watching} pairs
These are like your CROSS screenshot - tight bottom waiting for 8H breakout

Examples in memory:
""" + "\n".join([f"{v['base']} {v['exchange']} {v['days']}d" for k,v in list(memory.items())[:10]])

t(report)

# Save top watchlist for TradingView
watchlist_text = "\n".join([f"{v['exchange']}:{v['base']}USDT" for v in memory.values()][:100])
open("watchlist.txt","w").write(watchlist_text)

t(f"✅ Memory saved {MEMORY_FILE} - Bot will keep {total_watching} pairs until 8H breakout then auto-delete")
