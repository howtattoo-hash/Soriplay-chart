#!/usr/bin/env python3
"""스포티파이 일간 차트(지역 TOP 곡 + 일일 스트리밍 수)를 받아 CSV에 하루씩 쌓는다.

데이터 출처
  1순위: https://kworb.net/spotify/country/{kr|global}_daily.html
         - 스포티파이 일간 차트의 순위/일일 스트리밍을 그대로 표로 보여준다.
         - 페이지 상단에 차트 기준일("Spotify Daily Chart - South Korea - 2026/11/18")이 있다.
  2순위: 같은 페이지 재시도(백오프)
  3순위: 이미 받아둔 CSV의 최신 스냅샷(파이프라인이 죽지 않도록)

히스토리 보강
  kworb는 과거 일자 아카이브를 주지 않는다. 그래서 같은 표에 있는
  `Streams+`(전일 대비 증감), `7Day`(최근 7일 합계) 열로 **전날/3일 전 지점을 역산**해
  첫 실행부터 막대가 움직이는 레이스를 만들 수 있게 한다. 역산 행은 source 컬럼에
  `derived_prev` / `derived_7d`로 표시되며, 실제 관측일(`kworb`)이 생기면 그쪽이 우선한다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
import urllib.error
import urllib.request

import pandas as pd

COUNTRIES = {
    "kr": {
        "name": "South Korea",
        "label": "KOREA",
        "url": "https://kworb.net/spotify/country/kr_daily.html",
    },
    "global": {
        "name": "Global",
        "label": "GLOBAL",
        "url": "https://kworb.net/spotify/country/global_daily.html",
    },
}

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
COLUMNS = ["chart_date", "country", "rank", "artist", "title", "streams", "source", "fetched_at"]


# --------------------------------------------------------------------------- #
# 수집
# --------------------------------------------------------------------------- #
def fetch_html(url: str, retries: int = 3, timeout: int = 45) -> str:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise urllib.error.HTTPError(url, resp.status, "bad status", None, None)
                return resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001 - 네트워크 예외 전부 재시도
            last_err = exc
            wait = 2 ** attempt
            print(f"[fetch] {attempt}/{retries} 실패: {exc} → {wait}s 후 재시도", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"차트 페이지를 받지 못했습니다: {url} ({last_err})")


def parse_chart_date(html: str, fallback: dt.date) -> dt.date:
    m = re.search(r"Spotify Daily Chart\s*-\s*[^<]*?-\s*(\d{4})/(\d{2})/(\d{2})", html)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{4})/(\d{2})/(\d{2})", html)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return fallback


def _to_int(cell: str) -> int | None:
    cell = (cell or "").strip().replace(",", "").replace("+", "")
    if not cell or cell in {"-", "="}:
        return None
    try:
        return int(float(cell))
    except ValueError:
        return None


def parse_rows(html: str) -> list[dict]:
    """표(<tr>/<td>)를 헤더 기준으로 읽어 곡 목록을 만든다."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)
    header: list[str] | None = None
    out: list[dict] = []
    for raw in rows:
        cells = [re.sub(r"<[^>]+>", "", c).replace("&amp;", "&").strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", raw, re.S | re.I)]
        if not cells:
            continue
        if header is None:
            if any(c.lower() == "pos" for c in cells) and any("artist" in c.lower() for c in cells):
                header = cells
            continue
        if len(cells) < 4 or not cells[0].isdigit():
            continue

        def col(name: str, default: str = "") -> str:
            for i, h in enumerate(header):
                if h.lower().startswith(name.lower()) and i < len(cells):
                    return cells[i]
            return default

        title_cell = col("Artist and Title")
        if " - " not in title_cell:
            continue
        artist, title = title_cell.split(" - ", 1)
        out.append({
            "rank": int(cells[0]),
            "artist": artist.strip(),
            "title": title.strip(),
            "streams": _to_int(col("Streams")),
            "change": _to_int(col("Streams+")) if col("Streams+").startswith(("+", "-")) else None,
            "week": _to_int(col("7Day")),
        })
    return out


# --------------------------------------------------------------------------- #
# CSV 누적
# --------------------------------------------------------------------------- #
def load_csv(path: str) -> pd.DataFrame:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        df = pd.read_csv(path, dtype={"chart_date": str})
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = None
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


def append_snapshot(df: pd.DataFrame, rows: list[dict], country: str,
                    chart_date: dt.date, source: str) -> pd.DataFrame:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = pd.DataFrame([{
        "chart_date": chart_date.isoformat(),
        "country": country,
        "rank": r["rank"],
        "artist": r["artist"],
        "title": r["title"],
        "streams": int(r["streams"] or 0),
        "source": source,
        "fetched_at": now,
    } for r in rows])
    if new.empty:
        return df
    keys = ["chart_date", "artist", "title"]
    merged = pd.concat([df, new], ignore_index=True)
    # 실제 관측(kworb) > 역산(derived_prev) > 역산(derived_7d)
    prio = {"kworb": 0, "derived_prev": 1, "derived_7d": 2}
    merged["_prio"] = merged["source"].map(lambda s: prio.get(str(s), 9))
    merged = (merged.sort_values(["_prio", "rank"])
                    .drop_duplicates(keys, keep="first")
                    .drop(columns=["_prio"]))
    return merged


def reindex_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """역산 행이 섞인 날짜도 순위를 스트림 기준으로 다시 매긴다."""
    df = df.copy()
    for d, grp in df.groupby("chart_date"):
        if all(str(s).startswith("derived") for s in grp["source"]):
            order = grp.sort_values("streams", ascending=False).index
            for rank, idx in enumerate(order, start=1):
                df.at[idx, "rank"] = rank
    return df.sort_values(["chart_date", "rank"]).reset_index(drop=True)


def update_country(country: str, data_dir: str, top: int, backfill: bool,
                   offline: bool) -> pd.DataFrame:
    cfg = COUNTRIES[country]
    path = os.path.join(data_dir, f"{country}_daily.csv")
    hist = load_csv(path)
    today = dt.date.today()

    if offline:
        if hist.empty:
            raise SystemExit(f"{path}: 오프라인 모드인데 저장된 데이터가 없습니다.")
        print(f"[{country}] 오프라인 모드 - 기존 CSV {len(hist)}행 사용")
        return reindex_ranks(hist)

    try:
        html = fetch_html(cfg["url"])
        chart_date = parse_chart_date(html, today - dt.timedelta(days=1))
        rows = parse_rows(html)[:max(top, 20)]
        if len(rows) < 5:
            raise RuntimeError(f"표 파싱 결과가 너무 적습니다({len(rows)}행)")
    except Exception as exc:  # noqa: BLE001
        print(f"[{country}] 수집 실패: {exc}", file=sys.stderr)
        if hist.empty:
            raise SystemExit("차트 수집에 실패했고 저장된 데이터도 없습니다.")
        print(f"[{country}] 저장된 최신 스냅샷으로 계속 진행합니다.")
        return reindex_ranks(hist)

    print(f"[{country}] {chart_date} 차트 {len(rows)}곡 수집 (1위: "
          f"{rows[0]['artist']} - {rows[0]['title']}, {rows[0]['streams']:,}회)")
    hist = append_snapshot(hist, rows, country, chart_date, "kworb")

    if backfill:
        known_dates = set(hist["chart_date"])
        # 전날 지점: 스트림 - 증감
        prev_date = (chart_date - dt.timedelta(days=1)).isoformat()
        if prev_date not in known_dates:
            prev_rows = []
            for r in rows:
                if r["change"] is None or r["streams"] is None:
                    continue
                prev = r["streams"] - r["change"]
                if prev > 0:
                    prev_rows.append({"rank": r["rank"], "artist": r["artist"],
                                      "title": r["title"], "streams": prev})
            if prev_rows:
                hist = append_snapshot(hist, prev_rows, country,
                                       chart_date - dt.timedelta(days=1), "derived_prev")
                print(f"[{country}] 전날({prev_date}) 지점 {len(prev_rows)}곡 역산 추가")
        # 3일 전 지점: 7일 합계 / 7
        d3 = (chart_date - dt.timedelta(days=3)).isoformat()
        if d3 not in known_dates and len(hist[hist["chart_date"] == d3]) == 0:
            d3_rows = [{"rank": r["rank"], "artist": r["artist"], "title": r["title"],
                        "streams": int(round(r["week"] / 7))}
                       for r in rows if r["week"] and r["week"] > 0]
            if d3_rows:
                hist = append_snapshot(hist, d3_rows, country,
                                       chart_date - dt.timedelta(days=3), "derived_7d")
                print(f"[{country}] 3일 전({d3}) 지점 {len(d3_rows)}곡 역산 추가")

    hist = reindex_ranks(hist)
    os.makedirs(data_dir, exist_ok=True)
    hist.to_csv(path, index=False)
    dates = sorted(hist["chart_date"].unique())
    print(f"[{country}] {path} 저장 완료 · {len(hist)}행 · {len(dates)}개 날짜 "
          f"({dates[0]} ~ {dates[-1]})")
    return hist


def main() -> None:
    ap = argparse.ArgumentParser(description="스포티파이 일간 차트 수집")
    ap.add_argument("--country", default="kr", choices=["kr", "global", "both"],
                    help="kr / global / both (기본 kr)")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--top", type=int, default=15, help="저장할 상위 곡 수 (기본 15)")
    ap.add_argument("--no-backfill", action="store_true",
                    help="전날/3일 전 역산 지점을 만들지 않는다")
    ap.add_argument("--offline", action="store_true",
                    help="네트워크 없이 기존 CSV만 사용")
    args = ap.parse_args()

    targets = ["kr", "global"] if args.country == "both" else [args.country]
    for country in targets:
        update_country(country, args.data_dir, args.top, not args.no_backfill, args.offline)


if __name__ == "__main__":
    main()
