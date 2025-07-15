import os
import re
import pandas as pd
from datetime import datetime

def filter_untrusted_posts(all_data, untrusted_file, trusted_file):
    # 비신탁사 및 매체사 데이터 로드
    df_untrusted = pd.read_excel(untrusted_file)
    df_trusted = pd.read_excel(trusted_file)

    # 비신탁사 저작권 문구 및 도메인 리스트 생성
    untrusted_copyrights = df_untrusted["저작권 문구"].dropna().tolist()
    untrusted_domains = df_untrusted["도메인"].dropna().tolist()

    # 매체사 도메인 리스트 생성
    trusted_domains = df_trusted["도메인"].dropna().tolist()

    # 필터링 함수 정의
    def should_remove(post_content):
        post_content = str(post_content)
        contains_untrusted_copyright = any(c in post_content for c in untrusted_copyrights)
        contains_untrusted_domain = any(d in post_content for d in untrusted_domains)
        contains_trusted_domain = any(t in post_content for t in trusted_domains)

        return (contains_untrusted_copyright or contains_untrusted_domain) and not contains_trusted_domain

    # 결측값 방지
    content_series = all_data["게시물 내용"].fillna("")
    mask = content_series.apply(should_remove)

    # 유지할 데이터
    df_filtered = all_data[~mask]

    if df_filtered.empty:
        df_filtered = all_data.iloc[0:0]

    return df_filtered

def filter_da(df_filtered):
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

    mask = df_filtered.apply(lambda row: should_remove(row["게시물 제목"], row["게시물 내용"]), axis=1)

    df_final = df_filtered[~mask]
    return df_final




def process_file(
    search_excel_path,
    input_csv_template,
    output_excel_path,
    target_year,
    target_month
):
    result_dir = '결과'

    # 결과 폴더 생성
    os.makedirs(result_dir, exist_ok=True)

    # 검색어 목록 불러오기
    pd_search = pd.read_excel(search_excel_path, sheet_name='검색어 목록')
    searchs = pd_search['검색어명']


    # 게시물 등록일자 전처리
    try:
        df = pd.read_csv(input_csv_template, encoding="utf-8")
    except UnicodeDecodeError:
        print("⚠️ UTF-8 디코딩 실패, cp949로 재시도합니다.")
        df = pd.read_csv(input_csv_template, encoding="cp949")


    df['게시물 URL'] = df['게시물 URL'].apply(lambda x: x.split('&keyword=')[0])
    df['게시물 등록일자'] = pd.to_datetime(df['게시물 등록일자'], errors='coerce')
    df["게시물 제목"] = df["게시물 제목"].fillna("").astype(str)
    df["게시물 내용"] = df["게시물 내용"].fillna("").astype(str)

    df1 = df[
        (df.apply(
            lambda x: x['검색어'].lower() in str(x['게시물 제목']).lower() or x['검색어'].lower() in str(x['게시물 내용']).lower(),
            axis=1)) &
        (~df['게시물 내용'].fillna('').str.contains('신춘문예', case=False)) &
        (~df['게시물 제목'].fillna('').str.contains('신춘문예', case=False)) &
        (~df['계정명'].fillna('').str.contains('뽐뿌뉴스', case=False))
        ]
    # 등록일자 전처리
    df2 = df1 [
        (df1['게시물 등록일자'].dt.year == target_year) &
        (df1['게시물 등록일자'].dt.month == target_month)
    ]
    #URL 정리
    df3 = df2.drop_duplicates(subset=['게시물 URL'], keep='first')
    #비신탁사 전처리
    df_filtered = filter_untrusted_posts(
        df3,
        untrusted_file="../비신탁사_저작권문구+도메인주소.xlsx",
        trusted_file="../(언진) 전처리용 도메인 주소.xlsx"
    )
    filtered_df = filter_da(df_filtered)

    # 전처리 완료 파일을 Excel로 저장
    filtered_df.to_excel(output_excel_path, index=False)
    print(f"전처리된 데이터 저장 완료 (Excel): {output_excel_path}")
    print(f"전처리 이전 : {len(df)}개\n"
          f"전처리 이후 : {len(filtered_df)}개\n"
          f"삭제 개수 : {len(df)-len(filtered_df)}개")

    return filtered_df

