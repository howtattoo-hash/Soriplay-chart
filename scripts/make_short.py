#!/usr/bin/env python3
"""한 번에 끝내는 파이프라인: 차트 수집 → 영상 렌더 → (1위 곡 변경 시) 배경 음악 전환 → 최종 mp4.

13개국 주간 차트를 하루 두 곳씩 돌리는 것이 기본 동작이다.
GitHub Actions는 이 스크립트 하나만 호출한다.

  python scripts/make_short.py                          # 지금 시간대 순번의 국가 (주간)
  python scripts/make_short.py --period weekly --country kr
  python scripts/make_short.py --country all            # 13개국 전부 (수동 점검용, 오래 걸림)
  python scripts/make_short.py --country kr,global --period daily
  python scripts/make_short.py --country auto --now 2026-11-20T19:00
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys

import build_audio
import chart_config
import fetch_spotify
import render_chart
import rotation

DEFAULT_DAYS = {"weekly": 4, "daily": 5}
DEFAULT_DURATION = {"weekly": 45.0, "daily": 30.0}


def resolve_countries(spec: str, when: dt.datetime | None = None) -> list[str]:
    spec = (spec or "auto").strip()
    if spec == "auto":
        code = rotation.country_for(when or rotation.now_kst())
        return [code] if code else []
    if spec in {"all", "both"}:
        return chart_config.order() if spec == "all" else ["kr", "global"]
    return [c.strip() for c in spec.split(",") if c.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="스포티파이 차트 숏폼 원샷 파이프라인(13개국)")
    ap.add_argument("--country", default="auto",
                    help="auto(순번대로) / all(13개국) / kr,global 처럼 목록 / 코드 하나")
    ap.add_argument("--period", default="weekly", choices=["weekly", "daily"])
    ap.add_argument("--now", default="", help="순번 계산용 기준 시각(KST). 비우면 현재 시각")
    ap.add_argument("--audio", default=os.environ.get("AUDIO_MODE", "preview"),
                    choices=["preview", "silent", "off"])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--duration", type=float, default=0,
                    help="0이면 기간별 기본값(주간 45초 · 일간 30초)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--days", type=int, default=0, help="0이면 기간별 기본값(주간 4 · 일간 5)")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--offline", action="store_true", help="네트워크 없이 기존 CSV로만")
    args = ap.parse_args()

    when = dt.datetime.fromisoformat(args.now).replace(tzinfo=rotation.KST) if args.now else None
    countries = resolve_countries(args.country, when)
    if not countries:
        print("[make_short] 이번 시간대에 올릴 국가가 없습니다(일요일 저녁). 건너뜁니다.")
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                       "skipped": "no slot for this time", "results": []}, fh,
                      ensure_ascii=False, indent=1)
        return

    days = args.days or DEFAULT_DAYS.get(args.period, 4)
    duration = args.duration or DEFAULT_DURATION.get(args.period, 45.0)
    os.makedirs(args.out_dir, exist_ok=True)
    results: list[dict] = []

    for country in countries:
        cfg = chart_config.country(country)
        print(f"\n=========== {country.upper()} ({cfg['name_en']} · {args.period}) ===========")
        if not args.skip_fetch:
            fetch_spotify.update_country(country, args.period, args.data_dir,
                                         max(args.top, 15), backfill=True,
                                         offline=args.offline)

        hist = fetch_spotify.reindex_ranks(fetch_spotify.load_csv(
            chart_config.csv_path(args.data_dir, country, args.period)))
        if hist.empty:
            print(f"[make_short] {country}: 차트 데이터가 없어 건너뜁니다.", file=sys.stderr)
            continue
        chart_date = sorted(hist["chart_date"].unique())[-1]
        stem = (f"soriplay_spotify_{country}_{args.period}_"
                f"{str(chart_date).replace('-', '')}")
        raw = os.path.join(args.out_dir, f"{stem}_raw.mp4")
        final = os.path.join(args.out_dir, f"{stem}.mp4")

        render_args = argparse.Namespace(
            country=country, period=args.period, data_dir=args.data_dir,
            cache_dir=args.cache_dir, out=raw, top=args.top, duration=duration,
            fps=args.fps, days=days, crf=20, frames_dir="", preview="")
        info = render_chart.render(render_args)
        raw_timeline = os.path.splitext(raw)[0] + ".json"

        audio_args = argparse.Namespace(video=raw, timeline=raw_timeline,
                                        out=final, cache_dir=args.cache_dir,
                                        mode=args.audio, gain=0.55)
        out_path = build_audio.build(audio_args)
        if os.path.abspath(out_path) != os.path.abspath(final):
            shutil.move(out_path, final)

        # 타임라인 JSON은 최종 영상 이름에 맞춰 정리(업로드 단계에서 이 파일을 씀)
        timeline_path = os.path.splitext(final)[0] + ".json"
        info["video"] = final
        info["raw_video"] = raw
        info["period"] = args.period
        info["playlist_title"] = cfg.get("playlist", "")
        with open(timeline_path, "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=1)
        for p in (raw, raw_timeline):
            if os.path.exists(p):
                os.remove(p)

        segs = info.get("segments", [])
        last_vals = {k: v[-1] for k, v in (info.get("series") or {}).items() if v}
        top2 = [k for k, _v in sorted(last_vals.items(), key=lambda kv: -kv[1])[:2]]
        results.append({
            "country": country,
            "country_label": cfg["label"],
            "period": args.period,
            "chart_date": str(chart_date),
            "video": final,
            "timeline": timeline_path,
            "top1": info.get("top1"),
            "top2": top2,
            "top1_changes": len(segs),
            "duration": info.get("duration"),
            "size_mb": round(os.path.getsize(final) / 1e6, 2) if os.path.exists(final) else 0,
        })
        print(f"[done] {final} · 1위 {info.get('top1')} · 1위 변경 {len(segs)}회")

    summary = os.path.join(args.out_dir, "summary.json")
    with open(summary, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                   "period": args.period, "results": results}, fh,
                  ensure_ascii=False, indent=1)
    print(f"\n[summary] {summary}")
    for r in results:
        print(f"  - {r['country']}: {r['video']} ({r['size_mb']}MB)")


if __name__ == "__main__":
    main()
