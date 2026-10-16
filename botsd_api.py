import os
import time
import base64
import mimetypes
import logging
import requests
from typing import List, Dict, Any, Optional

import sys
import certifi

logger = logging.getLogger("BOTSD_API")

def resolve_ca_cert_path() -> Optional[str]:
    """Tìm kiếm file TLS CA cacert.pem hợp lệ cho Requests khi ứng dụng chạy từ PyInstaller hoặc môi trường độc lập."""
    candidates = []
    
    try:
        c1 = certifi.where()
        if c1 and os.path.exists(c1):
            candidates.append(c1)
    except Exception:
        pass

    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        candidates.extend([
            os.path.join(base, 'certifi', 'cacert.pem'),
            os.path.join(base, '_internal', 'certifi', 'cacert.pem'),
            os.path.join(os.path.dirname(sys.executable), 'certifi', 'cacert.pem'),
            os.path.join(os.path.dirname(sys.executable), '_internal', 'certifi', 'cacert.pem')
        ])

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None

CA_CERT_PATH = resolve_ca_cert_path()
if CA_CERT_PATH:
    os.environ['REQUESTS_CA_BUNDLE'] = CA_CERT_PATH
    os.environ['SSL_CERT_FILE'] = CA_CERT_PATH

class BOTSDAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after

class BOTSDClient:
    def __init__(self, base_url: str = "https://botsd.pro", client_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.client_token = client_token
        self.session = requests.Session()
        
        if CA_CERT_PATH and os.path.exists(CA_CERT_PATH):
            self.session.verify = CA_CERT_PATH
        else:
            self.session.verify = False
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass

        adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "BOTSD-Python-BatchClient/1.0",
            "Content-Type": "application/json"
        })

    def login(self, username: str, password: str, language: str = "vi") -> Dict[str, Any]:
        """Đăng nhập tài khoản Web để lấy clientToken."""
        url = f"{self.base_url}/api/web/account/login"
        payload = {
            "username": username,
            "password": password,
            "language": language
        }
        resp = self.session.post(url, json=payload, timeout=30)
        data = resp.json() if resp.content else {}
        if not resp.ok:
            raise BOTSDAPIError(
                message=data.get("error") or data.get("message") or f"HTTP {resp.status_code}",
                status_code=resp.status_code
            )
        
        token = data.get("clientToken")
        if token:
            self.client_token = token
        return data

    def get_session(self, token: Optional[str] = None, language: str = "vi") -> Dict[str, Any]:
        """Kiểm tra session, số dư Point và bảng giá videoPricing."""
        auth_token = token or self.client_token
        if not auth_token:
            raise BOTSDAPIError("Thiếu clientToken để kiểm tra session.")
        
        url = f"{self.base_url}/api/web/session"
        payload = {
            "clientToken": auth_token,
            "language": language
        }
        resp = self.session.post(url, json=payload, timeout=30)
        data = resp.json() if resp.content else {}
        if not resp.ok:
            raise BOTSDAPIError(
                message=data.get("error") or data.get("message") or f"HTTP {resp.status_code}",
                status_code=resp.status_code
            )
        return data

    def encode_images(self, image_paths: List[str]) -> List[Dict[str, str]]:
        """Mã hóa danh sách đường dẫn ảnh cục bộ sang định dạng Base64 thuần."""
        encoded_images = []
        if not image_paths:
            return encoded_images

        if len(image_paths) > 10:
            logger.warning("Vượt quá 10 ảnh tham chiếu. Chỉ giữ lại 10 ảnh đầu tiên.")
            image_paths = image_paths[:10]

        for i, img_path in enumerate(image_paths):
            img_path = img_path.strip()
            if not img_path:
                continue
            if not os.path.exists(img_path):
                raise FileNotFoundError(f"Không tìm thấy file ảnh tham chiếu: {img_path}")
            
            file_size_mb = os.path.getsize(img_path) / (1024 * 1024)
            if file_size_mb > 20:
                raise ValueError(f"Ảnh {img_path} có dung lượng {file_size_mb:.2f}MB, vượt quá giới hạn 20MB.")
            
            mime_type, _ = mimetypes.guess_type(img_path)
            if not mime_type:
                mime_type = "image/jpeg"
            
            with open(img_path, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode("utf-8")

            encoded_images.append({
                "name": os.path.basename(img_path),
                "type": mime_type,
                "data": b64_str,
                "clientId": f"ref_{i+1}"
            })
        return encoded_images

    def create_video(
        self,
        prompt: str,
        seconds: int = 10,
        model: str = "sd25",
        ratio: str = "9:16",
        resolution: str = "original",
        real_person_mode: bool = False,
        real_person_deep_mode: bool = False,
        image_paths: Optional[List[str]] = None,
        language: str = "vi",
        token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Tạo yêu cầu sinh video mới."""
        auth_token = token or self.client_token
        if not auth_token:
            raise BOTSDAPIError("Thiếu clientToken để tạo video.")

        images_payload = self.encode_images(image_paths) if image_paths else []

        payload = {
            "clientToken": auth_token,
            "language": language,
            "prompt": prompt,
            "seconds": int(seconds),
            "model": model,
            "ratio": ratio,
            "resolution": resolution,
            "realPersonMode": bool(real_person_mode),
            "realPersonDeepMode": bool(real_person_deep_mode),
            "promptImageMode": True,
            "images": images_payload
        }

        url = f"{self.base_url}/api/web/create"
        resp = self.session.post(url, json=payload, timeout=60)
        
        data = resp.json() if resp.content else {}
        
        if resp.status_code == 429:
            retry_after = data.get("retryAfterSeconds", 10)
            raise BOTSDAPIError(
                message=f"Rate limited (HTTP 429). Thử lại sau {retry_after}s.",
                status_code=429,
                retry_after=retry_after
            )

        if not resp.ok:
            raise BOTSDAPIError(
                message=data.get("error") or data.get("message") or f"HTTP {resp.status_code}",
                status_code=resp.status_code
            )
        return data

    def poll_job_status(self, job_id: str, token: Optional[str] = None) -> Dict[str, Any]:
        """Kiểm tra trạng thái job."""
        auth_token = token or self.client_token
        if not auth_token:
            raise BOTSDAPIError("Thiếu clientToken để kiểm tra trạng thái job.")

        url = f"{self.base_url}/api/web/job/{job_id}"
        params = {"clientToken": auth_token}
        resp = self.session.get(url, params=params, timeout=30)
        data = resp.json() if resp.content else {}
        
        if resp.status_code == 429:
            retry_after = data.get("retryAfterSeconds", 10)
            raise BOTSDAPIError(
                message=f"Rate limited (HTTP 429). Thử lại sau {retry_after}s.",
                status_code=429,
                retry_after=retry_after
            )

        if not resp.ok:
            raise BOTSDAPIError(
                message=data.get("error") or data.get("message") or f"HTTP {resp.status_code}",
                status_code=resp.status_code
            )
        return data

    def download_video(self, job_id: str, save_path: str, token: Optional[str] = None) -> str:
        """Tải file video đã sẵn sàng về đĩa cứng."""
        auth_token = token or self.client_token
        if not auth_token:
            raise BOTSDAPIError("Thiếu clientToken để tải video.")

        url = f"{self.base_url}/api/web/video/{job_id}"
        params = {"clientToken": auth_token, "download": "1"}

        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

        resp = self.session.get(url, params=params, stream=True, allow_redirects=True, timeout=120)
        if not resp.ok:
            try:
                data = resp.json()
                msg = data.get("error") or data.get("message") or f"HTTP {resp.status_code}"
            except Exception:
                msg = f"HTTP {resp.status_code}"
            raise BOTSDAPIError(message=f"Lỗi khi tải video: {msg}", status_code=resp.status_code)

        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        return save_path
