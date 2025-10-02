# dashboard/utils/recurrente.py
import requests
from django.conf import settings

BASE_URL = "https://app.recurrente.com/api"

def _headers():
    return {
        "X-PUBLIC-KEY": settings.RECURRENTE_PUBLIC_KEY,
        "X-SECRET-KEY": settings.RECURRENTE_SECRET_KEY,
        "Content-Type": "application/json",
    }
def test_auth():
    r = requests.get(f"{BASE_URL}/test", headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

def create_checkout(*, items, success_url, cancel_url, user_id=None, metadata=None, expires_at=None):
    payload = {
        "items": items,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata or {},
    }
    if user_id:
        payload["user_id"] = user_id
    if expires_at:
        payload["expires_at"] = expires_at

    r = requests.post(f"{BASE_URL}/checkouts", json=payload, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        # ✅ Logea TODO para saber qué no le gustó
        try:
            print("\n[RECURRENTE 400 DEBUG]")
            print("Status:", r.status_code)
            print("Response:", r.text)
            print("Payload:", payload)
            print("Headers:", _headers())
            print("[/RECURRENTE 400 DEBUG]\n")
        except Exception:
            pass
        r.raise_for_status()
    return r.json()