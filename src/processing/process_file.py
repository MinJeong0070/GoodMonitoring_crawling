import os
import re
import pandas as pd
from datetime import datetime

# ------------------------------
# 공용 유틸
# ------------------------------
def _ensure_parent_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

# ------------------------------
# 기존 보조 함수 (비페이스북 전처리에서 사용)
# ------------------------------
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

    # 필터링 함수 정의
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

    # 결측값 방지
    if "게시물 내용" not in all_data.columns:
        all_data["게시물 내용"] = ""
    content_series = all_data["게시물 내용"].fillna("")
    mask = content_series.apply(should_remove)

    # 유지할 데이터
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
                continue  # '니다.'이면 무시
            return True  # 유효한 '다.' 발견

        return False

    def should_remove(title, content):
        has_valid = has_valid_da(title) or has_valid_da(content)
        has_cartoon = "만평" in title or "만평" in content
        return not has_valid or has_cartoon

    # 결측/누락 컬럼 안전화
    for col in ["게시물 제목", "게시물 내용"]:
        if col not in df_filtered.columns:
            df_filtered[col] = ""
    mask = df_filtered.apply(lambda row: should_remove(row["게시물 제목"], row["게시물 내용"]), axis=1)

    df_final = df_filtered[~mask]
    return df_final


# ------------------------------
# 페이스북 전용: 계정 URL 기반 제외 처리만 적용
# ------------------------------
_URL_RE = re.compile(r'https?://[^\s)"\']+', re.IGNORECASE)

def _extract_urls_from_series(series: pd.Series) -> list:
    urls = []
    for val in series.dropna().astype(str):
        s = val.replace("\u200b", "").strip()
        # 셀 하나에 여러 URL이 줄바꿈/따옴표로 섞여 있는 경우 처리
        for piece in s.splitlines():
            p = piece.strip().strip('"').strip("'")
            if not p:
                continue
            # 상대경로 보정: /account/ → https://www.facebook.com/account/
            if p.startswith("/") and len(p) > 1:
                urls.append("https://www.facebook.com" + p)
                continue
            # 전체가 URL이면 그대로
            if p.startswith(("http://", "https://")):
                urls.append(p)
                continue
            # 문장 중 URL 패턴 추출
            found = _URL_RE.findall(p)
            urls.extend([u.strip() for u in found])
    return urls

def _normalize_url(u: str) -> str:
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
        sp = urlsplit(u)
        # 루트 도메인은 제거(모든 게시물과 매칭되는 사고 방지)
        if sp.netloc.lower().endswith("facebook.com") and (sp.path in ("", "/")):
            return ""
        # 불필요 파라미터 제거
        q = parse_qs(sp.query)
        for k in list(q):
            if k.startswith("utm") or k in ("refsrc", "mibextid", "_fb_noscript"):
                q.pop(k, None)
        return urlunsplit((sp.scheme, sp.netloc, sp.path.rstrip("/"),
                           urlencode({k: v[0] for k, v in q.items()}), ""))
    except Exception:
        return u.strip().rstrip("/")

def _load_account_urls(accounts_excel_path: str) -> list:
    """
    '(언진) 2025 매체사 검색어 계정.xlsx'의 모든 시트를 읽고,
    모든 텍스트 컬럼에서 URL/상대경로를 자동 추출 → 보정/정규화 → 중복 제거.
    루트 도메인은 자동 무시.
    """
    if not os.path.exists(accounts_excel_path):
        # 사용 중이던 클린 파일로 대체 사용 허용
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
        raise ValueError("엑셀에서 읽을 수 있는 시트를 찾지 못했습니다.")

    df_accounts = pd.concat(frames, ignore_index=True)

    # 우선순위 컬럼이 있으면 먼저, 없으면 전체 컬럼을 훑어서 추출
    candidate_cols = ["계정 URL", "계정URL", "url", "URL", "계정 링크", "계정링크",
                      "페이지 URL", "Page URL", "페이스북 URL"]
    cols = [c for c in candidate_cols if c in df_accounts.columns]
    urls = []
    if cols:
        for c in cols:
            urls.extend(_extract_urls_from_series(df_accounts[c]))
    else:
        for c in df_accounts.columns:
            urls.extend(_extract_urls_from_series(df_accounts[c]))

    # 정규화 + 공백/루트 제거 + 중복 제거
    urls = [_normalize_url(u) for u in urls]
    urls = [u for u in urls if u]  # 빈 값 제거
    urls = list(dict.fromkeys(urls))  # 순서 유지 중복 제거

    # 가능하면 facebook 도메인만
    fb_urls = [u for u in urls if "facebook.com" in u.lower()]
    final = fb_urls if fb_urls else urls
    if not final:
        raise ValueError("계정 URL을 추출하지 못했습니다. 엑셀에 계정 링크가 있는지 확인하세요.")
    print(f"[FACEBOOK] 계정 URL 로드: {len(final)}개")
    return final

def _facebook_only_preprocess(input_csv_template: str,
                              output_excel_path: str,
                              accounts_excel_path: str) -> pd.DataFrame:
    """
    페이스북만: 기존 전처리 전부 우회 + 계정 URL 포함 게시물 제외
    결과 컬럼: ['검색어', '게시물 URL', '게시물 제목']
    """
    # CSV 로드(인코딩 유연)
    try:
        df = pd.read_csv(input_csv_template, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도")
        df = pd.read_csv(input_csv_template, encoding="cp949")

    # 필수 컬럼 보정
    for col in ["게시물 URL", "게시물 제목", "검색어"]:
        if col not in df.columns:
            df[col] = ""

    # URL 표준화 (기존 로직 유지)
    df["게시물 URL"] = df["게시물 URL"].astype(str).apply(lambda x: x.split("&keyword=")[0])

    # 계정 URL 목록 적재
    account_urls = _load_account_urls(accounts_excel_path)

    # 제외 처리: '게시물 URL' 안에 계정 URL이 포함되면 제거
    before_len = len(df)
    def _keep_row(url: str) -> bool:
        url = str(url)
        if not url:
            return True
        return not any(acc in url for acc in account_urls)

    df = df[df["게시물 URL"].apply(_keep_row)]
    removed = before_len - len(df)
    print(f"[FACEBOOK] 계정 URL 제외: {removed}건 제거, 남은 {len(df)}건")

    # 중복 URL 제거(안정성)
    df = df.drop_duplicates(subset=["게시물 URL"], keep="first")

    # 최종 컬럼 제한
    out_df = df[["검색어", "게시물 URL", "게시물 제목"]].copy()

    # 저장
    _ensure_parent_dir(output_excel_path)
    out_df.to_excel(output_excel_path, index=False)
    print(f"[FACEBOOK] 저장 완료 → {output_excel_path}")
    print(f"[FACEBOOK] 최종 건수: {len(out_df)}개")
    return out_df


# ------------------------------
# 엔트리: 사이트별 분기
# ------------------------------
def process_file(
    search_excel_path,
    input_csv_template,
    output_excel_path,
    target_year,
    target_month
):
    """
    - 기본: 기존 전처리 파이프라인 실행
    - 페이스북: 기존 전처리 우회하고 '계정 URL 제외'만 적용 + 컬럼 ['검색어', '게시물 URL', '게시물 제목']
    """
    # 파일명 기준으로 '페이스북' 여부 판정 (run_preprocess에서도 동일 규칙)
    base = os.path.basename(input_csv_template)
    is_facebook = "페이스북" in base or "facebook" in base.lower()

    if is_facebook:
        try:
            return _facebook_only_preprocess(
                input_csv_template=input_csv_template,
                output_excel_path=output_excel_path,
                accounts_excel_path="(언진) 2025 매체사 검색어 계정.xlsx",
            )
        except Exception as e:
            print(f"[FACEBOOK] 전처리 오류: {e}")
            # 실패 시 빈 프레임이라도 저장
            empty = pd.DataFrame(columns=["검색어", "게시물 URL", "게시물 제목"])
            _ensure_parent_dir(output_excel_path)
            empty.to_excel(output_excel_path, index=False)
            return empty

    # ------------------------------
    # (비페이스북) 기존 전처리 파이프라인
    # ------------------------------
    result_dir = '결과'
    os.makedirs(result_dir, exist_ok=True)

    # 검색어 파일 로드 (미사용 변수지만 기존과 동일하게 유지)
    pd_search = pd.read_excel(search_excel_path, sheet_name='검색어 목록')
    _ = pd_search['검색어명']

    # CSV 로드
    try:
        df = pd.read_csv(input_csv_template, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도합니다.")
        df = pd.read_csv(input_csv_template, encoding="cp949")

    # 필수 컬럼 안전화
    for col in ["게시물 URL", "게시물 제목", "게시물 내용", "계정명"]:
        if col not in df.columns:
            df[col] = ""

    df['게시물 URL'] = df['게시물 URL'].apply(lambda x: str(x).split('&keyword=')[0])

    # 날짜 컬럼이 없거나 파싱 실패 시 NaT로 두고, 이후 연/월 필터에서 안전 처리
    if '게시물 등록일자' in df.columns:
        df['게시물 등록일자'] = pd.to_datetime(df['게시물 등록일자'], errors='coerce')
    else:
        df['게시물 등록일자'] = pd.NaT

    df["게시물 제목"] = df["게시물 제목"].fillna("").astype(str)
    df["게시물 내용"] = df["게시물 내용"].fillna("").astype(str)

    # 검색어 포함 여부 필터 (검색어 NaN 대비)
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

    # 연/월 필터 (NaT는 자동 제외)
    df2 = df1[
        (df1['게시물 등록일자'].dt.year == target_year) &
        (df1['게시물 등록일자'].dt.month == target_month)
    ]

    df3 = df2.drop_duplicates(subset=['게시물 URL'], keep='first')

    # 비신탁사 매체명 기반 필터링
    df_filtered = filter_untrusted_posts(
        df3,
        untrusted_file="비신탁사_저작권문구+도메인주소.xlsx",
        trusted_file="(언진) 전처리용 도메인 주소.xlsx",
        media_file="비신탁사 매체명(전처리).xlsx"
    )

    # '다.' 기준 추가 필터링
    filtered_df = filter_empty_image_and_no_da(df_filtered)

    # 결과 파일 저장
    _ensure_parent_dir(output_excel_path)
    filtered_df.to_excel(output_excel_path, index=False)

    print(f"전처리된 데이터 저장 완료 (Excel): {output_excel_path}")
    print(f"전처리 이전 : {len(df)}개\n"
          f"전처리 이후 : {len(filtered_df)}개\n"
          f"삭제 개수 : {len(df) - len(filtered_df)}개")

    return filtered_df
