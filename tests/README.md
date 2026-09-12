# 테스트 스크립트

별도 테스트 DB가 없다 — **운영 Oracle DB(SHINDB)에 직접 붙어서** 테스트 계정을 만들고, 각 스크립트가 끝에 스스로 지운다.
전략·커버리지 상세는 [`../설계문서/08-테스트계획.md`](../설계문서/08-테스트계획.md) 참고.

## 절대 원칙

**실사용자 계정과 그 데이터는 어떤 스크립트도 건드리지 않는다.**
각 스크립트의 `cleanup()`은 항상 해당 스크립트 전용 테스트 login_id만 대상으로 한다.
실사용자 목록은 계속 늘어나므로 테스트 전후 `select login_id, name from healthweb.app_user`로 항상 최신 상태를 직접 확인할 것 — 이 문서의 스냅샷을 믿지 말 것.

## 준비

```bash
cp .env.example .env   # HEALTHWEB_DB_PASSWORD 등 값 채우기 (.env는 git 미추적)
```

## 실행

```bash
# 1) 로컬 API 기동 (운영 DB에 연결됨)
./run_local_api.sh

# 2) 다른 터미널에서 스위트 실행 (Pillow·oracledb 필요 — api/venv 사용)
../api/venv/Scripts/python.exe test_p1.py
```

**스위트 사이에는 반드시 `run_local_api.sh`를 재시작할 것** — 회원가입 레이트리밋(5회/시간)이 인메모리라 이전 실행의 카운트가 남아있다.

## 스위트 목록

| 파일 | 커버 범위 |
|---|---|
| `test_p1.py` | 회원가입/중복확인/로그인/비번재설정, 몸무게 기록+글 공유, 이름 변경, 프로필 조회 |
| `test_p2.py` | 팔로우, 피드 scope, 응원+댓글 알림, 챌린지 생성/참여/체크인/나가기 |
| `test_p3a.py` | 리치 프로필, 글 고정, 검색, 양방향 차단, 공개 챌린지 페이지 |
| `test_p3b.py` | 이미지 업로드/서빙, 아바타, 진행/글 사진, 신고+관리자 큐 |
| `test_push.py` | 텔레그램 연동 코드/1회용/만료/재배정/해제 |
| `test_announce.py` | 관리자 공지 CRUD, 유효기간, 알림 노출 |
| `test_rank.py` | 등급 점수 누적, 승급 알림, **하락 없음**(핵심 불변조건) |
| `test_edit.py` | 글 수정(`PATCH /posts/:id`) 본문/권한/유효성 |
| `test_kind.py` | 글 종류(자랑/도전/성찰/그냥) 검증 + 수정 시 종류 변경 |
| `test_erp.py` | ERP 권한 게이팅, 오너 부여/회수, 영수증 업로드+Gemini 추출(실제 API 호출, 한국어 번역+상품 사진 썸네일 크롭), 저장/목록/합계/삭제+미디어 GC |

## 배포 전 회귀 체크리스트

1. `node --check ../app.js` / `python -m py_compile ../api/app.py`
2. 위 10개 스위트 전부 통과(스위트 사이 재시작)
3. 프론트 UI 변경이 있으면 브라우저로 직접 확인 — 자동화된 프론트 테스트는 없음
4. `select login_id, name from healthweb.app_user`로 테스트 계정이 안 남았는지 최종 확인
