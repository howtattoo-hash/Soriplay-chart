# GitHub에 올리는 방법 (현재 상태 안내)

이 폴더는 **완성된 자동화 프로젝트**입니다. 다만 지금 연결된 GitHub(`@howtattoo-hash`)의
Pickle 앱 권한으로는 **새 저장소를 만들 수도, 기존 저장소가 보이지도 않는 상태**라
자동으로 올리지 못했습니다.

- `gh api /user/repos` → `[]` (공유된 저장소 0개)
- `gh repo create` → `Resource not accessible by integration (createRepository)`

아래 둘 중 하나만 해주시면 바로 올리고 자동 실행까지 확인할 수 있습니다.

---

## 방법 A — 저장소를 하나 만들어 주시면 됩니다 (가장 간단, 20초)

1. https://github.com/new 접속
2. Repository name: **`sori-play-chart-shorts`**
3. **Private** 선택 → *Create repository* (README/ignore 파일은 추가하지 마세요)
4. https://github.com/apps/pickle/installations/new 에서 이 저장소가 Pickle에
   **선택(체크)** 되어 있는지 확인 (Repository access → *Only select repositories* →
   `sori-play-chart-shorts` 추가)

그다음 이 폴더에서 아래 한 줄만 실행하면 올라갑니다.

```bash
cd sori-play-chart-shorts
git push -u origin main
```

## 방법 B — Pickle 앱에 "저장소 만들기" 권한을 주는 경우

GitHub → Settings → Applications → Pickle → *Configure* 에서
**Administration: Read and write**(Repository creation) 항목을 허용하고
Repository access를 *All repositories* 로 바꿔주시면, 제가 저장소 생성부터
push·자동 실행 확인까지 한 번에 처리합니다.

---

## 올라간 뒤 자동 실행 확인

1. 저장소 → **Actions** 탭 → *Daily Spotify Chart Short* → **Run workflow**
   → `country` = `kr`(또는 `both`) → 실행
2. 약 4~6분 뒤 실행 결과에서 artifact **sori-shorts-N** 안의
   `soriplay_spotify_kr_YYYYMMDD.mp4` 를 내려받으면 완성본입니다.
3. 매일 09:00 KST 자동 실행이 켜져 있고, `data/*.csv` 가 매일 자동 커밋됩니다.

명령줄로 확인하려면:

```bash
gh workflow run daily-chart.yml -f country=kr
gh run list --workflow=daily-chart.yml
gh run watch
gh run download <run-id> -n sori-shorts-<n>
```

---

## 참고: GitHub Actions를 안 쓰고 서버에서 돌리는 방법

이미 운영 중인 서버(예: `swedish24` 서버나 `soriplay.com` 서버)에서 돌려도 됩니다.

```bash
# 1) 코드 복사 (zip 업로드 또는 git clone)
# 2) 의존성
sudo apt install -y ffmpeg fonts-noto-cjk python3-pip
pip3 install -r requirements.txt

# 3) 한 번 수동 실행해서 확인
python3 scripts/make_short.py --country both

# 4) cron 등록 (매일 09:00 KST)
crontab -e
0 9 * * * cd /home/ubuntu/sori-play-chart-shorts && /usr/bin/python3 scripts/make_short.py --country kr >> shorts.log 2>&1
```

YouTube 자동 업로드까지 하려면 `YOUTUBE_TOKEN_JSON` 환경변수에 토큰을 넣어주면 됩니다
(`python3 scripts/get_youtube_token.py` 로 발급).
