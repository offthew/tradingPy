import os
from dotenv import load_dotenv
import logging
from time import sleep
import time
import hmac
import hashlib
import requests
import json
import pandas as pd

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)

# Récupération des variables d'environnement
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
API_PASSPHRASE = os.getenv('API_PASSPHRASE')
BASE_URL = os.getenv('BASE_URL')

# Paramètre du levier
LEVERAGE = 10  # Utilisation d'un levier de 10

# Fonctions de connexion et de signature à l'API de Bitget
def sign_request(params, secret, method='GET', path='/api/v1/order'):
    query_string = '&'.join([f"{key}={value}" for key, value in sorted(params.items())])
    payload = query_string if method == 'GET' else json.dumps(params)
    pre_sign = method + path + payload + str(int(time.time() * 1000))  # ajout de timestamp pour la signature
    return hmac.new(secret.encode('utf-8'), pre_sign.encode('utf-8'), hashlib.sha256).hexdigest()

def send_request(endpoint, params, method='GET'):
    headers = {
        'Content-Type': 'application/json',
        'X-BG-APIKEY': API_KEY,
        'X-BG-PASSPHRASE': API_PASSPHRASE,
    }
    params['apiKey'] = API_KEY
    params['timestamp'] = str(int(time.time() * 1000))
    params['sign'] = sign_request(params, API_SECRET, method, endpoint)
    url = f"{BASE_URL}{endpoint}"
    
    if method == 'GET':
        response = requests.get(url, headers=headers, params=params)
    else:
        response = requests.post(url, headers=headers, json=params)
    
    return response.json()

# Fonction pour récupérer les données OHLCV (candles)
def get_ohlcv(symbol, interval='1m', limit=100):
    params = {
        'symbol': symbol,
        'granularity': interval,  # Intervalle
        'size': limit  # Nombre de bougies à récupérer
    }
    endpoint = '/api/v2/market/candles'
    data = send_request(endpoint, params)
    return data['data']

# Fonction pour calculer les EMAs
def calculate_ema(data, period):
    close_prices = [float(candle['close']) for candle in data]
    return pd.Series(close_prices).ewm(span=period).mean().tolist()

# Fonction pour obtenir les données de la time frame supérieure (15m)
def get_higher_timeframe_data(symbol, higher_timeframe="15m", ema_length=55):
    ohlcv = get_ohlcv(symbol, interval=higher_timeframe)
    return calculate_ema(ohlcv, ema_length)

# Fonction pour passer un ordre
def place_order(symbol, side, quantity, price=None, leverage=10):
    params = {
        'symbol': symbol,
        'side': side,
        'type': 'LIMIT' if price else 'MARKET',
        'quantity': quantity,
        'price': price,
        'leverage': leverage
    }
    endpoint = '/api/v1/order'
    data = send_request(endpoint, params, method='POST')
    return data

# Fonction pour dimensionner la quantité d'une position en fonction du risque
def calculate_position_size(capital, stop_loss_price, entry_price, risk_percent=1.0, leverage=10):
    # Calcul du risque par trade
    risk_amount = capital * (risk_percent / 100)
    
    # Calcul de la distance entre le prix d'entrée et le stop-loss
    stop_loss_distance = abs(entry_price - stop_loss_price)
    
    # Calcul de la taille de la position en fonction du risque et de la distance stop-loss
    position_size = risk_amount / stop_loss_distance
    
    # Appliquer le levier : la position est multipliée par le levier
    position_size_with_leverage = position_size * leverage
    return position_size_with_leverage

# Fonction pour exécuter la stratégie de trading
def execute_trade(symbol, **kwargs):
    try:
        ohlcv = get_ohlcv(symbol)
        if not ohlcv:
            logging.error("Impossible de récupérer les données OHLCV")
            return
            
        # Calcul des EMAs sur la time frame actuelle
        ema1 = calculate_ema(ohlcv, kwargs['ema1_length'])
        ema2 = calculate_ema(ohlcv, kwargs['ema2_length'])
        ema3 = calculate_ema(ohlcv, kwargs['ema3_length'])
        
        # Calcul des EMAs de la time frame supérieure (15m)
        ema2_HTF = get_higher_timeframe_data(symbol, higher_timeframe=kwargs['higher_timeframe'], ema_length=kwargs['ema2_length'])
        ema3_HTF = get_higher_timeframe_data(symbol, higher_timeframe=kwargs['higher_timeframe'], ema_length=kwargs['ema3_length'])
        
        # Déterminer la tendance sur la time frame supérieure (15m)
        is_bullish_trend_HTF = ema2_HTF[-1] > ema3_HTF[-1]
        is_bearish_trend_HTF = ema2_HTF[-1] < ema3_HTF[-1]
        
        # Détecter les croisements entre EMA2 et EMA3 sur la période actuelle
        cross2_3_up = ema2[-2] < ema3[-2] and ema2[-1] > ema3[-1]
        cross2_3_down = ema2[-2] > ema3[-2] and ema2[-1] < ema3[-1]
        
        # Condition de long (achat) et short (vente)
        long_entry = cross2_3_up and (ohlcv[-1]['high'] > ema3[-1] or ohlcv[-1]['low'] > ema3[-1])
        short_entry = cross2_3_down and (ohlcv[-1]['high'] < ema3[-1] or ohlcv[-1]['low'] < ema3[-1])
        
        # Filtrage selon la tendance de la time frame supérieure
        if not is_bullish_trend_HTF and long_entry:
            long_entry = False
        if not is_bearish_trend_HTF and short_entry:
            short_entry = False
        
        # Calculer le stop-loss pour chaque position
        long_stop_loss = ohlcv[-1]['close'] * (1 - kwargs['stop_loss_percent'] / 100)
        short_stop_loss = ohlcv[-1]['close'] * (1 + kwargs['stop_loss_percent'] / 100)
        
        # Calculer le take-profit pour chaque position
        long_take_profit = ohlcv[-1]['close'] * (1 + kwargs['take_profit_percent'] / 100)
        short_take_profit = ohlcv[-1]['close'] * (1 - kwargs['take_profit_percent'] / 100)
        
        # Calculer la taille de la position en fonction du capital, du risque et du levier
        entry_price = ohlcv[-1]['close']
        
        if long_entry:
            position_size = calculate_position_size(capital=kwargs['capital'], stop_loss_price=long_stop_loss, entry_price=entry_price, risk_percent=kwargs['risk_percent'], leverage=kwargs['leverage'])
            place_order(symbol, "buy", position_size, leverage=kwargs['leverage'])  # Ajuste la quantité de manière dynamique
            logging.info(f"Long Entry: {symbol} with {position_size} units")
            # Placer le stop-loss
            place_order(symbol, "sell", position_size, price=long_stop_loss, leverage=kwargs['leverage'])  # Stop Loss pour le long

            # **Condition de sortie** : Attendre que EMA1 > EMA2 puis sortir du trade
            while ema1[-1] <= ema2[-1]:  
                sleep(60)  
                ohlcv = get_ohlcv(symbol)  
                ema1 = calculate_ema(ohlcv, kwargs['ema1_length'])
                ema2 = calculate_ema(ohlcv, kwargs['ema2_length'])
            
            # Sortir du trade en market une fois que EMA1 > EMA2
            place_order(symbol, "sell", position_size, leverage=kwargs['leverage'])
            logging.info(f"Exited Long position: {symbol} with {position_size} units")

        if short_entry:
            position_size = calculate_position_size(capital=kwargs['capital'], stop_loss_price=short_stop_loss, entry_price=entry_price, risk_percent=kwargs['risk_percent'], leverage=kwargs['leverage'])
            place_order(symbol, "sell", position_size, leverage=kwargs['leverage'])  # Ajuste la quantité de manière dynamique
            logging.info(f"Short Entry: {symbol} with {position_size} units")
            # Placer le stop-loss
            place_order(symbol, "buy", position_size, price=short_stop_loss, leverage=kwargs['leverage'])  # Stop Loss pour le short

            # **Condition de sortie** : Attendre que EMA1 > EMA2 puis sortir du trade
            while ema1[-1] <= ema2[-1]:  
                sleep(60)  
                ohlcv = get_ohlcv(symbol)  
                ema1 = calculate_ema(ohlcv, kwargs['ema1_length'])
                ema2 = calculate_ema(ohlcv, kwargs['ema2_length'])
            
            # Sortir du trade en market une fois que EMA1 > EMA2
            place_order(symbol, "buy", position_size, leverage=kwargs['leverage'])
            logging.info(f"Exited Short position: {symbol} with {position_size} units")

    except Exception as e:
        logging.error(f"Erreur dans execute_trade: {str(e)}")
        return

# Exemple d'exécution du bot
if __name__ == "__main__":
    from config import TRADING_CONFIG
    
    logging.info("Démarrage du bot de trading")
    
    while True:
        try:
            execute_trade(
                TRADING_CONFIG['SYMBOL'],
                capital=TRADING_CONFIG['CAPITAL'],
                leverage=TRADING_CONFIG['LEVERAGE']
            )
            sleep(60)
        except Exception as e:
            logging.error(f"Erreur principale: {str(e)}")
            sleep(60)
