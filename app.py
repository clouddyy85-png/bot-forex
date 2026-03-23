# -*- coding: utf-8 -*-

from flask import Flask
import requests
import time
import os
import threading
from datetime import datetime, timezone

# ================= VARIÁVEIS =================

API_KEY = os.getenv("API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

ULTIMO_SINAL = {}

app = Flask(__name__)

PAIRS = ["EUR/USD"]
TIMEFRAMES = ["5min", "15min"]

# ================= TELEGRAM =================

def enviar_telegram(mensagem):
    try:
        if not BOT_TOKEN or not CHAT_ID:
            print("Telegram nao configurado")
            return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": mensagem
        }
        requests.post(url, data=payload, timeout=5)

    except Exception as e:
        print("Erro Telegram:", e)

# ================= FILTRO PROFISSIONAL =================

def horario_noticia_forte():
    agora = datetime.now(timezone.utc)
    minutos = agora.hour * 60 + agora.minute

    noticias = [
        13 * 60 + 30,  # 09:30 NY
        15 * 60,       # 11:00 NY
        19 * 60        # 15:00 NY
    ]

    for n in noticias:
        if abs(minutos - n) <= 15:
            print("Bloqueado por noticia forte")
            return True

    return False

# ================= INDICADORES =================

def get_rsi(symbol, interval):
    try:
        url = f"https://api.twelvedata.com/rsi?symbol={symbol}&interval={interval}&apikey={API_KEY}"
        data = requests.get(url, timeout=5).json()
        return float(data["values"][0]["rsi"])
    except:
        return None

def get_ema(symbol, interval, period):
    try:
        url = f"https://api.twelvedata.com/ema?symbol={symbol}&interval={interval}&time_period={period}&apikey={API_KEY}"
        data = requests.get(url, timeout=5).json()
        return float(data["values"][0]["ema"])
    except:
        return None

def get_macd(symbol, interval):
    try:
        url = f"https://api.twelvedata.com/macd?symbol={symbol}&interval={interval}&apikey={API_KEY}"
        data = requests.get(url, timeout=5).json()
        return (
            float(data["values"][0]["macd"]),
            float(data["values"][0]["macd_signal"])
        )
    except:
        return None, None

# ================= SNIPER ENTRY =================

def sniper_entry(preco, rsi, ema9, ema21, macd, macd_signal):
    if None in [preco, rsi, ema9, ema21, macd, macd_signal]:
        return None

    if (40 <= rsi <= 65 and preco > ema9 and ema9 > ema21 and macd > macd_signal):
        return "COMPRA FORTE"

    if (35 <= rsi <= 60 and preco < ema9 and ema9 < ema21 and macd < macd_signal):
        return "VENDA FORTE"

    return None

# ================= ENTRADA / STOP / ALVO =================

def calcular_entrada_stop_alvo(preco, sinal):
    if preco is None:
        return None, None, None

    margem = preco * 0.001

    if sinal == "COMPRA FORTE":
        return round(preco, 5), round(preco - margem, 5), round(preco + margem * 2, 5)

    if sinal == "VENDA FORTE":
        return round(preco, 5), round(preco + margem, 5), round(preco - margem * 2, 5)

    return None, None, None

# ================= TEMPO =================

def definir_tempo_operacao(scores):
    if len(scores) >= 2:
        if (scores[0] > 0 and scores[1] > 0) or (scores[0] < 0 and scores[1] < 0):
            return "15min"
    return "5min"

# ================= ANÁLISE =================

def analisar_multi_timeframe(symbol):
    scores = []
    precos = []

    for tf in TIMEFRAMES:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={tf}&outputsize=20&apikey={API_KEY}"
            data = requests.get(url, timeout=5).json()

            if "values" not in data:
                continue

            closes = [float(c["close"]) for c in data["values"]]

            preco = closes[0]
            antigo = closes[-1]

            variacao = abs(preco - antigo)
            prob = min(variacao * 5000, 100)

            rsi = get_rsi(symbol, tf)
            ema9 = get_ema(symbol, tf, 9)
            ema21 = get_ema(symbol, tf, 21)
            macd, macd_signal = get_macd(symbol, tf)

            sniper = sniper_entry(preco, rsi, ema9, ema21, macd, macd_signal)

            score = prob if preco > antigo else -prob

            if sniper == "COMPRA FORTE":
                score += 30
            elif sniper == "VENDA FORTE":
                score -= 30

            scores.append(score)
            precos.append(preco)

            time.sleep(1)

        except:
            continue

    if not scores:
        return "NEUTRO", 0, None, "5min"

    media = sum(scores) / len(scores)
    prob = round(abs(media), 2)

    if prob >= 70:
        sinal = "COMPRA FORTE" if media > 0 else "VENDA FORTE"
    else:
        sinal = "NEUTRO"

    preco = precos[0] if precos else None
    tempo = definir_tempo_operacao(scores)

    return sinal, prob, preco, tempo

# ================= LOOP =================

def rodar_bot():
    print("BOT ONLINE 24H")

    while True:
        try:
            if horario_noticia_forte():
                time.sleep(300)
                continue

            for pair in PAIRS:
                sinal, prob, preco, tempo = analisar_multi_timeframe(pair)

                entrada, stop, alvo = calcular_entrada_stop_alvo(preco, sinal)

                if sinal in ["COMPRA FORTE", "VENDA FORTE"]:
                    if pair not in ULTIMO_SINAL or ULTIMO_SINAL[pair] != sinal:

                        mensagem = f"{pair} - {sinal}\nProbabilidade: {prob}%\nTempo: {tempo}\nEntrada: {entrada}\nStop: {stop}\nAlvo: {alvo}"

                        enviar_telegram(mensagem)
                        ULTIMO_SINAL[pair] = sinal

            print("Rodando...")
            time.sleep(60)

        except Exception as e:
            print("Erro:", e)
            time.sleep(30)

# ================= WEB =================

@app.route("/")
def home():
    return "BOT ONLINE 24H 🚀"

# ================= START =================

if __name__ == "__main__":
    t = threading.Thread(target=rodar_bot, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)