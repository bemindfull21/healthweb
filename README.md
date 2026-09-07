# health-web

헬스봇(health-bot)에 기록한 몸무게를 그래프로 보는 웹앱. GitHub Pages 정적 사이트.

## 쓰는 법

1. 헬스봇에게 `/whoami` 를 보내 내 텔레그램 User ID 확인
2. 사이트 접속 → User ID + (선택)목표 몸무게 입력
3. 그 ID로 저장된 몸무게 추이·기록을 조회

데이터는 GitHub Actions가 6시간마다 DB에서 가져와 갱신한다.

## 개발/배포

`CLAUDE.md` 참고. 로컬 미리보기는 프로젝트 루트에서:

```
python -m http.server 8080
```

→ http://localhost:8080 (단, `data/users/*.json` 이 있어야 조회됨)
