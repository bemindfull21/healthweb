"""테스트 스크립트 공용 DB 연결.

자격증명은 절대 하드코딩하지 않는다 — 이 리포는 public이라 커밋되면 그대로 유출된다.
`tests/.env`(git 미추적, `.env.example` 참고해서 직접 만들 것)에서 읽는다.
"""
import os
from pathlib import Path

import oracledb

WALLET_DIR = r"C:\work\_shared\wallets\SHINDB"


def _load_env_file() -> None:
    path = Path(__file__).resolve().parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env_file()


def connect():
    pw = os.environ.get("HEALTHWEB_DB_PASSWORD")
    if not pw:
        raise RuntimeError(
            "HEALTHWEB_DB_PASSWORD가 없습니다 — tests/.env.example을 tests/.env로 복사하고 값을 채우세요."
        )
    return oracledb.connect(
        user="healthweb", password=pw, dsn="shindb_low",
        config_dir=WALLET_DIR, wallet_location=WALLET_DIR, wallet_password=pw,
    )
