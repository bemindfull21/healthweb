"""weight_log → data/users/<sha256(tg_user_id)>.json 로 유저별 내보내기.

GitHub Actions(refresh-data.yml)에서 실행. Oracle에 붙어 tg_user_id별로 몸무게 기록을
해시 파일명으로 저장한다. 사이트는 공개(Free repo)라, tg_user_id를 아는 사람만
자기 파일을 찾을 수 있도록 파일명을 해시로 둔다.

필요 env: DB_PASSWORD, DB_WALLET_PASSWORD, DB_WALLET_LOCATION(기본 wallet),
          DB_USER(기본 healthweb), DB_DSN(기본 shindb_low)
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib

import oracledb

WALLET = os.environ.get("DB_WALLET_LOCATION", "wallet")
OUT = pathlib.Path("data/users")

# tg_user_id 로 조회 가능한 것만 (weight 있는 행). raw_text만 있는 폴백 행은 제외.
QUERY = """
    select tg_user_id,
           to_char(log_date, 'YYYY-MM-DD') as d,
           to_char(log_date, 'HH24:MI:SS') as t,
           weight,
           quote
    from admin.weight_log
    where tg_user_id is not null
      and weight is not null
    order by tg_user_id, log_date
"""


def main() -> None:
    conn = oracledb.connect(
        user=os.environ.get("DB_USER", "healthweb"),
        password=os.environ["DB_PASSWORD"],
        dsn=os.environ.get("DB_DSN", "shindb_low"),
        config_dir=WALLET,
        wallet_location=WALLET,
        wallet_password=os.environ["DB_WALLET_PASSWORD"],
    )
    users: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        cur.execute(QUERY)
        for uid, d, t, weight, quote in cur:
            users.setdefault(str(uid), []).append(
                {"date": d, "time": t, "weight": float(weight), "quote": quote}
            )
    conn.close()

    OUT.mkdir(parents=True, exist_ok=True)
    # 기존 파일 제거 → 삭제된(또는 데이터 없어진) 유저 반영
    for f in OUT.glob("*.json"):
        f.unlink()

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for uid, entries in users.items():
        h = hashlib.sha256(uid.encode()).hexdigest()
        payload = {"updated_at": now, "count": len(entries), "entries": entries}
        (OUT / f"{h}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    print(f"내보내기 완료: {len(users)}명, 총 {sum(len(v) for v in users.values())}건")


if __name__ == "__main__":
    main()
