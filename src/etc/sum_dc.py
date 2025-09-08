import os
import glob
import pandas as pd

# 1) 병합할 폴더 지정
BASE_DIR = r"D:\jupyter\community_site_crawling-main\site crawling\csv\22.디시인사이드\250908"
OUTPUT = os.path.join(os.path.dirname(BASE_DIR), "디시인사이드_raw data_250908.csv")  # 같은 상위 폴더에 저장


# 2) 인코딩 안전하게 읽기 위한 헬퍼
def read_csv_kr(path, nrows=None):
    # 순서대로 시도: UTF-8 with BOM, CP949, EUC-KR
    encodings = ["utf-8-sig", "cp949", "euc-kr"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc, nrows=nrows)
        except Exception as e:
            last_err = e
    raise last_err


# 3) 폴더 내 CSV 수집 & 정렬
csv_files = sorted(glob.glob(os.path.join(BASE_DIR, "*.csv")))
if not csv_files:
    raise FileNotFoundError(f"CSV 파일을 찾지 못했습니다: {BASE_DIR}")

print(f"총 파일 수: {len(csv_files)}")
print("예시 파일 3개:", csv_files[:3])

# 4) 첫 파일로 헤더만 확보 후 저장
first = csv_files[0]
df_head = read_csv_kr(first, nrows=0)  # 헤더만
# 첫 파일 전체를 한번 읽어 첫 헤더 기준으로 저장
df_first_full = read_csv_kr(first)
df_first_full.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
print(f"[1/{len(csv_files)}] 헤더 포함 저장: {os.path.basename(first)} -> {OUTPUT}")

# 5) 나머지 파일은 헤더 없이 append
for i, fp in enumerate(csv_files[1:], start=2):
    try:
        # 열 이름이 동일하다는 전제(질문 조건)로 헤더 자동 인식 후,
        # 저장 시에는 header=False로 이어 붙임
        df = read_csv_kr(fp)

        # 열 검증(선택): 첫 파일과 다르면 보완
        if list(df.columns) != list(df_head.columns):
            # 열이 다르면 첫 헤더 기준으로 정렬/누락열 채우기
            df = df.reindex(columns=df_head.columns)

        # append (mode='a', header=False)
        df.to_csv(OUTPUT, index=False, header=False, mode="a", encoding="utf-8-sig")
        print(f"[{i}/{len(csv_files)}] 추가: {os.path.basename(fp)}")
    except Exception as e:
        print(f"[경고] 추가 실패: {os.path.basename(fp)} -> {e}")

print(f"완료! 병합 파일: {OUTPUT}")
