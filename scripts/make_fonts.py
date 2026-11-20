#!/usr/bin/env python3
"""번들 글꼴 준비: Pretendard(Bold/Black)의 이름표를 바꿔 무게별 가족으로 등록한다.

matplotlib 은 한 가족 안의 무게를 잘 구분하지 못하므로(특히 Black 은 내부적으로
Regular 로 읽힌다), 무게마다 고유 가족 이름을 붙여 둔다.

  fonts/Pretendard-Black.otf → 가족 "SoriSans Black"
  fonts/Pretendard-Bold.otf  → 가족 "SoriSans Bold"

OFL 1.1 은 수정 시 이름 변경을 요구하므로 이 리네이밍이 그 조건을 만족한다.
원본: https://github.com/orioncactus/pretendard
"""
from __future__ import annotations

import os
import sys
import urllib.request

from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(os.path.dirname(HERE), "fonts")
SOURCE_URL = ("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@main/packages/"
              "pretendard/dist/public/static/{name}")

JOBS = [
    ("Pretendard-Black.otf", "SoriSans-Black.otf", "SoriSans Black", 900),
    ("Pretendard-Bold.otf", "SoriSans-Bold.otf", "SoriSans Bold", 700),
]


def fetch(name: str) -> str:
    """원본 글꼴이 없으면 받아 온다(저장소에는 이름 바꾼 SoriSans-*.otf 만 둔다)."""
    path = os.path.join(FONT_DIR, name)
    if os.path.exists(path):
        return path
    os.makedirs(FONT_DIR, exist_ok=True)
    print(f"[fonts] 내려받기 {name} ...")
    urllib.request.urlretrieve(SOURCE_URL.format(name=name), path)
    return path


def rename(src: str, dst: str, family: str, weight: int) -> None:
    font = TTFont(src)
    ps = family.replace(" ", "")
    values = {1: family, 2: "Regular", 3: f"{family} v1.0", 4: family,
              6: ps, 16: family, 17: "Regular"}
    for rec in font["name"].names:
        if rec.nameID in values:
            try:
                rec.string = values[rec.nameID].encode(rec.getEncoding())
            except Exception:  # noqa: BLE001
                rec.string = values[rec.nameID].encode("utf-16-be")
    os2 = font["OS/2"]
    os2.usWeightClass = weight
    # REGULAR/BOLD 선택 비트를 무게에 맞춘다(다른 비트는 보존).
    os2.fsSelection = (os2.fsSelection & ~0x41) | (0x20 if weight >= 600 else 0x40)
    font["head"].macStyle = 0x01 if weight >= 600 else 0x00
    font.save(dst)
    print(f"[fonts] {os.path.basename(dst)} ← {family} ({weight})")


def main() -> int:
    for src, dst, family, weight in JOBS:
        try:
            path = fetch(src)
        except Exception as exc:  # noqa: BLE001
            print(f"[fonts] {src} 를 받지 못했습니다: {exc}", file=sys.stderr)
            return 2
        rename(path, os.path.join(FONT_DIR, dst), family, weight)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
