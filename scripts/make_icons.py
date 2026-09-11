"""홈 화면 아이콘 생성 — 초록/로즈 대각 분할 사각형 + 흰색 M.

실행: api/venv 의 python으로 (Pillow 있음) — 이 파일 기준 상위 폴더에 PNG 3장 저장.
    ../api/venv/Scripts/python.exe scripts/make_icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent

GREEN = (47, 107, 79, 255)   # --accent / weight
ROSE = (181, 72, 111, 255)   # --love
WHITE = (255, 255, 255, 255)

S = 1024  # 마스터 해상도


def make_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 대각 분할: 좌상 삼각형 = green, 우하 삼각형 = rose
    d.polygon([(0, 0), (S, 0), (0, S)], fill=GREEN)
    d.polygon([(S, 0), (S, S), (0, S)], fill=ROSE)
    # 굵은 M (둥근 이음새) — 0..100 좌표계를 S로 스케일, 폰트 없이 폴리라인으로 직접 그림
    def p(x, y):
        return (x / 100 * S, y / 100 * S)
    pts = [p(26, 76), p(26, 24), p(50, 54), p(74, 24), p(74, 76)]
    width = int(0.135 * S)
    d.line(pts, fill=WHITE, width=width, joint="curve")
    r = width / 2
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)
    return img


if __name__ == "__main__":
    master = make_master().convert("RGB")  # 알파 없음 — iOS가 투명을 검은색으로 표시하는 문제 방지
    master.save(OUT / "icon-512.png")
    master.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    master.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    print(f"saved icon-512.png, icon-192.png, apple-touch-icon.png in {OUT}")
