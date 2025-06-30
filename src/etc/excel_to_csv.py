import pandas as pd
import os
from datetime import datetime

def excel_to_csv(excel_path, csv_path=None):
    if not os.path.exists(excel_path):
        print(f"❌ 엑셀 파일이 존재하지 않습니다: {excel_path}")
        return

    if not csv_path:
        csv_path = os.path.splitext(excel_path)[0] + '.csv'

    try:
        df = pd.read_excel(excel_path)
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')  # 또는 encoding='CP949'
        print(f"✅ CSV 파일로 저장 완료: {csv_path}")
    except Exception as e:
        print(f"⚠️ 변환 실패: {e}")

if __name__ == "__main__":
    today = datetime.now().strftime("%y%m%d")
    csv_path = f"디시인사이드_원문기사_5월_250617.xlsx"
    excel_to_csv(csv_path)