#!/usr/bin/env python3
"""곡 메타데이터(앨범 커버 · 30초 미리듣기)를 iTunes Search API로 가져와 캐시한다.

- 앨범 커버: 바 차트 레이스 막대 왼쪽의 원형 썸네일로 쓴다.
- 미리듣기(previewUrl): 1위 곡이 바뀔 때 배경 음악을 갈아끼우는 데 쓴다.
- 결과는 cache/ 아래에 해시 키로 저장해서 매일 실행해도 API를 다시 부르지 않는다.
  (iTunes Search API는 무료지만 분당 호출 제한이 있어 캐시가 필수)
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

ITUNES_SEARCH = "https://itunes.apple.com/search"
UA = "Mozilla/5.0 (X11; Linux x86_64) SoriPlayChartBot/1.0"
_LAST_CALL = [0.0]
_FAILED = [0]      # 이번 lookup 에서 통신 실패(429 등)가 있었는지 세는 카운터
MIN_INTERVAL = 1.2  # iTunes 검색 호출 간 최소 간격(초)

# 차트 시장 스토어프런트에서 못 찾았을 때 이어서 볼 상점(미국 → 한국).
MARKET_FALLBACKS = ("US", "KR")


def storefronts(market: str | None, has_hangul: bool = False) -> list[str]:
    """검색할 iTunes 스토어프런트 순서.

    차트 시장(예: ph) → (한글이면 KR 먼저) → US → KR.
    iTunes Search API의 country 파라미터는 두 글자 국가 코드(PH·GB·BR…)를 받는다.
    'global' 처럼 상점이 없는 시장은 US 로 본다.
    """
    out: list[str] = []

    def add(code: str | None) -> None:
        code = (code or "").strip().upper()
        if len(code) == 2 and code.isalpha() and code not in out:
            out.append(code)

    if has_hangul:
        add("KR")
    if (market or "").strip().lower() not in ("", "global", "ww", "world"):
        add(market)
    for code in MARKET_FALLBACKS:
        add(code)
    return out or ["US"]


# --------------------------------------------------------------------------- #
# 문자열 정규화 / 유사도
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w가-힣ぁ-んァ-ヶ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def core_title(title: str) -> str:
    """'(w/ ...)', '(feat. ...)', '[Remix]' 같은 부가 표기를 떼어낸 핵심 제목."""
    t = title or ""
    t = re.sub(r"\(\s*(?:w/|with|feat\.?|ft\.?)\s[^)]*\)", "", t, flags=re.I)
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)
    t = re.sub(r"-\s*(?:remix|version|ver\.?)\b.*$", "", t, flags=re.I)
    return _norm(t)


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    return difflib.SequenceMatcher(None, a, b).ratio()


def _artist_sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb or na in nb or nb in na:
        return 1.0
    ta = {t for t in na.split() if len(t) > 1}
    tb = {t for t in nb.split() if len(t) > 1}
    if ta and tb and (ta & tb):
        return 0.75
    return difflib.SequenceMatcher(None, na, nb).ratio()


# --------------------------------------------------------------------------- #
# 네트워크
# --------------------------------------------------------------------------- #
def _throttle() -> None:
    dt = time.time() - _LAST_CALL[0]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _LAST_CALL[0] = time.time()


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def itunes_search(term: str, limit: int = 10, country: str | None = None) -> list[dict]:
    params = {"term": term, "entity": "song", "limit": str(limit)}
    if country:
        params["country"] = country
    url = f"{ITUNES_SEARCH}?{urllib.parse.urlencode(params)}"
    for attempt in range(1, 4):
        try:
            _throttle()
            data = json.loads(_get(url).decode("utf-8", "ignore"))
            return data.get("results", []) or []
        except Exception as exc:  # noqa: BLE001
            print(f"[media] iTunes 검색 실패({attempt}/3): {exc}")
            time.sleep(1.5 * attempt)
    _FAILED[0] += 1
    return []


# --------------------------------------------------------------------------- #
# 조회 + 캐시
# --------------------------------------------------------------------------- #
def _cache_key(artist: str, title: str) -> str:
    return hashlib.sha1(f"{_norm(artist)}|{core_title(title)}".encode()).hexdigest()[:16]


def _artist_strong(a: str, b: str) -> bool:
    """아티스트명이 사실상 같은 이름인가(단어 하나만 겹치는 오탐을 막는다)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        shorter = na if len(na) <= len(nb) else nb
        return len(shorter) >= 4
    return False


def _pick(results: list[dict], artist: str, title: str,
          trust_title_search: bool = False,
          title_only: bool = False) -> tuple[dict | None, float]:
    """후보 중 가장 그럴듯한 한 곡을 고른다.

    trust_title_search=True 이면 "iTunes가 제목으로 이미 찾아준 결과"로 보고,
    한글 제목 ↔ 영문 제목처럼 표기가 달라도 아티스트가 맞으면 인정한다
    (예: ILLIT - 체포하겠어 → ILLIT - You're Under Arrest).
    title_only=True 이면 제목만으로 검색한 결과라 아티스트명이 음차 표기
    (머무르 → MEOMURU)인 경우도 제목이 완전히 같으면 받아준다.
    """
    want_t = core_title(title)
    variant = re.compile(r"remix|sped up|slowed|instrumental|karaoke|nightcore|8d|live|acoustic",
                         re.I)
    best, best_score = None, 0.0
    for r in results:
        if not r.get("artworkUrl100"):
            continue
        name = r.get("trackName", "")
        album = r.get("collectionName", "")
        t = _sim(want_t, core_title(name))
        a = _artist_sim(artist, r.get("artistName", ""))
        if trust_title_search:
            # 아티스트가 사실상 같고 제목도 어느 정도 맞으면 통과.
            # 제목이 완전히 달라도(한글↔영문) 아티스트가 같은 이름일 때만 받아준다.
            if a >= 0.6 and (t >= 0.45 or (_artist_strong(artist, r.get("artistName", ""))
                                           and t >= 0.12)):
                score = 0.35 + 0.45 * a + 0.20 * t
            elif title_only and t >= 0.95:
                score = 0.66          # 음차 표기 아티스트명 - 제목이 같으면 인정
            else:
                continue
        else:
            if t < 0.45 or a < 0.45:
                continue
            score = 0.6 * t + 0.4 * a
        if variant.search(name) or variant.search(album):
            score -= 0.18
        if score > best_score:
            best, best_score = r, score
    return best, max(best_score, 0.0)


def lookup(artist: str, title: str, cache_dir: str = "cache",
           want_preview: bool = True, market: str | None = None) -> dict:
    """곡 하나의 커버/미리듣기 경로를 반환. 못 찾으면 빈 dict.

    market: 차트 시장 코드(ph·gb·br…). 그 나라 스토어프런트를 먼저 뒤지고,
    없으면 US·KR 까지 본다(한 나라 상점에만 있는 곡 때문에 무음이 생기던 문제).
    """
    key = _cache_key(artist, title)
    meta_path = os.path.join(cache_dir, "meta", f"{key}.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    os.makedirs(os.path.join(cache_dir, "art"), exist_ok=True)
    os.makedirs(os.path.join(cache_dir, "preview"), exist_ok=True)

    # 한글 제목은 미국/한국 스토어프런트 결과가 달라서 둘 다 모아놓고 가장 비슷한 것을 고른다.
    has_hangul = bool(re.search(r"[\uac00-\ud7a3]", f"{artist} {title}"))
    has_nonlatin = bool(re.search(r"[^\x00-\x7f]", f"{artist} {title}"))
    stores = storefronts(market, has_hangul)
    sig = ",".join(stores)

    if os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
            # 예전 실행이 다른 스토어프런트만 보고 남긴 결과는 이번 시장 기준으로 다시 찾는다.
            same_stores = meta.get("stores") == sig
            if meta.get("not_found"):
                if same_stores:
                    return {}
            else:
                art = meta.get("art_path")
                prev = meta.get("preview_path")
                have_art = bool(art) and os.path.exists(art)
                have_prev = (not want_preview) or (bool(prev) and os.path.exists(prev))
                if have_art and have_prev:
                    return meta
        except (json.JSONDecodeError, OSError):
            pass

    queries = [(f"{artist} {core_title(title)}".strip(), True, False),
               (f"{artist} {title}".strip(), True, False),
               # 제목만 검색은 로마자 표기가 다른 경우(한글·태국어 등)에만 봐준다.
               # (영문 곡에서 같은 제목의 남의 곡을 가져오는 오탐 방지)
               (f"{core_title(title)}".strip() or title.strip(), True, has_nonlatin),
               (artist, False, False)]
    pool: dict[str, dict] = {}
    hit, score = None, 0.0
    calls = 0
    failed_before = _FAILED[0]
    for q, trust, title_only in queries:
        if not q or calls >= 9:
            continue
        for store in stores:
            if calls >= 9:
                break
            calls += 1
            for r in itunes_search(q, limit=10, country=store):
                r.setdefault("__store", store)
                key_id = str(r.get("trackId") or r.get("artworkUrl100") or r.get("trackName"))
                pool.setdefault(key_id, r)
            # 상점을 하나 볼 때마다 바로 판단하고, 충분히 확실하면 나머지 상점은 건너뛴다.
            if pool:
                cand, cscore = _pick(list(pool.values()), artist, title,
                                     trust_title_search=trust, title_only=title_only)
                if cand is not None and cscore > score:
                    hit, score = cand, cscore
                if hit is not None and score >= 0.9:
                    break
        if hit and score >= 0.72:
            break
    if not hit or score < 0.55:
        transient = _FAILED[0] > failed_before
        if transient or hit:
            # 통신 오류로 못 찾은 것을 '없는 곡'으로 굳히지 않는다(다음 실행에 다시 시도).
            print(f"[media] 커버 못 찾음: {artist} - {title} (상점 {sig})"
                  + (" · 통신 오류로 이번만 건너뜀" if transient else "")
                  + (f" · 가장 비슷한 후보 {hit.get('artistName')} - {hit.get('trackName')}"
                     f"({score:.2f}) 라서 버림" if hit and not transient else ""))
            return {}
        json.dump({"not_found": True, "artist": artist, "title": title, "stores": sig},
                  open(meta_path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[media] 커버 못 찾음: {artist} - {title} (상점 {sig})")
        return {}

    meta = {"artist": artist, "title": title, "score": round(score, 3),
            "matched_title": hit.get("trackName"), "matched_artist": hit.get("artistName"),
            "album": hit.get("collectionName"), "stores": sig,
            "store": (hit.get("__store") or "")}

    art_url = (hit.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
    art_path = os.path.join(cache_dir, "art", f"{key}.jpg")
    if art_url and not os.path.exists(art_path):
        try:
            with open(art_path, "wb") as fh:
                fh.write(_get(art_url))
        except Exception as exc:  # noqa: BLE001
            print(f"[media] 커버 다운로드 실패 {artist} - {title}: {exc}")
    if os.path.exists(art_path):
        meta["art_path"] = art_path

    if want_preview and hit.get("previewUrl"):
        prev_path = os.path.join(cache_dir, "preview", f"{key}.m4a")
        if not os.path.exists(prev_path):
            try:
                with open(prev_path, "wb") as fh:
                    fh.write(_get(hit["previewUrl"]))
            except Exception as exc:  # noqa: BLE001
                print(f"[media] 미리듣기 다운로드 실패 {artist} - {title}: {exc}")
        if os.path.exists(prev_path):
            meta["preview_path"] = prev_path

    json.dump(meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return meta


# --------------------------------------------------------------------------- #
# 이미지 가공
# --------------------------------------------------------------------------- #
def circular_image(path: str | None, size: int = 320, ring: bool = True) -> np.ndarray:
    """정사각 크롭 → 원형 마스크 → 테두리 링. RGBA float 배열 반환."""
    ss = 4
    if path and os.path.exists(path):
        im = Image.open(path).convert("RGB")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        im = im.resize((size, size), Image.LANCZOS)
    else:
        im = _placeholder(size)

    mask = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    if ring:
        d = ImageDraw.Draw(out)
        rw = max(3, size // 45)
        d.ellipse((rw // 2, rw // 2, size - 1 - rw // 2, size - 1 - rw // 2),
                  outline=(255, 255, 255, 210), width=rw)
    return np.asarray(out).astype(np.float32) / 255.0


def _placeholder(size: int) -> Image.Image:
    """커버를 못 구했을 때 쓰는 브랜드 그라데이션 원."""
    img = Image.new("RGB", (size, size))
    top, bottom = np.array([124, 58, 237]), np.array([236, 72, 153])
    ramp = np.linspace(0, 1, size)[:, None, None]
    arr = (top[None, None, :] * (1 - ramp) + bottom[None, None, :] * ramp)
    arr = np.repeat(arr, size, axis=1).astype(np.uint8)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    # 가운데에 음표(♪) 대신 단순한 재생 삼각형을 그려 넣는다.
    c, r = size // 2, size // 6
    d.polygon([(c - r // 2, c - r), (c - r // 2, c + r), (c + r, c)],
              fill=(255, 255, 255))
    return img


def save_square(path: str, size: int = 320) -> str:
    """원형 아트를 PNG로 저장(디버깅/미리보기용)."""
    arr = (circular_image(path, size) * 255).astype(np.uint8)
    out = os.path.splitext(path)[0] + "_circle.png"
    Image.fromarray(arr, "RGBA").save(out)
    return out
