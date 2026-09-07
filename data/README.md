# data/users/

`<sha256(tg_user_id)>.json` 파일들. GitHub Actions(`.github/workflows/refresh-data.yml`)가
`scripts/export_weights.py`로 생성·커밋한다. 직접 편집하지 않는다.

## 파일 구조

```json
{
  "updated_at": "2026-09-07T11:02:16Z",
  "count": 3,
  "entries": [
    { "date": "2026-09-06", "time": "14:03:47", "weight": 72.3, "quote": "..." }
  ]
}
```

- `weight_log`에서 `tg_user_id`·`weight`가 **둘 다 있는** 행만 (raw_text만 있는 폴백 행 제외).
- 파일에는 `tg_user_id`·`username`을 담지 않는다. 조회는 파일명 해시로만.
- 사이트가 공개(Free/public repo)라, tg_user_id를 아는 사람만 자기 파일을 찾을 수 있는 수준의 보호다.
