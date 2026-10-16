"""Đường dẫn & tiện ích đa nền tảng (Windows / macOS) cho BOTSD Studio."""
import os
import re
import sys
import shutil

APP_NAME = "BOTSD Studio"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"
IS_FROZEN = getattr(sys, "frozen", False)

# Font monospace cho ô Log (Consolas không có trên macOS)
MONO_FONT = "Menlo" if IS_MAC else "Consolas"


def _resource_dir() -> str:
    """Thư mục chứa file đóng gói kèm app (config mẫu, template)."""
    if IS_FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _data_dir() -> str:
    """Thư mục ghi được để lưu config.json, user_usage.json."""
    if IS_FROZEN and IS_MAC:
        # Bên trong .app là chỉ đọc (và ghi vào sẽ làm hỏng chữ ký) -> dùng Application Support
        return os.path.join(os.path.expanduser("~/Library/Application Support"), APP_NAME)
    if IS_FROZEN:
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


RESOURCE_DIR = _resource_dir()
DATA_DIR = _data_dir()
os.makedirs(DATA_DIR, exist_ok=True)


def resource_path(name: str) -> str:
    return os.path.join(RESOURCE_DIR, name)


def data_path(name: str, seed: bool = True) -> str:
    """Đường dẫn file dữ liệu người dùng; lần đầu chạy sẽ copy bản mẫu đóng gói kèm app (nếu có)."""
    path = os.path.join(DATA_DIR, name)
    if seed and not os.path.exists(path):
        src = resource_path(name)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(path):
            try:
                shutil.copy2(src, path)
            except OSError:
                pass
    return path


def default_output_dir() -> str:
    if IS_MAC:
        return os.path.join(os.path.expanduser("~/Movies"), APP_NAME)
    return os.path.join(DATA_DIR, "outputs")


_WINDOWS_ABS_PATH = re.compile(r"^[A-Za-z]:[\\/]|^\\\\")


def is_foreign_path(path: str) -> bool:
    """True nếu là đường dẫn Windows (D:/..., \\\\server\\...) nhưng đang chạy trên macOS/Linux."""
    return bool(path) and not IS_WINDOWS and bool(_WINDOWS_ABS_PATH.match(path))


def resolve_output_dir(path: str) -> str:
    """Chuẩn hóa thư mục output: bỏ đường dẫn Windows khi chạy trên Mac, đổi đường dẫn tương đối thành tuyệt đối."""
    path = (path or "").strip()
    if not path or is_foreign_path(path) or path == "outputs":
        return default_output_dir()
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        return os.path.join(DATA_DIR, path)
    return path


def resolve_optional_dir(path: str) -> str:
    """Như resolve_output_dir nhưng trả về rỗng nếu không dùng được (vd: thư mục ảnh nhân vật)."""
    path = (path or "").strip()
    if not path or is_foreign_path(path):
        return ""
    return os.path.expanduser(path)
