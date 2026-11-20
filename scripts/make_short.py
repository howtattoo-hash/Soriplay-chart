#!/usr/bin/env python3
"""한 번에 끝내는 파이프라인: 차트 수집 → 영상 렌더 → (1위 곡 변경 시) 배경 음악 전환 → 최종 mp4.

GitHub Actions는 이 스크립트 하나만 호출한다.

  python scripts/make_short.py --country kr
  python scripts/make_short.py --country both --audio preview
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys

import fetch_spotify
import render_chart
import build_audio


def main() -> None:
    ap = argparse.ArgumentParser(description="스포티파이 차트 숏폼 원샷 파이프라인")
    ap.add_argument("--country", default="kr", choices=["kr", "global", "both"])
    ap.add_argument("--audio", default=os.environ.get("AUDIO_MODE", "preview"),
                    choices=["preview", "silent", "off"])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--duration", type=float, default=18.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--offline", action="store_true", help="네트워크 없이 기존 CSV로만")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    countries = ["kr", "global"] if args.country == "both" else [args.country]
    results = []

    for country in countries:
        print(f"\n=========== {country.upper()} ===========")
        if not args.skip_fetch:
            fetch_spotify.update_country(country, args.data_dir, max(args.top, 15),
                                         backfill=True, offline=args.offline)

        hist = fetch_spotify.reindex_ranks(fetch_spotify.load_csv(
            os.path.join(args.data_dir, f"{country}_daily.csv")))
        chart_date = sorted(hist["chart_date"].unique())[-1]
        stem = f"soriplay_spotify_{country}_{str(chart_date).replace('-', '')}"
        raw = os.path.join(args.out_dir, f"{stem}_raw.mp4")
        final = os.path.join(args.out_dir, f"{stem}.mp4")

        render_args = argparse.Namespace(
            country=country, data_dir=args.data_dir, cache_dir=args.cache_dir,
            out=raw, top=args.top, duration=args.duration, fps=args.fps,
            days=args.days, crf=20, frames_dir="", preview="")
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
        with open(timeline_path, "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=1)
        for p in (raw, raw_timeline):
            if os.path.exists(p):
                os.remove(p)

        segs = info.get("segments", [])
        results.append({
            "country": country,
            "chart_date": str(chart_date),
            "video": final,
            "timeline": timeline_path,
            "top1": info.get("top1"),
            "top1_changes": len(segs),
            "duration": info.get("duration"),
            "size_mb": round(os.path.getsize(final) / 1e6, 2) if os.path.exists(final) else 0,
        })
        print(f"[done] {final} · 1위 {info.get('top1')} · 1위 변경 {len(segs)}회")

    summary = os.path.join(args.out_dir, "summary.json")
    with open(summary, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                   "results": results}, fh, ensure_ascii=False, indent=1)
    print(f"\n[summary] {summary}")
    for r in results:
        print(f"  - {r['country']}: {r['video']} ({r['size_mb']}MB)")


if __name__ == "__main__":
    main()
