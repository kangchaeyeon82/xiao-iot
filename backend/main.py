import os
import secrets
import threading
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from supabase import Client, create_client

load_dotenv()                     # 로컬: backend/.env
load_dotenv("/etc/secrets/.env")  # Render: Secret File로 올린 .env

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
DEVICE_API_KEY = os.environ["DEVICE_API_KEY"]
DEVICE_ID = os.getenv("DEVICE_ID", "xiao-01")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
ONLINE_TIMEOUT_SEC = 10

# DB 접근 전용 (RLS 우회). 로그인 세션을 이 클라이언트에 걸면 권한이 바뀌므로
# 회원가입/로그인은 요청마다 anon 클라이언트를 새로 만들어 처리한다.
# FastAPI는 동기 엔드포인트를 여러 스레드에서 돌리는데, 클라이언트 하나를 공유하면
# 동시 요청 중 연결이 끊기는(Server disconnected) 일이 있어 스레드마다 따로 둔다.
_local = threading.local()


def _db(fresh: bool = False) -> Client:
    if fresh or not hasattr(_local, "client"):
        _local.client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _local.client


def run(fn):
    """fn(client) 실행. 연결 오류면 새 클라이언트로 1번 재시도, 그래도 실패하면 503."""
    try:
        return fn(_db())
    except httpx.TransportError:
        try:
            return fn(_db(fresh=True))
        except httpx.TransportError:
            raise HTTPException(503, "데이터베이스 연결 실패. 잠시 후 다시 시도하세요.")


def anon_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


app = FastAPI(title="XIAO ESP32S3 IoT API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 모델 ----------
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LedCommand(BaseModel):
    on: bool


class Reading(BaseModel):
    temperature: float | None = None
    rssi: int | None = None


# ---------- 인증 의존성 ----------
bearer = HTTPBearer(auto_error=False)
device_key_header = APIKeyHeader(name="X-Device-Key", auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    """대시보드용: Authorization: Bearer <access_token>"""
    if cred is None:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        res = run(lambda c: c.auth.get_user(cred.credentials))
    except HTTPException:
        raise  # 503: 연결 문제는 로그아웃시키지 않는다
    except Exception:
        raise HTTPException(401, "토큰이 유효하지 않습니다")
    if not res or not res.user:
        raise HTTPException(401, "토큰이 유효하지 않습니다")
    return res.user


def device_auth(key: str | None = Depends(device_key_header)):
    """ESP32용: X-Device-Key: <DEVICE_API_KEY>"""
    if not key or not secrets.compare_digest(key, DEVICE_API_KEY):
        raise HTTPException(401, "잘못된 장치 키")


def get_state() -> dict:
    rows = run(lambda c: c.table("device_state").select("*").eq("device_id", DEVICE_ID).execute().data)
    if not rows:
        rows = run(lambda c: c.table("device_state").insert({"device_id": DEVICE_ID}).execute().data)
    return rows[0]


def is_online(last_seen: str | None) -> bool:
    if not last_seen:
        return False
    seen = datetime.fromisoformat(last_seen)
    return (datetime.now(timezone.utc) - seen).total_seconds() < ONLINE_TIMEOUT_SEC


# ---------- 공통 ----------
@app.get("/health")
def health():
    return {"ok": True}


# ---------- 회원가입 / 로그인 ----------
AUTH_ERRORS_KO = {
    "Invalid login credentials": "이메일 또는 비밀번호가 올바르지 않습니다",
    "User already registered": "이미 가입된 이메일입니다",
    "Email not confirmed": "이메일 인증이 아직 완료되지 않았습니다",
}


def ko(e: Exception) -> str:
    return AUTH_ERRORS_KO.get(str(e), str(e))


@app.post("/auth/signup")
def signup(body: Credentials):
    try:
        res = anon_client().auth.sign_up({"email": body.email, "password": body.password})
    except Exception as e:
        raise HTTPException(400, ko(e))
    if res.session is None:
        # Supabase에서 이메일 인증(Confirm email)이 켜져 있으면 세션 없이 돌아온다
        return {"message": "가입 완료. 이메일 인증 후 로그인하세요.", "access_token": None}
    return {"message": "가입 완료", "access_token": res.session.access_token}


@app.post("/auth/login")
def login(body: Credentials):
    try:
        res = anon_client().auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except Exception as e:
        raise HTTPException(401, ko(e))
    return {
        "access_token": res.session.access_token,
        "expires_in": res.session.expires_in,
        "email": res.user.email,
    }


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "email": user.email}


# ---------- 대시보드: 센서 / LED ----------
@app.get("/sensors/latest")
def sensors_latest(user=Depends(current_user)):
    rows = run(lambda c: c.table("sensor_readings").select("*").eq("device_id", DEVICE_ID)
               .order("created_at", desc=True).limit(1).execute().data)
    state = get_state()
    return {
        "reading": rows[0] if rows else None,
        "online": is_online(state.get("last_seen")),
        "last_seen": state.get("last_seen"),
    }


@app.get("/sensors/history")
def sensors_history(limit: int = 60, user=Depends(current_user)):
    limit = max(1, min(limit, 500))
    rows = run(lambda c: c.table("sensor_readings").select("*").eq("device_id", DEVICE_ID)
               .order("created_at", desc=True).limit(limit).execute().data)
    return list(reversed(rows))


@app.get("/led")
def led_get(user=Depends(current_user)):
    s = get_state()
    return {"on": s["led"], "updated_at": s["updated_at"]}


@app.post("/led")
def led_set(cmd: LedCommand, user=Depends(current_user)):
    get_state()
    now = datetime.now(timezone.utc).isoformat()
    run(lambda c: c.table("device_state").update({"led": cmd.on, "updated_at": now})
        .eq("device_id", DEVICE_ID).execute())
    return {"on": cmd.on, "updated_at": now}


# ---------- 장치(ESP32) ----------
@app.post("/device/readings", dependencies=[Depends(device_auth)])
def device_post_reading(r: Reading):
    """센서값 저장 + 응답으로 LED 목표 상태 전달 (폴링 1회로 둘 다 처리)"""
    run(lambda c: c.table("sensor_readings").insert(
        {"device_id": DEVICE_ID, "temperature": r.temperature, "rssi": r.rssi}
    ).execute())
    state = get_state()
    run(lambda c: c.table("device_state").update({"last_seen": datetime.now(timezone.utc).isoformat()})
        .eq("device_id", DEVICE_ID).execute())
    return {"led": state["led"]}
