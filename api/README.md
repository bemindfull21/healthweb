# health-web read API (방식 B)

`admin.weight_log` 를 읽어 프론트 '새로고침' 버튼에 실시간 JSON을 주는 최소 API.
커밋된 `data/users/<hash>.json` 과 응답 형태가 동일하므로 프론트는 같은 렌더 경로를 쓴다.

```
브라우저(Pages) ─https─▶ Caddy(healthweb.duckdns.org) ─▶ 127.0.0.1:8000 (uvicorn) ─▶ oracledb + /opt/health-bot/wallet ─▶ ADB
```

## 엔드포인트

| | |
|---|---|
| `GET /healthz` | `{"ok": true}` |
| `GET /weights?uid=<tg_user_id>` | `{updated_at, count, entries:[{date,time,weight,quote}]}` · uid 형식 `^\d{3,}$` · IP당 20 req/min |

## 로컬 테스트

```
cd api && python -m venv venv && venv/Scripts/pip install -r requirements.txt
# .env.example 참고해 env 설정 (로컬 wallet: C:\Users\bemin\Oracle\SHINDB)
venv/Scripts/uvicorn app:app --port 8000
curl "http://localhost:8000/weights?uid=8974917114"
```

## VM 배포

1. `scp -i ../ssh-key-2026-08-08.key -r ./* opc@168.107.89.8:/opt/health-web-api/`
2. VM: `cd /opt/health-web-api && python3 -m venv venv && venv/bin/pip install -r requirements.txt`
3. `/opt/health-web-api/.env` 작성 (`.env.example` 참고, `chmod 600`) — `DB_PASSWORD`=healthweb 비번, `DB_WALLET_PASSWORD`=wallet 비번
4. `sudo cp healthweb-api.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now healthweb-api`
5. `curl http://127.0.0.1:8000/healthz`
6. 방화벽 80/443: OCI Security List Ingress + VM iptables (README of project CLAUDE.md 참고)
7. DuckDNS 서브도메인 → `168.107.89.8`
8. Caddy 설치 → `sudo cp Caddyfile /etc/caddy/Caddyfile && sudo systemctl enable --now caddy`
9. `curl https://healthweb.duckdns.org/weights?uid=<id>`

## 프론트 연동

`app.js` 상단 `LIVE_API` 상수에 `https://healthweb.duckdns.org` 지정. 빈 문자열이면 버튼 숨김.
