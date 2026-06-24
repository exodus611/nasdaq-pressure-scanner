import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

def get_alpaca_trading_client():
    """Получение Alpaca Trading клиента"""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("ALPACA_API_KEY и ALPACA_SECRET_KEY не установлены!")
    
    # Используем paper trading (бесплатный)
    return TradingClient(api_key, secret_key, paper=True)

def get_nasdaq_tickers():
    """Загрузка ВСЕХ тикеров NASDAQ через Alpaca Trading API"""
    print("  📡 Попытка загрузки через Alpaca Trading API...")
    
    try:
        client = get_alpaca_trading_client()
        
        # Запрашиваем все активные акции на US биржах
        request = GetAssetsRequest(
            status=AssetStatus.ACTIVE,
            asset_class=AssetClass.US_EQUITY
        )
        
        assets = client.get_all_assets(request)
        
        # Фильтруем только NASDAQ тикеры
        nasdaq_tickers = []
        for asset in assets:
            # Проверяем что это NASDAQ тикер и не special security
            if (asset.exchange and 'NASDAQ' in asset.exchange.upper() and
                asset.tradable and 
                not asset.symbol.startswith('$') and
                not asset.symbol.endswith('W') and
                not asset.symbol.endswith('U') and
                len(asset.symbol) <= 5):  # Обычные тикеры 1-5 символов
                
                nasdaq_tickers.append(asset.symbol)
        
        print(f"  ✅ Alpaca Trading API: {len(nasdaq_tickers)} тикеров NASDAQ")
        
        if len(nasdaq_tickers) > 500:
            return nasdaq_tickers
        else:
            print(f"  ⚠️ Alpaca вернул только {len(nasdaq_tickers)} тикеров (ожидалось 3000+)")
    
    except Exception as e:
        print(f"  ❌ Ошибка Alpaca Trading API: {e}")
    
    return []

def get_all_us_equities():
    """Fallback: Все US equities (NASDAQ + NYSE)"""
    print("  📡 Fallback: Загрузка всех US equities через Alpaca...")
    
    try:
        client = get_alpaca_trading_client()
        
        request = GetAssetsRequest(
            status=AssetStatus.ACTIVE,
            asset_class=AssetClass.US_EQUITY
        )
        
        assets = client.get_all_assets(request)
        
        all_tickers = []
        for asset in assets:
            if (asset.tradable and 
                not asset.symbol.startswith('$') and
                not asset.symbol.endswith('W') and
                not asset.symbol.endswith('U') and
                len(asset.symbol) <= 5):
                
                all_tickers.append(asset.symbol)
        
        print(f"  ✅ Alpaca US Equities: {len(all_tickers)} тикеров")
        return all_tickers
    
    except Exception as e:
        print(f"  ❌ Ошибка загрузки US equities: {e}")
        return []

def get_tickers():
    """Основной метод загрузки тикеров с несколькими стратегиями"""
    print("📦 Загрузка тикеров через Alpaca Trading API...")
    
    # Стратегия 1: Только NASDAQ тикеры
    print("\n🎯 СТРАТЕГИЯ 1: Только NASDAQ тикеры")
    tickers = get_nasdaq_tickers()
    
    if tickers and len(tickers) > 500:
        print(f"✅ Загружено {len(tickers)} тикеров NASDAQ")
        return tickers
    
    # Стратегия 2: Все US equities (NASDAQ + NYSE)
    print("\n🎯 СТРАТЕГИЯ 2: Все US equities (fallback)")
    tickers = get_all_us_equities()
    
    if tickers and len(tickers) > 500:
        print(f"✅ Загружено {len(tickers)} тикеров (NASDAQ + NYSE)")
        return tickers
    
    print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить тикеры!")
    print(f"   Проверь:")
    print(f"   1. ALPACA_API_KEY и ALPACA_SECRET_KEY правильные")
    print(f"   2. Аккаунт Alpaca активен")
    print(f"   3. Есть доступ к Trading API")
    return []
