#!/usr/bin/env python3
"""1위 곡이 바뀔 때마다 배경 음악을 갈아끼운 오디오 트랙을 만들어 영상에 합친다.

render_chart.py가 남긴 타임라인 JSON의 `segments`(1위 곡 구간)를 읽어서
  - 구간별로 그 곡의 30초 미리듣기(iTunes previewUrl)를 잘라 붙이고
  - 미리듣기가 없으면 그 구간만 무음으로 채운다(영상은 정상 진행)
  - 마지막에 영상과 합쳐(mux) 최종 mp4를 만든다.

사용 예
  python scripts/build_audio.py --video output/kr.mp4 --timeline output/kr.json --out output/kr_final.mp4
  python scripts/build_audio.py --mode off ...     # 오디오 없이 영상만
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import media
from render_chart import find_ffmpeg


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


def build(args) -> str:
    ffmpeg = find_ffmpeg()
    with open(args.timeline, encoding="utf-8") as fh:
        info = json.load(fh)
    segments = info.get("segments") or []
    if not segments:
        print("[audio] 1위 구간 정보가 없습니다. 영상만 사용합니다.")
        return args.video

    if args.mode == "off":
        if os.path.abspath(args.out) != os.path.abspath(args.video):
            shutil.copyfile(args.video, args.out)
        print("[audio] mode=off - 오디오 없이 영상만 저장했습니다.")
        return args.out

    if not segments:
        shutil.copyfile(args.video, args.out)
        return args.out

    tmp = tempfile.mkdtemp(prefix="soriaudio_")
    try:
        wavs: list[str] = []
        used = 0
        for idx, seg in enumerate(segments):
            artist, title = seg.get("artist", ""), seg.get("title", "")
            preview = None
            if args.mode != "silent":
                meta = media.lookup(artist, title, cache_dir=args.cache_dir,
                                    want_preview=True)
                preview = meta.get("preview_path")
            dur = float(seg["end"]) - float(seg["start"])
            wav = os.path.join(tmp, f"seg_{idx:02d}.wav")
            ok = make_segment(ffmpeg, wav, dur, preview, args.gain)
            used += 1 if ok else 0
            wavs.append(wav)
            tag = "미리듣기" if ok else "무음"
            print(f"[audio] {seg['start']:5.1f}~{seg['end']:5.1f}s  {artist} - {title}  [{tag}]")

        list_path = os.path.join(tmp, "list.txt")
        with open(list_path, "w", encoding="utf-8") as fh:
            for w in wavs:
                fh.write(f"file '{w}'\n")
        mix = os.path.join(tmp, "mix.wav")
        run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", list_path, "-af", "loudnorm=I=-15:TP=-1.0:LRA=9", "-c:a", "pcm_s16le", mix])

        if used == 0:
            print("[audio] 쓸 수 있는 미리듣기가 없어 영상만 저장합니다.", file=sys.stderr)
            if os.path.abspath(args.out) != os.path.abspath(args.video):
                shutil.copyfile(args.video, args.out)
            return args.out

        run([ffmpeg, "-y", "-loglevel", "error", "-i", args.video, "-i", mix,
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest",
             "-movflags", "+faststart", args.out])
        print(f"[audio] 완성: {args.out} ({os.path.getsize(args.out) / 1e6:.1f}MB, "
              f"{used}/{len(segments)}구간 미리듣기)")
        return args.out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="1위 곡 변경에 맞춰 배경 음악 전환")
    ap.add_argument("--video", required=True)
    ap.add_argument("--timeline", required=True, help="render_chart.py가 만든 .json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--mode", default="preview", choices=["preview", "silent", "off"],
                    help="preview: 미리듣기 전환(기본) / silent: 무음 / off: 오디오 없음")
    ap.add_argument("--gain", type=float, default=0.55, help="미리듣기 볼륨(기본 0.55)")
    args = ap.parse_args()
    build(args)


if __name__ == "__main__":
    main()
