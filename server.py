#!/usr/bin/env python3
import os
import requests
import threading
import time
import logging
import random
import urllib.parse
from flask import Flask, jsonify

# ----------------------
# Configuração básica
# ----------------------
logging.basicConfig(level=logging.INFO, format='[MINI] %(message)s')
app = Flask(__name__)

GAME_ID = os.environ.get("GAME_ID", "109983668079237")
BASE_URL = f"https://games.roblox.com/v1/games/{GAME_ID}/servers/Public?sortOrder=Asc&limit=100"
MAIN_API_URL = os.environ.get("MAIN_API_URL", "https://main-jobid-production.up.railway.app/add-pool")

SEND_INTERVAL = int(os.environ.get("SEND_INTERVAL", "30"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "10"))

# ----------------------
# Função para normalizar proxies
# ----------------------
def normalize_proxy(raw: str) -> str:
    """
    Aceita:
      - http://user:pass@host:port
      - https://user:pass@host:port
      - host:port:user:pass
      - host:porta:user:senha
      - host:port
    Retorna uma proxy string pronta para usar em requests, ex: http://user:pass@host:port
    """
    raw = raw.strip()
    if not raw:
        return None

    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    parts = raw.split(":")
    if len(parts) >= 4:
        host = parts[0]
        port = parts[1]
        user = parts[2]
        pwd = ":".join(parts[3:])
        user_enc = urllib.parse.quote(user, safe="")
        pwd_enc = urllib.parse.quote(pwd, safe="")
        return f"http://{user_enc}:{pwd_enc}@{host}:{port}"

    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"

    return raw

# ----------------------
# Leitura de proxies via variável de ambiente
# ----------------------
raw_proxies = os.environ.get("PROXIES", "")
PROXIES = [normalize_proxy(p) for p in raw_proxies.split(",") if p.strip()]

if not PROXIES:
    logging.warning("[WARN] Nenhuma proxy configurada — as requisições serão diretas.")
else:
    logging.info(f"[INIT] {len(PROXIES)} proxies carregadas.")

# ----------------------
# Função para coletar servidores Roblox
# ----------------------
def fetch_all_roblox_servers(retries=3):
    all_servers = []
    cursor = None
    page_count = 0
    proxy_index = 0

    while True:
        proxy = random.choice(PROXIES) if PROXIES else None
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            url = BASE_URL + (f"&cursor={cursor}" if cursor else "")
            page_count += 1
            logging.info(f"[FETCH] Página {page_count} via proxy {proxy or 'sem proxy'}...")

            r = requests.get(url, proxies=proxies, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                logging.warning("[429] Too Many Requests — trocando de proxy...")
                time.sleep(1)
                continue

            r.raise_for_status()
            data = r.json()
            servers = data.get("data", [])
            all_servers.extend(servers)
            cursor = data.get("nextPageCursor")

            logging.info(f"[PAGE {page_count}] +{len(servers)} servers (Total: {len(all_servers)})")

            if not cursor:
                logging.info("[INFO] Nenhuma página restante.")
                break

            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            logging.warning(f"[ERRO] Proxy {proxy or 'sem proxy'} falhou: {e}")
            time.sleep(1)
            proxy_index += 1
            if proxy_index >= (len(PROXIES) or 1) * retries:
                break

    return all_servers

# ----------------------
# Loop principal: coleta e envio
# ----------------------
def fetch_and_send():
    while True:
        servers = fetch_all_roblox_servers()
        if not servers:
            logging.warning("⚠️ Nenhum servidor encontrado neste ciclo.")
            time.sleep(SEND_INTERVAL)
            continue

        job_ids = [s["id"] for s in servers if "id" in s]
        payload = {"servers": job_ids}

        try:
            resp = requests.post(MAIN_API_URL, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.ok:
                added = resp.json().get("added", None)
                logging.info(f"✅ Enviados {len(job_ids)} servers — adicionados: {added}")
            else:
                logging.warning(f"⚠️ MAIN retornou {resp.status_code}: {resp.text}")
        except Exception as e:
            logging.exception(f"❌ Erro ao enviar para MAIN: {e}")

        time.sleep(SEND_INTERVAL)

# ----------------------
# Thread em background
# ----------------------
threading.Thread(target=fetch_and_send, daemon=True).start()

# ----------------------
# Endpoint simples
# ----------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "mini API running",
        "proxy_count": len(PROXIES),
        "game_id": GAME_ID,
        "target_api": MAIN_API_URL
    })

# ----------------------
# Main
# ----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    logging.info(f"Mini API rodando na porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
