# process_file.py
import os
import re
import pandas as pd
from datetime import datetime

# =========================================================
# 공통 유틸
# =========================================================
def _ensure_parent_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------
# RAW_KEYWORDS (크롤러와 동일, 키워드 병합 시 정렬 기준)
# ---------------------------------------------------------
RAW_KEYWORDS = [
    "기사공유","기사읽기","기사정리","뉴스스크랩","만평",
    "신문사설","신문필사","간추린뉴스","신문공부","지면기사",
    "경제","뉴스","스크랩","시사","정치","정부",
]
_ORDER = {k: i for i, k in enumerate(RAW_KEYWORDS)}

def _nospace(s: str) -> str:
    return (s or "").replace(" ", "").strip()

# =========================================================
# 비(非)페이스북 전처리(필요 시 사용)
#  - 검색어 포함, 연/월 필터, 비신탁사/도메인/저작권 필터, '다.' 규칙, 중복 제거
# =========================================================
def filter_untrusted_posts(all_data, untrusted_file, trusted_file, media_file):
    # 비신탁사 및 매체사 데이터 로드
    df_untrusted = pd.read_excel(untrusted_file)
    df_trusted = pd.read_excel(trusted_file)
    df_media = pd.read_excel(media_file)

    # 비신탁사 저작권 문구 및 도메인 리스트 생성
    untrusted_copyrights = df_untrusted["저작권 문구"].dropna().tolist()
    untrusted_domains = df_untrusted["도메인"].dropna().tolist()

    # 매체사 도메인 리스트 생성
    trusted_domains = df_trusted["도메인"].dropna().tolist()

    # 비신탁사 매체명 리스트 생성
    untrusted_media_names = df_media["매체명"].dropna().tolist()

    def should_remove(post_content):
        post_content = str(post_content)
        contains_untrusted_copyright = any(c in post_content for c in untrusted_copyrights)
        contains_untrusted_domain = any(d in post_content for d in untrusted_domains)
        contains_untrusted_media = any(m in post_content for m in untrusted_media_names)
        contains_trusted_domain = any(t in post_content for t in trusted_domains)
        return (
            (contains_untrusted_copyright or contains_untrusted_domain or contains_untrusted_media)
            and not contains_trusted_domain
        )

    if "게시물 내용" not in all_data.columns:
        all_data["게시물 내용"] = ""
    content_series = all_data["게시물 내용"].fillna("")
    mask = content_series.apply(should_remove)

    df_filtered = all_data[~mask]
    if df_filtered.empty:
        df_filtered = all_data.iloc[0:0]
    return df_filtered

def filter_empty_image_and_no_da(df_filtered):
    def has_valid_da(text):
        text = str(text)
        matches = list(re.finditer(r"다\.", text))
        for match in matches:
            start = match.start()
            if start >= 1 and text[start - 1] == "니":
                continue  # '니다.' 예외
            return True
        return False

    def should_remove(title, content):
        has_valid = has_valid_da(title) or has_valid_da(content)
        has_cartoon = "만평" in title or "만평" in content
        return not has_valid or has_cartoon

    for col in ["게시물 제목", "게시물 내용"]:
        if col not in df_filtered.columns:
            df_filtered[col] = ""
    mask = df_filtered.apply(lambda row: should_remove(row["게시물 제목"], row["게시물 내용"]), axis=1)
    df_final = df_filtered[~mask]
    return df_final

# =========================================================
# 페이스북 전용: 계정 URL + 숫자 ID 기반 제외
#   - 엑셀 여러 시트/컬럼에서 URL/ID 추출
#   - 상대경로 '/xxx/' → 'https://www.facebook.com/xxx/' 보정
#   - 루트 'https://www.facebook.com/' 는 무시
#   - 숫자 ID는 float/지수표기여도 숫자만 뽑아 길이≥5면 토큰으로 사용
# =========================================================
_URL_RE = re.compile(r'https?://[^\s)"\']+', re.IGNORECASE)

def _normalize_url(u: str) -> str:
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
        sp = urlsplit(u.strip())
        # 루트 도메인은 제외(오탐 방지)
        if sp.netloc.lower().endswith("facebook.com") and (sp.path in ("", "/")):
            return ""
        q = parse_qs(sp.query)
        for k in list(q):
            if k.startswith("utm") or k in ("refsrc", "mibextid", "_fb_noscript"):
                q.pop(k, None)
        return urlunsplit((sp.scheme, sp.netloc, sp.path.rstrip("/"),
                           urlencode({k: v[0] for k, v in q.items()}), ""))
    except Exception:
        return u.strip().rstrip("/")

def _extract_urls_from_series(series: pd.Series) -> list:
    urls = []
    for val in series.dropna().astype(str):
        s = val.replace("\u200b", "").strip()
        for piece in s.splitlines():
            p = piece.strip().strip('"').strip("'")
            if not p:
                continue
            # 상대경로 보정
            if p.startswith("/") and len(p) > 1:
                urls.append("https://www.facebook.com" + p)
                continue
            if p.startswith(("http://", "https://")):
                urls.append(p)
                continue
            found = _URL_RE.findall(p)
            urls.extend([u.strip() for u in found])
    return urls

_ID_TOKEN_RE = re.compile(r"(?:^|[^0-9])(\d{5,})")

def _normalize_id_token(raw) -> str:
    s = str(raw).strip()
    digits = re.sub(r"\D", "", s)   # 지수표기/콤마 등 제거 → 숫자만
    return digits if len(digits) >= 5 else ""

def _extract_ids_from_df(df: pd.DataFrame) -> list:
    ids = []
    for c in df.columns:
        col = df[c].dropna().astype(str)
        for text in col:
            from urllib.parse import urlsplit, parse_qs
            for u in _URL_RE.findall(text):
                sp = urlsplit(u)
                q = parse_qs(sp.query)
                for key in ("id", "fbid", "story_fbid", "page_id", "group_id"):
                    if key in q:
                        for v in q[key]:
                            tok = _normalize_id_token(v)
                            if tok:
                                ids.append(tok)
                for seg in sp.path.split("/"):
                    tok = _normalize_id_token(seg)
                    if tok:
                        ids.append(tok)
            for m in _ID_TOKEN_RE.finditer(text):
                tok = _normalize_id_token(m.group(1))
                if tok:
                    ids.append(tok)
    # 숫자 셀 자체도 처리
    for c in df.columns:
        for v in df[c].dropna():
            tok = _normalize_id_token(v)
            if tok:
                ids.append(tok)
    # 고유화
    return list(dict.fromkeys(ids))

def _load_account_urls_and_ids(accounts_excel_path: str):
    if not os.path.exists(accounts_excel_path):
        alt = accounts_excel_path.replace(".xlsx", "_cleaned.xlsx")
        if os.path.exists(alt):
            accounts_excel_path = alt
        else:
            raise FileNotFoundError(f"계정 파일을 찾을 수 없습니다: {accounts_excel_path}")

    xls = pd.ExcelFile(accounts_excel_path)
    frames = []
    for sheet in xls.sheet_names:
        try:
            frames.append(pd.read_excel(xls, sheet_name=sheet))
        except Exception:
            continue
    if not frames:
        raise ValueError("계정 시트가 비어있거나 읽을 수 없습니다.")

    df_accounts = pd.concat(frames, ignore_index=True)

    # URL 후보 컬럼 우선, 없으면 전체 텍스트에서 URL 추출
    candidate_cols = ["계정 URL","계정URL","url","URL","계정 링크","계정링크",
                      "페이지 URL","Page URL","페이스북 URL"]
    cols = [c for c in candidate_cols if c in df_accounts.columns]
    urls = []
    if cols:
        for c in cols:
            urls.extend(_extract_urls_from_series(df_accounts[c]))
    else:
        for c in df_accounts.columns:
            urls.extend(_extract_urls_from_series(df_accounts[c]))

    urls = [_normalize_url(u) for u in urls]
    urls = [u for u in urls if u]
    urls = list(dict.fromkeys(urls))
    fb_urls = [u for u in urls if "facebook.com" in u.lower()]
    account_urls = fb_urls if fb_urls else urls

    account_ids = _extract_ids_from_df(df_accounts)

    print(f"[FACEBOOK] 계정 URL {len(account_urls)}개 / 숫자 ID {len(account_ids)}개 로드")
    return account_urls, account_ids

# =========================================================
# 페이스북 전용 전처리
#  - 기존 전처리 우회
#  - 계정 URL/숫자 ID 포함 행 제외
#  - (URL) 단위로 중복 합치기 + 키워드 병합(|로 조인, RAW_KEYWORDS 순서 유지)
#  - 최종 저장 컬럼: ['검색어','키워드','게시물 URL','게시물 제목']
# =========================================================
def _facebook_only_preprocess(input_csv_path: str,
                              output_excel_path: str,
                              accounts_excel_path: str) -> pd.DataFrame:
    # CSV 로드(인코딩 유연)
    try:
        df = pd.read_csv(input_csv_path, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도")
        df = pd.read_csv(input_csv_path, encoding="cp949")

    # 필수 컬럼 보정
    for col in ["검색어", "키워드", "매칭키워드", "게시물 URL", "게시물 제목"]:
        if col not in df.columns:
            df[col] = ""

    # 과거 호환: '매칭키워드'만 있고 '키워드'가 비었으면 '키워드'로 이관
    df["키워드"] = df["키워드"].astype(str)
    df["매칭키워드"] = df["매칭키워드"].astype(str)
    df.loc[df["키워드"].str.strip() == "", "키워드"] = df["매칭키워드"]

    # URL 꼬리 정리(&keyword= 등)
    df["게시물 URL"] = df["게시물 URL"].astype(str).apply(lambda x: x.split("&keyword=")[0])

    # 계정 URL/ID 로드
    account_urls, account_ids = _load_account_urls_and_ids(accounts_excel_path)

    # 제외 규칙: 계정 URL/ID 포함
    def _keep(url: str) -> bool:
        s = str(url)
        if not s:
            return True
        for au in account_urls:
            if au and au in s:
                return False
        for tok in account_ids:
            if tok and tok in s:
                return False
        return True

    before = len(df)
    df = df[df["게시물 URL"].apply(_keep)]
    print(f"[FACEBOOK] 계정 URL/ID 제외: {before - len(df)}건 제거 (잔여 {len(df)})")

    # -----------------------------
    # URL 중복 합치기 + 키워드 병합
    # -----------------------------
    def _kw_to_list(s: str):
        # 'A|B|C' → ['A','B','C']
        items = [x.strip() for x in str(s).split("|") if x.strip()]
        return items

    # 그룹 단위 집계 함수들
    def _agg_keywords(series: pd.Series) -> str:
        seen = set()
        # RAW_KEYWORDS 순서 우선, 그 외 키워드는 알파벳순 뒤에
        collected = []
        # 1) RAW_KEYWORDS 내 키워드들
        bucket = []
        for s in series:
            for k in _kw_to_list(s):
                if k in _ORDER and k not in seen:
                    seen.add(k)
                    bucket.append(k)
        collected.extend(sorted(bucket, key=lambda x: _ORDER[x]))
        # 2) RAW_KEYWORDS 외 키워드들
        bucket2 = []
        for s in series:
            for k in _kw_to_list(s):
                if k not in _ORDER and k not in seen:
                    seen.add(k)
                    bucket2.append(k)
        collected.extend(sorted(bucket2))
        return "|".join(collected)

    def _first_non_empty(series: pd.Series) -> str:
        for v in series:
            sv = str(v).strip()
            if sv:
                return sv
        return ""

    def _longest_title(series: pd.Series) -> str:
        # 가장 긴 비어있지 않은 제목 선택(동률이면 최초)
        best = ""
        for v in series:
            sv = str(v).strip()
            if len(sv) > len(best):
                best = sv
        return best

    # 그룹화: 게시물 URL 기준
    grouped = df.groupby("게시물 URL", dropna=False).agg({
        "검색어": _first_non_empty,          # 대표 검색어(첫 비어있지 않은 값)
        "키워드": _agg_keywords,            # URL에 매칭된 모든 키워드를 병합
        "게시물 제목": _longest_title,       # 가장 긴 제목
    }).reset_index()

    # 최종 스키마 정렬
    out_df = grouped[["검색어", "키워드", "게시물 URL", "게시물 제목"]].copy()

    # 저장
    _ensure_parent_dir(output_excel_path)
    out_df.to_excel(output_excel_path, index=False)
    print(f"[FACEBOOK] 저장 완료 → {output_excel_path} (총 {len(out_df)}건)")
    return out_df

# =========================================================
# 엔트리: 파일명으로 페북/일반 분기
# =========================================================
def process_file(
    search_excel_path,
    input_csv_template,
    output_excel_path,
    target_year,
    target_month
):
    """
    - 페이스북: 기존 전처리 우회 + (계정 URL/숫자 ID) 제외 + URL 중복 합치기 + 키워드 병합
                → ['검색어','키워드','게시물 URL','게시물 제목'] 저장
    - 비페이스북: 기존 파이프라인 예시(검색어/연월/중복/신뢰도/'다.' 규칙)
    """
    base = os.path.basename(input_csv_template)
    is_facebook = ("페이스북" in base) or ("facebook" in base.lower())

    if is_facebook:
        try:
            return _facebook_only_preprocess(
                input_csv_path=input_csv_template,
                output_excel_path=output_excel_path,
                accounts_excel_path="(언진) 2025 매체사 검색어 계정.xlsx",
            )
        except Exception as e:
            print(f"[FACEBOOK] 전처리 오류: {e}")
            empty = pd.DataFrame(columns=["검색어", "키워드", "게시물 URL", "게시물 제목"])
            _ensure_parent_dir(output_excel_path)
            empty.to_excel(output_excel_path, index=False)
            return empty

    # ------------------------------
    # (비페이스북) 기존 전처리 파이프라인
    # ------------------------------
    try:
        pd_search = pd.read_excel(search_excel_path, sheet_name='검색어 목록')
        _ = pd_search['검색어명']
    except Exception:
        pass  # 검색어 파일이 없어도 계속

    try:
        df = pd.read_csv(input_csv_template, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도합니다.")
        df = pd.read_csv(input_csv_template, encoding="cp949")

    for col in ["게시물 URL", "게시물 제목", "게시물 내용", "계정명"]:
        if col not in df.columns:
            df[col] = ""

    df['게시물 URL'] = df['게시물 URL'].apply(lambda x: str(x).split('&keyword=')[0])
    if '게시물 등록일자' in df.columns:
        df['게시물 등록일자'] = pd.to_datetime(df['게시물 등록일자'], errors='coerce')
    else:
        df['게시물 등록일자'] = pd.NaT

    df["게시물 제목"] = df["게시물 제목"].fillna("").astype(str)
    df["게시물 내용"] = df["게시물 내용"].fillna("").astype(str)

    def _contains_keyword(row):
        kw = str(row.get('검색어', '')).lower()
        if not kw:
            return False
        return (kw in str(row['게시물 제목']).lower()) or (kw in str(row['게시물 내용']).lower())

    df1 = df[
        (df.apply(_contains_keyword, axis=1)) &
        (~df['게시물 내용'].fillna('').str.contains('신춘문예', case=False)) &
        (~df['게시물 제목'].fillna('').str.contains('신춘문예', case=False)) &
        (~df['계정명'].fillna('').str.contains('뽐뿌뉴스', case=False))
    ]

    df2 = df1[
        (df1['게시물 등록일자'].dt.year == target_year) &
        (df1['게시물 등록일자'].dt.month == target_month)
    ]

    df3 = df2.drop_duplicates(subset=['게시물 URL'], keep='first')

    df_filtered = filter_untrusted_posts(
        df3,
        untrusted_file="비신탁사_저작권문구+도메인주소.xlsx",
        trusted_file="(언진) 전처리용 도메인 주소.xlsx",
        media_file="비신탁사 매체명(전처리).xlsx"
    )

    filtered_df = filter_empty_image_and_no_da(df_filtered)

    _ensure_parent_dir(output_excel_path)
    filtered_df.to_excel(output_excel_path, index=False)

    print(f"전처리된 데이터 저장 완료 (Excel): {output_excel_path}")
    print(f"전처리 이전 : {len(df)}개\n"
          f"전처리 이후 : {len(filtered_df)}개\n"
          f"삭제 개수 : {len(df) - len(filtered_df)}개")

    return filtered_df
