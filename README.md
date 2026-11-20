# Sori Play · 스포티파이 차트 쇼츠 자동화

스포티파이 **일간 차트**(한국 / 글로벌)를 매일 자동으로 받아서
**9:16 세로 바 차트 레이스 숏폼(.mp4)** 을 만들고, 원하면 **YouTube Shorts**까지 자동 업로드한다.

- 해상도 1080×1920 · 30fps · 18초 · H.264(yuv420p)
- 막대 왼쪽에 **원형 앨범 커버 썸네일**이 순위를 따라 함께 움직임
- **1위 곡이 바뀌면 배경 음악도 그 곡의 30초 미리듣기로 교체** (없으면 그 구간만 무음)
- 매 실행마다 차트 스냅샷을 `data/*.csv` 에 쌓아서, 날짜가 늘수록 레이스가 풍부해짐

```
┌ 스포티파이 일간 차트 ─┐      ┌ 영상 렌더 ─┐      ┌ 오디오 전환 ─┐      ┌ 업로드 ─┐
│ kworb.net (순위+스트림)│ ─▶  │ matplotlib  │ ─▶  │ iTunes 30초  │ ─▶  │ YouTube │
│ data/{kr,global}_daily│      │ + ffmpeg    │      │ 미리듣기 교체 │      │ Shorts  │
└───────────────────────┘      └────────────┘      └─────────────┘      └─────────┘
```

## 폴더 구조

```
scripts/
  fetch_spotify.py      차트 수집 → data/{country}_daily.csv 누적
  media.py              iTunes에서 앨범 커버 + 30초 미리듣기 조회(캐시)
  chart_data.py         날짜 보간 타임라인 계산(렌더·오디오 공용)
  render_chart.py       1080×1920 바 차트 레이스 mp4 렌더
  build_audio.py        1위 곡 구간별 배경 음악 편집 + 영상에 합치기
  upload_youtube.py     YouTube Shorts 업로드(토큰 있을 때만)
  make_short.py         위 과정을 한 번에 실행
  get_youtube_token.py  업로드용 OAuth 토큰 발급 도우미
data/                   일자별 차트 스냅샷 CSV (자동 커밋됨)
output/                 만들어진 mp4 + 타임라인 json (artifact로 업로드)
.github/workflows/daily-chart.yml   매일 09:00 KST 자동 실행
```

## 바로 실행해 보기 (내 PC)

```bash
pip install -r requirements.txt
# ffmpeg 필요:  macOS `brew install ffmpeg` / Ubuntu `sudo apt install ffmpeg`
#              또는 `pip install imageio-ffmpeg` (자동 다운로드)

python scripts/make_short.py --country kr        # 한국 차트
python scripts/make_short.py --country global    # 글로벌 차트
python scripts/make_short.py --country both      # 둘 다
```

결과물: `output/soriplay_spotify_kr_YYYYMMDD.mp4` (+ 같은 이름의 `.json` 타임라인)

세부 옵션:

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--top` | 10 | 화면에 띄울 곡 수 |
| `--duration` | 18 | 영상 길이(초) |
| `--fps` | 30 | 프레임 레이트 |
| `--days` | 5 | 애니메이션에 쓸 최근 날짜 수 |
| `--audio` | preview | `preview`(1위 변경 시 음악 교체) / `silent`(무음) / `off`(오디오 트랙 없음) |
| `--skip-fetch` | – | 이미 받아둔 CSV로만 렌더 |

렌더 결과를 이미지로 먼저 확인하려면:

```bash
python scripts/render_chart.py --country kr --frames-dir .preview --preview 0,120,269
```

## GitHub Actions 자동 실행

`.github/workflows/daily-chart.yml` 이 매일 **00:00 UTC(09:00 KST)** 에 아래를 수행한다.

1. `ffmpeg` · `fonts-noto-cjk` 설치
2. 차트 수집 → 영상 렌더 → 오디오 전환
3. `data/*.csv` 를 저장소에 커밋(히스토리 누적)
4. `output/*.mp4` 를 **artifact** 로 업로드
5. `YOUTUBE_TOKEN_JSON` 시크릿이 있으면 YouTube 업로드까지

수동 실행: Actions 탭 → *Daily Spotify Chart Short* → **Run workflow** → 지역(`kr`/`global`/`both`) 선택.

### YouTube 자동 업로드 켜기 (선택)

1. Google Cloud Console → 프로젝트 생성 → **YouTube Data API v3** 사용 설정
2. OAuth 클라이언트 ID(데스크톱 앱) 생성 → JSON 다운로드
3. 내 PC에서 `python scripts/get_youtube_token.py --client-secret client_secret.json`
4. 출력된 JSON 한 줄을 저장소 → Settings → Secrets → Actions 에서
   이름 **`YOUTUBE_TOKEN_JSON`** 으로 저장
5. (선택) 기본 공개 범위는 `public`. `unlisted` 로 두려면 저장소 변수나 워크플로 env `YT_PRIVACY` 사용

토큰이 없으면 업로드 단계만 조용히 건너뛰고 영상은 artifact로 남는다.

## 데이터는 어떻게 쌓이나

- `data/{country}_daily.csv` 컬럼: `chart_date,country,rank,artist,title,streams,source,fetched_at`
- `source` 값
  - `kworb` : 실제 관측한 그날의 차트(순위·일일 스트리밍)
  - `derived_prev` : 같은 표의 `Streams+`(전일 대비) 열로 **역산한 전날** 지점
  - `derived_7d` : 같은 표의 `7Day`(7일 합계) 열 ÷ 7 로 만든 **3일 전** 지점
- kworb는 과거 일자 아카이브를 제공하지 않아서, **첫 실행에도 막대가 움직이는 레이스**가
  나오도록 위 두 지점을 역산해 넣는다. 실제 관측일이 쌓이면 그 값이 항상 우선한다.

## 알아둘 점

- **데이터 출처**: kworb.net의 스포티파이 일간 차트 표를 읽는다(로그인 불필요). 페이지 구조가
  바뀌면 `scripts/fetch_spotify.py`의 `parse_rows()`만 손보면 된다. 수집에 실패하면 저장된
  최신 스냅샷으로 계속 진행하므로 파이프라인은 멈추지 않는다.
- **커버/미리듣기**: iTunes Search API(무료, 키 불필요)를 쓴다. 한글 제목·음차 아티스트명은
  유사도 매칭으로 보정하고, 못 찾으면 브랜드 그라데이션 기본 커버로 대체한다.
  조회 결과는 `cache/` 에 남아 다음 실행부터는 API를 다시 부르지 않는다.
- **음악 저작권**: 배경 음악은 각 곡의 **30초 미리듣기**다. 업로드 후 YouTube Content ID
  청구(수익 배분·일부 국가 차단)가 붙을 수 있다. 청구가 싫으면 `--audio silent`(또는 `off`)로
  돌리면 된다. 1위가 자주 바뀌면 음악이 자주 끊기므로 영상 길이(18초)와 함께 조정할 것.
- **이미지/폰트**: Actions 러너에 `fonts-noto-cjk` 를 설치해 한글이 깨지지 않는다.
- 산출물은 세로 9:16 · 60초 이하라 YouTube Shorts 조건을 만족한다.

## 문제가 생기면

| 증상 | 확인할 것 |
|---|---|
| 한글이 □로 보임 | `fonts-noto-cjk` 설치 여부(`fc-list \| grep -i "noto sans cjk"`) |
| `ffmpeg를 찾을 수 없습니다` | `apt install ffmpeg` 또는 `pip install imageio-ffmpeg` |
| 커버가 기본 이미지 | `cache/meta/*.json` 의 `not_found` 항목 확인 후 해당 파일 삭제하고 재실행 |
| 커버가 엉뚱한 곡 | `cache/meta/<키>.json` 의 `matched_title` 확인 → 삭제 후 재실행 |
| 차트가 안 바뀜 | kworb 기준일이 하루~이틀 늦을 수 있음(정상). `data/*.csv` 의 마지막 날짜 확인 |
