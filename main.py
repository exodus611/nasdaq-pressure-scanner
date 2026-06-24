#!/usr/bin/env python3
import os
import sys
import json
import time
import datetime
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# Проверяем ключи Alpaca ПЕРЕД запуском
ALPACA_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

print("=" * 70)
print("Проверка ключей...")
print("=" * 70)
print(f"  DEEPSEEK_API_KEY: {'OK' if DEEPSEEK_KEY else 'MISSING'}")
print(f"  ALPACA_API_KEY: {'OK' if ALPACA_KEY else 'MISSING'}")
print(f"  ALPACA_SECRET_KEY: {'OK' if ALPACA_SECRET else 'MISSING'}")

if not ALPACA_KEY or not ALPACA_SECRET:
    print("")
    print("!" * 70)
    print("ОШИБКА: Ключи Alpaca не найдены!")
    print("!" * 70)
    print("")
    print("ЧТО ДЕЛАТЬ:")
    print("1. Зайди в Railway -> твой проект -> Variables")
    print("2. Добавь ДВЕ переменные:")
    print("   - ALPACA_API_KEY = PK... (из https://app.alpaca.markets/)")
    print("   - ALPACA_SECRET_KEY = ... (из того же места)")
    print("3. Нажми Redeploy")
    print("")
    sys.exit(1)

if not DEEPSEEK_KEY:
    print("")
    print("!" * 70)
    print("ОШИБКА: DEEPSEEK_API_KEY не найден!")
    print("!" * 70)
    print("Добавь в Railway Variables: DEEPSEEK_API_KEY")
    sys.exit(1)

print("")
print("Все ключи найдены! Запуск сканера...")
print("")

app = FastAPI(title="NASDAQ Pressure Scanner v8.0")

scan_results = {"timestamp": "", "signals": [], "stats": {}}
scan_lock = threading.Lock()
signal_history = []

def load_signal_history():
    global signal_history
    try:
        if os.path.exists("data/signal_history.json"):
            with open("data/signal_history.json", "r") as f:
                signal_history = json.load(f)
    except:
        signal_history = []

def save_signal_history():
    with open("data/signal_history.json", "w") as f:
        json.dump(signal_history, f, indent=2)

def run_scanner():
    global scan_results
    print("=" * 70)
    print("NASDAQ Pressure Scanner v8.0 - START")
    print("=" * 70)
    
    try:
        from scanner import (
            get_tickers, load_ohlcv, load_market_data,
            calculate_technical_indicators, get_resistance_levels,
            calculate_pressure_score, calculate_rs_score,
            calculate_breakout_score, calculate_catalyst_score,
            determine_state
        )
        
        tickers = get_tickers()
        print(f"Loaded {len(tickers)} tickers")
        
        all_data = load_ohlcv(tickers, days=180)
        market_data = load_market_data()
        
        signals = []
        for i, ticker in enumerate(tickers, 1):
            if i % 50 == 0:
                print(f"Progress: {i}/{len(tickers)}")
            
            if ticker not in all_data:
                continue
            
            df = calculate_technical_indicators(all_data[ticker])
            
            if 'QQQ' not in market_data or 'SPY' not in market_data:
                continue
            
            pressure_score, _ = calculate_pressure_score(df)
            rs_score, _ = calculate_rs_score(df, market_data['QQQ'], market_data['SPY'])
            resistance = get_resistance_levels(df)
            breakout_score, _ = calculate_breakout_score(df, resistance[-1] if resistance else df['High'].max())
            catalyst_score, _ = calculate_catalyst_score(ticker)
            
            state = determine_state(pressure_score, rs_score, breakout_score, catalyst_score)
            
            if state != "NO_SIGNAL":
                signals.append({
                    "ticker": ticker,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "state": state,
                    "pressure_score": round(pressure_score, 2),
                    "rs_score": round(rs_score, 2),
                    "breakout_score": round(breakout_score, 2),
                    "catalyst_score": round(catalyst_score, 2),
                    "price_at_signal": round(df['Close'].iloc[-1], 2)
                })
        
        scan_results = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "signals": signals,
            "stats": {
                "universe_size": len(tickers),
                "loaded": len(all_data),
                "filtered": len(signals)
            }
        }
        
        print(f"Scan completed: {len(signals)} signals found")
        
    except Exception as e:
        print(f"Scanner error: {e}")
        import traceback
        traceback.print_exc()

@app.on_event("startup")
async def startup_event():
    load_signal_history()
    threading.Thread(target=run_scanner, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    try:
        with open("dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "<h1>Dashboard not found</h1>"

@app.get("/api/results")
async def get_results():
    with scan_lock:
        return JSONResponse(content=scan_results)

@app.get("/api/signal_history")
async def get_signal_history():
    with scan_lock:
        return JSONResponse(content=signal_history)

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Dashboard: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
