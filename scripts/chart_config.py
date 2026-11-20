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
