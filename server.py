#!/usr/bin/env python3
import os
import requests
import threading
import time
import logging
import random
import urllib.parse
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format='[MINI] %(message)s')
app = Flask(__name__)

# ==============================
# CONFIG
# ==============================

GAME_ID = os.environ.get("GAME_ID", "109983668079237")

# URL base SEM cursor e SEM sortOrder (será aplicado dinamicamente)
BASE_URL = f"https://games.roblox.com/v1/games/{GAME_ID}/servers/Public"

MAIN_API_URL = os.environ.get("MAIN_API_URL", "https://main-jobid-production.up.railway.app/add-pool")

SEND_INTERVAL = int(os.environ.get("SEND_INTERVAL", "30"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "10"))
SEND_MIN_SERVERS = int(os.environ.get("SEND_MIN_SERVERS", "1"))
MAX_PAGES_PER_CYCLE = int(os.environ.get("MAX_PAGES_PER_CYCLE", "20"))

# Filtro de players
MIN_PLAYERS = int(os.environ.get("MIN_PLAYERS", "0"))
MAX_PLAYERS = int(os.environ.get("MAX_PLAYERS", "999"))

# ==============================
# PROXIES
# ==============================

def normalize_proxy(raw: str) -> str:
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


raw_proxies = os.environ.get("PROXIES", "")
PROXIES = [normalize_proxy(p) for p in raw_proxies.split(",") if p.strip()]

if PROXIES:
    logging.info(f"[INIT] {len(PROXIES)} proxies carregadas.")
else:
    logging.warning("[WARN] Nenhuma proxy configurada — requisições diretas.")


# ==============================
# FETCH SERVERS – ULTRA TURBO
# ==============================

def fetch_all_roblox_servers(retries=3):
    all_servers = []
    proxy_fail_count = 0
    page_count = 0

    # vamos coletar tanto Asc quanto Desc (muito mais servidores)
    for order in ["Asc", "Desc"]:

        # chance de iniciar no cursor aleatório
        cursor = None
        if random.random() < 0.75:
            cursor = str(random.randint(10000, 999999))

        while True:
            # Seleciona proxy
            proxy = random.choice(PROXIES) if PROXIES else None
            proxies = {"http": proxy, "https": proxy} if proxy else None

            try:
                # Monta URL
                url = f"{BASE_URL}?sortOrder={order}&limit=100"
                if cursor:
                    url += f"&cursor={cursor}"

                page_count += 1
                logging.info(f"[FETCH] {order} | Página {page_count} via {proxy or 'sem proxy'}")

                r = requests.get(url, proxies=proxies, timeout=REQUEST_TIMEOUT)

                # rate limit
                if r.status_code == 429:
                    logging.warning("[429] Too Many Requests — trocando proxy imediatamente...")
                    continue  # tenta novamente com outra proxy

                r.raise_for_status()
                data = r.json()

                # Coleta
                servers = data.get("data", [])
                all_servers.extend(servers)

                logging.info(f"[PAGE {page_count}] +{len(servers)} servers (Total: {len(all_servers)})")

                cursor = data.get("nextPageCursor")

                # limite atingido
                if not cursor or page_count >= MAX_PAGES_PER_CYCLE:
                    break

                time.sleep(0.2)

            except requests.exceptions.RequestException as e:
                logging.warning(f"[ERRO] Proxy {proxy or 'sem proxy'} falhou: {e}")
                proxy_fail_count += 1

                if proxy_fail_count >= retries * max(1, len(PROXIES)):
                    logging.error("[FATAL] Muitas falhas consecutivas. Abortando ciclo.")
                    break

                continue

    return all_servers


# ==============================
# LOOP PRINCIPAL
# ==============================

def fetch_and_send():
    while True:
        servers = fetch_all_roblox_servers()
        total_servers = len(servers)

        if total_servers == 0:
            logging.warning("⚠️ Nenhum servidor encontrado.")
            time.sleep(SEND_INTERVAL)
            continue

        # FILTRAR JOB IDS POR PLAYERS
        job_ids = [
            s["id"] for s in servers
            if "id" in s and MIN_PLAYERS <= s.get("playing", 0) <= MAX_PLAYERS
        ]

        logging.info(f"[FILTER] {len(job_ids)} servers válidos após filtro ({MIN_PLAYERS}–{MAX_PLAYERS} players)")

        if len(job_ids) < SEND_MIN_SERVERS:
            logging.info(f"[SKIP] Apenas {len(job_ids)} válidos (mínimo: {SEND_MIN_SERVERS}).")
            time.sleep(SEND_INTERVAL)
            continue

        payload = {"servers": job_ids}

        # enviar para main
        try:
            resp = requests.post(MAIN_API_URL, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.ok:
                added = resp.json().get("added", None)
                logging.info(f"✅ Enviados {len(job_ids)} — adicionados: {added}")
            else:
                logging.warning(f"⚠️ MAIN retornou {resp.status_code}: {resp.text}")

        except Exception as e:
            logging.exception(f"❌ Erro ao enviar para MAIN: {e}")

        time.sleep(SEND_INTERVAL)


# thread do coletor rodando em background
threading.Thread(target=fetch_and_send, daemon=True).start()



# ==============================
# ENDPOINT HTTP
# ==============================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "mini API running",
        "proxy_count": len(PROXIES),
        "game_id": GAME_ID,
        "target_api": MAIN_API_URL,
        "send_min_servers": SEND_MIN_SERVERS,
        "max_pages_per_cycle": MAX_PAGES_PER_CYCLE,
        "min_players": MIN_PLAYERS,
        "max_players": MAX_PLAYERS
    })


# ==============================
# RUN SERVER
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    logging.info(f"Mini API rodando na porta {port} | MIN={MIN_PLAYERS} MAX={MAX_PLAYERS}")
    app.run(host="0.0.0.0", port=port, debug=False)
