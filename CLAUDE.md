# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@../_shared/CLAUDE.md

# health-web

health-bot이 SHINDB `weight_log`에 저장한 몸무게를 조회하는 **정적 웹앱**. GitHub Pages(무료, public repo)로 호스팅.

## 아키텍처 (방식 A: Actions ETL)

브라우저는 Oracle DB에 직접 못 붙으므로(mTLS wallet, 자격증명 노출) GitHub Actions가 중간 ETL을 한다:

```
weight_log ──(6h마다/수동/repository_dispatch)──▶ scripts/export_weights.py
           ──▶ data/users/<sha256(tg_user_id)>.json 커밋 ──▶ GitHub Pages 서빙 ──▶ 정적 SPA가 fetch
```

- **멀티유저**: 사용자가 자기 텔레그램 User ID를 입력 → `sha256(id)` 계산 → `data/users/<hash>.json`만 fetch. User ID + 목표 몸무게는 `localStorage`에만 저장(클라이언트 전용, 서버로 안 감). 목표 몸무게는 차트 기준선.
- **보안**: 사이트는 공개. tg_user_id를 아는 사람만 자기 파일을 찾을 수 있는 수준(해시 파일명). 진짜 접근제어 아님 — 더 민감해지면 Cloudflare Pages + Access 등 검토.

## 파일

| 경로 | 역할 |
|---|---|
| `index.html` / `style.css` / `app.js` | 정적 SPA. Chart.js는 jsDelivr CDN. **빌드 스텝 없음** |
| `scripts/export_weights.py` | Oracle → 유저별 JSON. 자격증명은 env |
| `.github/workflows/refresh-data.yml` | 6시간마다 + `workflow_dispatch` + `repository_dispatch(healthbot-new-weight)` |
| `sql/001_create_healthweb_user.sql` | 읽기 전용 DB 유저 (ADMIN으로 1회 실행) |

## DB 접근

전용 유저 `healthweb` — `grant connect` + `grant select on admin.weight_log` (weight_log는 ADMIN 스키마). synonym 불필요(쿼리에서 `admin.weight_log` 로 한정). wallet은 [[healthbot-autonomous-db]]와 동일(공용 `_shared/wallets/SHINDB`). Actions에는 `WALLET_ZIP_B64` Secret으로 넣는다.

## 배포 (수동 1회 — GitHub 계정 필요)

1. `sql/001` 을 ADMIN으로 실행 → `healthweb` 생성, 비번을 정한다
2. GitHub에 **public** repo `health-web` 생성 → `git remote add origin ...` → push
3. repo **Settings → Secrets and variables → Actions** 에 3개 등록:
   - `DB_PASSWORD` = healthweb 비번
   - `DB_WALLET_PASSWORD` = SHINDB wallet 비번
   - `WALLET_ZIP_B64` = wallet zip을 base64 인코딩한 문자열 (`scripts/`에 만드는 법 주석)
4. **Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)`**
5. **Actions 탭 → "몸무게 데이터 갱신" → Run workflow** (수동 1회) → `data/users/*.json` 생성 확인
6. `https://<user>.github.io/health-web` 접속. 봇 `/whoami`로 User ID 확인 후 입력.

## (선택) 즉시 갱신

health-bot이 몸무게 저장 후 GitHub에 `repository_dispatch`(event_type `healthbot-new-weight`)를 쏘면 6시간 안 기다리고 갱신됨. health-bot에 GitHub PAT(repo 스코프) 필요.

## 실시간 새로고침 (방식 B — `api/`)

정적 JSON(방식 A)은 최대 6시간 지연. `api/`는 VM에서 `admin.weight_log`를 직접 읽어
프론트 **'새로고침' 버튼**에 실시간 응답을 준다. 방식 A는 그대로 두고(빠른 초기 로드·폴백),
버튼만 라이브 API를 친다.

```
브라우저 ─https─▶ Caddy(healthweb.duckdns.org, TLS 종단) ─▶ 127.0.0.1:8000 uvicorn
        ─▶ oracledb thin + /opt/health-bot/wallet ─▶ ADB
```

- `api/app.py` — FastAPI. `GET /weights?uid=<tg_user_id>` → `data/users/<hash>.json` 과 동일 형태. `:uid` 바인드 고정, uid `^\d{3,}$` 검증, IP당 20 req/min, CORS는 `ALLOW_ORIGIN`만.
- DB는 기존 `healthweb` 유저·기존 wallet 재사용 (wallet은 DB 단위라 유저 무관).
- `api/README.md` 에 로컬 테스트·VM 배포 절차. 서비스 유닛 `api/healthweb-api.service`, 프록시 `api/Caddyfile`.
- 프론트: `app.js` 의 `LIVE_API = "https://healthweb21.duckdns.org"` → 버튼 노출. 빈 문자열이면 숨김.
- 실패 시(API·Caddy 다운) 프론트는 배너만 띄우고 커밋된 JSON 데이터를 유지.

### VM 배포 상태 (2026-09-07 완료)

- VM: `memo-agent` (Oracle Linux 9.8, Singapore). 소스 `/opt/health-web-api/`, venv 로컬.
- **`healthweb-api.service`** — `uvicorn app:app --host 127.0.0.1 --port 8000`. `.env`(chmod 600)에 `healthweb`/wallet 자격증명. `healthweb` 유저 + `/opt/health-bot/wallet` 재사용.
- **`caddy.service`** — `/etc/caddy/Caddyfile`, `healthweb21.duckdns.org` → `127.0.0.1:8000`. LE 인증서 tls-alpn-01 자동 발급/갱신.
- 방화벽: firewalld `public` 존에 `http`·`https` 추가 (OCI Security List Ingress 80·443은 콘솔에서 별도 추가됨).
- DuckDNS: `healthweb21` → VM 공용 IP. 갱신 스크립트 `/opt/health-web-api/duck/duck.sh` + cron `*/5`.
- 재배포: `scp api/app.py opc@168.107.89.8:/opt/health-web-api/ && ssh ... 'sudo systemctl restart healthweb-api'`. Caddyfile 바꾸면 `sudo cp` 후 `sudo systemctl reload caddy`.
