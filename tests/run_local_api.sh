#!/bin/bash
# 로컬 API 기동 — 실제 운영 DB(SHINDB)에 연결됨. 테스트 계정만 만들고 반드시 스스로 정리할 것.
# 사전 준비: tests/.env.example 을 tests/.env 로 복사하고 HEALTHWEB_DB_PASSWORD 등 값을 채운다.
set -a
source "$(dirname "$0")/.env"
set +a

cd "$(dirname "$0")/../api"

export DB_USER=healthweb
export DB_PASSWORD="$HEALTHWEB_DB_PASSWORD"
export DB_DSN=shindb_low
export DB_WALLET_LOCATION='C:\work\_shared\wallets\SHINDB'
export DB_WALLET_PASSWORD="$HEALTHWEB_DB_PASSWORD"
export ALLOW_ORIGIN='*'
export MEDIA_DIR="$(cd "$(dirname "$0")" && pwd)/media"
export MEDIA_BASE_URL='http://127.0.0.1:8971/media'
export WEB_APP_URL='http://127.0.0.1:8080'
# JWT_SECRET, OWNER_LOGIN_ID, TELEGRAM_BOT_TOKEN, INTERNAL_KEY 는 tests/.env 에서 옴

exec ./venv/Scripts/python.exe -m uvicorn app:app --port 8971 --log-level warning
