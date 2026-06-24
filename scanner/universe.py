import requests
import pandas as pd

def get_nasdaq_tickers():
    """Загрузка тикеров NASDAQ с Nasdaq.com"""
    url = "https://api.nasdaq.com/api/screener/stocks?tableType=traded&exchange=NASDAQ&limit=10000"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json().get('data', {}).get('rows', [])
            return [x['symbol'] for x in data if x.get('symbol')]
    except:
        pass
    
    # Запасной список
    return ['AAPL', 'MSFT', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA', 'AMD', 'INTC', 'PYPL',
            'SQ', 'COIN', 'MARA', 'RIOT', 'PLTR', 'SOFI', 'UPST', 'RIVN', 'LCID', 'NIO',
            'XPEV', 'SNAP', 'PINS', 'UBER', 'LYFT', 'ABNB', 'DASH', 'ROKU', 'ZM', 'NFLX',
            'QCOM', 'AVGO', 'TXN', 'AMAT', 'LRCX', 'KLAC', 'ASML', 'ARM', 'SMCI', 'DELL',
            'PANW', 'CRWD', 'ZS', 'FTNT', 'NOW', 'ADBE', 'CRM', 'ORCL', 'CSCO', 'SOUN',
            'OKLO', 'SMR', 'BBAI', 'AI', 'SHOP', 'SE', 'BABA', 'JD', 'PDD', 'BIDU', 'TSM',
            'BILI', 'IQ', 'TCOM', 'VIPS', 'W', 'ETSY', 'AFRM', 'HOOD', 'RBLX', 'U', 'SNOW',
            'DDOG', 'NET', 'MDB', 'OKTA', 'WDAY', 'TEAM', 'HUBS', 'TTD', 'SPOT', 'SE', 'CPNG']

def get_tickers():
    """Основной метод загрузки тикеров"""
    return get_nasdaq_tickers()
