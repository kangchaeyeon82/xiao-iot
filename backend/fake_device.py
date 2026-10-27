"""보드 없이 테스트할 때 쓰는 가짜 ESP32.
사용법: python fake_device.py [백엔드 주소]   (기본 http://127.0.0.1:8000)
"""
import os
import random
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
KEY = os.environ["DEVICE_API_KEY"]

temp = 30.0
while True:
    temp = max(20, min(60, temp + random.uniform(-0.5, 0.5)))
    body = {"temperature": round(temp, 1), "rssi": random.randint(-75, -45)}
    try:
        r = httpx.post(f"{BASE}/device/readings", json=body,
                       headers={"X-Device-Key": KEY}, timeout=15)
        led = r.json().get("led") if r.status_code == 200 else r.text
        print(f"sent {body} -> {r.status_code}, LED={'ON' if led is True else 'OFF' if led is False else led}")
    except Exception as e:
        print("error:", e)
    time.sleep(2)
