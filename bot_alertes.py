import os, requests
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print(f"TOKEN = {TOKEN}")
print(f"CHAT_ID = {CHAT_ID}")

r = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": "Test — ça marche !"},
    timeout=10
)

print(f"Status = {r.status_code}")
print(f"Réponse = {r.text}")
