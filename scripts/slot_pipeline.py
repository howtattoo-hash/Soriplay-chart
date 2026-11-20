#!/usr/bin/env python3
"""예약 실행(09:00·19:00 KST)에서 한 편을 만드는 단계별 도우미.

45초 영상은 한 번에 5~7분이 걸려 셸 호출 하나로는 시간이 모자랄 수 있다.
그래서 단계를 나눈다(각 호출 2분 안팎).

  python scripts/slot_pipeline.py prepare [--period weekly] [--country auto]
      → 오늘 차례 국가 계산 + 차트 수집 → output/.slot.json (국가·기간·프레임 수)

  python scripts/slot_pipeline.py chunk --index 0
  python scripts/slot_pipeline.py chunk --index 1
  python scripts/slot_pipeline.py chunk --index 2
      → 450프레임씩 나눠 렌더(각 호출 2분 안팎) → output/.slot_chunkN.mp4

  python scripts/slot_pipeline.py finish
      → 조각 합치기 + (1위 변경 시) 배경 음악 전환 → output/soriplay_..._{날짜}.mp4
        + output/summary.json  (업로드 스크립트가 이 파일을 읽는다)

  python scripts/slot_pipeline.py status
      → 지금 상태(준비/조각/완료)를 사람이 읽을 수 있게 출력

업로드는 따로:
  python scripts/upload_youtube.py --summary output/summary.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys

import build_audio
import chart_config
import chart_data
import fetch_spotify
import render_chart
import rotation

SLOT_FILE = os.path.join("output", ".slot.json")
CHUNK_FRAMES = 450
DEFAULT_DAYS = {"weekly": 4, "daily": 5}
DEFAULT_DURATION = {"weekly": 45.0, "daily": 30.0}


def _load_slot() -> dict | None:
    if os.path.exists(SLOT_FILE):
        with open(SLOT_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def _save_slot(data: dict) -> None:
    os.makedirs(os.path.dirname(SLOT_FILE), exist_ok=True)
    with open(SLOT_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def cmd_prepare(args) -> int:
    when = dt.datetime.fromisoformat(args.now).replace(tzinfo=rotation.KST) if args.now else None
    country = args.country
    if country == "auto":
        country = rotation.country_for(when or rotation.now_kst()) or ""
    if not country:
        print("[slot] 이번 시각에 올릴 국가가 없습니다.")
        return 3

    cfg = chart_config.country(country)
    print(f"[slot] 이번 차례: {country} ({cfg['name_en']}) · {args.period}")
    fetch_spotify.update_country(country, args.period, "data", 15, backfill=True, offline=False)

    hist = fetch_spotify.reindex_ranks(
        fetch_spotify.load_csv(chart_config.csv_path("data", country, args.period)))
    if hist.empty:
        print(f"[slot] {country}: 차트 데이터가 없습니다.")
        return 4
    chart_date = sorted(hist["chart_date"].unique())[-1]
    latest = hist[hist["chart_date"] == chart_date]
    score_mode = latest["streams"].fillna(0).sum() <= 0

    days = DEFAULT_DAYS[args.period]
    duration = DEFAULT_DURATION[args.period]
    df = chart_data.load_history(chart_config.csv_path("data", country, args.period),
                                 max_days=days)
    tl_probe = chart_data.build_timeline(df, country, top_n=10, duration=duration,
                                        fps=30, period=args.period)
    frames = tl_probe.frames
    chunks = max(1, math.ceil(frames / CHUNK_FRAMES))
    stem = f"soriplay_spotify_{country}_{args.period}_{str(chart_date).replace('-', '')}"

    _save_slot({"country": country, "country_label": cfg["label"], "period": args.period,
                "chart_date": str(chart_date), "duration": duration, "fps": 30,
                "frames": frames, "chunks": chunks, "stem": stem,
                "score_mode": bool(score_mode),
                "final": os.path.join("output", stem + ".mp4"),
                "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    print(f"[slot] 차트일 {chart_date} · {frames}프레임({duration:.0f}초) · 조각 {chunks}개"
          f"{' · 순위점수 모드' if score_mode else ''}")
    print(f"[slot] 국가={country} → 다음: chunk --index 0 … {chunks - 1}, 그다음 finish")
    return 0


def cmd_chunk(args) -> int:
    slot = _load_slot()
    if not slot:
        print("[slot] prepare 를 먼저 실행하세요.")
        return 2
    idx = args.index
    if idx < 0 or idx >= slot["chunks"]:
        print(f"[slot] 조각 번호가 범위를 벗어났습니다(0~{slot['chunks'] - 1}).")
        return 2
    start = idx * CHUNK_FRAMES
    end = min((idx + 1) * CHUNK_FRAMES, slot["frames"])
    out = os.path.join("output", f".slot_chunk{idx}.mp4")
    print(f"[slot] 조각 {idx + 1}/{slot['chunks']}: 프레임 {start}~{end}")
    ns = argparse.Namespace(
        country=slot["country"], period=slot["period"], data_dir="data", cache_dir="cache",
        out=out, top=10, duration=slot["duration"], fps=slot["fps"], days=4, crf=20,
        frames_dir="", preview="", from_frame=start, to_frame=end)
    render_chart.render(ns)
    if not os.path.exists(out):
        print("[slot] 조각 렌더 실패")
        return 5
    print(f"[slot] 조각 저장: {out}")
    return 0


def cmd_finish(args) -> int:
    slot = _load_slot()
    if not slot:
        print("[slot] prepare 를 먼저 실행하세요.")
        return 2
    ffmpeg = render_chart.find_ffmpeg()
    parts = [os.path.join("output", f".slot_chunk{i}.mp4") for i in range(slot["chunks"])]
    missing = [p for p in parts if not os.path.exists(p)]
    if missing:
        print(f"[slot] 아직 없는 조각: {missing} → chunk 단계를 먼저 끝내세요.")
        return 2

    joined = os.path.join("output", ".slot_joined.mp4")
    list_path = os.path.join("output", ".slot_list.txt")
    root = os.path.abspath("output")
    with open(list_path, "w", encoding="utf-8") as fh:
        for p in parts:
            fh.write(f"file '{os.path.join(root, os.path.basename(p))}'\n")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", list_path, "-c", "copy", joined], check=True)
    print(f"[slot] 조각 합치기 완료: {joined}")

    timeline = os.path.splitext(parts[0])[0] + ".json"
    if not os.path.exists(timeline):
        # 첫 조각 json이 없으면 타임라인만 다시 계산해 만든다.
        df = chart_data.load_history(
            chart_config.csv_path("data", slot["country"], slot["period"]), max_days=4)
        tl = chart_data.build_timeline(df, slot["country"], top_n=10,
                                       duration=slot["duration"], fps=slot["fps"],
                                       period=slot["period"])
        info = tl.to_dict()
        info.update({"video": joined, "period": slot["period"],
                     "country_label": slot["country_label"],
                     "top1": tl.order_at(tl.frames - 1, 1)[0]})
        timeline = os.path.join("output", ".slot_timeline.json")
        with open(timeline, "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=1)

    final = slot["final"]
    audio_args = argparse.Namespace(video=joined, timeline=timeline, out=final,
                                    cache_dir="cache", mode=os.environ.get("AUDIO_MODE", "preview"),
                                    market=slot["country"], gain=0.55)
    out_path = build_audio.build(audio_args)
    if os.path.abspath(out_path) != os.path.abspath(final):
        shutil.move(out_path, final)

    # 呺음 구간·음량 검사 — 실패하면 올릴 수 있는 상태가 아니다.
    audio_rep = {}
    audio_json = os.path.splitext(final)[0] + ".audio.json"
    if os.path.exists(audio_json):
        with open(audio_json, encoding="utf-8") as fh:
            audio_rep = json.load(fh)
    elif audio_args.mode == "preview":
        audio_rep = {"verified": build_audio.verify(final, float(slot["duration"]),
                                                    "완성본")}

    with open(timeline, encoding="utf-8") as fh:
        info = json.load(fh)
    info["video"] = final
    info["period"] = slot["period"]
    info["playlist_title"] = chart_config.country(slot["country"]).get("playlist", "")
    timeline_final = os.path.splitext(final)[0] + ".json"
    with open(timeline_final, "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)

    last_vals = {k: v[-1] for k, v in (info.get("series") or {}).items() if v}
    top2 = [k for k, _v in sorted(last_vals.items(), key=lambda kv: -kv[1])[:2]]
    result = {
        "country": slot["country"], "country_label": slot["country_label"],
        "period": slot["period"], "chart_date": slot["chart_date"],
        "video": final, "timeline": timeline_final,
        "top1": info.get("top1"), "top2": top2,
        "metric": info.get("metric", "streams"),
        "top1_changes": len(info.get("segments") or []),
        "duration": info.get("duration"),
        "size_mb": round(os.path.getsize(final) / 1e6, 2) if os.path.exists(final) else 0,
        "audio": {"verified": audio_rep.get("verified"),
                  "silent_segments": audio_rep.get("silent_segments"),
                  "substituted": audio_rep.get("substituted"),
                  "market": audio_rep.get("market"),
                  "segments": audio_rep.get("segments")},
    }
    with open(os.path.join("output", "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                   "period": slot["period"], "results": [result]}, fh,
                  ensure_ascii=False, indent=1)
    for p in parts + [joined, list_path, timeline if timeline.endswith("_timeline.json") else ""]:
        if p and os.path.exists(p):
            os.remove(p)
    if os.path.exists(SLOT_FILE):
        os.remove(SLOT_FILE)
    print(f"[slot] 완성: {final} ({result['size_mb']}MB) · 1위 {result['top1']}")
    aud = result.get("audio") or {}
    if aud.get("verified"):
        print(f"[slot] 오디오 검사 통과: {aud['verified']['duration']:.2f}s · "
              f"평균 {aud['verified']['mean_db']} dB · 무음 {aud['verified']['silence_total']}s "
              f"· 대체곡 {aud.get('substituted') or 0}구간 · 무음구간 {aud.get('silent_segments') or 0}")
    print(f"[slot] 요약: output/summary.json → 다음: upload_youtube.py --summary output/summary.json")
    return 0


def cmd_status(args) -> int:
    slot = _load_slot()
    if not slot:
        print("[slot] 준비된 작업 없음(output/.slot.json 없음).")
        return 0
    done = [i for i in range(slot["chunks"])
            if os.path.exists(os.path.join("output", f".slot_chunk{i}.mp4"))]
    print(f"[slot] {slot['country']} {slot['period']} {slot['chart_date']} · "
          f"{slot['frames']}프레임 · 조각 {len(done)}/{slot['chunks']} 완료")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="예약 실행용 단계별 파이프라인")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--country", default="auto")
    p.add_argument("--period", default="weekly", choices=["weekly", "daily"])
    p.add_argument("--now", default="")

    c = sub.add_parser("chunk")
    c.add_argument("--index", type=int, required=True)

    sub.add_parser("finish")
    sub.add_parser("status")

    args = ap.parse_args()
    handlers = {"prepare": cmd_prepare, "chunk": cmd_chunk,
                "finish": cmd_finish, "status": cmd_status}
    raise SystemExit(handlers[args.cmd](args))


if __name__ == "__main__":
    main()
