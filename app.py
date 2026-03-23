from flask import Flask
import requests
import time
import os
import threading

# 🔐 VARIÁVEIS DO RENDER
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
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": mensagem
        }
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print("Erro Telegram:", e)

# ================= FILTRO DE NOTÍCIA =================

def tem_noticia_forte():
    try:
        url = f"https://api.twelvedata.com/economic_calendar?apikey={API_KEY}"
        data = requests.get(url, timeout=5).json()

        if "data" not in data:
            return False

        for evento in data["data"]:
            impacto = evento.get("importance", "")
            moeda = evento.get("currency", "")

            # 🔥 FILTRO: só moedas importantes
            if impacto == "high" and moeda in ["USD", "EUR"]:
                return True

        return False

    except:
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

# ================= ENTRADA / STOP / ALVO =================

def calcular_entrada_stop_alvo(preco, sinal):
    try:
        if preco is None:
            return None, None, None

        margem = preco * 0.001

        if sinal == "COMPRA FORTE":
            entrada = preco
            stop = preco - margem
            alvo = preco + (margem * 2)

        elif sinal == "VENDA FORTE":
            entrada = preco
            stop = preco + margem
            alvo = preco - (margem * 2)

        else:
            return None, None, None

        return round(entrada, 5), round(stop, 5), round(alvo, 5)

    except:
        return None, None, None

# ================= TEMPO =================

def definir_tempo_operacao(scores):
    try:
        if len(scores) >= 2:
            if scores[0] > 0 and scores[1] > 0:
                return "15min"
            elif scores[0] < 0 and scores[1] < 0:
                return "15min"
            else:
                return "5min"
        return "5min"
    except:
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

            preco_atual = closes[0]
            preco_antigo = closes[-1]

            variacao = abs(preco_atual - preco_antigo)
            prob = min(variacao * 5000, 100)

            rsi = get_rsi(symbol, tf)
            ema9 = get_ema(symbol, tf, 9)
            ema21 = get_ema(symbol, tf, 21)
            macd, macd_signal = get_macd(symbol, tf)

            score = 0

            score += prob if preco_atual > preco_antigo else -prob

            if rsi is not None:
                if rsi < 30:
                    score += 10
                elif rsi > 70:
                    score -= 10

            if ema9 and ema21:
                score += 15 if ema9 > ema21 else -15

            if macd and macd_signal:
                score += 10 if macd > macd_signal else -10

            scores.append(score)
            precos.append(preco_atual)

            time.sleep(1)

        except:
            continue

    if not scores:
        return "NEUTRO", 0, None, "5min"

    media = sum(scores) / len(scores)
    prob_final = round(abs(media), 2)

    if prob_final >= 70:
        sinal = "COMPRA FORTE" if media > 0 else "VENDA FORTE"
    else:
        sinal = "NEUTRO"

    preco = precos[0] if precos else None
    tempo = definir_tempo_operacao(scores)

    return sinal, prob_final, preco, tempo

# ================= LOOP =================

def rodar_bot():
    print("🤖 BOT ONLINE 24H...")

    while True:
        try:
            # 🔥 FILTRO DE NOTÍCIA
            if tem_noticia_forte():
                print("⚠️ Notícia forte detectada - pausado")
                time.sleep(300)
                continue

            for pair in PAIRS:
                sinal, prob, preco, tempo = analisar_multi_timeframe(pair)

                entrada, stop, alvo = calcular_entrada_stop_alvo(preco, sinal)

                if sinal in ["COMPRA FORTE", "VENDA FORTE"]:
                    if pair not in ULTIMO_SINAL or ULTIMO_SINAL[pair] != sinal:

                        mensagem = f"""
{pair} - {sinal}

Probabilidade: {prob}%
Tempo: {tempo}
Entrada: {entrada}
Stop: {stop}
Alvo: {alvo}
"""

                        enviar_telegram(mensagem)
                        ULTIMO_SINAL[pair] = sinal

            print("✔️ Rodando...")

            time.sleep(60)

        except Exception as e:
            print("Erro geral:", e)
            time.sleep(30)

# ================= WEB (RENDER) =================

@app.route("/")
def home():
    return "BOT ONLINE 24H 🚀"

# ================= START =================

if __name__ == "__main__":
    t = threading.Thread(target=rodar_bot)
    t.start()

    app.run(host="0.0.0.0", port=10000)