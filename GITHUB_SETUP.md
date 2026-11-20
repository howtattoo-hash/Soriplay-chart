> **운영 방식 변경(2026-11-20)**: 매일 09:00·19:00 KST 업로드는 **Pickle 예약 작업**이 담당한다.
> 이 저장소는 코드 백업용이고, 아래 GitHub Actions 설정은 선택 사항이다
> (두 곳에서 동시에 돌리면 같은 나라가 두 번 올라가니 한쪽만 쓴다).

# GitHub에 올리는 방법 / 현재 상태

- 저장소: **`howtattoo-hash/Soriplay-chart`** (사용자가 생성)
- 이 폴더는 그 저장소의 `main` 브랜치로 push 되어 있고, Actions 워크플로가 켜져 있다.

## 처음 한 번만 하는 설정

### 1) 저장소 Secrets

저장소 → **Settings → Secrets and variables → Actions → Secrets**

| 이름 | 값 | 출처 |
|---|---|---|
| `YOUTUBE_TOKEN_JSON` | 토큰 JSON **한 줄 전체** | `downloads/youtube_token.json` 내용 |
| `YOUTUBE_CLIENT_SECRET_JSON` | OAuth 클라이언트 JSON | `downloads/youtube_client_secret.json` 내용 |

명령줄로 넣을 수도 있다(이미 실행해 두었다면 건너뛰기):

```bash
gh secret set YOUTUBE_TOKEN_JSON        -R howtattoo-hash/Soriplay-chart < downloads/youtube_token.json
gh secret set YOUTUBE_CLIENT_SECRET_JSON -R howtattoo-hash/Soriplay-chart < downloads/youtube_client_secret.json
gh secret list -R howtattoo-hash/Soriplay-chart
```

### 2) (선택) Variables

저장소 → **Settings → Secrets and variables → Actions → Variables**

| 이름 | 값 | 효과 |
|---|---|---|
| `YT_PRIVACY` | `unlisted` | 모든 업로드를 미공개로 (시험 운영) |
| `YOUTUBE_PLAYLISTS_JSON` | `{"kr":"PL...","global":"PL..."}` | 재생목록 ID를 파일 대신 변수로 |

## 지금 상태에서 남은 한 가지: 재생목록

현재 토큰 스코프는 `youtube.upload + youtube.readonly` 라서
**영상 업로드는 되지만 재생목록 생성·추가는 권한 부족으로 실패**한다
(영상은 정상 업로드되고, 로그에 안내만 남는다).

13개국 재생목록까지 자동으로 쓰려면 토큰을 한 번 다시 발급한다.

```bash
python scripts/get_youtube_token.py --client-secret youtube_client_secret.json --scopes upload,playlist
# → 출력된 JSON 한 줄을 YOUTUBE_TOKEN_JSON 시크릿에 덮어쓰기
```

그다음 Actions → *13-Market Weekly Chart Shorts* → Run workflow →
`setup_playlists` 체크 → 실행하면 13개 재생목록이 만들어지고
`config/playlists.json` 에 ID가 커밋된다(수동으로 돌릴 때는 로컬에서
`python scripts/ensure_playlists.py`).

## 자동 실행 확인

1. 저장소 → **Actions** 탭 → *13-Market Weekly Chart Shorts*
2. **Run workflow** → `country`=auto(또는 kr), `period`=weekly,
   `upload`=skip(안전 확인) 또는 `unlisted`(실제 업로드 확인) → 실행
3. 5~10분 뒤 실행 결과에서 artifact **sori-shorts-N** 안의
   `soriplay_spotify_{국가}_weekly_YYYYMMDD.mp4` 를 내려받으면 완성본이다.
4. 이후 매일 09:00·19:00 KST 에 두 나라씩 자동으로 올라간다(일요일은 09:00 한 편).

명령줄로 확인:

```bash
gh workflow run weekly-chart.yml -R howtattoo-hash/Soriplay-chart -f country=kr -f upload=skip
gh run list -R howtattoo-hash/Soriplay-chart --limit 5
gh run watch <run-id> -R howtattoo-hash/Soriplay-chart
gh run download <run-id> -R howtattoo-hash/Soriplay-chart -n sori-shorts-<n>
```

## GitHub Actions를 안 쓰고 서버에서 돌리는 방법

이미 운영 중인 서버(예: `soriplay.com` 서버)에서 돌려도 된다.

```bash
# 1) 코드 복사 (zip 업로드 또는 git clone)
git clone https://github.com/howtattoo-hash/Soriplay-chart.git
cd Soriplay-chart

# 2) 의존성
sudo apt install -y ffmpeg fonts-noto-cjk fonts-noto-core fonts-nanum fonts-thai-tlwg python3-pip
pip3 install -r requirements.txt

# 3) 한 번 수동 실행해서 확인
python3 scripts/make_short.py --period weekly --country kr

# 4) cron 등록 (매일 09:00·19:00 KST → 순번 국가 자동 선택)
0 9,19 * * * cd /home/ubuntu/Soriplay-chart && /usr/bin/python3 scripts/make_short.py --period weekly --country auto >> shorts.log 2>&1
```

YouTube 자동 업로드까지 하려면 `YOUTUBE_TOKEN_JSON` 환경변수나
프로젝트 폴더의 `youtube_token.json` 파일을 쓰면 된다(`get_youtube_token.py` 로 발급).
