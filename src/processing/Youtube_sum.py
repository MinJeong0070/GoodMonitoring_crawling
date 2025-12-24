import re
from pathlib import Path
from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter

CANDIDATE_TITLE_HEADERS = ["게시물 제목", "게시글제목", "제목"]
URL_HEADER = "게시물 URL"

def parse_path_list(text: str):
    # ;, 줄바꿈, , 공백 구분 허용
    parts = re.split(r'[;\n,]+', text.strip())
    paths = []
    for p in parts:
        p = p.strip().strip('"').strip("'")
        if p:
            paths.append(Path(p))
    return paths

def find_header_column(ws, header_name_candidates):
    headers = {(c.value or "").strip(): c.column for c in ws[1]}
    for name in header_name_candidates:
        if name in headers:
            return headers[name], name
    # 느슨한 검색
    norm = lambda s: re.sub(r"\s+", "", str(s)).lower()
    normalized = {norm(k): v for k, v in headers.items()}
    for name in header_name_candidates:
        n = norm(name)
        if n in normalized:
            return normalized[n], name
    return None, None

def ensure_url_column(ws, after_col_idx, url_header=URL_HEADER):
    # 이미 있으면 그대로 사용
    for c in ws[1]:
        if (c.value or "").strip() == url_header:
            return c.column
    # 제목 열 바로 오른쪽에 신규 열 삽입
    insert_at = after_col_idx + 1
    ws.insert_cols(insert_at, amount=1)
    ws.cell(row=1, column=insert_at, value=url_header)
    return insert_at

def extract_hyperlink_target(cell):
    # 1) 정식 하이퍼링크
    if cell.hyperlink and cell.hyperlink.target:
        return cell.hyperlink.target
    # 2) 수식/텍스트에서 URL 패턴
    v = cell.value
    if isinstance(v, str):
        m = re.search(r'HYPERLINK\s*\(\s*"([^"]+)"\s*,', v, flags=re.IGNORECASE)
        if m:
            return m.group(1)
        m2 = re.search(r'(https?://\S+)', v)
        if m2:
            return m2.group(1)
    return None

def unlink_cell(cell):
    try:
        cell.hyperlink = None
    except Exception:
        pass
    # 파란색/밑줄 스타일 제거 시도
    if cell.font and (cell.font.u or (cell.font.color and getattr(cell.font.color, "rgb", None))):
        cell.font = cell.font.copy(u=None, color=None)

def process_input_sheet_in_place(ws):
    """제목 하이퍼링크 → URL 추출, 제목 링크 해제, URL 열 생성"""
    col_idx, _ = find_header_column(ws, CANDIDATE_TITLE_HEADERS)
    if not col_idx:
        raise ValueError("제목 열을 찾을 수 없습니다. (예: '게시물 제목', '게시글제목', '제목')")
    url_col_idx = ensure_url_column(ws, col_idx, URL_HEADER)

    for r in range(2, ws.max_row + 1):
        title_cell = ws.cell(row=r, column=col_idx)
        url_cell   = ws.cell(row=r, column=url_col_idx)

        url = extract_hyperlink_target(title_cell)
        if not url and isinstance(title_cell.value, str):
            m = re.search(r'(https?://\S+)', title_cell.value)
            if m:
                url = m.group(1)
        if url:
            url_cell.value = url

        unlink_cell(title_cell)
    return col_idx, url_col_idx

def get_last_data_row(ws):
    """내용이 있는 마지막 행(헤더 제외) 찾기. 없으면 1 반환(즉, 다음 데이터는 2행부터)."""
    last = ws.max_row
    for r in range(last, 1, -1):
        if any(ws.cell(row=r, column=c).value is not None for c in range(1, ws.max_column + 1)):
            return r
    return 1

def ensure_output_workbook(path: Path):
    if path.exists():
        wb_out = load_workbook(path)
        return wb_out
    wb_out = Workbook()
    default = wb_out.active
    wb_out.remove(default)
    return wb_out

def ensure_output_sheet(wb_out, ws_in):
    """출력 통합문서에 동일 시트명이 있으면 반환. 없으면 헤더를 복사해 새 시트 생성."""
    name = ws_in.title
    if name in wb_out.sheetnames:
        return wb_out[name], False
    ws_out = wb_out.create_sheet(title=name)
    # 헤더 복사
    for c in range(1, ws_in.max_column + 1):
        ws_out.cell(row=1, column=c, value=ws_in.cell(row=1, column=c).value)
    return ws_out, True

def append_data_rows(ws_out, ws_in, skip_header=True):
    """
    skip_header=True이면 입력의 2행부터 복사(헤더 제외),
    False이면 1행부터 복사(헤더 포함).
    """
    start_row_out = get_last_data_row(ws_out) + 1
    src_start = 2 if skip_header else 1
    for r in range(src_start, ws_in.max_row + 1):
        for c in range(1, ws_in.max_column + 1):
            ws_out.cell(row=start_row_out, column=c, value=ws_in.cell(row=r, column=c).value)
        start_row_out += 1

def main():
    print("📂 여러 입력 엑셀을 합쳐 하이퍼링크 URL 추출 후 하나의 출력 파일로 저장")
    print("   - 여러 경로는 세미콜론(;) 또는 줄바꿈으로 구분해 입력하세요.")
    inputs_text = input("👉 입력 파일 경로들: ").strip()
    output_path = Path(input("💾 출력 파일 경로(.xlsx): ").strip('"').strip())

    in_paths = parse_path_list(inputs_text)
    if not in_paths:
        print("❌ 입력 파일이 없습니다.")
        return
    for p in in_paths:
        if not p.exists():
            print(f"❌ 파일을 찾을 수 없습니다: {p}")
            return

    wb_out = ensure_output_workbook(output_path)

    # 시트별로 '첫 파일 여부' 추적 → 첫 파일만 헤더 포함 복사
    first_source_seen_for_sheet = set(s for s in wb_out.sheetnames if get_last_data_row(wb_out[s]) > 1)

    for file_idx, in_path in enumerate(in_paths):
        wb_in = load_workbook(in_path, data_only=False)
        print(f"\n[처리] 입력 파일: {in_path}")
        for s in wb_in.sheetnames:
            ws_in = wb_in[s]
            title_col, url_col = process_input_sheet_in_place(ws_in)
            print(f"  - 시트 '{s}': 제목열 {get_column_letter(title_col)} → URL열 {get_column_letter(url_col)}")

            ws_out, created = ensure_output_sheet(wb_out, ws_in)
            sheet_key = ws_in.title

            # 출력 시트가 이미 데이터(헤더 제외)를 갖고 있으면, 무조건 헤더 제외 이어붙임
            already_has_data = get_last_data_row(ws_out) > 1
            if already_has_data:
                append_data_rows(ws_out, ws_in, skip_header=True)
                action = "기존 데이터 아래로 추가"
            else:
                # 이 시트를 처음 채우는 경우: 첫 번째 입력 파일만 헤더 포함, 이후는 헤더 제외
                is_first_for_this_sheet = sheet_key not in first_source_seen_for_sheet
                if is_first_for_this_sheet:
                    append_data_rows(ws_out, ws_in, skip_header=False)  # 헤더 포함
                    first_source_seen_for_sheet.add(sheet_key)
                    action = "헤더 포함 복사(해당 시트 첫 입력)"
                else:
                    append_data_rows(ws_out, ws_in, skip_header=True)   # 헤더 제외
                    action = "헤더 제외 추가(해당 시트 2번째 이후)"

            print(f"    → 출력 '{s}': {action} (누적 행수: {ws_out.max_row - 1}행)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb_out.save(output_path)
    print(f"\n✅ 저장 완료 → {output_path}")

if __name__ == "__main__":
    main()
