"""13개 시장 설정 로더 (config/countries.json) + 공통 경로 헬퍼.

이 모듈 하나로 국가 목록·순서·언어·CSV 경로를 모두 얻는다.
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "countries.json")

# CSV를 못 읽을 때를 대비한 최소 기본값(설정 파일이 없어도 파이프라인은 돌게).
DEFAULT_ORDER = ["global", "kr", "us", "gb", "br", "mx", "id", "vn", "th", "ph", "my", "sa", "in"]
ALL_CODES = list(DEFAULT_ORDER)

_cache: dict | None = None


def load(path: str | None = None) -> dict:
    global _cache
    if path is None and _cache is not None:
        return _cache
    target = path or CONFIG_PATH
    with open(target, encoding="utf-8") as fh:
        data = json.load(fh)
    if "order" not in data or "countries" not in data:
        raise SystemExit(f"{target}: order / countries 키가 필요합니다.")
    if path is None:
        _cache = data
    return data


def order(path: str | None = None) -> list[str]:
    """하루 두 곳씩 도는 순서(13곳)."""
    return list(load(path)["order"])


def all_codes(path: str | None = None) -> list[str]:
    return list(load(path)["countries"].keys())


def country(code: str, path: str | None = None) -> dict:
    data = load(path)
    if code not in data["countries"]:
        raise SystemExit(f"알 수 없는 국가 코드: {code} (가능: {', '.join(data['countries'])})")
    cfg = dict(data["countries"][code])
    cfg["code"] = code
    cfg.setdefault("label", code.upper())
    cfg.setdefault("market", cfg.get("name_en", code))
    cfg.setdefault("lang", "en")
    cfg.setdefault("video_lang", cfg["lang"])
    cfg.setdefault("date_fmt", "%m/%d")
    cfg.setdefault("week_fmt", "%m.%d")
    return cfg


def csv_path(data_dir: str, code: str, period: str) -> str:
    """data/{code}_{period}.csv (period: daily / weekly)."""
    return os.path.join(data_dir, f"{code}_{period}.csv")


def chart_url(code: str, period: str) -> str:
    return f"https://kworb.net/spotify/country/{code}_{period}.html"


# --------------------------------------------------------------------------- #
# 날짜 표기 — 연·월을 항상 함께 보여준다
#   예전 표기: 11.12–11.18 / 11/12  (연도가 없어 어느 해 차트인지 알 수 없었다)
#   지금 표기: 2026.11.12–11.18 / 2026/11/12
# --------------------------------------------------------------------------- #
def _sep_of(fmt: str) -> str:
    """date_fmt/week_fmt 에서 구분자(/, ., -)를 뽑는다."""
    for ch in ("/", ".", "-"):
        if ch in fmt:
            return ch
    return "."


def _day_first(fmt: str) -> bool:
    """'%d.%m' 처럼 일이 앞에 오는 표기인지."""
    d, m = fmt.find("%d"), fmt.find("%m")
    return d != -1 and (m == -1 or d < m)


def date_label(d, fmt: str) -> str:
    """날짜 하나를 연·월·일까지 표기한다.

    월 우선(예: %m/%d) → 2026/11/12 , 일 우선(예: %d.%m) → 12.11.2026
    """
    sep = _sep_of(fmt)
    if _day_first(fmt):
        return f"{d.day:02d}{sep}{d.month:02d}{sep}{d.year}"
    return f"{d.year}{sep}{d.month:02d}{sep}{d.day:02d}"


def week_label(start, end, fmt: str, sep: str = "–") -> str:
    """주간 범위를 연·월과 함께 표기한다.

    시작은 연·월·일 전부, 끝은 같은 달이면 월.일, 달이 바뀌면 월.일,
    해가 바뀌면 연도까지 붙인다.
      2026.11.12–11.18 · 2026.11.28–12.04 · 2026.12.29–2027.01.04
      (일 우선) 12.11.2026–18.11 · 28.11.2026–04.12 · 29.12.2026–04.01.2027
    """
    ch = _sep_of(fmt)
    first = date_label(start, fmt)
    if end.year != start.year:
        last = date_label(end, fmt)
    elif _day_first(fmt):
        last = f"{end.day:02d}{ch}{end.month:02d}"
    else:
        last = f"{end.month:02d}{ch}{end.day:02d}"
    return f"{first}{sep}{last}"
