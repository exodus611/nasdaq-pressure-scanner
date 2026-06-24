import os
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient, StockBarsRequest, TimeFrame, DataFeed
from alpaca.data.timeframe import TimeFrameUnit
from ta.volatility import AverageTrueRange
from ta.trend import PSARIndicator

def get_alpaca_client():
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("ALPACA_API_KEY и ALPACA_SECRET_KEY не установлены!")
    return StockHistoricalDataClient(api_key, secret_key)

def load_via_alpaca_iex(tickers, days=180):
    """Загрузка через Alpaca IEX feed (бесплатный план)"""
    client = get_alpaca_client()
    end = datetime.now()
    start = end - timedelta(days=days)
    all_data = {}
    
    feed = DataFeed.IEX
    batch_size = 50
    total_batches = (len(tickers) + batch_size - 1) // batch_size
    
    print(f"  📡 Alpaca IEX: {len(tickers)} тикеров, {total_batches} батчей...")
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        batch_num = i // batch_size + 1
        
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                start=start,
                end=end,
                limit=1000,
                feed=feed
            )
            bars = client.get_stock_bars(request)
            
            loaded_count = 0
            for symbol in batch:
                if symbol in bars and bars[symbol] and len(bars[symbol]) >= 20:
                    df = pd.DataFrame([{
                        'Open': bar.open,
                        'High': bar.high,
                        'Low': bar.low,
                        'Close': bar.close,
                        'Volume': bar.volume,
                        'Date': bar.timestamp
                    } for bar in bars[symbol]])
                    
                    df.set_index('Date', inplace=True)
                    df.sort_index(inplace=True)
                    all_data[symbol] = df
                    loaded_count += 1
            
            if batch_num % 10 == 0 or batch_num == total_batches:
                print(f"    Batch {batch_num}/{total_batches}: {loaded_count}/{len(batch)} тикеров", flush=True)
            
        except Exception as e:
            err_msg = str(e)
            if batch_num % 10 == 0 or batch_num == total_batches:
                print(f"    Batch {batch_num}/{total_batches}: Ошибка - {err_msg[:80]}", flush=True)
    
    return all_data

def load_via_yahoo_fallback(tickers, days=180):
    """Fallback загрузка через Yahoo Finance для тикеров, недоступных на Alpaca IEX"""
    print(f"  📡 Yahoo Finance fallback: {len(tickers)} тикеров...")
    all_data = {}
    
    for i, ticker in enumerate(tickers, 1):
        if i % 50 == 0:
            print(f"    Progress: {i}/{len(tickers)}", flush=True)
        
        try:
            # Загружаем через yfinance
            df = yf.download(ticker, period=f"{days}d", interval="1d", progress=False)
            
            if not df.empty and len(df) >= 20:
                all_data[ticker] = df
            
            # Небольшая задержка чтобы не получить бан
            if i % 10 == 0:
                time.sleep(0.5)
        
        except Exception as e:
            # Пропускаем тикеры с ошибками
            pass
    
    print(f"    ✅ Yahoo Finance загрузил: {len(all_data)} тикеров")
    return all_data

def load_ohlcv(tickers, days=180):
    """Основной метод загрузки с двойной стратегией: Alpaca IEX → Yahoo Finance"""
    print("\n📊 СТРАТЕГИЯ ЗАГРУЗКИ: Alpaca IEX + Yahoo Finance Fallback")
    
    # Шаг 1: Пробуем Alpaca IEX для всех тикеров
    print("\nШАГ 1: Загрузка через Alpaca IEX...")
    alpaca_data = load_via_alpaca_iex(tickers, days)
    print(f"  ✅ Alpaca IEX загрузил: {len(alpaca_data)} тикеров")
    
    # Шаг 2: Определяем какие тикеры не загрузились
    missing_tickers = [t for t in tickers if t not in alpaca_data]
    print(f"  ⚠️ Не загружено через Alpaca: {len(missing_tickers)} тикеров")
    
    # Шаг 3: Fallback на Yahoo Finance для недостающих
    if missing_tickers:
        print(f"\nШАГ 2: Fallback на Yahoo Finance для {len(missing_tickers)} тикеров...")
        yahoo_data = load_via_yahoo_fallback(missing_tickers, days)
        
        # Объединяем данные
        all_data = {**alpaca_data, **yahoo_data}
    else:
        all_data = alpaca_data
    
    print(f"\n✅ ИТОГО ЗАГРУЖЕНО: {len(all_data)} из {len(tickers)} тикеров")
    return all_data

def load_market_data():
    """Загрузка данных QQQ и SPY для расчёта Relative Strength"""
    print("\n📡 Загрузка QQQ, SPY, IWM для расчёта RS...")
    
    # Пробуем Alpaca IEX
    market_data = load_via_alpaca_iex(['QQQ', 'SPY', 'IWM'], days=30)
    
    # Fallback на Yahoo если нужно
    missing = [t for t in ['QQQ', 'SPY', 'IWM'] if t not in market_data]
    if missing:
        yahoo_data = load_via_yahoo_fallback(missing, days=30)
        market_data.update(yahoo_data)
    
    print(f"  ✅ Загружено рыночных данных: {len(market_data)} ETF")
    return market_data

def calculate_technical_indicators(df):
    """Расчет технических индикаторов"""
    if df is None or df.empty or len(df) < 20:
        return df
    
    df = df.copy()
    
    try:
        # ATR
        atr = AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14)
        df['ATR'] = atr.average_true_range()
    except:
        df['ATR'] = 0
    
    try:
        # PSAR
        psar = PSARIndicator(high=df['High'], low=df['Low'], close=df['Close'], step=0.02, max_step=0.2)
        df['PSAR'] = psar.psar()
    except:
        df['PSAR'] = df['Close']
    
    return df

def get_resistance_levels(df, window=20):
    """Определение уровней сопротивления"""
    if df is None or df.empty or len(df) < window:
        return [df['High'].max() * 1.02 if not df.empty else 100]
    
    resistance = []
    for i in range(window, len(df)):
        recent_max = df['High'].iloc[max(0, i-window):i].max()
        if df['High'].iloc[i] >= recent_max * 0.98:
            resistance.append(df['High'].iloc[i])
    
    if not resistance:
        return [df['High'].max() * 1.02]
    
    # Возвращаем последние 5 уникальных уровней
    unique_levels = []
    for level in resistance[-10:]:
        if not unique_levels or abs(level - unique_levels[-1]) / unique_levels[-1] > 0.02:
            unique_levels.append(level)
    
    return unique_levels[-5:] if unique_levels else [df['High'].max() * 1.02]
