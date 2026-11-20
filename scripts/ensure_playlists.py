#!/usr/bin/env python3
"""13개국 유튜브 재생목록을 채널에 만들고, 그 ID를 config/playlists.json 에 적는다.

한 번만 돌리면 된다. 이후 upload_youtube.py 가 나라별로 알맞은 재생목록에 영상을 넣는다.

  python scripts/ensure_playlists.py --dry-run      # 무엇을 만들지 미리 보기
  python scripts/ensure_playlists.py                # 만들고 설정 파일에 ID 기록
  python scripts/ensure_playlists.py --print-env    # GitHub Secret 용 YOUTUBE_PLAYLISTS_JSON 출력

권한 안내
  재생목록 조회는 `youtube.readonly`, 생성은 `https://www.googleapis.com/auth/youtube`
  (또는 youtube.force-ssl) 스코프가 필요하다. 현재 발급된 토큰이
  `youtube.upload + youtube.readonly` 라면 목록만 읽고 생성은 "권한 부족"으로 실패한다.
  그때는 토큰을 다시 발급하면 된다:
      python scripts/get_youtube_token.py --client-secret youtube_client_secret.json \
          --scopes upload,playlist
  → 출력된 JSON 한 줄을 GitHub Secrets 의 YOUTUBE_TOKEN_JSON 에 덮어쓰기.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import chart_config
import upload_youtube

DESC = ("Sori Play · {market} 스포티파이 주간 차트 TOP 10을 매주 모아둡니다. "
        "매일 두 나라씩, 13개국 차트가 순서대로 올라옵니다. "
        "무료로 듣기: " + "https://play.google.com/store/apps/details?id=com.soriplay.app")


def load_cfg(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"playlists": {}}


def list_playlists(youtube) -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        resp = youtube.playlists().list(part="snippet,status", mine=True,
                                        maxResults=50, pageToken=token).execute()
        out.extend(resp.get("items", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="13개국 재생목록 생성/확인")
    ap.add_argument("--config", default=os.path.join("config", "playlists.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-create", action="store_true", help="없는 재생목록을 만들지 않고 보고만")
    ap.add_argument("--no-write", action="store_true", help="config/playlists.json 을 고치지 않음")
    ap.add_argument("--print-env", action="store_true",
                    help="YOUTUBE_PLAYLISTS_JSON 값(한 줄)을 출력")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--token-file", default="")
    ap.add_argument("--client-secret-file", default="")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    entries = cfg.get("playlists") or {}
    order = chart_config.order()
    plan = []
    for code in order:
        entry = entries.get(code) or {}
        title = entry.get("title") or chart_config.country(code).get("playlist") or code
        plan.append({"code": code, "title": title, "id": entry.get("id") or ""})

    if args.dry_run:
        print(f"{'코드':<8}{'상태':<8}재생목록 이름")
        for row in plan:
            print(f"{row['code']:<8}{'있음' if row['id'] else '없음':<8}{row['title']}")
        print(f"\n총 {len(plan)}개 · ID 있음 {sum(1 for r in plan if r['id'])}개")
        return

    creds = upload_youtube.load_credentials(args.token_file, args.client_secret_file)
    if creds is None:
        print("[playlists] 자격 증명을 찾지 못했습니다. "
              "YOUTUBE_TOKEN_JSON 또는 youtube_token.json 이 필요합니다.", file=sys.stderr)
        return

    from googleapiclient.discovery import build as gbuild
    youtube = gbuild("youtube", "v3", credentials=creds)

    try:
        existing = list_playlists(youtube)
    except Exception as exc:  # noqa: BLE001
        print(f"[playlists] 재생목록 조회 실패: {exc}", file=sys.stderr)
        return
    by_title = {}
    for item in existing:
        t = (item.get("snippet", {}).get("title") or "").strip().lower()
        by_title.setdefault(t, item.get("id"))

    changed = False
    created = 0
    for row in plan:
        title = row["title"].strip()
        found = by_title.get(title.lower())
        if found:
            print(f"[playlists] 이미 있음  {row['code']:<7}{title}  ({found})")
            if row["id"] != found:
                entries.setdefault(row["code"], {})["id"] = found
                entries[row["code"]]["title"] = title
                changed = True
            continue
        if args.no_create:
            print(f"[playlists] 없음      {row['code']:<7}{title}")
            continue
        try:
            resp = youtube.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {"title": title,
                                "description": DESC.format(
                                    market=chart_config.country(row["code"])["market"]),
                                "defaultLanguage": "ko"},
                    "status": {"privacyStatus": args.privacy},
                }).execute()
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            print(f"[playlists] 생성 실패 {row['code']} {title}: {msg[:300]}", file=sys.stderr)
            if "insufficient" in msg.lower() or "scope" in msg.lower():
                print("[playlists] 이 작업에는 https://www.googleapis.com/auth/youtube 스코프가 "
                      "필요합니다.\n  python scripts/get_youtube_token.py --client-secret "
                      "youtube_client_secret.json --scopes upload,playlist\n  → 나온 JSON을 "
                      "YOUTUBE_TOKEN_JSON 에 다시 저장하세요.", file=sys.stderr)
                return
            continue
        pid = resp.get("id")
        created += 1
        print(f"[playlists] 새로 만듦 {row['code']:<7}{title}  ({pid})")
        entries.setdefault(row["code"], {})["id"] = pid
        entries[row["code"]]["title"] = title
        changed = True

    if changed and not args.no_write:
        cfg["playlists"] = entries
        cfg["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(args.config) or ".", exist_ok=True)
        with open(args.config, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        print(f"[playlists] {args.config} 갱신 (새로 {created}개)")

    if args.print_env:
        env = {code: (entries.get(code) or {}).get("id") for code in order
               if (entries.get(code) or {}).get("id")}
        print("\nYOUTUBE_PLAYLISTS_JSON=" + json.dumps(env, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
