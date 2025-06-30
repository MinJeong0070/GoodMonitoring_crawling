import pandas as pd
import os
from datetime import datetime

def csv_to_excel(csv_path):
    try:
        # CSV 파일 읽기
        data = pd.read_csv(csv_path)

        # Excel 파일 경로 설정 (같은 이름으로 변환)
        excel_path = os.path.splitext(csv_path)[0] + ".xlsx"

        # Excel 파일로 저장
        with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
            data.to_excel(writer, index=False)
        print(f"변환 완료: {excel_path}")
    except Exception as e:
        print(f"오류 발생: {e}")


if __name__ == "__main__":
    today = datetime.now().strftime("%y%m%d")
    csv_path = f"../../csv/25.케이비디오/{today}/케이비디오.csv"
    csv_to_excel(csv_path)