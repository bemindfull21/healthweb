"""공용 wallet을 zip → base64 하여 wallet_b64.txt 로 저장.

그 내용을 GitHub Secret `WALLET_ZIP_B64` 에 통째로 붙여넣는다.
(wallet_b64.txt 는 .gitignore 처리됨)

    python scripts/make_wallet_b64.py [WALLET_DIR]

기본 WALLET_DIR = ../_shared/wallets/SHINDB (repo 루트 기준)
"""
import base64
import io
import pathlib
import sys
import zipfile

wallet_dir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "../_shared/wallets/SHINDB")
files = [p for p in wallet_dir.iterdir() if p.is_file() and p.suffix != ".txt"]
if not files:
    sys.exit(f"wallet 파일 없음: {wallet_dir}")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(f, f.name)

out = pathlib.Path("wallet_b64.txt")
out.write_text(base64.b64encode(buf.getvalue()).decode(), encoding="ascii")
print(f"생성: {out} ({out.stat().st_size} bytes, wallet 파일 {len(files)}개)")
print("→ GitHub repo Settings → Secrets and variables → Actions → WALLET_ZIP_B64 에 붙여넣기")
