import requests
import pandas as pd
import time

# Запасной список из 200+ ликвидных NASDAQ тикеров
FALLBACK_TICKERS = [
    # Mega-cap tech
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'COST',
    'NFLX', 'ADBE', 'PEP', 'CSCO', 'LIN', 'TMUS', 'INTC', 'CMCSA', 'AMD', 'TXN',
    'AMGN', 'QCOM', 'HON', 'AMAT', 'BKNG', 'SBUX', 'ISRG', 'VRTX', 'ADP', 'MDLZ',
    'GILD', 'ADI', 'REGN', 'PYPL', 'LRCX', 'MU', 'MELI', 'KLAC', 'SNPS', 'CDNS',
    'PANW', 'ASML', 'CHTR', 'MAR', 'MRVL', 'ORLY', 'CSX', 'PCAR', 'NXPI', 'ABNB',
    'WDAY', 'CRWD', 'ROP', 'MNST', 'ADSK', 'FTNT', 'CPRT', 'PAYX', 'BKR', 'ROST',
    'ODFL', 'KDP', 'AZN', 'EXC', 'FAST', 'CTAS', 'EA', 'IDXX', 'AEP', 'VRSK',
    'CTSH', 'KHC', 'BIIB', 'DDOG', 'GEHC', 'TTD', 'DXCM', 'ILMN', 'ZS', 'LULU',
    'TEAM', 'FANG', 'ANSS', 'CDW', 'ON', 'GFS', 'MRNA', 'XEL', 'CSGP', 'CCEP',
    'DLTR', 'WBD', 'SPLK', 'SIRI', 'ZM', 'JD', 'LCID', 'GRAB', 'ETSY', 'DOCU',
    'RIVN', 'OKTA', 'SNOW', 'NET', 'MDB', 'HUBS', 'PLTR', 'CRWD', 'COIN', 'RBLX',
    'SOFI', 'HOOD', 'U', 'SHOP', 'SQ', 'PINS', 'SNAP', 'UBER', 'LYFT', 'DASH',
    'SE', 'BABA', 'PDD', 'BIDU', 'TSM', 'BILI', 'IQ', 'TCOM', 'VIPS', 'W',
    # Semiconductor & AI
    'ARM', 'SMCI', 'DELL', 'WOLF', 'ON', 'MPWR', 'SWKS', 'QRVO', 'MCHP', 'TER',
    'ENTG', 'MKSI', 'CGNX', 'PTC', 'IPGP', 'AEHR', 'IIPR', 'POWI', 'ACMR',
    # Biotech & Healthcare
    'MRNA', 'BNTX', 'PFE', 'JNJ', 'LLY', 'ABBV', 'TMO', 'DHR', 'BMY', 'AMGN',
    'MDT', 'ISRG', 'GILD', 'VRTX', 'REGN', 'ZTS', 'BDX', 'CI', 'BSX', 'EW',
    'A', 'DXCM', 'IDXX', 'ILMN', 'ALGN', 'RMD', 'PODD', 'TECH', 'HOLX', 'INCY',
    # EV & Energy
    'TSLA', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'FSR', 'CHPT', 'BLNK', 'PLUG',
    'FCEL', 'BE', 'ENPH', 'SEDG', 'FSLR', 'RUN', 'NEE', 'AES', 'ORA',
    # FinTech & Crypto
    'SQ', 'PYPL', 'COIN', 'HOOD', 'SOFI', 'AFRM', 'UPST', 'MELI', 'MARA', 'RIOT',
    'HUT', 'BIT', 'CLSK', 'IREN', 'WULF', 'CIFR', 'BTBT',
    # Software & Cloud
    'CRM', 'ORCL', 'ADBE', 'INTU', 'NOW', 'WDAY', 'TEAM', 'HUBS', 'SNOW', 'DDOG',
    'NET', 'MDB', 'OKTA', 'ZS', 'PANW', 'CRWD', 'FTNT', 'TTD', 'SHOP', 'GDDY',
    'GTLB', 'BILL', 'MNDY', 'CFLT', 'S', 'PATH', 'BILL',
    # Consumer & Retail
    'AMZN', 'BKNG', 'ABNB', 'EBAY', 'ETSY', 'W', 'MELI', 'SE', 'PDD', 'JD',
    'CPNG', 'DLTR', 'ORLY', 'ROST', 'TJX', 'LULU', 'DECK', 'BIRK', 'ONON',
    # Other high-growth
    'PLTR', 'SOUN', 'SMCI', 'RKLB', 'LUNR', 'ASTS', 'IONQ', 'RGTI', 'QBTS',
    'OKLO', 'SMR', 'NNE', 'BWXT', 'CCJ', 'UUUU', 'DNN', 'LEU',
    'BBAI', 'AI', 'BIGC', 'BILL', 'BILL', 'PATH', 'PATH',
    'RBLX', 'U', 'SNAP', 'PINS', 'DASH', 'UBER', 'LYFT', 'GRAB',
    'TTD', 'ROKU', 'SPOT', 'NFLX', 'DIS', 'PARA', 'WBD'
]

def get_nasdaq_tickers():
    """Загрузка тикеров NASDAQ с Nasdaq.com"""
    url = "https://api.nasdaq.com/api/screener/stocks?tableType=traded&exchange=NASDAQ&limit=10000"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nasdaq.com/',
        'Origin': 'https://www.nasdaq.com'
    }
    
    try:
        print("  📡 Попытка загрузки с Nasdaq.com API...")
        r = requests.get(url, headers=headers, timeout=20)
        print(f"  📡 Status: {r.status_code}")
        
        if r.status_code == 200:
            data = r.json().get('data', {}).get('rows', [])
            tickers = [x['symbol'] for x in data if x.get('symbol') and not x['symbol'].startswith('$')]
            print(f"  ✅ Nasdaq.com API: {len(tickers)} тикеров")
            if len(tickers) > 100:
                return tickers
    except Exception as e:
        print(f"  ⚠️ Nasdaq.com API error: {e}")
    
    return None

def get_tickers():
    """Основной метод загрузки тикеров с fallback"""
    print("📦 Загрузка тикеров...")
    
    # Пробуем основной источник
    tickers = get_nasdaq_tickers()
    
    if tickers and len(tickers) > 100:
        print(f"✅ Загружено {len(tickers)} тикеров с Nasdaq.com")
        return tickers
    
    # Fallback на встроенный список
    print(f"⚠️ Используем fallback список из {len(FALLBACK_TICKERS)} тикеров")
    # Убираем дубликаты
    return list(set(FALLBACK_TICKERS))
