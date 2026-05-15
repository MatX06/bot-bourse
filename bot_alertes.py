"""
Bot d'alertes Telegram — Stratégie "achat en crise par paliers"
Indicateurs : RSI, Bandes de Bollinger, VIX
Adapté pour un ado belge avec compte-titres — cloud (PythonAnywhere)
"""

import os, time, logging, requests
from datetime import datetime
from dotenv import load_dotenv
import yfinance as yf
import pandas as pd

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION — MODIFIE ICI TES PARAMÈTRES
# ══════════════════════════════════════════════════════════════

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "METS_TON_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "METS_TON_CHAT_ID")

# Ton capital total disponible pour investir (en €)
CAPITAL_TOTAL = 10_000

# ─── Liste des actions à surveiller ───
# Format : "TICKER_YAHOO" : { "nom", "prix_reference" (prix avant la crise), "paliers" }
# Les paliers = % de baisse par rapport au prix de référence
# Pour chaque palier : { "baisse_pct", "montant_eur", "label" }

WATCHLIST = {
    "TTE.PA": {
        "nom": "TotalEnergies",
        "prix_reference": 60.0,   # ← Mets ici le prix actuel de l'action
        "paliers": [
            {"baisse_pct": 20, "montant_eur": 1000,  "label": "Bon"},
            {"baisse_pct": 25, "montant_eur": 1000,  "label": "Très bon"},
            {"baisse_pct": 35, "montant_eur": 2500,  "label": "Excellent"},
            {"baisse_pct": 50, "montant_eur": 5500,  "label": "Exceptionnel — tout in !"},
        ]
    },
    "ENGI.PA": {
        "nom": "Engie",
        "prix_reference": 16.0,
        "paliers": [
            {"baisse_pct": 20, "montant_eur": 1000,  "label": "Bon"},
            {"baisse_pct": 30, "montant_eur": 1500,  "label": "Très bon"},
            {"baisse_pct": 40, "montant_eur": 2500,  "label": "Excellent"},
            {"baisse_pct": 55, "montant_eur": 5000,  "label": "Exceptionnel"},
        ]
    },
    "UCB.BR": {
        "nom": "UCB (Bruxelles)",
        "prix_reference": 120.0,
        "paliers": [
            {"baisse_pct": 20, "montant_eur": 1000,  "label": "Bon"},
            {"baisse_pct": 30, "montant_eur": 1500,  "label": "Très bon"},
            {"baisse_pct": 40, "montant_eur": 2500,  "label": "Excellent"},
            {"baisse_pct": 55, "montant_eur": 5000,  "label": "Exceptionnel"},
        ]
    },
    "ABI.BR": {
        "nom": "AB InBev (Bruxelles)",
        "prix_reference": 55.0,
        "paliers": [
            {"baisse_pct": 20, "montant_eur": 1000,  "label": "Bon"},
            {"baisse_pct": 30, "montant_eur": 1500,  "label": "Très bon"},
            {"baisse_pct": 40, "montant_eur": 2500,  "label": "Excellent"},
            {"baisse_pct": 55, "montant_eur": 5000,  "label": "Exceptionnel"},
        ]
    },
    "OR.PA": {
        "nom": "L'Oréal",
        "prix_reference": 350.0,
        "paliers": [
            {"baisse_pct": 20, "montant_eur": 1000,  "label": "Bon"},
            {"baisse_pct": 30, "montant_eur": 1500,  "label": "Très bon"},
            {"baisse_pct": 40, "montant_eur": 2500,  "label": "Excellent"},
            {"baisse_pct": 55, "montant_eur": 5000,  "label": "Exceptionnel"},
        ]
    },
}

# ─── Seuils du VIX (indice de peur du marché) ───
# VIX < 20 = marché calme | 20-30 = tension | > 30 = crise | > 40 = panique
VIX_SEUIL_ATTENTION = 25   # Commence à surveiller
VIX_SEUIL_CRISE     = 35   # Vrai signal de crise = bon moment pour acheter

# ─── Seuils RSI ───
RSI_SURVENTE = 30           # En dessous = action survendue (bon signe pour acheter)

# ─── Vérification toutes les X secondes ───
# PythonAnywhere gratuit = on peut faire toutes les 5 min
CHECK_INTERVAL = 300

# ─── Anti-spam : délai min entre 2 alertes pour la même action (secondes) ───
COOLDOWN = 7200  # 2 heures

# ══════════════════════════════════════════════════════════════
#  INDICATEURS TECHNIQUES
# ══════════════════════════════════════════════════════════════

def get_rsi(prices: pd.Series, period=14) -> float:
    delta = prices.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, min_periods=period).mean()
    rs = gain / loss
    return round(float((100 - 100 / (1 + rs)).iloc[-1]), 1)


def get_bollinger(prices: pd.Series, period=20, std=2.0) -> dict:
    sma   = prices.rolling(period).mean()
    sigma = prices.rolling(period).std()
    return {
        "milieu": round(float(sma.iloc[-1]), 2),
        "haute":  round(float((sma + std * sigma).iloc[-1]), 2),
        "basse":  round(float((sma - std * sigma).iloc[-1]), 2),
    }


def get_vix() -> float | None:
    try:
        df = yf.Ticker("^VIX").history(period="2d", interval="1h")
        if df.empty: return None
        return round(float(df["Close"].iloc[-1]), 1)
    except:
        return None


def get_prix_et_indicateurs(ticker: str) -> dict | None:
    try:
        df = yf.Ticker(ticker).history(period="3mo", interval="1h", auto_adjust=True)
        if df.empty or len(df) < 40:
            return None
        prices = df["Close"]
        prix_actuel = round(float(prices.iloc[-1]), 2)
        prix_hier   = round(float(prices.iloc[-8]), 2) if len(prices) >= 8 else prix_actuel
        return {
            "prix":        prix_actuel,
            "variation_j": round((prix_actuel - prix_hier) / prix_hier * 100, 2),
            "rsi":         get_rsi(prices),
            "bb":          get_bollinger(prices),
        }
    except Exception as e:
        log.error(f"Erreur {ticker}: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  LOGIQUE DE PALIERS
# ══════════════════════════════════════════════════════════════

def calculer_palier_atteint(prix_ref: float, prix_actuel: float, paliers: list) -> dict | None:
    """
    Retourne le palier le plus profond atteint (mais pas encore déclenché).
    """
    baisse_pct = (prix_ref - prix_actuel) / prix_ref * 100
    if baisse_pct <= 0:
        return None  # Pas en baisse

    meilleur = None
    for p in sorted(paliers, key=lambda x: x["baisse_pct"]):
        if baisse_pct >= p["baisse_pct"]:
            meilleur = {**p, "baisse_reelle": round(baisse_pct, 1)}
    return meilleur


# ══════════════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════════════

def envoyer(message: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        log.error(f"Telegram: {e}")
        return False


def formater_alerte(ticker: str, info: dict, palier: dict, vix: float | None, config: dict) -> str:
    bb   = info["bb"]
    sous_bb = info["prix"] < bb["basse"]
    rsi_ok  = info["rsi"] < RSI_SURVENTE

    # Niveau d'urgence selon le palier
    urgence = {1: "💛", 2: "🟠", 3: "🔴", 4: "🚨"}.get(
        sorted([p["baisse_pct"] for p in config["paliers"]]).index(palier["baisse_pct"]) + 1, "💛"
    )

    lignes = [
        f"{urgence} <b>ALERTE ACHAT — {config['nom']} ({ticker})</b>",
        f"",
        f"📉 Prix actuel : <b>{info['prix']} €</b>  ({info['variation_j']:+.1f}% aujourd'hui)",
        f"📌 Prix de référence : {config['prix_reference']} €",
        f"📊 Baisse depuis le sommet : <b>−{palier['baisse_reelle']}%</b>",
        f"",
        f"🎯 Palier atteint : <b>{palier['label']}</b>",
        f"💰 Montant conseillé : <b>{palier['montant_eur']} €</b>",
        f"",
        f"── Indicateurs ──",
        f"  RSI (14) : {info['rsi']}  {'✅ survendu → bon signe !' if rsi_ok else ''}",
        f"  Bande Bollinger basse : {bb['basse']} €  {'✅ prix en-dessous !' if sous_bb else ''}",
        f"  Bande Bollinger haute : {bb['haute']} €",
    ]

    if vix is not None:
        if vix >= VIX_SEUIL_CRISE:
            lignes.append(f"  VIX : {vix} 🚨 PANIQUE sur les marchés — très bon moment !")
        elif vix >= VIX_SEUIL_ATTENTION:
            lignes.append(f"  VIX : {vix} ⚠️ Tension sur les marchés")
        else:
            lignes.append(f"  VIX : {vix} (marché calme — pas de panique)")

    confirmes = sum([rsi_ok, sous_bb, vix is not None and vix >= VIX_SEUIL_CRISE])
    lignes += [
        f"",
        f"⚡ Signaux confirmés : {confirmes}/3",
        f"  (RSI survendu + sous BB basse + VIX en crise = signal maximum)",
        f"",
        f'🔗 <a href="https://finance.yahoo.com/quote/{ticker}">Voir {config["nom"]} sur Yahoo Finance</a>',
        f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
    ]
    return "\n".join(lignes)


def formater_alerte_vix(vix: float) -> str:
    return (
        f"🚨 <b>ALERTE VIX — Panique sur les marchés !</b>\n\n"
        f"Le VIX est à <b>{vix}</b> (seuil de crise = {VIX_SEUIL_CRISE}).\n\n"
        f"C'est souvent le <b>meilleur moment pour acheter</b> selon ta stratégie.\n"
        f"Vérifie tes actions dans la watchlist !\n\n"
        f"📖 VIX > 40 = panique extrême (2008, COVID) = opportunité historique\n"
        f"📖 VIX > 30 = vraie crise = commence à acheter\n"
        f"📖 VIX < 20 = marché calme = attends"
    )


# ══════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════

def run():
    last_alert: dict[str, datetime] = {}
    last_vix_alert: datetime | None = None
    last_heartbeat: datetime | None = None

    log.info("Bot démarré !")
    envoyer(
        f"🤖 <b>Bot d'alertes boursières démarré !</b>\n"
        f"Je surveille {len(WATCHLIST)} actions toutes les {CHECK_INTERVAL//60} min.\n"
        f"Je t'enverrai un message dès qu'un palier d'achat est atteint."
    )

    while True:

        # ── Message "je suis prêt" toutes les 48h ──
        if last_heartbeat is None or (datetime.now() - last_heartbeat).total_seconds() > 60:
            vix_hb = get_vix()
            envoyer(
                f"✅ <b>Hey, je suis prêt !</b>\n\n"
                f"Je surveille tes {len(WATCHLIST)} actions et je n'ai pas dormi.\n"
                f"Aucune alerte d'achat depuis mon dernier message.\n\n"
                f"📊 VIX actuel : {vix_hb if vix_hb else 'indisponible'} "
                f"{'(marché calme)' if vix_hb and vix_hb < 20 else '(tension)' if vix_hb and vix_hb < 35 else '(CRISE !)' if vix_hb else ''}\n"
                f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
            )
            last_heartbeat = datetime.now()

        vix = get_vix()
        log.info(f"VIX = {vix}")

        # Alerte VIX seule (si pas envoyée depuis 4h)
        if vix and vix >= VIX_SEUIL_CRISE:
            if last_vix_alert is None or (datetime.now() - last_vix_alert).seconds > 14400:
                envoyer(formater_alerte_vix(vix))
                last_vix_alert = datetime.now()

        for ticker, config in WATCHLIST.items():
            try:
                info = get_prix_et_indicateurs(ticker)
                if not info:
                    continue

                palier = calculer_palier_atteint(
                    config["prix_reference"], info["prix"], config["paliers"]
                )

                log.info(
                    f"{ticker}: {info['prix']}€  RSI={info['rsi']}  "
                    f"palier={'aucun' if not palier else palier['label']}"
                )

                if not palier:
                    time.sleep(1)
                    continue

                # Anti-spam
                derniere = last_alert.get(ticker)
                if derniere and (datetime.now() - derniere).seconds < COOLDOWN:
                    log.info(f"{ticker}: cooldown actif, alerte ignorée")
                    time.sleep(1)
                    continue

                msg = formater_alerte(ticker, info, palier, vix, config)
                if envoyer(msg):
                    last_alert[ticker] = datetime.now()

                time.sleep(2)

            except Exception as e:
                log.error(f"Erreur inattendue {ticker}: {e}")

        log.info(f"Prochaine vérification dans {CHECK_INTERVAL // 60} min.")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
