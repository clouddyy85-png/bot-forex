import MetaTrader5 as mt5
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
import time
import os

# ================= CONFIG =================
symbol = "EURUSD"
lot = 0.01
timeframe = mt5.TIMEFRAME_M5

stop_loss = 100
take_profit = 200

# 💰 gestão diária
DAILY_TARGET = 50
DAILY_LOSS = -5

# 📰 notícias
NEWS_BEFORE = 30
NEWS_AFTER = 30
CACHE_MINUTES = 30
CURRENCIES = ["EUR", "USD"]

# 📲 TELEGRAM (Render)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# cache
news_cache = []
last_news_update = None

# ==========================================

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except:
        print("Erro Telegram")

# conectar
if not mt5.initialize():
    print("Erro ao conectar")
    send_telegram("❌ Erro ao conectar MT5")
    quit()

if not mt5.symbol_select(symbol, True):
    print("Erro ao selecionar par")
    send_telegram("❌ Erro ao selecionar ativo")
    mt5.shutdown()
    quit()


# ================= NOTÍCIAS =================
def get_news():
    global news_cache, last_news_update

    now = datetime.now(timezone.utc)

    if last_news_update and (now - last_news_update) < timedelta(minutes=CACHE_MINUTES):
        return news_cache

    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            news_cache = response.json()
            last_news_update = now
            print("✅ Notícias atualizadas")
            return news_cache

        elif response.status_code == 429:
            print("🚫 Bloqueado (429)")
            return news_cache if news_cache else None

    except Exception as e:
        print("Erro notícias:", e)

    if news_cache:
        return news_cache

    print("🚨 Sem notícias")
    return None


def is_news_time():
    news = get_news()

    if news is None:
        send_telegram("🚨 Sem notícias - bot pausado")
        return True

    now = datetime.now(timezone.utc)

    for event in news:
        if event.get('impact') == 'High':
            try:
                if event.get('currency') not in CURRENCIES:
                    continue

                event_time = datetime.fromisoformat(event['date'])

                if (event_time - timedelta(minutes=NEWS_BEFORE)) <= now <= (event_time + timedelta(minutes=NEWS_AFTER)):
                    print("⛔ Notícia forte")
                    send_telegram("⛔ Pausado por notícia forte")
                    return True
            except:
                continue

    return False


# ================= LUCRO =================
def get_daily_profit():
    today = datetime.now(timezone.utc).date()

    deals = mt5.history_deals_get(
        datetime(today.year, today.month, today.day),
        datetime.now(timezone.utc)
    )

    if deals is None:
        return 0

    return sum(d.profit for d in deals)


def reached_daily_limit():
    profit = get_daily_profit()

    print(f"💰 Lucro: {profit:.2f}")

    if profit >= DAILY_TARGET:
        send_telegram("🎯 Meta diária atingida")
        return True

    if profit <= DAILY_LOSS:
        send_telegram("🛑 Loss diário atingido")
        return True

    return False


# ================= SPREAD =================
def spread_ok():
    tick = mt5.symbol_info_tick(symbol)
    point = mt5.symbol_info(symbol).point
    spread = (tick.ask - tick.bid) / point

    if spread > 20:
        print("Spread alto")
        return False

    return True


# ================= DADOS =================
def get_data(tf):
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 100)
    return pd.DataFrame(rates)


def calculate_indicators(df):
    df['ma'] = df['close'].rolling(50).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    exp1 = df['close'].ewm(span=12).mean()
    exp2 = df['close'].ewm(span=26).mean()
    df['macd'] = exp1 - exp2
    df['signal'] = df['macd'].ewm(span=9).mean()

    return df


# ================= TREND =================
def get_trend_m15():
    df = get_data(mt5.TIMEFRAME_M15)
    ma = df['close'].rolling(50).mean()
    return "up" if df.iloc[-1]['close'] > ma.iloc[-1] else "down"


# ================= POSIÇÕES =================
def has_position():
    pos = mt5.positions_get(symbol=symbol)
    return pos and len(pos) > 0


# ================= MODIFY =================
def modify_sl(ticket, sl):
    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": sl})


def modify_sl_tp(ticket, sl, tp):
    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": sl, "tp": tp})


# ================= PROTEÇÃO =================
def break_even():
    pos = mt5.positions_get(symbol=symbol)
    if not pos:
        return

    for p in pos:
        tick = mt5.symbol_info_tick(symbol)
        point = mt5.symbol_info(symbol).point

        if p.type == mt5.ORDER_TYPE_BUY:
            profit = (tick.bid - p.price_open) / point
            if profit > 30 and p.sl < p.price_open:
                send_telegram("🔒 Break Even")
                modify_sl(p.ticket, p.price_open)

        else:
            profit = (p.price_open - tick.ask) / point
            if profit > 30:
                send_telegram("🔒 Break Even")
                modify_sl(p.ticket, p.price_open)


def trailing_stop():
    pos = mt5.positions_get(symbol=symbol)
    if not pos:
        return

    for p in pos:
        tick = mt5.symbol_info_tick(symbol)
        point = mt5.symbol_info(symbol).point

        if p.type == mt5.ORDER_TYPE_BUY:
            profit = (tick.bid - p.price_open) / point
            if profit > 50:
                send_telegram("📈 Trailing Stop")
                modify_sl(p.ticket, tick.bid - 30 * point)

        else:
            profit = (p.price_open - tick.ask) / point
            if profit > 50:
                send_telegram("📉 Trailing Stop")
                modify_sl(p.ticket, tick.ask + 30 * point)


# ================= ORDEM =================
def send_order(type_):
    tick = mt5.symbol_info_tick(symbol)
    point = mt5.symbol_info(symbol).point

    if type_ == "buy":
        price = tick.ask
        sl = price - stop_loss * point
        tp = price + take_profit * point
        order = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + stop_loss * point
        tp = price - take_profit * point
        order = mt5.ORDER_TYPE_SELL

    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order,
        "price": price,
        "deviation": 10,
        "magic": 123456,
        "comment": "BOT PRO",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    })

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        send_telegram(f"📊 Ordem {type_} executada")
        modify_sl_tp(result.order, sl, tp)


# ================= ESTRATÉGIA =================
def strategy():
    if not spread_ok():
        return

    trend = get_trend_m15()
    df = calculate_indicators(get_data(timeframe))

    last = df.iloc[-2]
    prev = df.iloc[-3]

    macd_up = prev['macd'] < prev['signal'] and last['macd'] > last['signal']
    macd_down = prev['macd'] > prev['signal'] and last['macd'] < last['signal']

    if last['close'] > last['ma'] and trend == "up":
        if 30 < last['rsi'] < 45 and macd_up:
            send_telegram("📈 Sinal de COMPRA")
            send_order("buy")

    elif last['close'] < last['ma'] and trend == "down":
        if 55 < last['rsi'] < 70 and macd_down:
            send_telegram("📉 Sinal de VENDA")
            send_order("sell")


# ================= LOOP =================
while True:

    if reached_daily_limit():
        print("⛔ Parado por meta/loss")
        time.sleep(300)
        continue

    if is_news_time():
        print("⛔ Pausado por notícia")
    else:
        trailing_stop()
        break_even()

        if not has_position():
            strategy()
        else:
            print("Gerenciando posição...")

    time.sleep(60)