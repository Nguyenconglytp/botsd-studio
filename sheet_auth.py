import os
import re
import json
import logging
import pandas as pd
import requests
from typing import Dict, Any, Tuple, Optional

from app_paths import data_path

logger = logging.getLogger("SheetAuth")

# Đường dẫn tuyệt đối: trên macOS app mở từ Finder có thư mục làm việc là "/" (không ghi được)
USAGE_FILE = data_path("user_usage.json", seed=False)

def get_csv_export_url(sheet_url: str) -> str:
    """Chuyển đổi URL xem Google Sheet chuẩn sang URL xuất file CSV."""
    sheet_url = sheet_url.strip()
    if "gviz/tq" in sheet_url or "export?format=csv" in sheet_url:
        return sheet_url

    # Regex lấy Sheet ID
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
    if match:
        sheet_id = match.group(1)
        # Lấy gid nếu có (từ #gid=X, ?gid=X, &gid=X), nếu không mặc định &gid=0
        gid_match = re.search(r'[#&?]gid=([0-9]+)', sheet_url)
        gid_val = gid_match.group(1) if gid_match else "0"
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid_val}"
    
    return sheet_url

def load_usage_data() -> Dict[str, int]:
    """Đọc lịch sử tiêu thụ Quota của từng người dùng đã lưu cục bộ."""
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Lỗi đọc file {USAGE_FILE}: {e}")
    return {}

def save_usage_data(usage: Dict[str, int]):
    """Lưu lịch sử tiêu thụ Quota."""
    try:
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(usage, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Lỗi ghi file {USAGE_FILE}: {e}")

def normalize_col_name(c: Any) -> str:
    """Loại bỏ BOM, khoảng trắng, dấu tiếng Việt và ký tự đặc biệt để so sánh tên cột."""
    if c is None or pd.isna(c):
        return ""
    s = str(c).strip().strip('\ufeff\u200b\ufffe').lower()
    # Bỏ dấu tiếng Việt
    s = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', s)
    s = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', s)
    s = re.sub(r'[ìíịỉĩ]', 'i', s)
    s = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', s)
    s = re.sub(r'[ùúụủũưừứựửữ]', 'u', s)
    s = re.sub(r'[ỳýỵỷỹ]', 'y', s)
    s = re.sub(r'[đ]', 'd', s)
    return re.sub(r'[^a-z0-9]', '', s)

COLUMN_ALIASES = {
    'username': ['username', 'user', 'account', 'acc', 'taikhoan', 'tendangnhap', 'tenuser', 'nguoidung', 'subusername'],
    'password': ['password', 'pass', 'pwd', 'matkhau', 'mk', 'passwordhash'],
    'quota_points': ['quotapoints', 'quota', 'quotapoint', 'point', 'points', 'hanmuc', 'sopoint', 'diem'],
    'status': ['status', 'trangthai', 'kichhoat', 'active', 'tinhtrang'],
    'role': ['role', 'quyen', 'chucvu', 'vaitro']
}

def clean_cell_str(val: Any) -> str:
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if s.endswith('.0'):
        s = s[:-2]
        s = s.strip()
    return s

def fetch_users_from_sheet(sheet_url: str) -> pd.DataFrame:
    """Tải dữ liệu danh sách người dùng từ Google Sheet với khả năng xử lý BOM & nhận diện tên cột linh hoạt."""
    csv_url = get_csv_export_url(sheet_url)
    resp = requests.get(csv_url, timeout=15)
    if not resp.ok:
        raise ValueError(f"Không thể tải Google Sheet (HTTP {resp.status_code}). Đảm bảo sheet đã mở quyền 'Anyone with link can view'.")
    
    from io import StringIO
    content = resp.content.decode('utf-8-sig', errors='ignore')
    df = pd.read_csv(StringIO(content), dtype=str)

    if df.empty:
        raise ValueError("Google Sheet trống không có dữ liệu.")

    # Tìm dòng chứa header nếu dòng đầu tiên là tiêu đề trống hoặc tiêu đề chung
    target_row_idx = None
    for row_idx in range(min(5, len(df) + 1)):
        cols_to_check = list(df.columns) if row_idx == 0 else [str(val) for val in df.iloc[row_idx - 1].values]
        norm_cols = [normalize_col_name(c) for c in cols_to_check]
        
        has_user = any(n in COLUMN_ALIASES['username'] for n in norm_cols)
        has_pass = any(n in COLUMN_ALIASES['password'] for n in norm_cols)
        if has_user and has_pass:
            target_row_idx = row_idx
            break

    if target_row_idx is not None and target_row_idx > 0:
        header_vals = [str(val) for val in df.iloc[target_row_idx - 1].values]
        df = df.iloc[target_row_idx:].copy()
        df.columns = header_vals

    # Ánh ánh tên cột về chuẩn (username, password, quota_points, status, role)
    col_mapping = {}
    detected_cols = [str(c).strip() for c in df.columns]

    for orig_col in df.columns:
        norm = normalize_col_name(orig_col)
        for std_name, aliases in COLUMN_ALIASES.items():
            if norm in aliases and std_name not in col_mapping.values():
                col_mapping[orig_col] = std_name
                break

    df = df.rename(columns=col_mapping)

    required_cols = ['username', 'password']
    for req in required_cols:
        if req not in df.columns:
            cols_str = ", ".join([f"'{c}'" for c in detected_cols if c and not c.startswith('Unnamed')])
            raise ValueError(f"Google Sheet thiếu cột bắt buộc: '{req}'. Các cột tìm thấy trong Sheet: [{cols_str}]. Hãy kiểm tra lại dòng tiêu đề (header) của Sheet.")

    if 'quota_points' not in df.columns:
        df['quota_points'] = 100
    if 'status' not in df.columns:
        df['status'] = 'active'

    return df

def authenticate_sub_user(username: str, password: str, sheet_url: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Xác thực người dùng Web con theo Google Sheet."""
    if not sheet_url:
        return False, "Chưa cấu hình URL Google Sheet trong ứng dụng.", {}

    try:
        df = fetch_users_from_sheet(sheet_url)
    except Exception as e:
        return False, f"Lỗi đọc dữ liệu từ Google Sheet: {e}", {}

    username_clean = clean_cell_str(username)
    password_clean = clean_cell_str(password)

    # Tìm user theo username
    matched_idx = None
    for idx, row in df.iterrows():
        if clean_cell_str(row.get('username')) == username_clean:
            matched_idx = idx
            break

    if matched_idx is None:
        return False, f"Tài khoản '{username_clean}' không tồn tại trên hệ thống.", {}

    user_row = df.iloc[matched_idx]
    sheet_pass = clean_cell_str(user_row.get('password'))

    if sheet_pass != password_clean:
        return False, "Mật khẩu không chính xác.", {}


    status = str(user_row.get('status', 'active')).strip().lower()
    if status not in ['active', '1', 'true', 'yes', 'enabled']:
        return False, "Tài khoản của bạn đã bị khóa hoặc chưa kích hoạt.", {}

    try:
        quota_assigned = int(user_row.get('quota_points', 0))
    except ValueError:
        quota_assigned = 0

    usage_data = load_usage_data()
    used_points = usage_data.get(username_clean, 0)
    remaining_points = max(0, quota_assigned - used_points)

    role = str(user_row.get('role', '')).strip().lower()
    is_admin = (role == 'admin') or (username_clean.lower() in ['admin', 'root', 'master'])

    user_info = {
        "username": username_clean,
        "is_admin": is_admin,
        "quota_assigned": quota_assigned,
        "used_points": used_points,
        "remaining_points": remaining_points,
        "status": status,
        "note": str(user_row.get('note', ''))
    }


    return True, "Đăng nhập thành công!", user_info

def record_user_consumption(username: str, cost_points: int):
    """Ghi nhận số Point người dùng đã tiêu thụ."""
    if cost_points <= 0:
        return
    username_clean = str(username).strip()
    usage_data = load_usage_data()
    usage_data[username_clean] = usage_data.get(username_clean, 0) + int(cost_points)
    save_usage_data(usage_data)
