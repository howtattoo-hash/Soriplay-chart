# Sori Play · 14개국 주간 차트 쇼츠 자동화

스포티파이 **주간 차트**(14개 시장)를 하루 두 나라씩 돌아가며 받아서
**9:16 세로 바 차트 레이스 숏폼(.mp4, 45초)** 을 만들고, 그 나라 **언어로 된 제목·설명**과
**나라별 재생목록**에 맞춰 YouTube Shorts로 올린다.

- 14개 시장: `global` `kr` `us` `gb` `br` `mx` `id` `vn` `th` `ph` `my` `sa` `in` `tr`
- 45초 · 1080×1920 · 30fps · H.264(yuv420p) — 쇼츠 60초 제한 안
- 헤더에 **주간 범위(11.12 – 11.18)** 와 **날짜 티커(11.15 · 4/7)** 가 있어 하루씩 흐르는 것이 바로 보임
- 주간 차트는 **7일치로 펼쳐서** 그린다: 날마다 막대가 차오르고, 그 사이에 1위가 바뀌기도 한다
- 막대 왼쪽에 **원형 앨범 커버 썸네일**이 순위를 따라 함께 움직임
- **곡마다 다른 속도 곡선**으로 자라서 막대가 서로를 **추월했다가 다시 따라잡음**
- 순위가 바뀌면 **스프링 이동**(살짝 튀어 오름) + **▲/▼/NEW 배지** + **금색 번쩍임**
- **1위가 바뀌면 상단에 `★ NEW #1` 왕관 배너** + 그 막대 금색 강조
- 스트림 숫자는 매 프레임 갱신되는 **롤링 카운터**
- **1위 곡이 바뀌면 배경 음악도 그 곡의 30초 미리듣기로 교체**(길면 자동 루프·페이드)

```
┌ 스포티파이 주간 차트 ─┐   ┌ 영상 렌더 ─┐   ┌ 오디오 전환 ─┐   ┌ 업로드 ─┐
│ kworb.net 14개국      │─▶│ matplotlib │─▶│ iTunes 30초  │─▶│ YouTube │
│ data/{국가}_weekly.csv │   │ + ffmpeg   │   │ 미리듣기 교체 │   │ + 재생목록│
└───────────────────────┘   └───────────┘   └─────────────┘   └────────┘
```

## 하루 두 나라씩, 한 주에 14개국 (순번)

| 요일 | 09:00 KST | 19:00 KST |
|---|---|---|
| 월 | global | kr |
| 화 | us | gb |
| 수 | br | mx |
| 목 | id | vn |
| 금 | th | ph |
| 토 | my | sa |
| 일 | in | tr |

- 순서는 `config/countries.json` 의 `order` 배열을 따른다. 바꾸면 그대로 반영된다.
- 09:00 칸이 가장 중요한 자리라 가장 먼저 볼 시장(글로벌·한국)을 앞에 두었다.
- `python scripts/rotation.py --table` 로 언제든 시간표를 확인할 수 있다.
- **인도(`in`)는 kworb가 스트림 수치를 주지 않는다**(전부 0). 그래서 인도만은 순위를
  100점 만점으로 환산한 **Chart Score** 모드로 그린다(영상 상단에 `CHART SCORE` 표시, 제목·설명에도 안내).

## 폴더 구조

```
config/
  countries.json        14개 시장 설정(순서·표기·언어·재생목록 이름)
  playlists.json        나라별 유튜브 재생목록 ID (ensure_playlists.py가 채움)
scripts/
  chart_config.py       설정 로더 · CSV 경로
  rotation.py           오늘 차례 국가 계산 (09:00/19:00 · 일요일 1편)
  fetch_spotify.py      차트 수집 → data/{국가}_{weekly|daily}.csv 누적
  media.py              iTunes 앨범 커버 + 30초 미리듣기 조회(캐시)
  chart_data.py         곡별 속도 곡선 타임라인 계산(렌더·오디오 공용)
  render_chart.py       1080×1920 바 차트 레이스 mp4 렌더(배지·왕관·스프링)
  build_audio.py        1위 곡 구간별 배경 음악 편집 + 영상에 합치기
  locales.py            11개 언어 제목·설명·해시태그·영상 문구
  upload_youtube.py     업로드 + 나라별 재생목록 + 중복 방지
  ensure_playlists.py   14개국 재생목록 생성/확인 → config/playlists.json
  make_short.py         위 과정을 한 번에 실행
  get_youtube_token.py  업로드·재생목록용 OAuth 토큰 발급 도우미
data/                   시점별 차트 스냅샷 CSV (자동 커밋)
output/                 만들어진 mp4 + 타임라인 json (artifact로 업로드)
state/uploads.json      어느 나라를 어느 주에 올렸는지 (중복 방지)
.github/workflows/weekly-chart.yml   매일 09:00·19:00 KST 자동 실행
```

## 바로 실행해 보기 (내 PC)

```bash
pip install -r requirements.txt
# ffmpeg 필요:  macOS `brew install ffmpeg` / Ubuntu `sudo apt install ffmpeg`
#              또는 `pip install imageio-ffmpeg` (자동 다운로드)

python scripts/make_short.py --period weekly --country kr      # 한국 주간 차트
python scripts/make_short.py --period weekly --country global  # 글로벌
python scripts/make_short.py --period weekly --country all     # 14개국 전부(오래 걸림)
python scripts/make_short.py --period daily  --country kr,us   # 일간 차트도 가능
```

결과물: `output/soriplay_spotify_{국가}_weekly_{YYYYMMDD}.mp4` (+ 같은 이름의 `.json` 타임라인)

세부 옵션:

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--country` | auto | `auto`(순번) · `all`(14개국) · `kr,us` 처럼 목록 · 코드 하나 |
| `--period` | weekly | `weekly`(주간) / `daily`(일간) |
| `--top` | 10 | 화면에 띄울 곡 수 |
| `--duration` | 45(주간)·30(일간) | 영상 길이(초) |
| `--days` | 4(주간)·5(일간) | 애니메이션에 쓸 최근 시점 수 |
| `--fps` | 30 | 프레임 레이트 |
| `--audio` | preview | `preview`(1위 변경 시 음악 교체) / `silent` / `off` |
| `--now` | 현재 | 순번 계산 기준 시각(예: `2026-11-20T19:00`) |
| `--skip-fetch` | – | 이미 받아둔 CSV로만 렌더 |

렌더 결과를 이미지로 먼저 확인하려면(느림):

```bash
python scripts/render_chart.py --country kr --period weekly --frames-dir .preview --preview 0,400,900,1349
```

## 제목·설명은 그 나라 언어로

| 시장 | 언어 | 제목 예시 |
|---|---|---|
| kr | ko | `A2O·RESCENE \| 스포티파이 한국 주간 차트 TOP 10 (11/12) #Shorts` |
| global/us/gb | en | `KAROL G & Tate McRae — Spotify Global Weekly Chart Top 10 (11/12) #Shorts` |
| br | pt | `A2O e RESCENE — Top 10 Spotify Brasil (Semanal 12/11) #Shorts` |
| mx | es | `A2O y RESCENE — Top 10 Spotify México (Semanal 12/11) #Shorts` |
| id | id | `A2O & RESCENE — Top 10 Spotify Indonesia (Mingguan 12/11) #Shorts` |
| vn | vi | `A2O & RESCENE — Top 10 Spotify Việt Nam (Tuần 12/11) #Shorts` |
| th | th | `A2O & RESCENE — Top 10 Spotify ไทย (รายสัปดาห์ 12/11) #Shorts` |
| ph | fil | `A2O at RESCENE — Top 10 Spotify Philippines (Lingguhan 11/12) #Shorts` |
| my | ms | `A2O & RESCENE — Top 10 Spotify Malaysia (Mingguan 12/11) #Shorts` |
| sa | ar | `A2O وRESCENE — توب 10 سبوتيفاي السعودية (الأسبوعي 12/11) #Shorts` |
| in | hi | `A2O और RESCENE — Spotify भारत साप्ताहिक टॉप 10 (12/11) #Shorts` |

- 제목 맨 앞은 **이번 주 1위·2위 아티스트** 이름이다(조회수에 가장 큰 영향).
- 설명에는 그 나라 말 소개 + TOP 5 + **Google Play 링크**
  (`https://play.google.com/store/apps/details?id=com.soriplay.app`) + soriplay.com 이 들어간다.
- 해시태그는 **제목+설명 합쳐 5개 이하**(제목의 `#Shorts` 포함)로 자동 제한한다.
- 영상 안 문구도 그 나라 말로 바뀐다. 단, 태국어·아랍어·데바나가리는 글자 조합(셰이핑)이
  matplotlib에서 깨질 수 있어 **영상 안내 문구만 영어**로 두고, 유튜브 제목·설명은 그 나라 말을 쓴다
  (`config/countries.json` 의 `video_lang`).

## 유튜브 재생목록 (나라별 13개)

`upload_youtube.py` 는 영상을 올린 뒤 `config/playlists.json` 에 적힌 그 나라 재생목록에 넣는다.
ID가 비어 있으면 **영상만 올리고 조용히 넘어간다**(파이프라인은 멈추지 않음).

한 번만 아래를 실행하면 없는 재생목록을 만들고 ID를 채워 준다.

```bash
python scripts/ensure_playlists.py --dry-run   # 무엇을 만들지 미리 보기
python scripts/ensure_playlists.py             # 생성 + config/playlists.json 기록
python scripts/ensure_playlists.py --print-env # YOUTUBE_PLAYLISTS_JSON 값 출력
```

> **권한 주의**: 재생목록 **조회**는 `youtube.readonly` 로 되지만, **생성·영상 추가**는
> `https://www.googleapis.com/auth/youtube` (또는 `youtube.force-ssl`) 스코프가 필요하다.
> 현재 쓰는 토큰이 `youtube.upload + youtube.readonly` 라면 업로드는 되고 재생목록 추가만
> "권한 부족"으로 실패한다(영상은 정상 업로드, 로그에 안내 출력). 이때는 토큰을 다시 발급:

```bash
python scripts/get_youtube_token.py --client-secret youtube_client_secret.json \
    --scopes upload,playlist
# → 출력된 JSON 한 줄을 GitHub Secrets 의 YOUTUBE_TOKEN_JSON 에 덮어쓰기
```

## 자동 실행 (운영은 Pickle 예약 작업)

실제 매일 업로드는 **Pickle 예약 작업**(09:00 · 19:00 KST)이 담당한다.
한 번의 실행은 아래 순서로 돌고, 각 단계가 2분 안팎이라 나눠져 있다.

```
cd /workspace/downloads/sori-play-chart-shorts
export YOUTUBE_TOKEN_JSON="$(cat /workspace/downloads/youtube_token.json)"
export YOUTUBE_CLIENT_SECRET_JSON="$(cat /workspace/downloads/youtube_client_secret.json)"
python3 scripts/slot_pipeline.py prepare --period weekly --country auto
python3 scripts/slot_pipeline.py chunk --index 0
python3 scripts/slot_pipeline.py chunk --index 1
python3 scripts/slot_pipeline.py chunk --index 2
python3 scripts/slot_pipeline.py finish
python3 scripts/upload_youtube.py --summary output/summary.json
```

순서·보고 규칙은 `scheduled-actions/🎬-14개국-주간-차트-쇼츠-자동-업로드/action.md` 에 있다.

### GitHub Actions (선택 · 백업용)

`.github/workflows/weekly-chart.yml` 은 같은 일을 GitHub에서 돌리는 백업 워크플로다.
저장소에 워크플로를 쓰려면 Pickle GitHub 앱에 **Workflows / Secrets** 권한이 필요해,
현재는 올라가 있지 않다(그대로 두는 것을 권장 — 두 곳에서 돌면 같은 나라가 두 번 올라간다).

1. `ffmpeg` · 다국어 폰트(`fonts-noto-cjk`, `fonts-noto-core`, `fonts-nanum`, `fonts-thai-tlwg`) 설치
2. 오늘 차례 국가 계산(`rotation.py`) — 매일 두 칸이라 항상 한 나라가 정해진다
3. 차트 수집 → 영상 렌더 → 오디오 전환
4. `data/*.csv` · `state/uploads.json` 을 저장소에 커밋
5. `output/*.mp4` 를 **artifact** 로 업로드
6. `YOUTUBE_TOKEN_JSON` 이 있으면 업로드 + 재생목록 추가
   (같은 주·같은 나라를 이미 올렸으면 건너뛴다 — `--force` 로 무시)

수동 실행: Actions 탭 → *14-Market Weekly Chart Shorts* → **Run workflow**

| 입력 | 설명 |
|---|---|
| `country` | `auto`(순번) · `all`(14개국) · `kr,us` 처럼 목록 |
| `period` | `weekly` / `daily` |
| `audio` | `preview` / `silent` / `off` |
| `upload` | `auto`(공개) · `skip`(올리지 않음) · `unlisted`(미공개 테스트) |
| `force_upload` | 같은 주·같은 나라도 다시 업로드 |
| `setup_playlists` | 14개국 재생목록 생성/확인 실행 |

### 필요한 Secret / Variable

| 이름 | 종류 | 설명 |
|---|---|---|
| `YOUTUBE_TOKEN_JSON` | Secret | 업로드용 OAuth 토큰 JSON 한 줄 |
| `YOUTUBE_CLIENT_SECRET_JSON` | Secret | (선택) 토큰에 client_id/secret 이 없을 때 채움 |
| `YOUTUBE_PLAYLISTS_JSON` | Variable | (선택) `{"kr":"PL...","global":"PL..."}` — 있으면 설정 파일보다 우선 |
| `YT_PRIVACY` | Variable | (선택) `unlisted` 로 두면 모든 업로드가 미공개(시험 운영) |

토큰이 없으면 업로드 단계만 조용히 건너뛰고 영상은 artifact로 남는다.

### YouTube 자동 업로드 켜기

1. Google Cloud Console → 프로젝트 생성 → **YouTube Data API v3** 사용 설정
2. OAuth 클라이언트 ID(데스크톱 앱) 생성 → JSON 다운로드
3. 내 PC에서 `python scripts/get_youtube_token.py --client-secret youtube_client_secret.json --scopes upload,playlist`
4. 출력된 JSON 한 줄을 저장소 → Settings → Secrets → Actions 에서 **`YOUTUBE_TOKEN_JSON`** 으로 저장
5. (선택) 미공개로 먼저 시험하려면 Settings → Variables 에 `YT_PRIVACY=unlisted`

로컬에서는 `youtube_token.json`(과 필요하면 `youtube_client_secret.json`) 파일을 프로젝트 폴더에
두면 환경변수 없이도 동작한다. 두 파일은 `.gitignore` 로 커밋에서 제외된다.

## 데이터는 어떻게 쌓이나

- `data/{국가}_{period}.csv` 컬럼:
  `chart_date, country, rank, artist, title, streams, source, fetched_at, rank_change`
- `source` 값
  - `kworb` : 실제 관측한 그 주(일간이면 그날)의 차트
  - `derived_prev` : 같은 표의 `Streams+`(직전 주 대비) 열로 **역산한 지난주** 지점
  - `derived_7d` : 일간 표의 `7Day`(7일 합계) ÷ 7 로 만든 **3일 전** 지점(일간 전용)
- `rank_change` 는 kworb의 `P+` 열(`+7` / `-1` / `NEW`)이고, 영상의 ▲/▼/NEW 배지에 그대로 쓰인다.
- kworb는 과거 아카이브를 주지 않아서 첫 실행에도 막대가 움직이도록 위 지점을 역산해 넣는다.
  주가 쌓일수록(`--days 4` → 최대 4주) 레이스가 더 풍부해진다.
- 곡별 속도 곡선은 제목 해시로 정해지므로, 같은 데이터를 다시 렌더해도 결과가 똑같다.

## 알아둘 점

- **데이터 출처**: kworb.net의 스포티파이 주간/일간 표를 읽는다(로그인 불필요). 페이지 구조가
  바뀌면 `scripts/fetch_spotify.py`의 `parse_rows()`만 손보면 된다. 수집에 실패하면 저장된
  최신 스냅샷으로 계속 진행하므로 파이프라인은 멈추지 않는다.
- **커버/미리듣기**: iTunes Search API(무료, 키 불필요)를 쓴다. 한글 제목·음차 아티스트명은
  유사도 매칭으로 보정하고, 못 찾으면 브랜드 그라데이션 기본 커버로 대체한다.
  조회 결과는 `cache/` 에 남아 다음 실행부터는 API를 다시 부르지 않는다.
- **음악 저작권**: 배경 음악은 각 곡의 **30초 미리듣기**다(45초 구간은 자동 루프·페이드).
  업로드 후 YouTube Content ID 청구(수익 배분·일부 국가 차단)가 붙을 수 있다. 청구가 싫으면
  `--audio silent`(또는 `off`)로 돌리면 된다.
- **이미지/폰트**: Actions 러너에 다국어 폰트를 설치해 한글·태국어·아랍어가 깨지지 않는다.
- 산출물은 세로 9:16 · 45초라 YouTube Shorts 조건(60초 이하)을 만족한다.

## 문제가 생기면

| 증상 | 확인할 것 |
|---|---|
| 한글이 □로 보임 | `fonts-noto-cjk` 설치 여부(`fc-list \| grep -i "noto sans cjk"`) |
| `ffmpeg를 찾을 수 없습니다` | `apt install ffmpeg` 또는 `pip install imageio-ffmpeg` |
| 커버가 기본 이미지 | `cache/meta/*.json` 의 `not_found` 항목 확인 후 해당 파일 삭제하고 재실행 |
| 커버가 엉뚱한 곡 | `cache/meta/<키>.json` 의 `matched_title` 확인 → 삭제 후 재실행 |
| 차트가 안 바뀜 | kworb 주간 차트는 목요일에 갱신된다(정상). `data/*.csv` 의 마지막 날짜 확인 |
| 업로드가 안 됨 | `YOUTUBE_TOKEN_JSON` 존재 여부 · 토큰 만료 → `get_youtube_token.py` 재발급 |
| 재생목록에 안 들어감 | 토큰 스코프에 `youtube` 없음 → `--scopes upload,playlist` 로 재발급 |
| 같은 영상이 두 번 올라감 | `state/uploads.json` 확인 · 필요하면 `--force` 없이 다시 실행 |
