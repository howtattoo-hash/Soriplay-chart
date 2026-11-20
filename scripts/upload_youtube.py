#!/usr/bin/env python3
"""완성된 숏폼을 YouTube Shorts로 업로드한다 (YouTube Data API v3).

필요한 시크릿
  YOUTUBE_TOKEN_JSON  : 아래 형식의 JSON 문자열
      {"token": "...", "refresh_token": "...", "client_id": "...",
       "client_secret": "...", "token_uri": "https://oauth2.googleapis.com/token",
       "scopes": ["https://www.googleapis.com/auth/youtube.upload"]}
  (토큰이 하나도 없으면 이 스크립트는 조용히 건너뛴다 → 자동화는 영상 생성까지만 진행)

사용 예
  python scripts/upload_youtube.py --video output/kr_final.mp4 --meta output/kr_final.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HASHTAGS = "#SoriPlay #스포티파이차트 #음악차트 #Shorts"


def load_credentials():
    raw = os.environ.get("YOUTUBE_TOKEN_JSON", "").strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[youtube] YOUTUBE_TOKEN_JSON 파싱 실패: {exc}", file=sys.stderr)
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("[youtube] google-api-python-client가 설치되어 있지 않습니다.", file=sys.stderr)
        return None
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("[youtube] 토큰이 유효하지 않고 갱신할 수도 없습니다.", file=sys.stderr)
            return None
    return creds


def build_text(meta: dict) -> tuple[str, str, list[str]]:
    country = meta.get("country", "kr")
    label = "한국" if country == "kr" else "글로벌"
    date = (meta.get("dates") or [""])[-1]
    short_date = date.replace("-", ".")[2:] if date else ""
    top_keys = meta.get("top1") or ""
    title = f"스포티파이 {label} 차트 TOP 10 ({short_date}) #Shorts"
    if len(title) > 95:
        title = title[:95]
    top_lines = []
    series = meta.get("series") or {}
    if series:
        last = {k: (v[-1] if v else 0) for k, v in series.items()}
        for i, (k, v) in enumerate(sorted(last.items(), key=lambda kv: -kv[1])[:5], 1):
            top_lines.append(f"{i}. {k} — {v:,}회")
    desc = "\n".join([
        f"스포티파이 {label} 일간 차트 스트리밍 TOP 10, {date} 기준",
        "",
        "[오늘의 TOP 5]",
        *top_lines,
        "",
        "매일 아침 자동 업데이트됩니다.",
        "Sori Play에서 지금 무료로 들어보세요 ▶ https://soriplay.com",
        "",
        HASHTAGS + " #스포티파이 #차트 #케이팝",
    ])
    return title, desc, [h.strip("#") for h in HASHTAGS.split()]


def main() -> None:
    ap = argparse.ArgumentParser(description="YouTube Shorts 업로드")
    ap.add_argument("--video", required=True)
    ap.add_argument("--meta", default="", help="render_chart.py 타임라인 JSON")
    ap.add_argument("--title", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--privacy", default=os.environ.get("YT_PRIVACY", "public"),
                    choices=["public", "unlisted", "private"])
    args = ap.parse_args()

    creds = load_credentials()
    if creds is None:
        print("[youtube] 자격 증명이 없어 업로드를 건너뜁니다.")
        return

    from googleapiclient.discovery import build as gbuild
    from googleapiclient.http import MediaFileUpload

    meta = {}
    if args.meta and os.path.exists(args.meta):
        meta = json.load(open(args.meta, encoding="utf-8"))
    title, desc, tags = build_text(meta) if meta else ("Sori Play 차트 #Shorts", HASHTAGS, ["Shorts"])
    title = args.title or title
    desc = args.description or desc

    youtube = gbuild("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title, "description": desc, "tags": tags,
                    "categoryId": "10"},
        "status": {"privacyStatus": args.privacy, "selfDeclaredMadeForKids": False},
    }
    media_file = MediaFileUpload(args.video, chunksize=-1, resumable=True,
                                 mimetype="video/mp4")
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media_file)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"[youtube] 업로드 {int(status.progress() * 100)}%")
    vid = resp.get("id")
    print(f"[youtube] 업로드 완료: https://youtube.com/shorts/{vid}")
    print(f"YOUTUBE_URL=https://youtube.com/shorts/{vid}")


if __name__ == "__main__":
    main()
