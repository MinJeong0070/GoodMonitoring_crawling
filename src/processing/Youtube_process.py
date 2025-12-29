import re
from pathlib import Path
import pandas as pd
from urllib.parse import urlparse

# ====== 설정 ======
MAIN_CAND = {
    "search": ["검색어"],
    "platform": ["플랫폼", "platform"],
    "post_url": ["게시물 URL", "게시물URL", "포스트URL", "URL"],
    "title": ["게시물 제목", "게시글제목", "제목"],
    "date": ["등록일자", "게시물 등록일자", "업로드일자"],
    "account_name": ["채널명", "계정명"],
    "account_url": ["계정 URL", "계정URL", "채널URL", "채널 URL"],
}
OUTPUT_ORDER = ["검색어", "플랫폼", "게시물 URL", "게시물 제목", "게시물 등록일자", "계정명"]
DEFAULT_PLATFORM = "유튜브"
YOUTUBE_HOSTS = {"youtube.com", "youtu.be"}


# ====== 유틸 ======
def choose_col(df, candidates):
    for name in candidates:
        if name in df.columns:
            return name
    norm = {re.sub(r"\s+", "", c).lower(): c for c in df.columns}
    for name in candidates:
        key = re.sub(r"\s+", "", name).lower()
        if key in norm:
            return norm[key]
    return None


def normalize_url(u: str) -> str:
    """스킴/www/쿼리/프래그먼트 제거, 소문자화, 끝 슬래시 제거. 유튜브 도메인만 유지."""
    if not isinstance(u, str) or not u.strip():
        return ""
    u = u.strip()
    if not re.match(r"^https?://", u, flags=re.I):
        u_work = "http://" + u
    else:
        u_work = u
    try:
        p = urlparse(u_work)
        host = (p.netloc or "").lower()
        host = host[4:] if host.startswith("www.") else host
        path = (p.path or "").strip("/")
        if host not in YOUTUBE_HOSTS:
            return ""
        core = f"{host}/{path}" if path else host
        return core.rstrip("/")
    except Exception:
        return ""


def extract_urls_from_text(text: str):
    """임의 텍스트에서 모든 http(s) URL 추출"""
    if not isinstance(text, str):
        return []
    return re.findall(r"https?://[^\s\"'>)]+", text)


def collect_ref_urls_from_excel(path: Path):
    """엑셀의 모든 시트/셀을 스캔해 URL 전부 수집"""
    urls = []
    xls = pd.ExcelFile(path, engine="openpyxl")
    for sheet in xls.sheet_names:
        df = xls.parse(sheet)
        for col in df.columns:
            series = df[col].dropna().astype(str)
            for v in series:
                urls.extend(extract_urls_from_text(v))
    return urls


def collect_ref_urls_from_txt(path: Path, encoding_candidates=("utf-8-sig", "cp949", "utf-8")):
    """TXT/CSV 등 텍스트 파일에서 URL 수집(인코딩 자동 시도)"""
    text = None
    for enc in encoding_candidates:
        try:
            text = Path(path).read_text(encoding=enc, errors="ignore")
            break
        except Exception:
            text = None
    if text is None:
        text = Path(path).read_text(errors="ignore")
    return extract_urls_from_text(text)


def collect_ref_names_from_excel(path: Path):
    """
    엑셀 파일에서 '채널명/계정명' 등 계정명 후보 문자열 수집
    (컬럼명에 채널/계정/channel/name/account/이름 포함 시 계정명 컬럼으로 간주)
    """
    names = []
    xls = pd.ExcelFile(path, engine="openpyxl")
    for sheet in xls.sheet_names:
        df = xls.parse(sheet)
        for col in df.columns:
            norm_col = re.sub(r"\s+", "", str(col)).lower()
            if any(key in norm_col for key in ["채널", "계정", "channel", "name", "account", "이름"]):
                series = df[col].dropna().astype(str)
                names.extend([s.strip() for s in series if s.strip()])
    return names


def build_ref_sets(ref_paths):
    """
    여러 화이트리스트 파일(.xlsx/.txt/.csv…)에서
    - URL 수집 → 정규화 → 고유 URL set
    - 계정명(채널명/계정명) 수집 → 소문자/strip → 고유 이름 set
    를 동시에 생성
    return: (url_set, name_set, raw_url_count, raw_name_count)
    """
    raw_urls = []
    raw_names = []

    for p in ref_paths:
        p = Path(p)
        if not p.exists():
            print(f"⚠️ 파일을 찾을 수 없습니다: {p}")
            continue

        if p.suffix.lower() in [".xlsx", ".xlsm", ".xls"]:
            raw_urls.extend(collect_ref_urls_from_excel(p))
            raw_names.extend(collect_ref_names_from_excel(p))
        else:
            raw_urls.extend(collect_ref_urls_from_txt(p))

    norm_urls = [normalize_url(u) for u in raw_urls]
    norm_urls = [u for u in norm_urls if u]

    norm_names = []
    for n in raw_names:
        if isinstance(n, str):
            n_strip = n.strip()
            if n_strip:
                norm_names.append(n_strip.lower())

    return set(norm_urls), set(norm_names), len(raw_urls), len(raw_names)


def mark_rows_to_drop(df_main, acc_url_col, acc_name_col, search_col, ref_url_set, ref_name_set):
    """
    전처리(삭제) 기준:
    1) 계정 URL(정규화)이 화이트리스트 URL에 '정확히 일치' 하거나
    2) 채널명/계정명이 화이트리스트 계정명과 일치하거나
    3) 검색어가 화이트리스트 계정명과 일치하는 경우
    """
    # URL 기준
    urls = df_main[acc_url_col].astype(str).map(normalize_url)

    if acc_name_col:
        names = df_main[acc_name_col].astype(str).str.strip().str.lower()
    else:
        names = pd.Series([""] * len(df_main), index=df_main.index)

    # 검색어 기준
    if search_col:
        searches = df_main[search_col].astype(str).str.strip().str.lower()
    else:
        searches = pd.Series([""] * len(df_main), index=df_main.index)

    flags = []
    for u, n, s in zip(urls, names, searches):
        cond_url = u in ref_url_set if u else False
        cond_name = n in ref_name_set if n else False
        cond_search = s in ref_name_set if s else False
        flags.append(cond_url or cond_name or cond_search)
    return flags


# ====== 메인 ======
def main():
    print("📂 유튜브 계정 URL 전처리")
    main_path = Path(input("👉 원본 파일 경로(.xlsx): ").strip('"').strip())

    off_input = input("📘 공식 화이트리스트 파일 경로들(.xlsx/.txt, 여러 개는 ; 또는 줄바꿈 구분):\n")
    unofficial_input = input("📕 비공식 계정 정보 파일 경로들(.xlsx/.txt, 여러 개는 ; 또는 줄바꿈 구분):\n")

    official_paths = [p.strip().strip('"').strip() for p in re.split(r"[;\n]+", off_input) if p.strip()]
    unofficial_paths = [p.strip().strip('"').strip() for p in re.split(r"[;\n]+", unofficial_input) if p.strip()]

    if not main_path.exists():
        print(f"❌ 원본 파일을 찾을 수 없습니다: {main_path}")
        return
    if not official_paths and not unofficial_paths:
        print("❌ 공식/비공식 파일 경로가 비어 있습니다.")
        return

    # ---- 메인 데이터 로드 ----
    df_main = pd.read_excel(main_path, engine="openpyxl")

    # ---- 컬럼 식별 ----
    m_search = choose_col(df_main, MAIN_CAND["search"])
    m_platform = choose_col(df_main, MAIN_CAND["platform"])
    m_post_url = choose_col(df_main, MAIN_CAND["post_url"])
    m_title = choose_col(df_main, MAIN_CAND["title"])
    m_date = choose_col(df_main, MAIN_CAND["date"])
    m_acc_name = choose_col(df_main, MAIN_CAND["account_name"])
    m_acc_url = choose_col(df_main, MAIN_CAND["account_url"])
    if not m_acc_url:
        raise ValueError("⚠️ 원본 파일에서 '계정 URL' 컬럼을 찾지 못했습니다.")

    if official_paths:
        official_url_set, official_name_set, official_raw_url, official_raw_name = build_ref_sets(official_paths)
    else:
        official_url_set, official_name_set, official_raw_url, official_raw_name = set(), set(), 0, 0

    if unofficial_paths:
        unofficial_url_set, unofficial_name_set, unofficial_raw_url, unofficial_raw_name = build_ref_sets(unofficial_paths)
    else:
        unofficial_url_set, unofficial_name_set, unofficial_raw_url, unofficial_raw_name = set(), set(), 0, 0

    union_url_set = official_url_set | unofficial_url_set
    union_name_set = official_name_set | unofficial_name_set

    print("\n📊 기준 URL/계정명 집계(정규화 후 고유 기준은 유튜브 도메인 한정)")
    print(f"- 공식 원시 URL 총 개수              : {official_raw_url}")
    print(f"- 공식 정규화 고유 URL 개수          : {len(official_url_set)}")
    print(f"- 공식 계정명 원시 개수              : {official_raw_name}")
    print(f"- 공식 계정명 고유 개수              : {len(official_name_set)}")
    print(f"- 비공식 원시 URL 총 개수            : {unofficial_raw_url}")
    print(f"- 비공식 정규화 고유 URL 개수        : {len(unofficial_url_set)}")
    print(f"- 비공식 계정명 원시 개수            : {unofficial_raw_name}")
    print(f"- 비공식 계정명 고유 개수            : {len(unofficial_name_set)}")
    print(f"- 공식+비공식 합집합 고유 URL 수     : {len(union_url_set)}")
    print(f"- 공식+비공식 합집합 고유 계정명 수 : {len(union_name_set)}\n")

    total_before = len(df_main)
    drop_flags = mark_rows_to_drop(
        df_main,
        m_acc_url,
        m_acc_name,
        m_search,
        union_url_set,
        union_name_set,
    )
    to_delete = sum(drop_flags)
    df_after = df_main.loc[[not f for f in drop_flags]].copy()
    total_after = len(df_after)

    if not m_platform:
        df_after["플랫폼"] = DEFAULT_PLATFORM
        out_platform_col = "플랫폼"
    else:
        out_platform_col = m_platform

    rename_map = {}
    if m_post_url and m_post_url != "게시물 URL":
        rename_map[m_post_url] = "게시물 URL"
    if m_title and m_title != "게시물 제목":
        rename_map[m_title] = "게시물 제목"
    if m_search and m_search != "검색어":
        rename_map[m_search] = "검색어"
    if m_date and m_date != "게시물 등록일자":
        rename_map[m_date] = "게시물 등록일자"
    if m_acc_name and m_acc_name != "계정명":
        rename_map[m_acc_name] = "계정명"

    df_after = df_after.rename(columns=rename_map)

    if "검색어" not in df_after.columns:
        df_after["검색어"] = ""
    if "게시물 URL" not in df_after.columns:
        df_after["게시물 URL"] = ""
    if "게시물 제목" not in df_after.columns:
        df_after["게시물 제목"] = ""
    if "게시물 등록일자" not in df_after.columns:
        df_after["게시물 등록일자"] = pd.NaT
    if "계정명" not in df_after.columns:
        df_after["계정명"] = ""
    if out_platform_col not in df_after.columns:
        df_after[out_platform_col] = DEFAULT_PLATFORM
    if out_platform_col != "플랫폼":
        df_after = df_after.rename(columns={out_platform_col: "플랫폼"})

    df_out = df_after[OUTPUT_ORDER].copy()

    out_path = main_path.parent / f"{main_path.stem}_전처리완료.xlsx"
    df_out.to_excel(out_path, index=False)

    print("===== 전처리 결과 =====")
    print(f"전처리 전(총)        : {total_before}")
    print(f"삭제 개수            : {to_delete}")
    print(f"전처리 후(총)        : {total_after}")
    print(f"\n💾 저장 경로: {out_path}")


if __name__ == "__main__":
    main()
