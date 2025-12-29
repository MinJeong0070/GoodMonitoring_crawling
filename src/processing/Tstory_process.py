# -*- coding: utf-8 -*-
import os
import re
from datetime import datetime
import pandas as pd

# ====== 설정 (환경에 맞게 바꾸세요) ======
INPUT_TISTORY_CSV = r"C:\Users\USER\Downloads\티스토리 12월\12월 3주차\12월 3주차 티스토리 통합.csv"

SEARCH_KEYWORD_XLSX = r"D:\jupyter\community_site_crawling-main\site crawling\(언진) 2025 매체사 검색어 목록.xlsx"
TRUSTED_DOMAIN_XLSX = r"D:\jupyter\community_site_crawling-main\site crawling\(언진) 전처리용 도메인 주소.xlsx"
UNTRUSTED_COPY_DOMAIN_XLSX = r"D:\jupyter\community_site_crawling-main\site crawling\비신탁사_저작권문구+도메인주소.xlsx"
UNTRUSTED_MEDIA_XLSX = r"D:\jupyter\community_site_crawling-main\site crawling\비신탁사 매체명(전처리).xlsx"

TARGET_YEAR = 2025
TARGET_MONTH = 12

RESULT_DIR = r"C:\Users\USER\Downloads\티스토리 12월\12월 2주차"

# ======================================

REQUIRED_COLS = {
    "검색어": ["검색어", "키워드"],
    "게시물 제목": ["게시물 제목", "게시글 제목", "티스토리 제목", "글 제목", "포스트 제목"],
    "게시물 내용": ["게시물 내용", "게시글내용", "본문", "내용"],
    "게시물 URL": ["게시물 URL", "URL", "링크", "도메인"],  # URL이 없고 '도메인'만 있는 경우도 대응
    "게시물 등록일자": ["게시물 등록일자", "등록일자", "작성일자", "작성일", "포스트 등록일"],
    "계정명": ["계정명", "작성자", "블로그명", "티스토리명"],
}

def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {}
    for std_col, candidates in REQUIRED_COLS.items():
        found = None
        for c in candidates:
            if c in df.columns:
                found = c
                break
        if not found:
            raise KeyError(f"필수 컬럼 '{std_col}'(가능한 이름: {candidates})을(를) 찾을 수 없습니다.")
        col_map[found] = std_col
    return df.rename(columns=col_map)

def _sanitize_url(url: str) -> str:
    url = str(url)
    if '&keyword=' in url:
        return url.split('&keyword=')[0]
    return url

def _parse_datetime_safe(series: pd.Series) -> pd.Series:
    """
    - 예: 2025-08-12 오전 10:41:21 → 오전/오후 → AM/PM 치환 후 포맷 지정
    - 그 외 포맷 섞임 방지를 위해 1차 지정 포맷 시도 후 실패값은 포괄 파싱으로 재시도
    """
    s = series.astype(str).str.replace("오전", "AM").str.replace("오후", "PM")
    dt = pd.to_datetime(s, format="%Y-%m-%d %p %I:%M:%S", errors="coerce")
    if dt.isna().any():
        # 포맷이 다른 값이 섞여있다면 포괄 파싱로 보완
        dt2 = pd.to_datetime(s, errors="coerce")
        dt = dt.fillna(dt2)
    return dt

def _load_reference_lists():
    # 검색어 목록(옵션)
    try:
        df_search = pd.read_excel(SEARCH_KEYWORD_XLSX, sheet_name='검색어 목록')
        search_words = df_search['검색어명'].dropna().astype(str).tolist()
    except Exception:
        search_words = []

    # 신뢰/비신탁/매체명
    df_trusted = pd.read_excel(TRUSTED_DOMAIN_XLSX)
    trusted_domains = df_trusted['도메인'].dropna().astype(str).tolist()

    df_untrusted = pd.read_excel(UNTRUSTED_COPY_DOMAIN_XLSX)
    untrusted_copyrights = df_untrusted['저작권 문구'].dropna().astype(str).tolist()
    untrusted_domains = df_untrusted['도메인'].dropna().astype(str).tolist()

    df_media = pd.read_excel(UNTRUSTED_MEDIA_XLSX)
    untrusted_media_names = df_media['매체명'].dropna().astype(str).tolist()

    return {
        "search_words": search_words,
        "trusted_domains": trusted_domains,
        "untrusted_copyrights": untrusted_copyrights,
        "untrusted_domains": untrusted_domains,
        "untrusted_media_names": untrusted_media_names,
    }

def _contains_any(text: str, needles: list[str]) -> bool:
    text = str(text)
    return any(n and n in text for n in needles)

def _should_remove_by_trust_rule(row, lists) -> bool:
    title = str(row['게시물 제목'])
    content = str(row['게시물 내용'])
    both = title + " " + content

    has_untrusted = (
        _contains_any(both, lists["untrusted_copyrights"]) or
        _contains_any(both, lists["untrusted_domains"]) or
        _contains_any(both, lists["untrusted_media_names"])
    )
    has_trusted = _contains_any(both, lists["trusted_domains"])
    return has_untrusted and not has_trusted

def _has_valid_da(text: str) -> bool:
    text = str(text)
    for m in re.finditer(r"다\.", text):
        i = m.start()
        if i >= 1 and text[i - 1] == "니":  # '니다.'는 무시
            continue
        return True
    return False

def _should_remove_by_da_rule(row) -> bool:
    title = str(row['게시물 제목'])
    content = str(row['게시물 내용'])
    has_valid = _has_valid_da(title) or _has_valid_da(content)
    has_cartoon = ("만평" in title) or ("만평" in content)
    return (not has_valid) or has_cartoon

def preprocess_tistory_csv(input_csv: str, out_dir: str, year: int, month: int) -> str:
    os.makedirs(out_dir, exist_ok=True)

    try:
        df = pd.read_csv(input_csv, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도합니다.")
        df = pd.read_csv(input_csv, encoding="cp949")  # :contentReference[oaicite:4]{index=4}

    df = _ensure_columns(df)  # :contentReference[oaicite:5]{index=5}

    # 타입/결측 보정 + URL 정규화
    df["게시물 제목"] = df["게시물 제목"].fillna("").astype(str)
    df["게시물 내용"] = df["게시물 내용"].fillna("").astype(str)
    df["게시물 URL"] = df["게시물 URL"].fillna("").astype(str).map(_sanitize_url)  # :contentReference[oaicite:6]{index=6}

    # 날짜 파싱(한국어 오전/오후 대응)
    df["게시물 등록일자"] = _parse_datetime_safe(df["게시물 등록일자"])

    def _search_hit(x):
        kw = str(x['검색어']).lower()
        title = str(x['게시물 제목']).lower()
        content = str(x['게시물 내용']).lower()
        return (kw in title) or (kw in content)

    df1 = df[
        (df.apply(_search_hit, axis=1)) &
        (~df['게시물 내용'].fillna('').str.contains('신춘문예', case=False)) &
        (~df['게시물 제목'].fillna('').str.contains('신춘문예', case=False)) &
        (~df['계정명'].fillna('').str.contains('뽐뿌뉴스', case=False))
    ]  # :contentReference[oaicite:7]{index=7}

    # ----- 2) 연·월 필터 -----
    df2 = df1[
        (df1['게시물 등록일자'].dt.year == year) &
        (df1['게시물 등록일자'].dt.month == month)
    ]  # :contentReference[oaicite:8]{index=8}

    # ----- 3) URL 기준 중복 제거 -----
    df3 = df2.drop_duplicates(subset=['게시물 URL'], keep='first')  # :contentReference[oaicite:9]{index=9}

    # ----- 4) 비신탁/신뢰 도메인 룰 (본문 기반) -----
    lists = _load_reference_lists()
    mask_trust_remove = df3.apply(lambda r: _should_remove_by_trust_rule(r, lists), axis=1)
    df4 = df3[~mask_trust_remove]  # :contentReference[oaicite:10]{index=10}

    # ----- 5) '다.' 규칙 + '만평' 제외 -----
    mask_da_remove = df4.apply(_should_remove_by_da_rule, axis=1)
    filtered = df4[~mask_da_remove]  # :contentReference[oaicite:11]{index=11}

    # ----- 저장 (openpyxl로 안전 저장) -----
    ts = datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(out_dir, f"티스토리_전처리_{ts}.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        filtered.to_excel(writer, index=False)

    print(f"전처리된 데이터 저장 완료 (Excel): {out_path}")
    print(f"전처리 이전 : {len(df)}개\n"
          f"전처리 이후 : {len(filtered)}개\n"
          f"삭제 개수 : {len(df) - len(filtered)}개")  # :contentReference[oaicite:12]{index=12}

    return out_path

if __name__ == "__main__":
    preprocess_tistory_csv(
        input_csv=INPUT_TISTORY_CSV,
        out_dir=RESULT_DIR,
        year=TARGET_YEAR,
        month=TARGET_MONTH
    )
