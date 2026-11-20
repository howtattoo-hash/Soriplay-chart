#!/usr/bin/env python3
"""스포티파이 차트(주간/일간)를 13개국에서 받아 CSV에 쌓는다.

데이터 출처
  1순위: https://kworb.net/spotify/country/{code}_{weekly|daily}.html
         - 주간 표: Pos / P+ / Artist and Title / Wks / Pk / (x?) / Streams / Streams+ / Total
         - 일간 표: Pos / P+ / Artist and Title / Days / Pk / (x?) / Streams / Streams+ / 7Day / 7Day+ / Total
         - 페이지 상단에 차트 기준일("Spotify Weekly Chart - South Korea - 2026/11/12")이 있다.
  2순위: 같은 페이지 재시도(백오프)
  3순위: 이미 받아둔 CSV의 최신 스냅샷(파이프라인이 죽지 않도록)

히스토리 보강
  kworb는 과거 아카이브를 주지 않는다. 그래서 같은 표의 `Streams+`(직전 기간 대비 증감)로
  **직전 주(일간이면 전날)** 지점을 역산해 첫 실행부터 막대가 움직이는 레이스를 만든다.
  일간 표에는 `7Day`(7일 합계)도 있어 3일 전 지점을 하나 더 만들 수 있다.
  역산 행은 source 컬럼에 `derived_prev` / `derived_7d`로 표시되고, 실제 관측(`kworb`)이
  생기면 그쪽이 항상 우선한다. 주간 차트는 한 주에 한 번만 갱신되므로 CSV도 주 단위로 쌓인다.

사용 예
  python scripts/fetch_spotify.py --period weekly --country kr
  python scripts/fetch_spotify.py --period weekly --country all
  python scripts/fetch_spotify.py --period daily --country kr,global
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

import chart_config

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
COLUMNS = ["chart_date", "country", "rank", "artist", "title", "streams", "source",
           "fetched_at", "rank_change"]


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
    m = re.search(r"Spotify\s+(?:Daily|Weekly)\s+Chart\s*-\s*[^<]*?-\s*"
                  r"(\d{4})/(\d{2})/(\d{2})", html)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(20\d{2})/(\d{2})/(\d{2})", html)
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
    """표(<tr>/<td>)를 헤더 기준으로 읽어 곡 목록을 만든다(주간·일간 공용)."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)
    header: list[str] | None = None
    out: list[dict] = []
    for raw in rows:
        cells = [re.sub(r"<[^>]+>", "", c).replace("&amp;", "&")
                 .replace("&#39;", "'").replace("&quot;", "\"")
                 .replace("&lt;", "<").replace("&gt;", ">").strip()
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
        change_raw = col("Streams+", "\x00")
        pos_raw = col("P+").strip()
        rank_change = "" if pos_raw in {"", "=", "0"} else pos_raw
        out.append({
            "rank": int(cells[0]),
            "artist": artist.strip(),
            "title": title.strip(),
            "streams": _to_int(col("Streams")),
            "change": (_to_int(change_raw)
                       if change_raw.startswith(("+", "-")) else None),
            "week": _to_int(col("7Day")),          # 일간 표에만 있다
            "total": _to_int(col("Total")),
            "rank_change": rank_change,             # '+7' / '-1' / 'NEW' / ''
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
        "rank_change": r.get("rank_change", ""),
    } for r in rows])
    if new.empty:
        return df
    keys = ["chart_date", "artist", "title"]
    if source == "kworb":
        # 같은 날짜를 다시 받았으면 그날의 관측 스냅샷은 방금 받은 것으로 교체한다.
        df = df[~((df["chart_date"] == chart_date.isoformat()) & (df["source"] == "kworb"))]
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
    for _d, grp in df.groupby("chart_date"):
        if all(str(s).startswith("derived") for s in grp["source"]):
            order = grp.sort_values("streams", ascending=False).index
            for rank, idx in enumerate(order, start=1):
                df.at[idx, "rank"] = rank
    return df.sort_values(["chart_date", "rank"]).reset_index(drop=True)


def _prev_period(period: str) -> dt.timedelta:
    return dt.timedelta(days=7) if period == "weekly" else dt.timedelta(days=1)


def update_country(country: str, period: str = "weekly", data_dir: str = "data",
                   top: int = 15, backfill: bool = True,
                   offline: bool = False) -> pd.DataFrame:
    path = chart_config.csv_path(data_dir, country, period)
    cfg = chart_config.country(country)
    hist = load_csv(path)
    today = dt.date.today()

    if offline:
        if hist.empty:
            raise SystemExit(f"{path}: 오프라인 모드인데 저장된 데이터가 없습니다.")
        print(f"[{country}/{period}] 오프라인 모드 - 기존 CSV {len(hist)}행 사용")
        return reindex_ranks(hist)

    try:
        html = fetch_html(chart_config.chart_url(country, period))
        chart_date = parse_chart_date(html, today - _prev_period(period))
        rows = parse_rows(html)[:max(top, 20)]
        if len(rows) < 5:
            raise RuntimeError(f"표 파싱 결과가 너무 적습니다({len(rows)}행)")
    except Exception as exc:  # noqa: BLE001
        print(f"[{country}/{period}] 수집 실패: {exc}", file=sys.stderr)
        if hist.empty:
            raise SystemExit(f"{country}/{period}: 차트 수집에 실패했고 저장된 데이터도 없습니다.")
        print(f"[{country}/{period}] 저장된 최신 스냅샷으로 계속 진행합니다.")
        return reindex_ranks(hist)

    print(f"[{country}/{period}] {chart_date} 차트 {len(rows)}곡 수집 ({cfg['name_en']}, 1위: "
          f"{rows[0]['artist']} - {rows[0]['title']}, {rows[0]['streams'] or 0:,}회)")
    if not any((r.get("streams") or 0) > 0 for r in rows):
        print(f"[{country}/{period}] 알림: 이 시장은 kworb가 스트림 수치를 주지 않습니다(전부 0). "
              f"순위 점수(Chart Score) 모드로 렌더합니다.", file=sys.stderr)
    hist = append_snapshot(hist, rows, country, chart_date, "kworb")

    if backfill:
        known_dates = set(hist["chart_date"])
        # 직전 기간 지점: 스트림 - 증감 (주간이면 지난주, 일간이면 어제)
        prev_date = (chart_date - _prev_period(period)).isoformat()
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
                                       chart_date - _prev_period(period), "derived_prev")
                print(f"[{country}/{period}] 직전({prev_date}) 지점 {len(prev_rows)}곡 역산 추가")

        # 일간 표의 7일 합계 → 3일 전 지점 (주간 표에는 없는 열)
        if period == "daily":
            d3 = (chart_date - dt.timedelta(days=3)).isoformat()
            if d3 not in known_dates and len(hist[hist["chart_date"] == d3]) == 0:
                d3_rows = [{"rank": r["rank"], "artist": r["artist"], "title": r["title"],
                            "streams": int(round(r["week"] / 7))}
                           for r in rows if r["week"] and r["week"] > 0]
                if d3_rows:
                    hist = append_snapshot(hist, d3_rows, country,
                                           chart_date - dt.timedelta(days=3), "derived_7d")
                    print(f"[{country}/{period}] 3일 전({d3}) 지점 {len(d3_rows)}곡 역산 추가")

    hist = reindex_ranks(hist)
    os.makedirs(data_dir, exist_ok=True)
    hist.to_csv(path, index=False)
    dates = sorted(hist["chart_date"].unique())
    print(f"[{country}/{period}] {path} 저장 완료 · {len(hist)}행 · {len(dates)}개 시점 "
          f"({dates[0]} ~ {dates[-1]})")
    return hist


def parse_countries(spec: str) -> list[str]:
    """'kr', 'kr,global', 'all', 'both'(예전 이름) 모두 받는다."""
    spec = (spec or "auto").strip()
    if spec in {"all", "both"}:
        return chart_config.order() if spec == "all" else ["kr", "global"]
    if spec == "auto":
        import rotation
        code = rotation.country_for(rotation.now_kst())
        return [code] if code else []
    return [c.strip() for c in spec.split(",") if c.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="스포티파이 차트 수집(13개국 · 주간/일간)")
    ap.add_argument("--country", default="auto",
                    help="auto / all / kr,global 처럼 쉼표 목록 / 13개국 코드")
    ap.add_argument("--period", default="weekly", choices=["weekly", "daily"])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--top", type=int, default=15, help="저장할 상위 곡 수 (기본 15)")
    ap.add_argument("--no-backfill", action="store_true",
                    help="직전 기간 역산 지점을 만들지 않는다")
    ap.add_argument("--offline", action="store_true", help="네트워크 없이 기존 CSV만 사용")
    args = ap.parse_args()

    codes = parse_countries(args.country)
    if not codes:
        print("[fetch] 이번 시간대에 돌릴 국가가 없습니다.", file=sys.stderr)
        return
    for country in codes:
        update_country(country, args.period, args.data_dir, args.top,
                       backfill=not args.no_backfill, offline=args.offline)


if __name__ == "__main__":
    main()
