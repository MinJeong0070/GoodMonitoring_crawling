# process_file.py
import os
import re
import pandas as pd
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode, unquote

# =========================================================
# 동작 옵션 (Facebook)
# =========================================================
# video/reel을 전처리에서 제외할지 여부 (태깅만 원하면 set()로)
REMOVE_URL_TYPES = {"video", "reel"}

# 링크공유형(본문 거의 없고 외부 링크 카드만) 처리 방식: "tag" 또는 "drop"
LINK_SHARE_MODE = "tag"

# 제목이 '...Facebook...' 패턴일 때 처리: "tag" 또는 "drop"
FB_SUFFIX_MODE = "drop"          # 원하시면 "tag"로
FB_SUFFIX_KO_MAXLEN = 15         # '마지막 Facebook' 앞 한글 허용 최대 길이

# 계정 엑셀 기본 경로
DEFAULT_ACCOUNTS_XLSX = "(언진) 2025 매체사 검색어 페이스북 계정.xlsx"

# =========================================================
# 동작 옵션 (Instagram) - Facebook과 독립 상수
# =========================================================
INSTAGRAM_REMOVE_URL_TYPES = {"video", "reel"}  # {"video","reel"} 일괄 제외
INSTAGRAM_LINK_SHARE_MODE = "tag"               # "tag" | "drop"
INSTAGRAM_SUFFIX_MODE = "drop"                  # "tag" | "drop"
INSTAGRAM_SUFFIX_KO_MAXLEN = 15                 # Facebook 임계치와 동일

# =========================================================
# 키워드 병합 시 정렬 기준 (크롤러와 동일) - FB/IG 공용
# =========================================================
RAW_KEYWORDS = [
    "기사공유","기사읽기","기사정리","뉴스스크랩","만평",
    "신문사설","신문필사","간추린뉴스","신문공부","지면기사",
    "경제","뉴스","스크랩","시사","정치","정부",
]
_ORDER = {k: i for i, k in enumerate(RAW_KEYWORDS)}


# =========================================================
# 공용 유틸
# =========================================================
def _ensure_parent_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def _nospace(s: str) -> str:
    return (s or "").replace("\u200b", "").replace(" ", "").strip()


# =========================================================
# 비(非)페이스북 전처리 (필요 시 사용)
# =========================================================
def filter_untrusted_posts(all_data, untrusted_file, trusted_file, media_file):
    df_untrusted = pd.read_excel(untrusted_file)
    df_trusted = pd.read_excel(trusted_file)
    df_media = pd.read_excel(media_file)

    untrusted_copyrights = df_untrusted["저작권 문구"].dropna().tolist()
    untrusted_domains = df_untrusted["도메인"].dropna().tolist()
    trusted_domains = df_trusted["도메인"].dropna().tolist()
    untrusted_media_names = df_media["매체명"].dropna().tolist()

    def should_remove(post_content):
        post_content = str(post_content)
        contains_uc = any(c in post_content for c in untrusted_copyrights)
        contains_ud = any(d in post_content for d in untrusted_domains)
        contains_um = any(m in post_content for m in untrusted_media_names)
        contains_td = any(t in post_content for t in trusted_domains)
        return (contains_uc or contains_ud or contains_um) and not contains_td

    if "게시물 내용" not in all_data.columns:
        all_data["게시물 내용"] = ""
    mask = all_data["게시물 내용"].fillna("").apply(should_remove)
    df_filtered = all_data[~mask]
    if df_filtered.empty:
        df_filtered = all_data.iloc[0:0]
    return df_filtered

def filter_empty_image_and_no_da(df_filtered):
    def has_valid_da(text):
        text = str(text)
        for m in re.finditer(r"다\.", text):
            if m.start() >= 1 and text[m.start()-1] == "니":
                continue  # '니다.' 예외
            return True
        return False

    def should_remove(title, content):
        t_ok = has_valid_da(title) or has_valid_da(content)
        has_cartoon = ("만평" in str(title)) or ("만평" in str(content))
        return (not t_ok) or has_cartoon

    for col in ["게시물 제목", "게시물 내용"]:
        if col not in df_filtered.columns:
            df_filtered[col] = ""
    mask = df_filtered.apply(lambda r: should_remove(r["게시물 제목"], r["게시물 내용"]), axis=1)
    return df_filtered[~mask]


# =========================================================
# URL/토큰 추출 공용
# =========================================================
_URL_RE = re.compile(r'https?://[^\s)"\']+', re.IGNORECASE)

def _extract_urls_from_series(series: pd.Series) -> list:
    urls = []
    for val in series.dropna().astype(str):
        s = val.replace("\u200b", "").strip()
        for piece in s.splitlines():
            p = piece.strip().strip('"').strip("'")
            if not p:
                continue
            if p.startswith(("http://", "https://")):
                urls.append(p)
                continue
            urls.extend([u.strip() for u in _URL_RE.findall(p)])
    return urls

_ID_TOKEN_RE = re.compile(r"(?:^|[^0-9])(\d{5,})")

def _normalize_id_token(raw) -> str:
    s = str(raw).strip()
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) >= 5 else ""

def _extract_ids_from_df(df: pd.DataFrame) -> list:
    ids = []
    for c in df.columns:
        col = df[c].dropna().astype(str)
        for text in col:
            # URL 내부에서 추출
            for u in _URL_RE.findall(text):
                sp = urlsplit(u)
                q = parse_qs(sp.query)
                # FB/IG 공용으로 숫자 토큰 키를 대략 커버
                for key in ("id", "fbid", "story_fbid", "page_id", "group_id", "ig_id", "user_id"):
                    if key in q:
                        for v in q[key]:
                            tok = _normalize_id_token(v)
                            if tok:
                                ids.append(tok)
                for seg in sp.path.split("/"):
                    tok = _normalize_id_token(seg)
                    if tok:
                        ids.append(tok)
            # 일반 텍스트 숫자 토큰
            for m in _ID_TOKEN_RE.finditer(text):
                tok = _normalize_id_token(m.group(1))
                if tok:
                    ids.append(tok)
    # 숫자 셀 자체
    for c in df.columns:
        for v in df[c].dropna():
            tok = _normalize_id_token(v)
            if tok:
                ids.append(tok)
    return list(dict.fromkeys(ids))


# =========================================================
# 페이스북용 URL 표준화/접두/유형/계정엑셀 파서
# =========================================================
_FB_HOSTS = {
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "web.facebook.com", "mbasic.facebook.com"
}

def _canon_fb_url(u: str) -> str:
    """
    페이스북 URL 표준화:
      - l.php 리다이렉트 해체(l.php?u=…)
      - 호스트를 www.facebook.com 으로 통일
      - 쿼리에서 utm*/fbclid/_rdr/refsrc/mibextid/gidzl/locale 제거
      - 경로 끝 슬래시 제거, 전체 소문자
    """
    s = (u or "").strip().replace("\u200b", "")
    if not s:
        return s
    sp = urlsplit(s)

    # l.php 리다이렉트 복원
    if sp.netloc.lower().endswith("facebook.com") and sp.path.lower().startswith("/l.php"):
        q = parse_qs(sp.query)
        if "u" in q and q["u"]:
            target = unquote(q["u"][0])
            return _canon_fb_url(target)

    # 호스트 통일
    host = sp.netloc.lower()
    if host in _FB_HOSTS:
        host = "www.facebook.com"

    # 쿼리 정리
    q = parse_qs(sp.query)
    DROP = {"fbclid", "_rdr", "refsrc", "mibextid", "gidzl", "locale"}
    q = {k: v for k, v in q.items() if not (k.startswith("utm") or k in DROP)}
    new_query = urlencode({k: v[0] for k, v in q.items()})

    path = sp.path.rstrip("/")

    return urlunsplit(("https", host, path, new_query, "")).lower()

def _fb_account_prefix(u: str) -> str:
    """계정 접두(prefix): https://www.facebook.com/<첫 세그먼트>"""
    cu = _canon_fb_url(u)
    sp = urlsplit(cu)
    segs = [p for p in sp.path.split("/") if p]
    if not segs:
        return ""
    return urlunsplit((sp.scheme, sp.netloc, "/" + segs[0], "", ""))

_FB_GROUP_POST_RE = re.compile(r"/groups/\d+/posts/\d+", re.IGNORECASE)

def _detect_fb_url_type(url: str) -> str:
    """
    유형 분류:
      reel/reels → 'reel'
      videos, video.php, watch?v= → 'video'
      photo.php, /photos/ → 'photo'
      /groups/<id>/posts/<id> → 'group_post'
      /posts/, /permalink/, (story_fbid|fbid query) → 'post'
      그 외 → 'unknown'
    """
    try:
        cu = _canon_fb_url(url)
        sp = urlsplit(cu)
        path = sp.path.lower()
        qs = parse_qs(sp.query)

        if "/reel/" in path or "/reels/" in path:
            return "reel"
        if "/videos/" in path or "video.php" in path:
            return "video"
        if path.startswith("/watch") or "v" in qs:
            return "video"
        if "/photo.php" in path or "/photos/" in path:
            return "photo"
        if _FB_GROUP_POST_RE.search(path):
            return "group_post"
        if "/posts/" in path or "/permalink/" in path or "story_fbid" in qs or "fbid" in qs:
            return "post"
        return "unknown"
    except Exception:
        return "unknown"

def _load_account_prefixes_and_ids(accounts_excel_path: str):
    path = accounts_excel_path
    if not os.path.exists(path):
        alt = path.replace(".xlsx", "_cleaned.xlsx")
        if os.path.exists(alt):
            path = alt
        else:
            raise FileNotFoundError(f"계정 파일을 찾을 수 없습니다: {accounts_excel_path}")

    xls = pd.ExcelFile(path)
    frames = []
    for sheet in xls.sheet_names:
        try:
            frames.append(pd.read_excel(xls, sheet_name=sheet))
        except Exception:
            continue
    if not frames:
        raise ValueError("계정 시트가 비어있거나 읽을 수 없습니다.")

    df_accounts = pd.concat(frames, ignore_index=True)

    # URL 추출 → 표준화 → 접두(prefix)
    urls = []
    candidate_cols = ["계정 URL","계정URL","url","URL","계정 링크","계정링크",
                      "페이지 URL","Page URL","페이스북 URL"]
    cols = [c for c in candidate_cols if c in df_accounts.columns]
    if cols:
        for c in cols:
            urls.extend(_extract_urls_from_series(df_accounts[c]))
    else:
        for c in df_accounts.columns:
            urls.extend(_extract_urls_from_series(df_accounts[c]))

    urls = [_canon_fb_url(u) for u in urls]
    urls = [u for u in urls if u and "facebook.com" in urlsplit(u).netloc]
    urls = list(dict.fromkeys(urls))

    prefixes = [_fb_account_prefix(u) for u in urls]
    prefixes = [p for p in prefixes if p]
    prefixes = list(dict.fromkeys(prefixes))

    ids = _extract_ids_from_df(df_accounts)

    print(f"[FACEBOOK] 계정 접두 {len(prefixes)}개 / 숫자 ID {len(ids)}개 로드")
    return prefixes, ids


# =========================================================
# 링크공유형 판정 (공용 틀 + FB/IG 토큰 분리)
# =========================================================
_FB_RM_TOKENS = ("facebook ·", "facebook·", "가입", "그룹", "관리자")
_IG_RM_TOKENS = ("instagram ·", "instagram·", "가입", "관리자")

def _norm_token(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", (s or "").lower())

def _detect_link_share(title: str, url: str):
    """
    (Facebook) 조건 중 2개 이상이면 링크공유형(True):
      - 정규화 제목 길이 < 10
      - 제목이 계정 접두 슬러그와 동일/유사
      - 제목에 fixed 토큰 포함
    """
    t_raw = str(title or "")
    t = t_raw
    for tok in _FB_RM_TOKENS:
        t = t.replace(tok, "")
    t = t.strip()
    t_norm = _norm_token(t)

    sp = urlsplit(_canon_fb_url(url))
    segs = [p for p in sp.path.split("/") if p]
    slug = segs[0] if segs else ""
    slug_norm = _norm_token(slug)

    reasons = []
    if len(t_norm) < 10:
        reasons.append("short_title")
    if slug_norm and (t_norm == slug_norm or (slug_norm in t_norm) or (t_norm in slug_norm)):
        reasons.append("slug_match")
    if any(tok in t_raw.lower() for tok in _FB_RM_TOKENS):
        reasons.append("fixed_token")

    return (len(reasons) >= 2, "|".join(reasons))

def _detect_link_share_instagram(title: str, url: str):
    """
    (Instagram) 조건 중 2개 이상이면 링크공유형(True):
      - 정규화 제목 길이 < 10
      - 제목이 계정 슬러그(@없이)와 동일/유사
      - 제목에 고정 토큰(instagram ·, 가입, 관리자 등) 포함
    """
    t_raw = str(title or "")
    t = t_raw
    for tok in _IG_RM_TOKENS:
        t = t.replace(tok, "")
    t = t.strip()
    t_norm = _norm_token(t)

    sp = urlsplit(_canon_instagram_url(url))
    segs = [p for p in sp.path.split("/") if p]
    slug = segs[0] if segs else ""
    slug = slug.lstrip("@")
    slug_norm = _norm_token(slug)

    reasons = []
    if len(t_norm) < 10:
        reasons.append("short_title")
    if slug_norm and (t_norm == slug_norm or (slug_norm in t_norm) or (t_norm in slug_norm)):
        reasons.append("slug_match")
    if any(tok in t_raw.lower() for tok in _IG_RM_TOKENS):
        reasons.append("fixed_token")

    return (len(reasons) >= 2, "|".join(reasons))


# =========================================================
# '...Facebook...' / '...Instagram...' 제목 패턴 감지
#  - 제목 안의 '마지막 키워드' 앞 '한글' 길이가 임계치 이하면 히트
# =========================================================
def _detect_short_ko_facebook_title(title: str):
    """
    ex) '경남도민일보Facebookhttps://m.facebook.com › idomin › posts'
        '대한민국박사모 - Facebook'
    """
    t_raw = str(title or "").replace("\u200b", "").strip()
    t_low = t_raw.lower()
    i = t_low.rfind("facebook")
    if i == -1:
        return (False, "")
    base = t_raw[:i].rstrip()
    base = re.sub(r'[\s\-\|·–—]+$', "", base).strip()
    ko_only = "".join(re.findall(r"[가-힣]", base))
    return (1 <= len(ko_only) <= FB_SUFFIX_KO_MAXLEN, base)

def _detect_short_ko_instagram_title(title: str):
    t_raw = str(title or "").replace("\u200b", "").strip()
    t_low = t_raw.lower()
    i = t_low.rfind("instagram")
    if i == -1:
        return (False, "")
    base = t_raw[:i].rstrip()
    base = re.sub(r'[\s\-\|·–—]+$', "", base).strip()
    ko_only = "".join(re.findall(r"[가-힣]", base))
    return (1 <= len(ko_only) <= INSTAGRAM_SUFFIX_KO_MAXLEN, base)


# =========================================================
# Instagram URL 표준화/접두/유형/계정엑셀 파서
# =========================================================
_IG_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}

def _canon_instagram_url(u: str) -> str:
    s = (u or "").strip().replace("\u200b", "")
    if not s:
        return s
    sp = urlsplit(s)

    # l.instagram.com/?u=... 리다이렉트 복원
    if sp.netloc.lower().startswith("l.instagram.com"):
        q = parse_qs(sp.query)
        if "u" in q and q["u"]:
            target = unquote(q["u"][0])
            return _canon_instagram_url(target)

    # 호스트만 표준화 (소문자)  ← path는 건드리지 않음!
    host = sp.netloc.lower()
    if host in _IG_HOSTS:
        host = "www.instagram.com"

    # 쿼리 정리
    q = parse_qs(sp.query)
    DROP = {"igshid", "__a", "__d", "fbclid", "_rdr", "refsrc"}
    q = {k: v for k, v in q.items() if not (k.startswith("utm") or k in DROP)}
    new_query = urlencode({k: v[0] for k, v in q.items()})

    path = sp.path.rstrip("/")

    # 최종 URL 반환 시 .lower() 금지  ← 대소문자 보존
    cu = urlunsplit(("https", host, path, new_query, ""))

    # 루트는 빈값 처리
    if host == "www.instagram.com" and (path == "" or path == "/") and not new_query:
        return ""
    return cu

def _ig_account_prefix(u: str) -> str:
    """계정 접두(prefix): https://www.instagram.com/<username>"""
    cu = _canon_instagram_url(u)
    if not cu:
        return ""
    sp = urlsplit(cu)
    segs = [p for p in sp.path.split("/") if p]
    if not segs:
        return ""
    return urlunsplit((sp.scheme, sp.netloc, "/" + segs[0].lstrip("@"), "", ""))

def _detect_instagram_url_type(url: str) -> str:
    """
    유형 분류 (소문자 경로 기준):
      /p/<shortcode>     → 'post'
      /reel/<shortcode>  → 'reel'
      /tv/<shortcode>    → 'video'
      /stories/<u>/<id>  → 'story'
      그 외(루트/프로필/탐색 등) → 'unknown'
    """
    try:
        cu = _canon_instagram_url(url)
        if not cu:
            return "unknown"
        sp = urlsplit(cu)
        path = sp.path.lower()
        segs = [p for p in path.split("/") if p]
        if len(segs) >= 2 and segs[0] == "p":
            return "post"
        if len(segs) >= 2 and segs[0] == "reel":
            return "reel"
        if len(segs) >= 2 and segs[0] == "tv":
            return "video"
        if len(segs) >= 3 and segs[0] == "stories":
            return "story"
        return "unknown"
    except Exception:
        return "unknown"

_HANDLE_RE = re.compile(r"@([a-zA-Z0-9._]{2,30})")
_USERNAME_RE = re.compile(r"\b([a-zA-Z0-9._]{2,30})\b")

def _load_instagram_accounts(accounts_excel_path: str):
    path = accounts_excel_path
    if not os.path.exists(path):
        alt = path.replace(".xlsx", "_cleaned.xlsx")
        if os.path.exists(alt):
            path = alt
        else:
            raise FileNotFoundError(f"인스타그램 계정 파일을 찾을 수 없습니다: {accounts_excel_path}")

    xls = pd.ExcelFile(path)
    frames = []
    for sheet in xls.sheet_names:
        try:
            frames.append(pd.read_excel(xls, sheet_name=sheet))
        except Exception:
            continue
    if not frames:
        raise ValueError("인스타그램 계정 시트가 비어있거나 읽을 수 없습니다.")

    df_accounts = pd.concat(frames, ignore_index=True)

    # 1) URL → 정규화 → 접두(prefix)
    urls = []
    for c in df_accounts.columns:
        urls.extend(_extract_urls_from_series(df_accounts[c]))
    urls = [_canon_instagram_url(u) for u in urls]
    urls = [u for u in urls if u and "instagram.com" in (urlsplit(u).netloc or "")]
    urls = list(dict.fromkeys(urls))
    prefixes = [_ig_account_prefix(u) for u in urls]
    prefixes = [p for p in prefixes if p]
    prefixes = list(dict.fromkeys(prefixes))

    # 2) 핸들(@username) / 일반 텍스트 username
    handles = []
    for c in df_accounts.columns:
        for val in df_accounts[c].dropna().astype(str):
            for m in _HANDLE_RE.finditer(val):
                handles.append(m.group(1).lower())
            # 추가: URL이 아닌 일반 텍스트에도 username 존재 가능
            for m in _USERNAME_RE.finditer(val):
                s = m.group(1).lower()
                # URL/이메일 등 혼동 최소화: 너무 짧은/긴 값 또는 도메인 포함 제외
                if 2 <= len(s) <= 30 and "." not in s or s.count(".") <= 2:
                    handles.append(s)
    handles = list(dict.fromkeys(handles))

    # 3) 숫자 ID
    ids = _extract_ids_from_df(df_accounts)

    print(f"[INSTAGRAM] 계정 접두 {len(prefixes)}개 / 핸들 {len(handles)}개 / 숫자 ID {len(ids)}개 로드")
    return prefixes, handles, ids


# =========================================================
# Facebook 전처리 메인
# =========================================================
def _facebook_only_preprocess(input_csv_path: str,
                              output_excel_path: str,
                              accounts_excel_path: str) -> pd.DataFrame:
    # CSV 로드
    try:
        df = pd.read_csv(input_csv_path, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도")
        df = pd.read_csv(input_csv_path, encoding="cp949")

    # 필수 컬럼 보정
    for col in ["검색어", "키워드", "매칭키워드", "게시물 URL", "게시물 제목", "게시물 내용"]:
        if col not in df.columns:
            df[col] = ""

    # 과거 호환: '매칭키워드'만 있고 '키워드'가 비었으면 이관
    df["키워드"] = df["키워드"].astype(str)
    df["매칭키워드"] = df["매칭키워드"].astype(str)
    df.loc[df["키워드"].str.strip() == "", "키워드"] = df["매칭키워드"]

    # URL 표준화
    df["게시물 URL"] = df["게시물 URL"].astype(str).apply(_canon_fb_url)

    # 계정 접두/ID 로드
    account_prefixes, account_ids = _load_account_prefixes_and_ids(accounts_excel_path)

    # (1) 계정 접두/ID 포함 제외
    def _keep(url: str) -> bool:
        s = _canon_fb_url(url)
        if not s:
            return True
        for pre in account_prefixes:
            if s == pre or s.startswith(pre + "/"):
                return False
        for tok in account_ids:
            if tok and tok in s:
                return False
        return True

    before = len(df)
    df = df[df["게시물 URL"].apply(_keep)]
    print(f"[FACEBOOK] 계정 접두/ID 제외: {before - len(df)}건 제거 (잔여 {len(df)})")

    # (2) URL 유형 태깅
    df["유형"] = df["게시물 URL"].apply(_detect_fb_url_type)

    # (3) 유형 일괄 제외(설정)
    if REMOVE_URL_TYPES:
        b2 = len(df)
        df = df[~df["유형"].isin(REMOVE_URL_TYPES)]
        print(f"[FACEBOOK] 유형 제외 {REMOVE_URL_TYPES}: {b2 - len(df)}건 제거 (잔여 {len(df)})")

    # (4) 링크공유형 태깅/제외
    ls_flags, ls_reasons = [], []
    for _, r in df.iterrows():
        flag, reason = _detect_link_share(r.get("게시물 제목", ""), r.get("게시물 URL", ""))
        ls_flags.append("Y" if flag else "N")
        ls_reasons.append(reason)
    df["링크공유형"] = ls_flags
    df["링크공유_사유"] = ls_reasons

    if LINK_SHARE_MODE.lower() == "drop":
        b3 = len(df)
        df = df[df["링크공유형"] != "Y"]
        print(f"[FACEBOOK] 링크공유형 제외: {b3 - len(df)}건 제거 (잔여 {len(df)})")
    else:
        print("[FACEBOOK] 링크공유형은 태깅만 수행(LINK_SHARE_MODE='tag')")

    # (5) '...Facebook...' 제목 패턴 태깅/제외
    fb_suf_flags, fb_suf_bases = [], []
    for _, r in df.iterrows():
        hit, base = _detect_short_ko_facebook_title(r.get("게시물 제목", ""))
        fb_suf_flags.append("Y" if hit else "N")
        fb_suf_bases.append(base)
    df["제목_Facebook접미사"] = fb_suf_flags
    df["제목_접미사_앞부분"] = fb_suf_bases

    if FB_SUFFIX_MODE.lower() == "drop":
        b4 = len(df)
        df = df[df["제목_Facebook접미사"] != "Y"]
        print(f"[FACEBOOK] '...Facebook...' 제목 패턴 제외: {b4 - len(df)}건 제거 (잔여 {len(df)})")
    else:
        print("[FACEBOOK] '...Facebook...' 제목 패턴은 태깅만 수행(FB_SUFFIX_MODE='tag')")

    # (6) URL 중복 합치기 + 키워드 병합
    def _kw_to_list(s: str):
        return [x.strip() for x in str(s).split("|") if x.strip()]

    def _agg_keywords(series: pd.Series) -> str:
        seen = set()
        collected = []
        # RAW_KEYWORDS 순서 우선
        bucket = []
        for s in series:
            for k in _kw_to_list(s):
                if k in _ORDER and k not in seen:
                    seen.add(k); bucket.append(k)
        collected.extend(sorted(bucket, key=lambda x: _ORDER[x]))
        # 그 외 키워드
        bucket2 = []
        for s in series:
            for k in _kw_to_list(s):
                if k not in _ORDER and k not in seen:
                    seen.add(k); bucket2.append(k)
        collected.extend(sorted(bucket2))
        return "|".join(collected)

    def _first_non_empty(series: pd.Series) -> str:
        for v in series:
            sv = str(v).strip()
            if sv:
                return sv
        return ""

    def _longest_title(series: pd.Series) -> str:
        best = ""
        for v in series:
            sv = str(v).strip()
            if len(sv) > len(best):
                best = sv
        return best

    grouped = df.groupby("게시물 URL", dropna=False).agg({
        "검색어": _first_non_empty,
        "키워드": _agg_keywords,
        "게시물 제목": _longest_title,
        "유형": _first_non_empty,
        "링크공유형": lambda s: "Y" if any(x == "Y" for x in s) else "N",
        "링크공유_사유": _first_non_empty,
        "제목_Facebook접미사": lambda s: "Y" if any(x == "Y" for x in s) else "N",
        "제목_접미사_앞부분": _first_non_empty,
    }).reset_index()

    # (7) 저장 컬럼 고정
    desired_cols = ["검색어", "키워드", "게시물URL", "게시물 제목", "유형"]
    tmp = grouped.rename(columns={"게시물 URL": "게시물URL"}).copy()
    for c in desired_cols:
        if c not in tmp.columns:
            tmp[c] = ""
    out_df = tmp.reindex(columns=desired_cols)

    _ensure_parent_dir(output_excel_path)
    out_df.to_excel(output_excel_path, index=False)
    print(f"[FACEBOOK] 저장 완료 → {output_excel_path} (총 {len(out_df)}건)")
    return out_df


# =========================================================
# Instagram 전처리 메인
# =========================================================
def _instagram_only_preprocess(input_csv_path: str,
                               output_excel_path: str,
                               accounts_excel_path: str) -> pd.DataFrame:
    # 1) CSV 로드
    try:
        df = pd.read_csv(input_csv_path, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도")
        df = pd.read_csv(input_csv_path, encoding="cp949")

    # 필수 컬럼 보정
    for col in ["검색어", "키워드", "매칭키워드", "게시물 URL", "게시물 제목", "게시물 내용"]:
        if col not in df.columns:
            df[col] = ""

    # 과거 호환: '매칭키워드'만 있고 '키워드'가 비었으면 이관
    df["키워드"] = df["키워드"].astype(str)
    df["매칭키워드"] = df["매칭키워드"].astype(str)
    df.loc[df["키워드"].str.strip() == "", "키워드"] = df["매칭키워드"]

    # 2) URL 표준화
    df["게시물 URL"] = df["게시물 URL"].astype(str).apply(_canon_instagram_url)

    # 3) 계정 접두/핸들/ID 로드
    account_prefixes, account_handles, account_ids = _load_instagram_accounts(accounts_excel_path)
    handles_set = set(h.lower().lstrip("@") for h in account_handles)

    # ✅ 접두 URL에서 username만 뽑아 세트로 보관(엑셀에 핸들이 없어도 동작)
    def _user_from_prefix(p: str) -> str:
        try:
            sp = urlsplit(p)
            segs = [s for s in sp.path.split("/") if s]
            return segs[0].lstrip("@").lower() if segs else ""
        except Exception:
            return ""

    prefix_users = {_user_from_prefix(p) for p in account_prefixes if p}
    prefix_users.discard("")

    # 기존 핸들 세트(있으면 활용)
    handles_set = {h.lower().lstrip("@") for h in account_handles if isinstance(h, str) and h}

    # ✅ 최종 비교용: 접두에서 추출한 username ∪ 핸들
    account_users = prefix_users | handles_set

    def _contains_account_in_url(full_url: str,
                                 prefixes: set[str],
                                 users: set[str]) -> bool:
        """
        URL 전체(스킴~쿼리~해시)를 소문자로 두고,
        - 접두 URL이 그대로 포함되는지
        - '/username/' 같은 경계가 있는 패턴이 포함되는지
        - unquote한 문자열에도 포함되는지
        를 모두 확인한다.
        """
        if not full_url:
            return False
        raw = full_url
        s = raw.lower()
        su = unquote(raw).lower()

        # ① 접두 URL(https://www.instagram.com/<username>) 그대로 포함
        for pre in prefixes:
            pl = pre.lower().rstrip("/")
            if not pl:
                continue
            if (pl == s) or s.startswith(pl + "/") or s.startswith(pl + "?") or s.startswith(pl + "#") \
                    or (pl in s):  # 안전하게 부분 포함까지
                return True
            if (pl in su):  # 쿼리 인코딩 상태에 들어있을 수도 있음
                return True

        # ② '/<username>/' 경계 포함 (stories/<u>/..., reel/<u>/..., tv/<u>/... 포함)
        for u in users:
            ul = u.lower().lstrip("@")
            if not ul:
                continue
            for hay in (s, su):
                if f"/{ul}/" in hay or hay.endswith(f"/{ul}") or hay.startswith(f"https://www.instagram.com/{ul}") \
                        or f"/stories/{ul}/" in hay:
                    return True

        return False

    # 4) 계정 제외
    def _keep(url: str) -> bool:
        s = _canon_instagram_url(url)
        if not s:
            return True
        sp = urlsplit(s)
        path_raw = sp.path or ""
        path_low = path_raw.lower()

        # ① 접두 URL 자체(=프로필 루트/하위 경로) → ?,/ 구분 모두 허용
        for pre in account_prefixes:
            if not pre:
                continue
            if s == pre or s.startswith(pre + "/") or s.startswith(pre + "?"):
                return False

        # ② 경로 세그먼트 어디든 계정명이 나오면 제외 (stories/계정/ID, reel/계정/…, tv/계정/… 포함)
        segs = [p.lstrip("@") for p in path_low.split("/") if p]
        if any(seg in account_users for seg in segs):
            return False

        # ③ 숫자 ID 토큰 매칭으로도 제외
        for tok in account_ids:
            if tok and tok in s:
                return False

        return True

    before = len(df)
    df = df[df["게시물 URL"].apply(_keep)]
    print(f"[INSTAGRAM] 계정 접두/핸들/ID 제외: {before - len(df)}건 제거 (잔여 {len(df)})")

    # 5) 유형 태깅
    df["유형"] = df["게시물 URL"].apply(_detect_instagram_url_type)

    # 6) 유형 일괄 제외
    if INSTAGRAM_REMOVE_URL_TYPES:
        b2 = len(df)
        df = df[~df["유형"].isin(INSTAGRAM_REMOVE_URL_TYPES)]
        print(f"[INSTAGRAM] 유형 제외 {INSTAGRAM_REMOVE_URL_TYPES}: {b2 - len(df)}건 제거 (잔여 {len(df)})")

    # 7) 링크공유형 태깅/제외
    ls_flags, ls_reasons = [], []
    for _, r in df.iterrows():
        flag, reason = _detect_link_share_instagram(r.get("게시물 제목", ""), r.get("게시물 URL", ""))
        ls_flags.append("Y" if flag else "N")
        ls_reasons.append(reason)
    df["링크공유형"] = ls_flags
    df["링크공유_사유"] = ls_reasons

    if INSTAGRAM_LINK_SHARE_MODE.lower() == "drop":
        b3 = len(df)
        df = df[df["링크공유형"] != "Y"]
        print(f"[INSTAGRAM] 링크공유형 제외: {b3 - len(df)}건 제거 (잔여 {len(df)})")
    else:
        print("[INSTAGRAM] 링크공유형은 태깅만 수행(INSTAGRAM_LINK_SHARE_MODE='tag')")

    # 8) '...Instagram...' 제목 패턴 태깅/제외
    ig_suf_flags, ig_suf_bases = [], []
    for _, r in df.iterrows():
        hit, base = _detect_short_ko_instagram_title(r.get("게시물 제목", ""))
        ig_suf_flags.append("Y" if hit else "N")
        ig_suf_bases.append(base)
    df["제목_Instagram접미사"] = ig_suf_flags
    df["제목_접미사_앞부분"] = ig_suf_bases

    if INSTAGRAM_SUFFIX_MODE.lower() == "drop":
        b4 = len(df)
        df = df[df["제목_Instagram접미사"] != "Y"]
        print(f"[INSTAGRAM] '...Instagram...' 제목 패턴 제외: {b4 - len(df)}건 제거 (잔여 {len(df)})")
    else:
        print("[INSTAGRAM] '...Instagram...' 제목 패턴은 태깅만 수행(INSTAGRAM_SUFFIX_MODE='tag')")

    # 9) URL 중복 합치기 + 키워드 병합 (FB와 동일 로직)
    def _kw_to_list(s: str):
        return [x.strip() for x in str(s).split("|") if x.strip()]

    def _agg_keywords(series: pd.Series) -> str:
        seen = set()
        collected = []
        bucket = []
        for s in series:
            for k in _kw_to_list(s):
                if k in _ORDER and k not in seen:
                    seen.add(k); bucket.append(k)
        collected.extend(sorted(bucket, key=lambda x: _ORDER[x]))
        bucket2 = []
        for s in series:
            for k in _kw_to_list(s):
                if k not in _ORDER and k not in seen:
                    seen.add(k); bucket2.append(k)
        collected.extend(sorted(bucket2))
        return "|".join(collected)

    def _first_non_empty(series: pd.Series) -> str:
        for v in series:
            sv = str(v).strip()
            if sv:
                return sv
        return ""

    def _longest_title(series: pd.Series) -> str:
        best = ""
        for v in series:
            sv = str(v).strip()
            if len(sv) > len(best):
                best = sv
        return best

    grouped = df.groupby("게시물 URL", dropna=False).agg({
        "검색어": _first_non_empty,
        "키워드": _agg_keywords,
        "게시물 제목": _longest_title,
        "유형": _first_non_empty,
        "링크공유형": lambda s: "Y" if any(x == "Y" for x in s) else "N",
        "링크공유_사유": _first_non_empty,
        "제목_Instagram접미사": lambda s: "Y" if any(x == "Y" for x in s) else "N",
        "제목_접미사_앞부분": _first_non_empty,
    }).reset_index()

    # 10) 저장 컬럼/순서 고정
    desired_cols = ["검색어", "키워드", "게시물URL", "게시물 제목", "유형"]
    tmp = grouped.rename(columns={"게시물 URL": "게시물URL"}).copy()
    for c in desired_cols:
        if c not in tmp.columns:
            tmp[c] = ""
    out_df = tmp.reindex(columns=desired_cols)

    # 11) 저장 & 요약
    _ensure_parent_dir(output_excel_path)
    out_df.to_excel(output_excel_path, index=False)
    print(f"[INSTAGRAM] 저장 완료 → {output_excel_path} (총 {len(out_df)}건)")
    return out_df


# =========================================================
# 엔트리: 파일명으로 페북/인스타/일반 분기
# =========================================================
def process_file(
    search_excel_path,
    input_csv_template,
    output_excel_path,
    target_year,
    target_month
):
    """
    - 페이스북: 계정 접두/ID 제외 → 유형 태깅(+video/reel 제외 옵션)
               → 링크공유형 태깅/제외 → '...Facebook...' 제목 패턴 태깅/제외
               → URL 중복 합치기 + 키워드 병합
               → ['검색어','키워드','게시물 URL','게시물 제목','유형', ...] 저장
    - 인스타그램: 계정 접두/핸들/ID 제외 → 유형 태깅(+video/reel 제외 옵션)
               → 링크공유형 태깅/제외 → '...Instagram...' 제목 패턴 태깅/제외
               → URL 중복 합치기 + 키워드 병합
               → ['검색어','키워드','게시물 URL','게시물 제목','유형'] 저장
    - 기타(비-FB/IG): 기존 파이프라인(검색어/연월/신뢰도/'다.' 규칙) 후 전체 컬럼 저장
    """
    base = os.path.basename(input_csv_template)
    low = base.lower()
    is_facebook = ("페이스북" in base) or ("facebook" in low)
    is_instagram = ("인스타그램" in base) or ("instagram" in low)

    if is_facebook:
        try:
            accounts_path = DEFAULT_ACCOUNTS_XLSX
            return _facebook_only_preprocess(
                input_csv_path=input_csv_template,
                output_excel_path=output_excel_path,
                accounts_excel_path=accounts_path,
            )
        except Exception as e:
            print(f"[FACEBOOK] 전처리 오류: {e}")
            cols = ["검색어", "키워드", "게시물 URL", "게시물 제목", "유형"]
            if LINK_SHARE_MODE.lower() == "tag":
                cols += ["링크공유형", "링크공유_사유"]
            if FB_SUFFIX_MODE.lower() == "tag":
                cols += ["제목_Facebook접미사", "제목_접미사_앞부분"]
            empty = pd.DataFrame(columns=cols)
            _ensure_parent_dir(output_excel_path)
            empty.to_excel(output_excel_path, index=False)
            return empty

    if is_instagram:
        try:
            accounts_path = "(언진) 2025 매체사 검색어 인스타그램 계정.xlsx"
            return _instagram_only_preprocess(
                input_csv_path=input_csv_template,
                output_excel_path=output_excel_path,
                accounts_excel_path=accounts_path,
            )
        except Exception as e:
            print(f"[INSTAGRAM] 전처리 오류: {e}")
            cols = ["검색어", "키워드", "게시물 URL", "게시물 제목", "유형"]
            if INSTAGRAM_LINK_SHARE_MODE.lower() == "tag":
                cols += ["링크공유형", "링크공유_사유"]
            if INSTAGRAM_SUFFIX_MODE.lower() == "tag":
                cols += ["제목_Instagram접미사", "제목_접미사_앞부분"]
            empty = pd.DataFrame(columns=cols)
            _ensure_parent_dir(output_excel_path)
            empty.to_excel(output_excel_path, index=False)
            return empty

    # ------------------------------
    # (비-FB/IG) 기존 전처리 파이프라인
    # ------------------------------
    try:
        pd_search = pd.read_excel(search_excel_path, sheet_name='검색어 목록')
        _ = pd_search['검색어명']
    except Exception:
        pass

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
