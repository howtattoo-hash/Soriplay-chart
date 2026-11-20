#!/usr/bin/env python3
"""1위 곡이 바뀔 때마다 배경 음악을 갈아끼운 오디오 트랙을 만들어 영상에 합친다.

render_chart.py가 남긴 타임라인 JSON의 `segments`(1위 곡 구간)를 읽어서
  - 구간별로 그 곡의 30초 미리듣기(iTunes previewUrl)를 잘라 붙이고
  - 그 곡의 미리듣기를 어느 스토어프런트에서도 못 구하면, 그 시점 순위가 높은
    다음 곡(#2, #3 …) 중 미리듣기가 있는 곡으로 자동 대체한다 → 무음 구간 없음
  - 마지막에 영상과 합쳐(mux) 최종 mp4를 만들고, 오디오가 영상 전체 길이에
    걸쳐 실제로 들리는지(무음 구간·음량) 검사한다. 실패하면 완성을 중단한다.

사용 예
  python scripts/build_audio.py --video output/kr.mp4 --timeline output/kr.json --out output/kr_final.mp4
  python scripts/build_audio.py --video output/kr.mp4 --timeline output/kr.json --out output/kr_final.mp4 --market ph
  python scripts/build_audio.py --mode off ...     # 오디오 없이 영상만
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import media
from render_chart import find_ffmpeg

# 무음 판정: -50dB 아래가 1.5초 이상 이어지면 "들리지 않는 구간"으로 본다.
SILENCE_NOISE = "-50dB"
SILENCE_MIN = 1.5
MIN_MEAN_DB = -45.0          # 전체 평균 음량이 이보다 작으면 사실상 무음
MAX_SILENCE_TOTAL = 1.0      # 전체 무음 합계 허용치(초)


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {' '.join(cmd)}\n{res.stderr[-2000:]}")


def make_segment(ffmpeg: str, out_wav: str, duration: float, preview: str | None,
                 gain: float) -> bool:
    """한 구간 오디오(무음 또는 미리듣기 루프)를 만든다. 미리듣기 사용 여부 반환."""
    duration = max(duration, 0.25)
    fade_out = max(duration - 0.35, 0.0)
    if preview and os.path.exists(preview):
        af = (f"atrim=0:{duration:.3f},asetpts=N/SR/TB,volume={gain},"
              f"afade=t=in:st=0:d=0.25,afade=t=out:st={fade_out:.3f}:d=0.35,"
              f"aresample=44100,aformat=channel_layouts=stereo")
        run([ffmpeg, "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", preview,
             "-t", f"{duration:.3f}", "-af", af, "-ar", "44100", "-ac", "2",
             "-c:a", "pcm_s16le", out_wav])
        return True
    run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{duration:.3f}",
         "-c:a", "pcm_s16le", out_wav])
    return False


# --------------------------------------------------------------------------- #
# 구간 곡 고르기(무음이 생기지 않게 대체 곡까지)
# --------------------------------------------------------------------------- #
def _value_at(info: dict, key: str, t_sec: float) -> int:
    series = (info.get("series") or {}).get(key) or []
    if not series:
        return -1
    fps = int(info.get("fps") or 30)
    frame = int(round(max(0.0, t_sec) * fps))
    return series[min(frame, len(series) - 1)]


def candidates_for(info: dict, seg: dict, avoid: set[str] | None = None) -> list[tuple[str, str, str]]:
    """이 구간에 쓸 곡 후보를 (아티스트, 제목, 키) 순서로 돌려준다.

    1순위는 그 구간의 실제 1위 곡. 그 곡에 미리듣기가 없으면 그 시점 순위
    (#2, #3 …)가 높은 순으로 이어 붙인다. 바로 앞·뒤 구간에서 쓰는 곡은 ‘겹침’이라
    맨 뒤로 미뤄서, 가능하면 곡이 바뀌는 소리가 나게 한다.
    """
    avoid = avoid or set()
    labels = info.get("labels") or {}
    lead = (seg.get("artist") or "", seg.get("title") or "", seg.get("key") or "")
    out: list[tuple[str, str, str]] = [lead]

    ranked = sorted((k for k in (info.get("keys") or [])),
                    key=lambda k: -_value_at(info, k, float(seg.get("start") or 0.0)))
    tail: list[tuple[str, str, str]] = []
    for k in ranked:
        if k == lead[2]:
            continue
        label = labels.get(k) or [k, ""]
        artist, title = (label[0], label[1]) if isinstance(label, list) and len(label) > 1 else (label[0], "")
        if not artist:
            continue
        tail.append((artist, title, k))
    tail.sort(key=lambda item: item[2] in avoid)      # 앞·뒤 구간 곡은 뒤로
    return out + tail


def resolve_segment(ffmpeg: str, out_wav: str, duration: float, cands: list,
                    cache_dir: str, market: str, gain: float) -> dict:
    """후보를 차례로 시도해 실제로 소리가 나는 구간 WAV를 만든다."""
    for rank, (artist, title, key) in enumerate(cands):
        meta = media.lookup(artist, title, cache_dir=cache_dir, want_preview=True,
                            market=market)
        preview = meta.get("preview_path")
        if not preview:
            continue
        try:
            make_segment(ffmpeg, out_wav, duration, preview, gain)
        except RuntimeError as exc:  # 미리듣기 파일이 깨졌으면 다음 후보로
            print(f"   ! {artist} - {title} 미리듣기 사용 실패: {str(exc)[:160]}")
            continue
        return {"ok": True, "artist": artist, "title": title, "key": key,
                "substitute": rank > 0, "matched_store": meta.get("store", "")}
    make_segment(ffmpeg, out_wav, duration, None, gain)
    return {"ok": False, "artist": cands[0][0] if cands else "",
            "title": cands[0][1] if cands else "", "key": cands[0][2] if cands else "",
            "substitute": False, "matched_store": ""}


# --------------------------------------------------------------------------- #
# 검사: 영상 전체 길이에 오디오가 실제로 있는가
# --------------------------------------------------------------------------- #
def probe(path: str) -> dict:
    """ffmpeg -i 로 길이·스트림 정보만 읽는다(ffprobe 없이도 동작)."""
    ffmpeg = find_ffmpeg()
    res = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                         capture_output=True, text=True)
    err = res.stderr or ""
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return {"duration": dur,
            "has_audio": "Audio:" in err,
            "has_video": "Video:" in err}


def analyze(path: str) -> dict:
    """길이·평균 음량·무음 구간을 잰다."""
    ffmpeg = find_ffmpeg()
    info = probe(path)
    res = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-vn",
                          "-af", f"volumedetect,silencedetect=noise={SILENCE_NOISE}:d={SILENCE_MIN}",
                          "-f", "null", "-"], capture_output=True, text=True)
    err = res.stderr or ""
    mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", err)
    peak = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", err)
    silences: list[tuple[float, float]] = []
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", err)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?\d+(?:\.\d+)?)", err)]
    for i, st in enumerate(starts):
        en = ends[i] if i < len(ends) else info["duration"]
        silences.append((round(max(st, 0.0), 2), round(en, 2)))
    total_silence = sum(max(0.0, en - st) for st, en in silences)
    return {
        "duration": round(info["duration"], 2),
        "has_audio": info["has_audio"],
        "mean_db": float(mean.group(1)) if mean else None,
        "peak_db": float(peak.group(1)) if peak else None,
        "silences": silences,
        "silence_total": round(total_silence, 2),
    }


def verify(path: str, expected: float | None = None, label: str = "") -> dict:
    """오디오가 처음부터 끝까지 들리는지 확인. 문제면 RuntimeError."""
    rep = analyze(path)
    tag = f"[audio] {label + ' ' if label else ''}"
    problems: list[str] = []
    if not rep["has_audio"]:
        problems.append("오디오 스트림이 없습니다")
    if expected and rep["duration"] < expected - 0.4:
        problems.append(f"길이가 짧습니다({rep['duration']:.2f}s < {expected:.2f}s)")
    if rep["mean_db"] is None or rep["mean_db"] < MIN_MEAN_DB:
        problems.append(f"평균 음량이 너무 작습니다({rep['mean_db']} dB)")
    long_spans = [(s, e) for s, e in rep["silences"] if e - s >= SILENCE_MIN]
    if long_spans:
        problems.append(f"{len(long_spans)}초 이상 무음 구간: {long_spans}")
    if rep["silence_total"] > MAX_SILENCE_TOTAL:
        problems.append(f"무음 합계 {rep['silence_total']:.2f}s > {MAX_SILENCE_TOTAL}s")
    print(f"{tag}길이 {rep['duration']:.2f}s · 평균 {rep['mean_db']} dB · "
          f"최고 {rep['peak_db']} dB · 무음 {rep['silence_total']}s")
    if problems:
        raise RuntimeError(f"{tag}오디오 검사 실패: " + " / ".join(problems))
    return rep


def build(args) -> str:
    ffmpeg = find_ffmpeg()
    with open(args.timeline, encoding="utf-8") as fh:
        info = json.load(fh)
    segments = info.get("segments") or []
    expected = float(info.get("duration") or 0) or None

    if args.mode == "off":
        if os.path.abspath(args.out) != os.path.abspath(args.video):
            shutil.copyfile(args.video, args.out)
        print("[audio] mode=off - 오디오 없이 영상만 저장했습니다.")
        return args.out

    if not segments:
        print("[audio] 1위 구간 정보가 없습니다. 영상만 사용합니다.")
        if os.path.abspath(args.out) != os.path.abspath(args.video):
            shutil.copyfile(args.video, args.out)
        return args.out

    market = args.market or info.get("country") or ""
    tmp = tempfile.mkdtemp(prefix="soriaudio_")
    try:
        wavs: list[str] = []
        used = 0
        report: list[dict] = []
        prev_key = ""
        for idx, seg in enumerate(segments):
            dur = float(seg["end"]) - float(seg["start"])
            wav = os.path.join(tmp, f"seg_{idx:02d}.wav")
            avoid = {prev_key} if prev_key else set()
            if idx + 1 < len(segments) and segments[idx + 1].get("key"):
                avoid.add(segments[idx + 1]["key"])   # 다음 구간 곡도 가능하면 피한다
            cands = candidates_for(info, seg, avoid)
            got = resolve_segment(ffmpeg, wav, dur, cands, args.cache_dir, market, args.gain)
            used += 1 if got["ok"] else 0
            prev_key = got["key"] or prev_key
            wavs.append(wav)
            if got["ok"] and not got["substitute"]:
                tag = "미리듣기"
                name = f"{got['artist']} - {got['title']}"
            elif got["ok"]:
                tag = "대체곡"
                name = (f"{seg.get('artist')} - {seg.get('title')} → "
                        f"{got['artist']} - {got['title']}")
            else:
                tag = "무음"
                name = f"{seg.get('artist')} - {seg.get('title')}"
            print(f"[audio] {seg['start']:5.1f}~{seg['end']:5.1f}s  {name}  [{tag}]")
            report.append({"start": seg["start"], "end": seg["end"],
                           "segment_key": seg.get("key"), "used_key": got["key"],
                           "artist": got["artist"], "title": got["title"],
                           "substitute": got["substitute"], "audible": got["ok"],
                           "matched_store": got.get("matched_store", "")})

        if used == 0:
            if args.mode == "silent":
                print("[audio] mode=silent - 소리는 넣지 않고 영상만 저장합니다.")
                if os.path.abspath(args.out) != os.path.abspath(args.video):
                    shutil.copyfile(args.video, args.out)
                return args.out
            raise RuntimeError("[audio] 어떤 구간에서도 미리듣기를 구하지 못했습니다 - "
                               "무음 영상은 만들지 않습니다.")

        list_path = os.path.join(tmp, "list.txt")
        with open(list_path, "w", encoding="utf-8") as fh:
            for w in wavs:
                fh.write(f"file '{w}'\n")
        mix = os.path.join(tmp, "mix.wav")
        # apad: 음원이 영상보다 짧으면 끝을 무음이 아닌 마지막 소리로 채워 길이를 영상에 맞춘다.
        mix_cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                   "-i", list_path, "-af", "loudnorm=I=-15:TP=-1.0:LRA=9,apad"]
        if expected:
            mix_cmd += ["-t", f"{expected:.3f}"]
        run(mix_cmd + ["-c:a", "pcm_s16le", mix])
        verify(mix, expected, "믹스")

        run([ffmpeg, "-y", "-loglevel", "error", "-i", args.video, "-i", mix,
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest",
             "-movflags", "+faststart", args.out])
        rep = verify(args.out, expected, "완성본")
        print(f"[audio] 완성: {args.out} ({os.path.getsize(args.out) / 1e6:.1f}MB, "
              f"{used}/{len(segments)}구간 소리 있음)")
        with open(os.path.splitext(args.out)[0] + ".audio.json", "w", encoding="utf-8") as fh:
            json.dump({"market": market, "segments": report,
                       "silent_segments": sum(1 for r in report if not r["audible"]),
                       "substituted": sum(1 for r in report if r["substitute"]),
                       "verified": rep}, fh, ensure_ascii=False, indent=1)
        return args.out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="1위 곡 변경에 맞춰 배경 음악 전환")
    ap.add_argument("--video", required=True)
    ap.add_argument("--timeline", required=True, help="render_chart.py가 만든 .json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--market", default="", help="iTunes 스토어프런트(타임라인의 country 사용)")
    ap.add_argument("--mode", default="preview", choices=["preview", "silent", "off"],
                    help="preview: 미리듣기 전환(기본) / silent: 무음 / off: 오디오 없음")
    ap.add_argument("--gain", type=float, default=0.55, help="미리듣기 볼륨(기본 0.55)")
    args = ap.parse_args()
    try:
        build(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(7)


if __name__ == "__main__":
    main()
