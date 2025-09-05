import os
import glob
from datetime import datetime
import pandas as pd

"""
여러 개의 엑셀(.xlsx) 파일을 하나로 통합하는 스크립트
- 첫 파일의 헤더(첫 행)만 유지
- 나머지 파일들은 헤더 제외하고 데이터만 이어붙임
- 임시 잠금 파일(~$...)은 자동 제외
- 파일마다 열 구성이 달라도 누락되지 않도록 열의 '합집합'으로 정렬
- 모든 값을 문자열로 읽어 포맷(앞자리 0 등) 손실 방지
"""

def combine_excels(
    base_dir: str,
    pattern: str = "*.xlsx",
    output_prefix: str = "8월_티스토리 통합",
    add_source_column: bool = False,  # True로 하면 원본 파일명 열 추가
) -> str:
    """
    base_dir 내 pattern에 매칭되는 모든 .xlsx 파일을 통합하여 저장하고, 저장 경로를 반환.
    """
    # 1) 대상 파일 수집 (임시파일 제외)
    all_files = sorted(
        p for p in glob.glob(os.path.join(base_dir, pattern))
        if not os.path.basename(p).startswith("~$")
    )

    if not all_files:
        raise FileNotFoundError(f"'{base_dir}'에 엑셀 파일이 없습니다.")

    combined_df = None
    canonical_cols = None
    processed = []

    for idx, fpath in enumerate(all_files):
        try:
            # 모든 값을 문자열로 읽기
            df = pd.read_excel(fpath, dtype=str)  # header=0 기본값
        except Exception as e:
            print(f"[경고] 파일을 읽는 중 오류가 발생했습니다: {os.path.basename(fpath)} -> {e}")
            continue

        # 필요 시 원본 파일명 열 추가
        if add_source_column:
            df.insert(0, "source_file", os.path.basename(fpath))

        if combined_df is None:
            # 첫 성공 파일의 컬럼을 기준(canonical)으로 삼음
            canonical_cols = list(df.columns)
            combined_df = df.copy()
            processed.append(os.path.basename(fpath))
        else:
            # 열 합집합으로 확장(누락 방지)
            if set(df.columns) != set(canonical_cols):
                union_cols = list(dict.fromkeys(canonical_cols + [c for c in df.columns if c not in canonical_cols]))
                combined_df = combined_df.reindex(columns=union_cols)
                df = df.reindex(columns=union_cols)
                canonical_cols = union_cols

            # 헤더는 컬럼으로만 쓰이므로 concat으로 행만 이어붙임
            combined_df = pd.concat([combined_df, df], ignore_index=True)
            processed.append(os.path.basename(fpath))

    if combined_df is None or combined_df.empty:
        raise RuntimeError("유효한 데이터가 없어 통합 결과가 비어 있습니다.")

    # 3) 결과 저장
    ts = datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(base_dir, f"{output_prefix}_{ts}.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        combined_df.to_excel(writer, index=False, sheet_name="통합")

    print("처리된 파일 수:", len(processed))
    for name in processed:
        print(" -", name)
    print("저장 경로:", out_path)
    return out_path


if __name__ == "__main__":
    # 예시: /mnt/data 폴더에 있는 모든 .xlsx 통합
    BASE_DIR = r"C:\Users\USER\Documents\카카오톡 받은 파일\티스토리 8월"  # 필요 시 변경
    # 원본 파일명을 보관하려면 add_source_column=True 로 바꾸세요.
    combine_excels(base_dir=BASE_DIR, add_source_column=False)
