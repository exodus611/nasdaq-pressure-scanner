#!/usr/bin/env python3
import os, sys, re, json, time, datetime, threading
import numpy as np
import pandas as pd
import requests
import yfinance as yf
import uvicorn
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from alpaca.data import StockHistoricalDataClient, StockBarsRequest, TimeFrame, DataFeed
from alpaca.data.timeframe import TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
from ta.volatility import AverageTrueRange
from ta.trend import PSARIndicator

ALPACA_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
DEEPSEEK_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")

print("="*70)
for name, val in [("ALPACA_API_KEY",ALPACA_KEY),("ALPACA_SECRET_KEY",ALPACA_SECRET),("DEEPSEEK_API_KEY",DEEPSEEK_KEY)]:
    print(f"  {name}: {'OK' if val else 'MISSING'}")
if not ALPACA_KEY or not ALPACA_SECRET:
    print("❌ Добавь ALPACA ключи в Railway Variables"); sys.exit(1)
if not DEEPSEEK_KEY:
    print("❌ Добавь DEEPSEEK_API_KEY в Railway Variables"); sys.exit(1)
print("✅ Все ключи найдены\n")

CACHE_FILE = "tickers_cache.json"
CACHE_TTL_HRS = 24
TICKER_SOURCES = [
    {"name":"Alpaca NASDAQ","type":"alpaca_nasdaq"},
    {"name":"Alpaca All US","type":"alpaca_all"},
    {"name":"Nasdaq.com API","type":"nasdaq_api",
     "url":"https://api.nasdaq.com/api/screener/stocks?tableType=traded&exchange=NASDAQ&limit=10000",
     "headers":{"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://www.nasdaq.com/"}},
    {"name":"NASDAQ FTP","type":"ftp_txt",
     "url":"https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt",
     "headers":{"User-Agent":"Mozilla/5.0"}},
    {"name":"GitHub backup","type":"plain_list",
     "url":"https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.txt",
     "headers":{}},
]

def _is_valid_ticker(s):
    if not s or len(s)>6: return False
    if "$" in s or "." in s: return False
    if re.search(r"[A-Z]{4,}(WS|W|U|R)$",s): return False
    return True

def _load_ticker_cache():
    if not os.path.exists(CACHE_FILE): return []
    try:
        with open(CACHE_FILE) as f: cache=json.load(f)
        cached_at=datetime.datetime.fromisoformat(cache["cached_at"])
        if datetime.datetime.now()-cached_at<timedelta(hours=CACHE_TTL_HRS):
            print(f"  💾 Кэш: {len(cache['tickers'])} тикеров"); return cache["tickers"]
        print("  ⏰ Кэш устарел")
    except: pass
    return []

def _save_ticker_cache(tickers):
    try:
        with open(CACHE_FILE,"w") as f: json.dump({"cached_at":datetime.datetime.now().isoformat(),"tickers":tickers},f)
        print(f"  💾 Кэш сохранён: {len(tickers)}")
    except Exception as e: print(f"  ⚠️ {e}")

def _fetch_alpaca_tickers(nasdaq_only=True):
    try:
        client=TradingClient(ALPACA_KEY,ALPACA_SECRET,paper=True)
        assets=client.get_all_assets(GetAssetsRequest(status=AssetStatus.ACTIVE,asset_class=AssetClass.US_EQUITY))
        tickers=[a.symbol for a in assets if a.tradable and
                 (not nasdaq_only or (a.exchange and "NASDAQ" in a.exchange.upper())) and _is_valid_ticker(a.symbol)]
        print(f"  ✅ Alpaca {'NASDAQ' if nasdaq_only else 'All'}: {len(tickers)}"); return tickers
    except Exception as e: print(f"  ❌ Alpaca: {e}"); return []

def _fetch_http_tickers(src):
    for attempt in range(3):
        try:
            r=requests.get(src["url"],headers=src.get("headers",{}),timeout=30)
            if r.status_code!=200: time.sleep((attempt+1)*5); continue
            raw=[]
            if src["type"]=="nasdaq_api": raw=[row.get("symbol","").strip() for row in r.json().get("data",{}).get("rows",[])]
            elif src["type"]=="ftp_txt":
                for line in r.text.strip().split("\n")[1:]:
                    parts=line.split("|")
                    if len(parts)>=2: raw.append(parts[0].strip())
            elif src["type"]=="plain_list": raw=[t.strip() for t in r.text.strip().split("\n") if t.strip()]
            valid=[t for t in raw if _is_valid_ticker(t)]
            print(f"  ✅ {src['name']}: {len(valid)}"); return valid if len(valid)>500 else []
        except Exception as e: print(f"  ⚠️ {src['name']}: {e}"); time.sleep((attempt+1)*5)
    return []

def get_tickers():
    print("📦 Загрузка тикеров...")
    cached=_load_ticker_cache()
    if cached: return cached
    for src in TICKER_SOURCES:
        tickers=_fetch_alpaca_tickers(src["type"]=="alpaca_nasdaq") if src["type"].startswith("alpaca") else _fetch_http_tickers(src)
        if tickers and len(tickers)>500: _save_ticker_cache(tickers); return tickers
    print("❌ Тикеры не загружены!"); return []

def _fix_yfinance_df(df,ticker):
    if isinstance(df.columns,pd.MultiIndex):
        lvl=df.columns.get_level_values(1)
        df=df.xs(ticker,axis=1,level=1) if ticker in lvl else df.droplevel(1,axis=1)
    return df

def load_via_alpaca_iex(tickers,days=180):
    client=StockHistoricalDataClient(ALPACA_KEY,ALPACA_SECRET)
    end,start=datetime.datetime.now(),datetime.datetime.now()-timedelta(days=days)
    all_data,bs={},50
    total=(len(tickers)+bs-1)//bs
    print(f"  📡 Alpaca IEX: {len(tickers)} тикеров, {total} батчей...")
    for i in range(0,len(tickers),bs):
        batch,bn=tickers[i:i+bs],i//bs+1
        try:
            bars=client.get_stock_bars(StockBarsRequest(symbol_or_symbols=batch,
                timeframe=TimeFrame(1,TimeFrameUnit.Day),start=start,end=end,limit=1000,feed=DataFeed.IEX))
            loaded=0
            for sym in batch:
                if sym in bars and bars[sym] and len(bars[sym])>=20:
                    df=pd.DataFrame([{"Open":b.open,"High":b.high,"Low":b.low,"Close":b.close,"Volume":b.volume,"Date":b.timestamp} for b in bars[sym]])
                    df.set_index("Date",inplace=True); df.sort_index(inplace=True); all_data[sym]=df; loaded+=1
            if bn%10==0 or bn==total: print(f"    Batch {bn}/{total}: {loaded}/{len(batch)}",flush=True)
        except Exception as e:
            if bn%10==0 or bn==total: print(f"    Batch {bn}/{total}: ERR {str(e)[:60]}",flush=True)
    return all_data

def _dl_yahoo(ticker,days):
    try:
        df=yf.download(ticker,period=f"{days}d",interval="1d",progress=False)
        if df.empty: return ticker,None
        df=_fix_yfinance_df(df,ticker)
        return ticker,df if len(df)>=20 else None
    except: return ticker,None

def load_via_yahoo_fallback(tickers,days=180):
    print(f"  📡 Yahoo: {len(tickers)} тикеров (x5)...")
    all_data,done={},0
    with ThreadPoolExecutor(max_workers=5) as ex:
        for future in as_completed({ex.submit(_dl_yahoo,t,days):t for t in tickers}):
            ticker,df=future.result(); done+=1
            if df is not None: all_data[ticker]=df
            if done%200==0: print(f"    {done}/{len(tickers)} ({len(all_data)} OK)",flush=True)
    print(f"    ✅ Yahoo: {len(all_data)}"); return all_data

def load_ohlcv(tickers,days=180):
    print("\n📊 Alpaca IEX → Yahoo Finance")
    alpaca=load_via_alpaca_iex(tickers,days)
    missing=[t for t in tickers if t not in alpaca]
    yahoo=load_via_yahoo_fallback(missing,days) if missing else {}
    all_data={**alpaca,**yahoo}
    print(f"✅ ИТОГО: {len(all_data)}/{len(tickers)}"); return all_data

def load_market_data():
    print("\n📡 QQQ, SPY, IWM...")
    etfs=["QQQ","SPY","IWM"]
    data=load_via_alpaca_iex(etfs,days=30)
    missing=[t for t in etfs if t not in data]
    if missing: data.update(load_via_yahoo_fallback(missing,days=30))
    print(f"  ✅ ETF: {len(data)}"); return data

def calculate_technical_indicators(df):
    if df is None or df.empty or len(df)<20: return df
    df=df.copy()
    try: df["ATR"]=AverageTrueRange(high=df["High"],low=df["Low"],close=df["Close"],window=14).average_true_range()
    except: df["ATR"]=0.0
    try: df["PSAR"]=PSARIndicator(high=df["High"],low=df["Low"],close=df["Close"],step=0.02,max_step=0.2).psar()
    except: df["PSAR"]=df["Close"]
    return df

def get_resistance_levels(df,window=20):
    if df is None or df.empty or len(df)<window:
        return [df["High"].max()*1.02 if df is not None and not df.empty else 100]
    resistance=[]
    for i in range(window,len(df)):
        if df["High"].iloc[i]>=df["High"].iloc[max(0,i-window):i].max()*0.98: resistance.append(df["High"].iloc[i])
    if not resistance: return [df["High"].max()*1.02]
    unique=[]
    for level in resistance[-10:]:
        if not unique or abs(level-unique[-1])/unique[-1]>0.02: unique.append(level)
    return unique[-5:] if unique else [df["High"].max()*1.02]

def _safe_div(a,b,default=0.0):
    try:
        if b==0 or b!=b: return default
        r=a/b
        return r if r==r else default
    except: return default

def calculate_pressure_score(df):
    if df.empty or len(df)<20: return 0,{}
    avg_vol=df["Volume"].rolling(20).mean().iloc[-1]
    vol_score=100-min(100,_safe_div(df["Volume"].iloc[-1],avg_vol,1.0)*100)
    avg_atr=df["ATR"].rolling(20).mean().iloc[-1]
    atr_score=100-min(100,_safe_div(df["ATR"].iloc[-1],avg_atr,1.0)*100)
    df=df.copy(); df["Range"]=df["High"]-df["Low"]
    avg_rng=df["Range"].rolling(20).mean().iloc[-1]
    rng_score=100-min(100,_safe_div(df["Range"].iloc[-1],avg_rng,1.0)*100)
    higher_lows=1 if df["Low"].iloc[-1]>df["Low"].iloc[-5] else 0
    dist_score=min(100,((df["High"].max()*1.02-df["Close"].iloc[-1])/(df["High"].max()*1.02))*100)
    score=vol_score*0.25+atr_score*0.25+rng_score*0.20+higher_lows*15+dist_score*0.15
    return score,{}

def calculate_rs_score(tdf,qdf,sdf):
    def ret(df): return (df["Close"].iloc[-1]/df["Close"].iloc[-5]-1)*100 if len(df)>=5 else 0
    tr,qr,sr=ret(tdf),ret(qdf),ret(sdf)
    rs_qqq=(tr/qr*100) if qr!=0 else 100
    rs_spy=(tr/sr*100) if sr!=0 else 100
    score=min(200,max(0,rs_qqq))*0.70+min(200,max(0,rs_spy))*0.30
    if qr<0 and tr>0: score=min(200,score+50)
    return score,{}

def calculate_breakout_score(df,resistance):
    pct=_safe_div(df["Close"].iloc[-1],resistance,0.0)*100
    avg_vol=df["Volume"].rolling(20).mean().iloc[-1]
    vol_surge=_safe_div(df["Volume"].iloc[-1],avg_vol,1.0)*100
    return min(100,max(0,pct))*0.60+min(200,max(0,vol_surge))*0.40,{}

def calculate_catalyst_score(ticker): return 40.0,{}

def determine_state(p,rs,b,c):
    # catalyst заглушка 40.0, пороги без него
    if p>=70 and rs>=60 and b>=60: return "TRIGGERED"
    if p>=55 and rs>=45 and b>=50: return "READY"
    if p>=40 and rs>=30 and b>=35: return "WATCH"
    return "NO_SIGNAL"

DASHBOARD_HTML = """<!DOCTYPE html><html><head><title>NASDAQ Pressure Scanner v8.1</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Arial,sans-serif;margin:20px;background:#f5f5f5}
h1{color:#333;text-align:center}.container{max-width:1200px;margin:0 auto}
.stats{display:flex;justify-content:space-around;margin:20px 0;flex-wrap:wrap;gap:10px}
.stat-box{background:white;padding:15px 25px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,.1);text-align:center}
.stat-value{font-size:26px;font-weight:bold;color:#0066cc}
.signal-card{background:white;margin-bottom:20px;padding:20px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,.1)}
.state-watch{border-left:4px solid #4caf50}.state-ready{border-left:4px solid #ff9800}.state-triggered{border-left:4px solid #f44336}
.signal-header{display:flex;justify-content:space-between;margin-bottom:10px}
.signal-title{font-size:18px;font-weight:bold}
.state-badge{padding:5px 10px;border-radius:4px;color:white;font-weight:bold}
.watch{background:#4caf50}.ready{background:#ff9800}.triggered{background:#f44336}
.score-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.score-box{background:#f9f9f9;padding:10px;border-radius:4px}
.score-label{font-size:12px;color:#666}.score-value{font-size:20px;font-weight:bold}
.history-table{width:100%;border-collapse:collapse;margin-top:30px}
.history-table th,.history-table td{padding:10px 12px;text-align:left;border-bottom:1px solid #ddd}
.history-table th{background:#f2f2f2}.scanning{text-align:center;padding:40px;color:#888;font-size:18px}
</style></head><body><div class="container">
<h1>NASDAQ Pressure Scanner v8.1</h1>
<div class="stats">
<div class="stat-box"><div>Универсум</div><div class="stat-value" id="u">—</div></div>
<div class="stat-box"><div>Загружено</div><div class="stat-value" id="l">—</div></div>
<div class="stat-box"><div>Сигналов</div><div class="stat-value" id="f">—</div></div>
<div class="stat-box"><div>Время</div><div class="stat-value" id="t">—</div></div>
<div class="stat-box"><div>Обновлено</div><div class="stat-value" id="ts" style="font-size:14px">—</div></div>
</div>
<h2>Текущие сигналы</h2>
<div id="sc"><div class="scanning">⏳ Сканирование...</div></div>
<h2 style="margin-top:40px">История</h2>
<table class="history-table"><thead><tr>
<th>Тикер</th><th>Статус</th><th>Дата</th><th>Цена</th>
<th>Pressure</th><th>RS</th><th>Breakout</th><th>Catalyst</th>
<th>T+1</th><th>T+3</th><th>T+5</th>
</tr></thead><tbody id="hc"></tbody></table>
</div>
<script>
async function go(){
try{
const d=(await(await fetch("/api/results")).json()),s=d.stats||{};
document.getElementById("u").textContent=s.universe_size??"—";
document.getElementById("l").textContent=s.loaded??"—";
document.getElementById("f").textContent=s.filtered??"—";
document.getElementById("t").textContent=s.scan_time_sec?s.scan_time_sec+"s":"—";
document.getElementById("ts").textContent=d.timestamp||"—";
const box=document.getElementById("sc");
if(!d.signals||!d.signals.length){box.innerHTML='<div class="scanning">Нет сигналов</div>';}
else{box.innerHTML=d.signals.map(s=>`<div class="signal-card state-${s.state.toLowerCase()}">
<div class="signal-header"><div class="signal-title">${s.ticker} $${s.price_at_signal}</div>
<span class="state-badge ${s.state.toLowerCase()}">${s.state}</span></div>
<div class="score-grid">
<div class="score-box"><div class="score-label">Pressure</div><div class="score-value">${s.pressure_score}</div></div>
<div class="score-box"><div class="score-label">RS</div><div class="score-value">${s.rs_score}</div></div>
<div class="score-box"><div class="score-label">Breakout</div><div class="score-value">${s.breakout_score}</div></div>
<div class="score-box"><div class="score-label">Catalyst</div><div class="score-value">${s.catalyst_score}</div></div>
</div></div>`).join("");}
const h=(await(await fetch("/api/signal_history")).json());
document.getElementById("hc").innerHTML=h.map(s=>`<tr>
<td><b>${s.ticker}</b></td><td><span class="state-badge ${s.state.toLowerCase()}">${s.state}</span></td>
<td>${s.timestamp}</td><td>$${s.price_at_signal}</td>
<td>${s.pressure_score}</td><td>${s.rs_score}</td><td>${s.breakout_score}</td><td>${s.catalyst_score}</td>
<td>${(s.returns||{})["T+1"]??"—"}%</td><td>${(s.returns||{})["T+3"]??"—"}%</td><td>${(s.returns||{})["T+5"]??"—"}%</td>
</tr>`).join("");
}catch(e){console.error(e)}}
setInterval(go,30000);go();
</script></body></html>"""

app=FastAPI(title="NASDAQ Pressure Scanner v8.1")
scan_results={"timestamp":"","signals":[],"stats":{}}
scan_lock=threading.Lock()
signal_history=[]
os.makedirs("data",exist_ok=True)

def _load_history():
    global signal_history
    try:
        if os.path.exists("data/signal_history.json"):
            with open("data/signal_history.json") as f: signal_history=json.load(f)
    except: signal_history=[]

def _save_history():
    try:
        with open("data/signal_history.json","w") as f: json.dump(signal_history,f,indent=2)
    except Exception as e: print(f"⚠️ {e}")

def run_scanner():
    global scan_results
    print("="*70+"\nNASDAQ Pressure Scanner v8.1 — START\n"+"="*70)
    t0=time.time()
    try:
        tickers=get_tickers()
        if not tickers: print("❌ Тикеры не загружены"); return
        all_data=load_ohlcv(tickers,days=180)
        market=load_market_data()
        if "QQQ" not in market or "SPY" not in market: print("❌ QQQ/SPY не загружены"); return
        signals=[]
        for i,ticker in enumerate(tickers,1):
            if i%100==0: print(f"Progress: {i}/{len(tickers)}, signals: {len(signals)}",flush=True)
            if ticker not in all_data: continue
            df=calculate_technical_indicators(all_data[ticker])
            if df is None or df.empty or len(df)<20: continue
            p,_=calculate_pressure_score(df)
            rs,_=calculate_rs_score(df,market["QQQ"],market["SPY"])
            res=get_resistance_levels(df)
            b,_=calculate_breakout_score(df,res[-1])
            c,_=calculate_catalyst_score(ticker)
            state=determine_state(p,rs,b,c)
            if state!="NO_SIGNAL":
                signals.append({"ticker":ticker,
                    "timestamp":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "state":state,"pressure_score":round(p,2),"rs_score":round(rs,2),
                    "breakout_score":round(b,2),"catalyst_score":round(c,2),
                    "price_at_signal":round(df["Close"].iloc[-1],2)})
        elapsed=round(time.time()-t0)
        with scan_lock:
            scan_results={"timestamp":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "signals":signals,"stats":{"universe_size":len(tickers),"loaded":len(all_data),
                "filtered":len(signals),"scan_time_sec":elapsed}}
        print(f"\n✅ Скан завершён за {elapsed}s — {len(signals)} сигналов")
        _save_history()
    except Exception as e:
        print(f"❌ {e}"); import traceback; traceback.print_exc()

@app.on_event("startup")
async def startup_event():
    _load_history(); threading.Thread(target=run_scanner,daemon=True).start()

@app.get("/",response_class=HTMLResponse)
async def dashboard(): return DASHBOARD_HTML

@app.get("/api/results")
async def get_results():
    with scan_lock: return JSONResponse(content=scan_results)

@app.get("/api/signal_history")
async def get_signal_history():
    with scan_lock: return JSONResponse(content=signal_history)

@app.get("/api/health")
async def health(): return {"status":"ok","timestamp":datetime.datetime.now().isoformat()}



# ══════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════
import warnings
warnings.filterwarnings("ignore")

BACKTEST_TICKERS_SAMPLE = 300   # сколько тикеров брать для бэктеста
BACKTEST_DAYS           = 360   # загружаем 360 дней истории
SIGNAL_LOOKBACK         = 120   # дней данных для расчёта сигнала
FORWARD_DAYS            = [1, 3, 5]  # горизонты оценки

backtest_results = {}
backtest_lock    = threading.Lock()


def passes_quality_filter(df):
    try:
        close = df["Close"].iloc[-1]
        avg_dollar_vol = (df["Close"] * df["Volume"]).rolling(20).mean().iloc[-1]
        ema50 = df["Close"].ewm(span=50, adjust=False).mean().iloc[-1]
        if close < 2.0: return False, "penny"
        if avg_dollar_vol < 500_000: return False, "illiquid"
        if close < ema50 * 0.95: return False, "downtrend"
        return True, "ok"
    except: return False, "error"

def _run_backtest_for_ticker(ticker, df, market):
    """
    Для одного тикера прогоняем скользящее окно:
    каждый день с индекса SIGNAL_LOOKBACK до конца-5 —
    считаем сигнал и смотрим что было через 1/3/5 дней.
    """
    rows = []
    n    = len(df)

    for i in range(SIGNAL_LOOKBACK, n - max(FORWARD_DAYS) - 1):
        window = df.iloc[:i].copy()   # данные доступные на момент сигнала
        future = df.iloc[i:]          # будущее (не видим при генерации сигнала)

        # Качество
        ok, _ = passes_quality_filter(window)
        if not ok:
            continue

        # Скоры
        try:
            p,  _ = calculate_pressure_score(window)
            rs, _ = calculate_rs_score(window, market["QQQ"], market["SPY"])
            res   = get_resistance_levels(window)
            b,  _ = calculate_breakout_score(window, res[-1])
            c,  _ = calculate_catalyst_score(ticker)
            state = determine_state(p, rs, b, c)
        except Exception:
            continue

        if state == "NO_SIGNAL":
            continue

        # Фактические доходности
        entry_price = future["Close"].iloc[0]
        rets = {}
        for t in FORWARD_DAYS:
            if t < len(future):
                rets[f"T+{t}"] = round((future["Close"].iloc[t] / entry_price - 1) * 100, 2)

        rows.append({
            "ticker":         ticker,
            "date":           str(df.index[i])[:10],
            "state":          state,
            "pressure_score": p,
            "rs_score":       rs,
            "breakout_score": b,
            "entry_price":    round(entry_price, 2),
            **rets
        })

    return rows


def run_backtest():
    """Полный бэктест за 2024-H2 на выборке тикеров."""
    global backtest_results
    print("="*70)
    print("BACKTEST START — 2024-H2, 6 months")
    print("="*70)
    t0 = time.time()

    import warnings; warnings.filterwarnings("ignore")

    # 1. Тикеры
    all_tickers = get_tickers()
    if not all_tickers:
        print("❌ Тикеры не загружены"); return

    # Берём выборку — случайные 300 + все что прошли фильтр в последнем скане
    import random; random.seed(42)
    sample = random.sample(all_tickers, min(BACKTEST_TICKERS_SAMPLE, len(all_tickers)))
    print(f"📊 Выборка: {len(sample)} тикеров")

    # 2. Загружаем данные (360 дней)
    print("\n📡 Загрузка исторических данных...")
    all_data = load_ohlcv(sample, days=BACKTEST_DAYS)
    market   = load_market_data()

    if "QQQ" not in market or "SPY" not in market:
        print("❌ QQQ/SPY не загружены"); return

    # 3. Скользящий бэктест
    print("\n🔄 Прогон скользящего окна...")
    all_signals = []
    done = 0

    for ticker in sample:
        done += 1
        if done % 50 == 0:
            print(f"  {done}/{len(sample)} тикеров, сигналов: {len(all_signals)}", flush=True)
        if ticker not in all_data:
            continue
        df = calculate_technical_indicators(all_data[ticker])
        if df is None or df.empty or len(df) < SIGNAL_LOOKBACK + max(FORWARD_DAYS) + 5:
            continue
        rows = _run_backtest_for_ticker(ticker, df, market)
        all_signals.extend(rows)

    if not all_signals:
        print("❌ Нет сигналов для анализа")
        with backtest_lock:
            backtest_results = {"error": "no_signals", "tickers_checked": len(sample)}
        return

    print(f"\n📊 Всего сигналов для анализа: {len(all_signals)}")

    # 4. Агрегация результатов
    import statistics

    def aggregate(signals, label):
        if not signals: return {}
        res = {}
        for t in [f"T+{x}" for x in FORWARD_DAYS]:
            vals = [s[t] for s in signals if t in s]
            if not vals: continue
            wins = [v for v in vals if v > 0]
            res[t] = {
                "count":       len(vals),
                "win_rate":    round(len(wins) / len(vals) * 100, 1),
                "avg_return":  round(statistics.mean(vals), 2),
                "median":      round(statistics.median(vals), 2),
                "avg_win":     round(statistics.mean(wins), 2) if wins else 0,
                "avg_loss":    round(statistics.mean([v for v in vals if v <= 0]), 2) if [v for v in vals if v <= 0] else 0,
                "best":        round(max(vals), 2),
                "worst":       round(min(vals), 2),
            }
        return res

    # По состояниям
    by_state = {}
    for state in ["TRIGGERED", "READY", "WATCH"]:
        subset = [s for s in all_signals if s["state"] == state]
        if subset:
            by_state[state] = {
                "count":   len(subset),
                "metrics": aggregate(subset, state)
            }

    # Общая статистика
    overall = aggregate(all_signals, "ALL")

    # Score buckets — корреляция pressure_score → доходность T+5
    buckets = {"0-25": [], "25-50": [], "50-75": [], "75-100": []}
    for s in all_signals:
        p = s["pressure_score"]
        t = s.get("T+5")
        if t is None: continue
        if p < 25:   buckets["0-25"].append(t)
        elif p < 50: buckets["25-50"].append(t)
        elif p < 75: buckets["50-75"].append(t)
        else:        buckets["75-100"].append(t)

    score_correlation = {}
    for bucket, vals in buckets.items():
        if vals:
            score_correlation[bucket] = {
                "count":      len(vals),
                "avg_return": round(sum(vals)/len(vals), 2),
                "win_rate":   round(sum(1 for v in vals if v > 0)/len(vals)*100, 1)
            }

    # Equity curve (по датам, все сигналы T+5)
    from collections import defaultdict
    daily = defaultdict(list)
    for s in all_signals:
        if "T+5" in s:
            daily[s["date"]].append(s["T+5"])
    equity = []
    cumulative = 0.0
    for date in sorted(daily.keys()):
        avg_day = sum(daily[date]) / len(daily[date])
        cumulative += avg_day
        equity.append({"date": date, "daily_avg": round(avg_day, 2), "cumulative": round(cumulative, 2)})

    elapsed = round(time.time() - t0)
    result = {
        "timestamp":        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec":      elapsed,
        "tickers_checked":  len(sample),
        "tickers_with_data":len(all_data),
        "total_signals":    len(all_signals),
        "overall":          overall,
        "by_state":         by_state,
        "score_correlation": score_correlation,
        "equity_curve":     equity[-60:],   # последние 60 точек
        "sample_signals":   sorted(all_signals, key=lambda x: x.get("T+5", 0), reverse=True)[:20]
    }

    with backtest_lock:
        backtest_results = result

    # Печатаем краткий отчёт в логи
    print(f"\n{'='*70}")
    print(f"BACKTEST RESULTS — {len(all_signals)} сигналов за {elapsed}s")
    print(f"{'='*70}")
    for state, data in by_state.items():
        m = data["metrics"].get("T+5", {})
        print(f"  {state:10} n={data['count']:4d}  WR={m.get('win_rate','?')}%  avg={m.get('avg_return','?')}%  T+5")
    print(f"\nScore correlation (Pressure → T+5 avg return):")
    for bucket, data in score_correlation.items():
        print(f"  Pressure {bucket}: WR={data['win_rate']}%  avg={data['avg_return']}%  n={data['count']}")


# ─── API эндпоинты для бэктеста ───────────────────────────────────────

@app.get("/backtest/run")
async def start_backtest():
    """Запускает бэктест в фоне. Результат через /backtest/results."""
    with backtest_lock:
        if backtest_results.get("running"):
            return {"status": "already_running"}
    backtest_results["running"] = True
    threading.Thread(target=run_backtest, daemon=True).start()
    return {"status": "started", "check": "/backtest/results"}


@app.get("/backtest/results")
async def get_backtest_results():
    with backtest_lock:
        return JSONResponse(content=backtest_results)


@app.get("/backtest", response_class=HTMLResponse)
async def backtest_dashboard():
    return BACKTEST_HTML


BACKTEST_HTML = """<!DOCTYPE html><html><head>
<title>Backtest — NASDAQ Pressure Scanner</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Arial,sans-serif;margin:20px;background:#0d1117;color:#e6edf3}
h1,h2{color:#58a6ff}h2{border-bottom:1px solid #30363d;padding-bottom:8px;margin-top:30px}
.container{max-width:1300px;margin:0 auto}
.btn{padding:10px 28px;background:#238636;color:white;border:none;border-radius:6px;cursor:pointer;font-size:16px;margin-bottom:20px}
.btn:hover{background:#2ea043}.btn.running{background:#9e6a03}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}
.stat-box{background:#161b22;padding:14px 20px;border-radius:8px;border:1px solid #30363d;text-align:center;min-width:130px}
.stat-value{font-size:24px;font-weight:bold;color:#58a6ff}
.stat-label{font-size:11px;color:#8b949e;margin-bottom:4px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
th{padding:10px;text-align:left;border-bottom:2px solid #30363d;color:#8b949e;font-weight:normal}
td{padding:9px 10px;border-bottom:1px solid #21262d}
tr:hover td{background:#161b22}
.pos{color:#3fb950}.neg{color:#f85149}.neu{color:#d29922}
.state-badge{padding:3px 10px;border-radius:12px;font-size:12px;font-weight:bold;color:white}
.triggered{background:#da3633}.ready{background:#9e6a03}.watch{background:#238636}
.section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:20px}
.bucket-bar{display:flex;align-items:center;gap:10px;margin:6px 0}
.bucket-label{width:80px;font-size:12px;color:#8b949e}
.bar{height:20px;background:#58a6ff;border-radius:3px;min-width:4px}
.bar-val{font-size:12px;color:#e6edf3}
#status{color:#8b949e;font-style:italic;margin:10px 0}
canvas{max-width:100%;margin-top:10px}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
</head><body><div class="container">
<h1>📊 Backtest — NASDAQ Pressure Scanner v8.2</h1>
<p style="color:#8b949e">Период: 2024-H2 &nbsp;|&nbsp; Горизонты: T+1, T+3, T+5 дней &nbsp;|&nbsp; Выборка: 300 тикеров</p>

<button class="btn" id="runBtn" onclick="startBacktest()">▶ Запустить бэктест (~10 мин)</button>
<div id="status">Нажми кнопку чтобы запустить</div>

<div id="results" style="display:none">

  <h2>Общая статистика</h2>
  <div class="stats" id="overall-stats"></div>

  <h2>По состояниям сигнала</h2>
  <div class="section">
  <table id="state-table">
    <thead><tr>
      <th>Состояние</th><th>Сигналов</th>
      <th>WR T+1</th><th>Avg T+1</th>
      <th>WR T+3</th><th>Avg T+3</th>
      <th>WR T+5</th><th>Avg T+5</th>
      <th>Best T+5</th><th>Worst T+5</th>
    </tr></thead>
    <tbody id="state-body"></tbody>
  </table>
  </div>

  <h2>Корреляция Pressure Score → доходность T+5</h2>
  <div class="section" id="correlation-section"></div>

  <h2>Equity Curve (накопленный avg T+5 по датам)</h2>
  <div class="section"><canvas id="equityChart" height="80"></canvas></div>

  <h2>Топ-20 лучших сигналов (T+5)</h2>
  <div class="section">
  <table>
    <thead><tr><th>Тикер</th><th>Дата</th><th>Статус</th><th>Цена входа</th>
    <th>Pressure</th><th>RS</th><th>Breakout</th>
    <th>T+1</th><th>T+3</th><th>T+5</th></tr></thead>
    <tbody id="top-signals"></tbody>
  </table>
  </div>

</div>
</div>

<script>
let pollInterval = null;
let chartInst = null;

function colorRet(v){
  const n=parseFloat(v);
  return isNaN(n)?'':(n>0?'pos':n<0?'neg':'neu');
}

async function startBacktest(){
  document.getElementById('runBtn').textContent='⏳ Запущен...';
  document.getElementById('runBtn').classList.add('running');
  document.getElementById('status').textContent='Бэктест запущен. Обновляем каждые 15 сек...';
  await fetch('/backtest/run');
  pollInterval = setInterval(checkResults, 15000);
  checkResults();
}

async function checkResults(){
  try{
    const r = await fetch('/backtest/results');
    const d = await r.json();
    if(d.error){
      document.getElementById('status').textContent='❌ Ошибка: '+d.error;
      clearInterval(pollInterval); return;
    }
    if(!d.total_signals && !d.elapsed_sec){
      document.getElementById('status').textContent='⏳ Идёт загрузка данных...'; return;
    }
    if(d.total_signals){
      clearInterval(pollInterval);
      document.getElementById('runBtn').textContent='✅ Готово — запустить снова';
      document.getElementById('runBtn').classList.remove('running');
      document.getElementById('status').textContent=
        `Завершено за ${d.elapsed_sec}s | Тикеров: ${d.tickers_checked} | Сигналов: ${d.total_signals}`;
      renderResults(d);
    }
  }catch(e){console.error(e)}
}

function renderResults(d){
  document.getElementById('results').style.display='block';

  // Overall stats
  const ov = d.overall||{};
  const t5 = ov['T+5']||{};
  document.getElementById('overall-stats').innerHTML=[
    ['Всего сигналов', d.total_signals],
    ['WR T+5', (t5.win_rate??'—')+'%'],
    ['Avg T+5', (t5.avg_return??'—')+'%'],
    ['Median T+5', (t5.median??'—')+'%'],
    ['Avg Win', (t5.avg_win??'—')+'%'],
    ['Avg Loss', (t5.avg_loss??'—')+'%'],
    ['Best T+5', (t5.best??'—')+'%'],
    ['Worst T+5', (t5.worst??'—')+'%'],
  ].map(([l,v])=>`<div class="stat-box"><div class="stat-label">${l}</div><div class="stat-value">${v}</div></div>`).join('');

  // By state table
  const stateBody = document.getElementById('state-body');
  stateBody.innerHTML='';
  for(const [state, data] of Object.entries(d.by_state||{})){
    const m=data.metrics||{};
    const t1=m['T+1']||{},t3=m['T+3']||{},t5=m['T+5']||{};
    const tr=document.createElement('tr');
    tr.innerHTML=`
      <td><span class="state-badge ${state.toLowerCase()}">${state}</span></td>
      <td>${data.count}</td>
      <td class="${colorRet(t1.avg_return)}">${t1.win_rate??'—'}%</td>
      <td class="${colorRet(t1.avg_return)}">${t1.avg_return??'—'}%</td>
      <td class="${colorRet(t3.avg_return)}">${t3.win_rate??'—'}%</td>
      <td class="${colorRet(t3.avg_return)}">${t3.avg_return??'—'}%</td>
      <td class="${colorRet(t5.avg_return)}">${t5.win_rate??'—'}%</td>
      <td class="${colorRet(t5.avg_return)}">${t5.avg_return??'—'}%</td>
      <td class="pos">${t5.best??'—'}%</td>
      <td class="neg">${t5.worst??'—'}%</td>`;
    stateBody.appendChild(tr);
  }

  // Score correlation bars
  const corr = d.score_correlation||{};
  const maxAvg = Math.max(...Object.values(corr).map(c=>Math.abs(c.avg_return)),0.1);
  document.getElementById('correlation-section').innerHTML=
    '<p style="color:#8b949e;font-size:13px">Чем выше Pressure Score → тем лучше доходность T+5?</p>'+
    Object.entries(corr).map(([bucket,data])=>{
      const barW = Math.max(4, Math.round(Math.abs(data.avg_return)/maxAvg*300));
      const col  = data.avg_return>0?'#3fb950':'#f85149';
      return `<div class="bucket-bar">
        <div class="bucket-label">P: ${bucket}</div>
        <div class="bar" style="width:${barW}px;background:${col}"></div>
        <div class="bar-val">${data.avg_return}% &nbsp; WR ${data.win_rate}% &nbsp; n=${data.count}</div>
      </div>`;
    }).join('');

  // Equity curve
  const eq = d.equity_curve||[];
  if(eq.length && chartInst){ chartInst.destroy(); chartInst=null; }
  if(eq.length){
    const ctx=document.getElementById('equityChart').getContext('2d');
    chartInst=new Chart(ctx,{type:'line',data:{
      labels:eq.map(e=>e.date),
      datasets:[{
        label:'Cumulative avg T+5 return %',
        data:eq.map(e=>e.cumulative),
        borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,0.1)',
        tension:0.3,pointRadius:2,fill:true
      }]
    },options:{plugins:{legend:{labels:{color:'#8b949e'}}},
      scales:{x:{ticks:{color:'#8b949e',maxTicksLimit:10}},
              y:{ticks:{color:'#8b949e'},grid:{color:'#21262d'}}}}});
  }

  // Top signals
  document.getElementById('top-signals').innerHTML=(d.sample_signals||[]).map(s=>`<tr>
    <td><b>${s.ticker}</b></td>
    <td>${s.date}</td>
    <td><span class="state-badge ${s.state.toLowerCase()}">${s.state}</span></td>
    <td>$${s.entry_price}</td>
    <td>${Math.round(s.pressure_score)}</td>
    <td>${Math.round(s.rs_score)}</td>
    <td>${Math.round(s.breakout_score)}</td>
    <td class="${colorRet(s['T+1'])}">${s['T+1']??'—'}%</td>
    <td class="${colorRet(s['T+3'])}">${s['T+3']??'—'}%</td>
    <td class="${colorRet(s['T+5'])}">${s['T+5']??'—'}%</td>
  </tr>`).join('');
}

// Проверяем есть ли уже результаты
checkResults();
</script></body></html>"""

if __name__=="__main__":
    port=int(os.environ.get("PORT",8000))
    print(f"🚀 http://0.0.0.0:{port}")
    uvicorn.run(app,host="0.0.0.0",port=port)
