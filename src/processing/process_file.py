import os
import pandas as pd
from datetime import datetime

def process_file(
    search_excel_path,
    input_csv_template,
    output_excel_path,
    target_year,
    target_month,
    site
):

    # 오늘 날짜 설정
    today = datetime.now().strftime("%y%m%d")
    result_dir = '결과'
    csv_dir = f'csv/{today}'

    # 결과 폴더 생성
    os.makedirs(result_dir, exist_ok=True)

    # 검색어 목록 불러오기
    pd_search = pd.read_excel(search_excel_path, sheet_name='검색어 목록')
    searchs = pd_search['검색어명']

    # 개별 검색어 CSV 파일 읽기 함수
    def result_csv_data(search):
        file_path = f'{csv_dir}/뽐뿌_{search}.csv'
        if not os.path.isfile(file_path):
            print(f"파일 '{file_path}'이 존재하지 않습니다. 스킵합니다.")
            return None
        return pd.read_csv(file_path, encoding='utf-8')

    # 검색어별 데이터프레임 병합
    all_dataframes = [result_csv_data(search) for search in searchs]
    all_data = pd.concat([df for df in all_dataframes if df is not None], ignore_index=True)

    # raw data를 CSV로 저장
    raw_csv_path = os.path.join(result_dir, f'뽐뿌_raw data_{today}.csv')
    all_data.to_csv(raw_csv_path, encoding='utf-8', index=False)
    print(f"Raw data 저장 완료: {raw_csv_path}")

    # 게시물 등록일자 전처리
    df = all_data.copy()
    df['게시물 등록일자'] = pd.to_datetime(df['게시물 등록일자'], errors='coerce')

    # 필터링
    filtered_df = df[
        (df['게시물 등록일자'].dt.year == target_year) &
        (df['게시물 등록일자'].dt.month == target_month)
    ]

    # 전처리 완료 파일을 Excel로 저장
    filtered_df.to_excel(output_excel_path, index=False)
    print(f"전처리된 데이터 저장 완료 (Excel): {output_excel_path}")

    return filtered_df
