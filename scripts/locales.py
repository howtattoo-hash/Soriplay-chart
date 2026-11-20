"""나라별 문구(유튜브 제목·설명·해시태그 + 영상 안 글자) 모음.

13개 시장은 11개 언어를 쓴다. 여기 한 곳에서만 문구를 고치면
유튜브 메타데이터(upload_youtube.py)와 영상 렌더(render_chart.py)가 같이 바뀐다.

사용 가능한 치환자
  {a1} {a2}  1위·2위 아티스트 이름
  {market}   그 나라 말 나라 이름 (예: 한국 / Brasil / السعودية)
  {n}        화면에 올리는 곡 수 (TOP n)
  {date}     차트 기준일 (나라별 표기, 예: 11/12 · 12/11)
  {week}     주간 차트 기간 (예: 11.12–11.18) · 일간이면 그날 날짜
  {pw}       기간 단어 소문자 (weekly / 주간 / semanal ...)
  {pw_cap}   기간 단어 대문자형 (Weekly / 주간 / Semanal ...)
  {playstore} Google Play 링크
  {site}      soriplay.com
"""
from __future__ import annotations

PLAYSTORE = "https://play.google.com/store/apps/details?id=com.soriplay.app"
SITE = "https://soriplay.com"

LOCALES: dict[str, dict] = {
    "ko": {
        "period_word": {"weekly": ("주간", "주간"), "daily": ("일간", "일간")},
        "title": "{a1}·{a2} | 스포티파이 {market} {pw} 차트 TOP {n} ({date}) #Shorts",
        "desc_head": "스포티파이 {market} {pw} 차트 · {week} · {metric} TOP {n}",
        "metric_phrase": {"streams": "스트리밍", "score": "순위 점수"},
        "top_head": "[{pw} TOP 5]",
        "cta": "Sori Play에서 이 곡들을 지금 무료로 들어보세요.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ 웹에서 바로 듣기: {site}",
        "note": "하루 두 나라씩, 13개국 {pw} 차트를 매일 09:00·19:00에 올립니다.",
        "hashtags": ["#SoriPlay", "#스포티파이", "#케이팝", "#{pw}차트"],
        "video": {
            "chart": "스포티파이 {pw} 차트",
            "cta": "▶   지금 무료 감상 · Sori Play",
            "footer": "데이터 Spotify {pw} 차트 · 매일 자동 업데이트",
        },
        "score_badge": "차트 점수",
        "score_note": "스트림 수치를 공개하지 않는 차트라 순위 점수(1위 = 100)로 표시합니다.",
    },
    "en": {
        "period_word": {"weekly": ("weekly", "Weekly"), "daily": ("daily", "Daily")},
        "title": "{a1} & {a2} — Spotify {market} {pw_cap} Chart Top {n} ({date}) #Shorts",
        "desc_head": "Spotify {market} {pw_cap} Chart — Top {n} {metric} · {week}",
        "metric_phrase": {"streams": "by streams", "score": "by chart score"},
        "top_head": "[{pw_cap} Top 5]",
        "cta": "Listen to these free on Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Listen on the web: {site}",
        "note": "Two new country charts a day — all 13 markets every week, 09:00 & 19:00 KST.",
        "hashtags": ["#SoriPlay", "#Spotify", "#{pw_cap}Chart", "#MusicChart"],
        "video": {
            "chart": "Spotify {pw_cap} Chart",
            "cta": "▶   Listen free · Sori Play",
            "footer": "Data: Spotify {pw} chart · updated daily",
        },
        "score_note": "This chart does not publish stream counts, so the bars show a rank score (No.1 = 100).",
    },
    "pt": {
        "period_word": {"weekly": ("semanal", "Semanal"), "daily": ("diário", "Diário")},
        "title": "{a1} e {a2} — Top {n} Spotify {market} ({pw_cap} {date}) #Shorts",
        "desc_head": "Parada {pw} da Spotify {market} — Top {n} {metric} · {week}",
        "metric_phrase": {"streams": "por streams", "score": "por pontuação do chart"},
        "top_head": "[Top 5 da semana]",
        "cta": "Ouça tudo de graça no Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Ouça na web: {site}",
        "note": "Dois países por dia — as 13 paradas toda semana, 09:00 e 19:00 (KST).",
        "hashtags": ["#SoriPlay", "#SpotifyBrasil", "#MúsicaBrasileira", "#ParadaSemanal"],
        "video": {
            "chart": "Spotify {market} · Parada {pw_cap}",
            "cta": "▶   Ouça de graça · Sori Play",
            "footer": "Dados: parada {pw} da Spotify · atualizado todo dia",
        },
    },
    "es": {
        "period_word": {"weekly": ("semanal", "Semanal"), "daily": ("diario", "Diario")},
        "title": "{a1} y {a2} — Top {n} Spotify {market} ({pw_cap} {date}) #Shorts",
        "desc_head": "Top {n} {pw} de Spotify {market} {metric} · {week}",
        "metric_phrase": {"streams": "por reproducciones", "score": "por puntuación del chart"},
        "top_head": "[Top 5 de la semana]",
        "cta": "Escúchalas gratis en Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Escucha en la web: {site}",
        "note": "Dos países al día — las 13 listas cada semana, 09:00 y 19:00 (KST).",
        "hashtags": ["#SoriPlay", "#SpotifyMéxico", "#MúsicaMexicana", "#TopSemanal"],
        "video": {
            "chart": "Spotify {market} · Top {pw_cap}",
            "cta": "▶   Escucha gratis · Sori Play",
            "footer": "Datos: lista {pw} de Spotify · se actualiza a diario",
        },
    },
    "id": {
        "period_word": {"weekly": ("mingguan", "Mingguan"), "daily": ("harian", "Harian")},
        "title": "{a1} & {a2} — Top {n} Spotify {market} ({pw_cap} {date}) #Shorts",
        "desc_head": "Tangga lagu {pw} Spotify {market} — Top {n} {metric} · {week}",
        "metric_phrase": {"streams": "berdasarkan streaming", "score": "berdasarkan skor chart"},
        "top_head": "[Top 5 pekan ini]",
        "cta": "Dengarkan semuanya gratis di Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Dengar di web: {site}",
        "note": "Dua negara setiap hari — 13 tangga lagu tiap pekan, 09:00 & 19:00 KST.",
        "hashtags": ["#SoriPlay", "#SpotifyIndonesia", "#MusikIndonesia", "#TanggaLagu"],
        "video": {
            "chart": "Spotify {market} · Tangga {pw_cap}",
            "cta": "▶   Dengar gratis · Sori Play",
            "footer": "Data: tangga lagu {pw} Spotify · diperbarui tiap hari",
        },
    },
    "vi": {
        "period_word": {"weekly": ("tuần", "Tuần"), "daily": ("ngày", "Ngày")},
        "title": "{a1} & {a2} — Top {n} Spotify {market} ({pw_cap} {date}) #Shorts",
        "desc_head": "Bảng xếp hạng {pw} Spotify {market} — Top {n} {metric} · {week}",
        "metric_phrase": {"streams": "theo lượt stream", "score": "theo điểm xếp hạng"},
        "top_head": "[Top 5 tuần này]",
        "cta": "Nghe miễn phí tất cả trên Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Nghe trên web: {site}",
        "note": "Mỗi ngày hai quốc gia — đủ 13 bảng xếp hạng mỗi tuần, 09:00 và 19:00 (KST).",
        "hashtags": ["#SoriPlay", "#SpotifyViệtNam", "#NhạcViệt", "#BảngXếpHạngTuần"],
        "video": {
            "chart": "Spotify {market} · BXH {pw_cap}",
            "cta": "▶   Nghe miễn phí · Sori Play",
            "footer": "Dữ liệu: bảng xếp hạng {pw} Spotify · cập nhật hằng ngày",
        },
    },
    "th": {
        "period_word": {"weekly": ("รายสัปดาห์", "รายสัปดาห์"), "daily": ("รายวัน", "รายวัน")},
        "title": "{a1} & {a2} — Top {n} Spotify {market} ({pw} {date}) #Shorts",
        "desc_head": "ชาร์ต Spotify {market} {pw} — Top {n} {metric} · {week}",
        "metric_phrase": {"streams": "จากการสตรีม", "score": "ตามคะแนนอันดับ"},
        "top_head": "[Top 5 สัปดาห์นี้]",
        "cta": "ฟังทั้งหมดได้ฟรีที่ Sori Play",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ ฟังบนเว็บ: {site}",
        "note": "วันละสองประเทศ — ครบ 13 ชาร์ตทุกสัปดาห์ เวลา 09:00 และ 19:00 (KST)",
        "hashtags": ["#SoriPlay", "#Spotifyไทย", "#เพลงไทย", "#ชาร์ตเพลง"],
        "video": {
            "chart": "Spotify {market} · ชาร์ต{pw}",
            "cta": "▶   ฟังฟรี · Sori Play",
            "footer": "ข้อมูล: ชาร์ต{pw} Spotify · อัปเดตทุกวัน",
        },
    },
    "fil": {
        "period_word": {"weekly": ("lingguhan", "Lingguhan"), "daily": ("araw-araw", "Araw-araw")},
        "title": "{a1} at {a2} — Top {n} Spotify {market} ({pw_cap} {date}) #Shorts",
        "desc_head": "Spotify {market} — Top {n} {metric} · {week}",
        "metric_phrase": {"streams": "ayon sa streams", "score": "ayon sa chart score"},
        "top_head": "[Top 5 ngayong linggo]",
        "cta": "Pakinggan silang lahat nang libre sa Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Pakinggan sa web: {site}",
        "note": "Dalawang bansa kada araw — 13 chart kada linggo, 09:00 at 19:00 KST.",
        "hashtags": ["#SoriPlay", "#SpotifyPhilippines", "#OPM", "#WeeklyChart"],
        "video": {
            "chart": "Spotify {market} · {pw_cap} Chart",
            "cta": "▶   Pakinggan nang libre · Sori Play",
            "footer": "Data: Spotify {pw} chart · awtomatikong ina-update",
        },
    },
    "ms": {
        "period_word": {"weekly": ("mingguan", "Mingguan"), "daily": ("harian", "Harian")},
        "title": "{a1} & {a2} — Top {n} Spotify {market} ({pw_cap} {date}) #Shorts",
        "desc_head": "Carta {pw} Spotify {market} — Top {n} {metric} · {week}",
        "metric_phrase": {"streams": "mengikut strim", "score": "mengikut skor carta"},
        "top_head": "[Top 5 minggu ini]",
        "cta": "Dengar semuanya percuma di Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Dengar di web: {site}",
        "note": "Dua negara setiap hari — 13 carta seminggu, 09:00 & 19:00 KST.",
        "hashtags": ["#SoriPlay", "#SpotifyMalaysia", "#MuzikMalaysia", "#CartaMingguan"],
        "video": {
            "chart": "Spotify {market} · Carta {pw_cap}",
            "cta": "▶   Dengar percuma · Sori Play",
            "footer": "Data: carta {pw} Spotify · dikemas kini setiap hari",
        },
    },
    "ar": {
        "period_word": {"weekly": ("الأسبوعي", "الأسبوعي"), "daily": ("اليومي", "اليومي")},
        "title": "{a1} و{a2} — توب {n} سبوتيفاي {market} ({pw} {date}) #Shorts",
        "desc_head": "قائمة سبوتيفاي {market} {pw} — أفضل {n} {metric} · {week}",
        "metric_phrase": {"streams": "حسب عدد الاستماعات", "score": "حسب نقاط الترتيب"},
        "top_head": "[أفضل 5 هذا الأسبوع]",
        "cta": "استمع إليها مجانًا على Sori Play.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ استمع على الويب: {site}",
        "note": "دولتان كل يوم — 13 قائمة كل أسبوع، 09:00 و19:00 بتوقيت كوريا.",
        "hashtags": ["#SoriPlay", "#سبوتيفاي", "#الموسيقى_السعودية", "#قائمة_أسبوعية"],
        "video": {
            "chart": "Spotify {market} · {pw_cap} Chart",
            "cta": "▶   استمع مجانًا · Sori Play",
            "footer": "البيانات: قائمة سبوتيفاي {pw} · تُحدَّث يوميًا",
        },
    },
    "hi": {
        "period_word": {"weekly": ("साप्ताहिक", "साप्ताहिक"), "daily": ("दैनिक", "दैनिक")},
        "title": "{a1} और {a2} — Spotify {market} {pw} टॉप {n} ({date}) #Shorts",
        "desc_head": "Spotify {market} का {pw} चार्ट — टॉप {n} {metric} · {week}",
        "metric_phrase": {"streams": "स्ट्रीम्स के आधार पर", "score": "रैंक स्कोर के आधार पर"},
        "top_head": "[इस हफ़्ते के टॉप 5]",
        "cta": "इन्हें Sori Play पर मुफ़्त सुनें।",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ वेब पर सुनें: {site}",
        "note": "हर दिन दो देश — हर हफ़्ते सभी 13 चार्ट, सुबह 09:00 और शाम 19:00 (KST)।",
        "hashtags": ["#SoriPlay", "#SpotifyIndia", "#IndianMusic", "#WeeklyChart"],
        "video": {
            "chart": "Spotify {market} · {pw_cap} Chart",
            "cta": "▶   मुफ़्त सुनें · Sori Play",
            "footer": "डेटा: Spotify {pw} चार्ट · रोज़ अपडेट",
        },
        "score_note": "यह चार्ट स्ट्रीम संख्या नहीं दिखाता, इसलिए बार में रैंक स्कोर (1 = सबसे ऊपर) दिखाया गया है।",
    },
    "tr": {
        "period_word": {"weekly": ("haftalık", "Haftalık"), "daily": ("günlük", "Günlük")},
        "title": "{a1} & {a2} — Spotify {market} {pw_cap} Liste • İlk {n} ({date}) #Shorts",
        "desc_head": "Spotify {market} {pw_cap} Liste — {metric} ilk {n} · {week}",
        "metric_phrase": {"streams": "akış sayısına göre", "score": "sıralama puanına göre"},
        "top_head": "[Bu haftanın ilk 5'i]",
        "cta": "Hepsini Sori Play'de ücretsiz dinleyin.",
        "store": "▶ Google Play: {playstore}",
        "web": "▶ Web'de dinle: {site}",
        "note": "Her gün iki ülke — haftada 14 liste, 09:00 ve 19:00 (KST).",
        "hashtags": ["#SoriPlay", "#SpotifyTürkiye", "#TürkçeMüzik", "#HaftalıkListe"],
        "video": {
            "chart": "Spotify {market} · {pw_cap} Liste",
            "cta": "▶   Ücretsiz dinle · Sori Play",
            "footer": "Veri: Spotify {pw} liste · her gün güncellenir",
        },
        "score_badge": "SIRALAMA PUANI",
        "score_note": "Bu liste akış sayısı yayınlamadığı için çubuklar sıralama puanını gösterir (1. = 100).",
    },
}


def get(lang: str) -> dict:
    """언어 코드로 문구 묶음을 가져온다(없으면 영어)."""
    return LOCALES.get((lang or "en").lower(), LOCALES["en"])


def period_words(lang: str, period: str) -> tuple[str, str]:
    """(소문자형, 대문자형) 기간 단어."""
    loc = get(lang)
    return loc["period_word"].get(period, loc["period_word"]["weekly"])


def metric_word(lang: str, metric: str = "streams") -> str:
    """설명에 쓰는 “스트림 기준 / 순위 점수 기준” 문구."""
    loc = get(lang)
    phrases = loc.get("metric_phrase") or LOCALES["en"]["metric_phrase"]
    return phrases.get(metric, phrases["streams"])


def score_badge(lang: str) -> str:
    """스트림 수치가 없는 차트에서 쓰는 상단 배지 문구."""
    return get(lang).get("score_badge") or "CHART SCORE"


def score_note(lang: str) -> str:
    """설명 끝에 붙이는 “순위 점수” 안내."""
    return get(lang).get("score_note") or get("en")["score_note"]
