#!/usr/bin/env python3
"""완성된 숏폼을 YouTube Shorts로 업로드하고, 나라별 재생목록(13개)에 넣는다.

제목·설명은 **그 나라 언어**로 만든다
  · 제목 맨 앞에 이번 주 1위·2위 아티스트 이름
  · 설명에 그 나라 말 소개 + Sori Play 스토어 링크 + 해시태그(제목·설명 합쳐 5개 이하)

자격 증명 (아무거나 하나)
  1) 환경변수 `YOUTUBE_TOKEN_JSON`  ← GitHub Actions 시크릿 (권장)
  2) 파일 `youtube_token.json`      ← 내 PC에서 발급한 토큰
  토큰에 client_id/secret 이 없으면 아래에서 채운다.
     · 환경변수 `YOUTUBE_CLIENT_SECRET_JSON`
     · 파일 `youtube_client_secret.json` (또는 `client_secret.json`)

재생목록
  config/playlists.json 의 나라별 `id` 를 쓰고, 환경변수 `YOUTUBE_PLAYLISTS_JSON`
  (예: {"kr": "PLxxxx", "global": "PLyyyy"}) 이 있으면 그쪽이 우선한다.
  아직 ID가 없으면 영상만 올리고 재생목록 단계는 조용히 건너뛴다(파이프라인은 멈추지 않음).
  재생목록 생성·영상 추가에는 `https://www.googleapis.com/auth/youtube` 스코프가 필요하다
  (youtube.upload / youtube.readonly 만으로는 불가). scripts/ensure_playlists.py 참고.

사용 예
  python scripts/upload_youtube.py --summary output/summary.json
  python scripts/upload_youtube.py --video output/x.mp4 --meta output/x.json
  python scripts/upload_youtube.py --summary output/summary.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import chart_config
import locales

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",          # 재생목록 생성/추가용
]
TOKEN_FILES = ["youtube_token.json", "config/youtube_token.json"]
CLIENT_SECRET_FILES = ["youtube_client_secret.json", "client_secret.json",
                       "config/youtube_client_secret.json"]
MAX_HASHTAGS = 5          # 제목 + 설명 합쳐서
MAX_TITLE = 100           # YouTube 제한
STATE_PATH = os.path.join("state", "uploads.json")


# --------------------------------------------------------------------------- #
# 자격 증명
# --------------------------------------------------------------------------- #
def _read_json_file(path: str) -> dict | None:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError as exc:
            print(f"[youtube] {path} 파싱 실패: {exc}", file=sys.stderr)
    return None


def _normalize_token(data: dict | None) -> dict | None:
    """여러 형태의 토큰 JSON을 google-auth 형식으로 맞춘다.

    지원: google-auth 저장 형식(token/scopes)과 OAuth 응답 형식
    (access_token/scope/expires_in — 앱이나 다른 도구가 떨어준 파일).
    """
    if not isinstance(data, dict):
        return None
    scopes = data.get("scopes") or data.get("scope") or []
    if isinstance(scopes, str):
        scopes = [s for s in scopes.replace(",", " ").split() if s]
    return {
        "token": data.get("token") or data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "client_id": data.get("client_id"),
        "client_secret": data.get("client_secret"),
        "token_uri": data.get("token_uri") or "https://oauth2.googleapis.com/token",
        "scopes": list(scopes) or SCOPES,
    }


def load_token_info(token_file: str = "") -> dict | None:
    raw = os.environ.get("YOUTUBE_TOKEN_JSON", "").strip()
    if raw:
        try:
            return _normalize_token(json.loads(raw))
        except json.JSONDecodeError as exc:
            print(f"[youtube] YOUTUBE_TOKEN_JSON 파싱 실패: {exc}", file=sys.stderr)
            return None
    for cand in ([token_file] if token_file else []) + TOKEN_FILES:
        data = _read_json_file(cand)
        if data:
            print(f"[youtube] 토큰 파일 사용: {cand}")
            return _normalize_token(data)
    return None


def load_client_secret(path: str = "") -> dict | None:
    raw = os.environ.get("YOUTUBE_CLIENT_SECRET_JSON", "").strip()
    if raw:
        if os.path.exists(raw):
            return _read_json_file(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print("[youtube] YOUTUBE_CLIENT_SECRET_JSON 파싱 실패", file=sys.stderr)
            return None
    for cand in ([path] if path else []) + CLIENT_SECRET_FILES:
        data = _read_json_file(cand)
        if data:
            return data
    return None


def load_credentials(token_file: str = "", client_secret_file: str = ""):
    info = load_token_info(token_file)
    if not info:
        return None
    # 파일로 받은 OAuth 클라이언트(installed/web)면 token_uri·client_id 를 채워 준다
    secret = load_client_secret(client_secret_file)
    if secret:
        block = secret.get("installed") or secret.get("web") or secret
        for key in ("client_id", "client_secret", "token_uri"):
            if not info.get(key) and block.get(key):
                info[key] = block[key]
    info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("[youtube] google-api-python-client가 설치되어 있지 않습니다.", file=sys.stderr)
        return None
    creds = Credentials.from_authorized_user_info(info, info.get("scopes") or SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001
                print(f"[youtube] 토큰 갱신 실패: {exc}", file=sys.stderr)
                return None
        else:
            print("[youtube] 토큰이 유효하지 않고 갱신할 수도 없습니다.", file=sys.stderr)
            return None
    return creds


# --------------------------------------------------------------------------- #
# 재생목록
# --------------------------------------------------------------------------- #
def playlist_id_for(country: str, config_path: str = "", explicit: str = "") -> str:
    if explicit:
        return explicit
    raw = os.environ.get("YOUTUBE_PLAYLISTS_JSON", "").strip()
    if raw:
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError:
            print("[youtube] YOUTUBE_PLAYLISTS_JSON 파싱 실패 - 설정 파일로 넘어갑니다.",
                  file=sys.stderr)
        else:
            found = (mapping.get("playlists") or mapping).get(country)
            if isinstance(found, dict):
                found = found.get("id")
            if found:
                return str(found)
    cfg = _read_json_file(config_path or os.path.join("config", "playlists.json")) or {}
    entry = (cfg.get("playlists") or {}).get(country) or {}
    return str(entry.get("id") or "") if isinstance(entry, dict) else str(entry or "")


def add_to_playlist(youtube, playlist_id: str, video_id: str) -> bool:
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": playlist_id,
                              "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
        ).execute()
        print(f"[youtube] 재생목록 {playlist_id} 에 추가했습니다.")
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        print(f"[youtube] 재생목록 추가 실패(영상은 정상 업로드됨): {msg[:400]}", file=sys.stderr)
        if "insufficient" in msg.lower() or "scope" in msg.lower():
            print("[youtube] 토큰 스코프에 'https://www.googleapis.com/auth/youtube' 가 필요합니다. "
                  "python scripts/get_youtube_token.py --client-secret ... --scopes upload,playlist "
                  "로 다시 발급해 YOUTUBE_TOKEN_JSON 을 갱신하세요.", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# 제목 · 설명
# --------------------------------------------------------------------------- #
def _hashtags(text: str) -> list[str]:
    return re.findall(r"#\w+", text or "")


def _clean_title(title: str) -> str:
    title = re.sub(r"\s{2,}", " ", title)
    title = re.sub(r"^[\s&·—-]+", "", title)
    title = re.sub(r"\s*&\s*\|", " |", title)
    return title.strip()


def _short(name: str, limit: int = 26) -> str:
    name = (name or "").strip()
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def build_metadata(meta: dict, period: str = "", top_n: int = 10) -> tuple[str, str, list[str]]:
    """타임라인 JSON 하나로 (제목, 설명, 태그)를 만든다."""
    code = meta.get("country") or "kr"
    cfg = chart_config.country(code)
    period = period or meta.get("period") or "weekly"
    loc = locales.get(cfg["lang"])
    pw, pw_cap = locales.period_words(cfg["lang"], period)

    import datetime as dt
    dates = [d for d in (meta.get("dates") or []) if d]
    last = dt.date.fromisoformat(dates[-1]) if dates else dt.date.today()
    if period == "weekly":
        # 주간 차트는 “하루”가 아니라 7일 범위로 표시한다(2026.11.12–11.18).
        try:
            start = dt.date.fromisoformat(meta.get("week_start") or dates[0])
            end = dt.date.fromisoformat(meta.get("week_end") or "")
        except ValueError:
            start, end = last, last + dt.timedelta(days=6)
        if end <= start:
            end = start + dt.timedelta(days=6)
        # 연·월을 함께: (11.12–11.18) → (2026.11.12–11.18)
        week = chart_config.week_label(start, end, cfg["week_fmt"])
        date_label = week
    else:
        date_label = chart_config.date_label(last, cfg["date_fmt"])
        week = chart_config.date_label(last, cfg["week_fmt"])

    labels = meta.get("labels") or {}
    series = meta.get("series") or {}
    metric = meta.get("metric", "streams")
    unit = " pt" if metric == "score" else ""
    ranked = sorted(((k, v[-1]) for k, v in series.items() if v), key=lambda kv: -kv[1])
    n = min(top_n, len(ranked)) or top_n

    def artist_of(key: str) -> str:
        val = labels.get(key) or [key]
        return val[0] if isinstance(val, list) else str(val)

    a1 = _short(artist_of(ranked[0][0])) if ranked else ""
    a2 = _short(artist_of(ranked[1][0])) if len(ranked) > 1 else ""

    ctx = dict(a1=a1, a2=a2, market=cfg["market"], pw=pw, pw_cap=pw_cap, n=n,
               date=date_label, week=week,
               metric=locales.metric_word(cfg["lang"], meta.get("metric", "streams")),
               playstore=locales.PLAYSTORE, site=locales.SITE)

    title = _clean_title(loc["title"].format(**ctx))
    # 100자가 넘으면 날짜·#Shorts를 잘라내지 말고 아티스트 이름을 줄인다.
    limit = 26
    while True:
        if not ctx["a2"]:
            title = title.replace("&  ", "").replace("·", "").replace("  ", " ")
        if len(title) <= MAX_TITLE or limit <= 10:
            break
        limit -= 4
        ctx["a1"] = _short(artist_of(ranked[0][0]), limit) if ranked else ""
        ctx["a2"] = _short(artist_of(ranked[1][0]), limit) if len(ranked) > 1 else ""
        title = _clean_title(loc["title"].format(**ctx))
    if len(title) > MAX_TITLE:
        title = title[:MAX_TITLE].rstrip()

    lines = [loc["desc_head"].format(**ctx), "", loc["top_head"].format(**ctx)]
    for i, (key, val) in enumerate(ranked[:5], 1):
        label = labels.get(key) or [key, ""]
        artist, song = (label[0], label[1]) if isinstance(label, list) and len(label) > 1 else (label[0], "")
        lines.append(f"{i}. {artist} — {song} · {val:,}{unit}")
    lines += [
        "",
        loc["cta"],
        loc["store"].format(playstore=locales.PLAYSTORE),
        loc["web"].format(site=locales.SITE),
        "",
        loc["note"].format(**ctx),
    ]
    if meta.get("metric") == "score":
        lines += [locales.score_note(cfg["lang"])]
    lines += [""]

    # 해시태그: 제목에 이미 있는 것(#Shorts)까지 합쳐 5개 이하
    used = len(_hashtags(title))
    tags_line: list[str] = []
    for tag in loc["hashtags"]:
        tag = tag.format(**ctx)
        if used + len(tags_line) >= MAX_HASHTAGS:
            break
        if tag not in tags_line:
            tags_line.append(tag)
    desc = "\n".join(lines + [" ".join(tags_line)])

    tags = ["Sori Play", "Spotify", cfg["name_en"], "chart", pw, "Shorts"]
    tags += [artist_of(k) for k, _v in ranked[:4] if artist_of(k)]
    tags = [t for i, t in enumerate(tags) if t and t not in tags[:i]][:15]
    return title, desc, tags


# --------------------------------------------------------------------------- #
# 업로드 상태(같은 주·같은 나라 중복 업로드 방지)
# --------------------------------------------------------------------------- #
def load_state(path: str = STATE_PATH) -> dict:
    data = _read_json_file(path)
    return data if isinstance(data, dict) else {}


def save_state(state: dict, path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


def state_key(country: str, period: str) -> str:
    return f"{country}|{period}"


# --------------------------------------------------------------------------- #
# 실행
# --------------------------------------------------------------------------- #
def upload_one(youtube, video: str, meta: dict, args, state: dict) -> dict | None:
    period = args.period or meta.get("period") or "weekly"
    country = meta.get("country") or "kr"
    chart_date = (meta.get("dates") or [""])[-1]
    key = state_key(country, period)

    if not args.force and state.get(key, {}).get("chart_date") == chart_date:
        print(f"[youtube] {country}/{period} {chart_date} 는 이미 올렸습니다 - 건너뜁니다.")
        return state[key]

    title, desc, tags = build_metadata(meta, period)
    if args.title:
        title = args.title
    if args.description:
        desc = args.description
    if args.dry_run:
        print(f"\n=== [dry-run] {country}/{period} ===")
        print(f"제목: {title} ({len(title)}자)")
        print(f"태그: {tags}")
        print("설명:\n" + desc)
        return None

    from googleapiclient.discovery import build as gbuild
    from googleapiclient.http import MediaFileUpload

    youtube = youtube or gbuild("youtube", "v3", credentials=args.creds)
    body = {
        "snippet": {"title": title, "description": desc, "tags": tags,
                    "categoryId": "10"},
        "status": {"privacyStatus": args.privacy, "selfDeclaredMadeForKids": False},
    }
    media_file = MediaFileUpload(video, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media_file)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"[youtube] 업로드 {int(status.progress() * 100)}%")
    vid = resp.get("id")
    print(f"[youtube] 업로드 완료: https://youtube.com/shorts/{vid}")
    print(f"YOUTUBE_URL=https://youtube.com/shorts/{vid}")

    pid = playlist_id_for(country, args.playlist_config, args.playlist_id)
    added = False
    if pid:
        added = add_to_playlist(youtube, pid, vid)
    else:
        print(f"[youtube] {country} 재생목록 ID가 없어 건너뜁니다 "
              f"(config/playlists.json 또는 YOUTUBE_PLAYLISTS_JSON).")

    state[key] = {"chart_date": chart_date, "video_id": vid, "title": title,
                  "playlist_id": pid, "playlist_added": added}
    save_state(state, args.state)
    return state[key]


def main() -> None:
    ap = argparse.ArgumentParser(description="YouTube Shorts 업로드 + 나라별 재생목록")
    ap.add_argument("--video", default="", help="업로드할 mp4 (--summary 없이 쓸 때)")
    ap.add_argument("--meta", default="", help="render_chart.py 타임라인 JSON")
    ap.add_argument("--summary", default="", help="make_short.py가 만든 output/summary.json")
    ap.add_argument("--period", default="", choices=["", "weekly", "daily"])
    ap.add_argument("--title", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--privacy", default=os.environ.get("YT_PRIVACY", "public"),
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--playlist-id", default="", help="이 영상 하나만 넣을 재생목록 ID")
    ap.add_argument("--playlist-config", default="", help="config/playlists.json 경로")
    ap.add_argument("--token-file", default="", help="youtube_token.json 경로")
    ap.add_argument("--client-secret-file", default="", help="youtube_client_secret.json 경로")
    ap.add_argument("--state", default=STATE_PATH, help="중복 업로드 방지 기록 파일")
    ap.add_argument("--force", action="store_true", help="같은 주·같은 나라도 다시 올린다")
    ap.add_argument("--dry-run", action="store_true", help="올리지 않고 제목/설명만 확인")
    args = ap.parse_args()

    jobs: list[tuple[str, dict]] = []
    if args.summary:
        try:
            with open(args.summary, encoding="utf-8") as fh:
                summary = json.load(fh)
        except FileNotFoundError:
            print(f"[youtube] {args.summary} 가 없습니다.", file=sys.stderr)
            return
        for res in summary.get("results") or []:
            if res.get("skipped"):
                print(f"[youtube] {res.get('country')} 건너뜀({res['skipped']})")
                continue
            meta_path = res.get("timeline") or os.path.splitext(res.get("video", ""))[0] + ".json"
            if not os.path.exists(meta_path):
                continue
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            video = res.get("video") or meta.get("video")
            if video and os.path.exists(video):
                jobs.append((video, meta))
    elif args.video:
        meta = {}
        meta_path = args.meta or os.path.splitext(args.video)[0] + ".json"
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        jobs.append((args.video, meta))
    else:
        print("[youtube] --summary 또는 --video 가 필요합니다.", file=sys.stderr)
        return

    if not jobs:
        print("[youtube] 올릴 영상이 없습니다.")
        return

    if args.dry_run:
        for video, meta in jobs:
            upload_one(None, video, meta, args, {})
        return

    creds = load_credentials(args.token_file, args.client_secret_file)
    if creds is None:
        print("[youtube] 자격 증명이 없어 업로드를 건너뜁니다(영상은 output/ 에 그대로 있음).")
        return
    args.creds = creds
    from googleapiclient.discovery import build as gbuild
    youtube = gbuild("youtube", "v3", credentials=creds)

    state = load_state(args.state)
    for video, meta in jobs:
        try:
            upload_one(youtube, video, meta, args, state)
        except Exception as exc:  # noqa: BLE001 - 한 편 실패가 전체를 멈추지 않게
            print(f"[youtube] {video} 업로드 실패: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
