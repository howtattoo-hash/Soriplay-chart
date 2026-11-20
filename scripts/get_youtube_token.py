#!/usr/bin/env python3
"""YouTube 업로드용 OAuth 토큰(JSON)을 만들어 주는 도우미.

준비물 (한 번만)
  1. Google Cloud Console → 새 프로젝트 → "YouTube Data API v3" 사용 설정
  2. 사용자 인증 정보 → OAuth 클라이언트 ID 만들기 → 애플리케이션 유형 "데스크톱 앱"
  3. JSON 다운로드 (예: client_secret.json)
  4. API 액세스 동의 화면에서 본인 계정을 "테스트 사용자"로 추가

실행 (내 PC에서, 브라우저가 뜨는 환경)
  python scripts/get_youtube_token.py --client-secret client_secret.json

그러면 콘솔에 {"token": ... } 형태의 JSON 한 줄이 출력된다.
그 값을 GitHub 저장소 → Settings → Secrets and variables → Actions 에서
이름 `YOUTUBE_TOKEN_JSON` 로 저장하면 매일 자동 업로드가 켜진다.
"""
from __future__ import annotations

import argparse
import json

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-secret", required=True, help="OAuth 클라이언트 JSON 파일")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, SCOPES)
    creds = flow.run_local_server(port=args.port, prompt="consent",
                                  authorization_prompt_message="브라우저에서 구글 로그인 후 권한을 허용하세요...")
    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": SCOPES,
    }
    print("\n=== 아래 한 줄 전체를 YOUTUBE_TOKEN_JSON 시크릿에 붙여넣으세요 ===\n")
    print(json.dumps(payload, ensure_ascii=False))
    print("\n(이 값은 비밀번호와 같습니다. 채팅·이슈·커밋에 올리지 마세요.)")


if __name__ == "__main__":
    main()
