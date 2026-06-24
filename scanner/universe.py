import requests
import pandas as pd
import time

def get_nasdaq_tickers():
    """Загрузка ВСЕХ тикеров NASDAQ с Nasdaq.com API"""
    url = "https://api.nasdaq.com/api/screener/stocks?tableType=traded&exchange=NASDAQ&limit=10000"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nasdaq.com/',
        'Origin': 'https://www.nasdaq.com',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin'
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"  📡 Попытка {attempt + 1}/{max_retries} загрузки с Nasdaq.com API...")
            r = requests.get(url, headers=headers, timeout=30)
            print(f"  📡 Status: {r.status_code}")
            
            if r.status_code == 200:
                data = r.json()
                rows = data.get('data', {}).get('rows', [])
                
                if rows:
                    # Фильтруем только реальные тикеры (без $, warrants, units)
                    tickers = []
                    for row in rows:
                        symbol = row.get('symbol', '')
                        # Пропускаем специальные символы
                        if symbol and not symbol.startswith('$') and not symbol.endswith('W') and not symbol.endswith('U'):
                            tickers.append(symbol)
                    
                    print(f"  ✅ Nasdaq.com API: {len(tickers)} тикеров")
                    
                    if len(tickers) > 500:
                        return tickers
                else:
                    print(f"  ⚠️ API вернул пустой список")
            else:
                print(f"  ⚠️ HTTP ошибка: {r.status_code}")
        
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️ Ошибка сети: {e}")
        except Exception as e:
            print(f"  ⚠️ Неожиданная ошибка: {e}")
        
        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 5
            print(f"  ⏱️ Ждём {wait_time} секунд перед следующей попыткой...")
            time.sleep(wait_time)
    
    print("  ❌ Не удалось загрузить тикеры после всех попыток")
    return []

def get_tickers():
    """Основной метод загрузки тикеров"""
    print("📦 Загрузка ВСЕХ тикеров NASDAQ...")
    tickers = get_nasdaq_tickers()
    
    if tickers and len(tickers) > 500:
        print(f"✅ Загружено {len(tickers)} тикеров с Nasdaq.com")
        return tickers
    
    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить тикеры!")
    print(f"   Возможные причины:")
    print(f"   1. Railway IP заблокирован Nasdaq.com")
    print(f"   2. Изменилась структура API")
    print(f"   3. Проблема с сетью")
    print(f"")
    print(f"   РЕШЕНИЕ: Используй локальный запуск или другой хостинг")
    return []
