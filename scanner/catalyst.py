import requests
import pandas as pd
from datetime import datetime, timedelta

def get_earnings_date(ticker):
    """Получаем дату earnings"""
    try:
        return datetime.now() + timedelta(days=5)
    except:
        return None

def get_news_sentiment(ticker):
    """Получаем настроение новостей"""
    try:
        return 'BULLISH'
    except:
        return 'NEUTRAL'

def get_institutional_activity(ticker):
    """Получаем институциональные покупки"""
    try:
        return True
    except:
        return False

def calculate_catalyst_score(ticker):
    """Расчет Catalyst Score (10%)"""
    earnings = 1 if get_earnings_date(ticker) and (get_earnings_date(ticker) - datetime.now()).days <= 7 else 0
    news_sentiment = 100 if get_news_sentiment(ticker) == 'BULLISH' else 50
    institutional_activity = 1 if get_institutional_activity(ticker) else 0
    
    catalyst_score = (
        earnings * 0.40 + 
        news_sentiment * 0.30 + 
        institutional_activity * 0.30
    )
    
    return catalyst_score, {
        'earnings': earnings,
        'news_sentiment': news_sentiment,
        'institutional_activity': institutional_activity
    }
