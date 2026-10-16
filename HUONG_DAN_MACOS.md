# BOTSD Studio cho macOS (Apple Silicon M1 – M5)

Người dùng Mac chỉ nhận **1 file `.dmg`**, mở file đó rồi kéo app vào Applications là dùng được. Python, thư viện và mọi thứ khác đều đã nằm sẵn trong app, người dùng không cần mở Terminal.

---

## Phần A: Người dùng Mac cài đặt (không cần Terminal)

1. Mở file `BOTSD_Studio_x.y.z_macOS_AppleSilicon.dmg`.
2. Kéo **BOTSD Studio** thả vào thư mục **Applications**.
3. Mở app từ Launchpad.
   - Nếu macOS báo không mở được: vào **System Settings → Privacy & Security**, kéo xuống dưới và bấm **Open Anyway**. Chỉ cần làm 1 lần.
   - Nếu app đã được ký và notarize (xem Phần C) thì sẽ không gặp bước này.

Bên trong DMG có sẵn file *Hướng dẫn cài đặt.txt* ghi lại các bước trên.

---

## Phần B: Tạo file `.dmg` (người phát hành làm, không cần có Mac)

Bản `.app` cho Mac bắt buộc phải build trên macOS. GitHub cung cấp miễn phí máy Mac chip M để build tự động.

### Lần đầu thiết lập
1. Tạo một repo **Private** trên GitHub và đẩy thư mục dự án này lên.
   - `.gitignore` đã chặn `config.json`, `user_usage.json`, `build/`, `dist/`, nên mật khẩu không bị đẩy lên.
2. Trong repo, vào **Settings → Secrets and variables → Actions → New repository secret** và tạo:
   - **Tên:** `BOTSD_CONFIG_JSON`
   - **Giá trị:** toàn bộ nội dung `config.json` muốn cài sẵn cho người dùng Mac (master token, link Google Sheet, mật khẩu admin…). Nên để `output_dir` là `"outputs"` và `ref_char_dir` là `""`.
   - Nếu không tạo secret này, app sẽ dùng cấu hình mặc định và admin phải nhập trong **⚙️ Cấu Hình Admin**.

### Mỗi lần ra bản mới
- **Cách nhanh:** vào tab **Actions**, chọn **Build macOS app**, bấm **Run workflow**. Khoảng 5–10 phút sau, tải file `.dmg` ở mục **Artifacts**.
- **Ra bản chính thức:** tạo tag, ví dụ `v1.2.0`, rồi đẩy lên:
  ```bash
  git tag v1.2.0
  ```
  ```bash
  git push origin v1.2.0
  ```
  GitHub sẽ tự tạo trang **Releases** kèm file `BOTSD_Studio_1.2.0_macOS_AppleSilicon.dmg` để gửi link cho người dùng.

### Nếu có máy Mac sẵn
Có thể build ngay trên máy Mac, không cần GitHub. Cài Python 3.12 từ python.org, rồi mở Terminal tại thư mục dự án và chạy:
```bash
bash build_macos.sh
```
File DMG sẽ nằm trong `dist/macos/`.

---

## Phần C (tùy chọn): Mở app không bị macOS cảnh báo

Để người dùng double-click là chạy luôn, không phải bấm *Open Anyway*, cần ký app bằng tài khoản **Apple Developer** (99 USD/năm). Sau khi có tài khoản, thêm các secret sau vào GitHub:

| Secret | Nội dung |
|---|---|
| `MACOS_CERT_P12_BASE64` | Chứng chỉ *Developer ID Application* xuất ra file `.p12`, rồi mã hóa base64 |
| `MACOS_CERT_PASSWORD` | Mật khẩu của file `.p12` |
| `APPLE_SIGN_IDENTITY` | Ví dụ `Developer ID Application: Ten Cua Anh (AB12CD34EF)` |
| `APPLE_ID` | Email Apple ID |
| `APPLE_TEAM_ID` | Team ID gồm 10 ký tự |
| `APPLE_APP_PASSWORD` | App-specific password tạo tại appleid.apple.com |

Khi có đủ các secret này, workflow sẽ tự ký, notarize và đóng dấu (staple) file DMG.

---

## Dữ liệu trên máy Mac

| Nội dung | Vị trí |
|---|---|
| Cấu hình `config.json`, `user_usage.json` | `~/Library/Application Support/BOTSD Studio/` |
| Video xuất ra (mặc định) | `~/Movies/BOTSD Studio/` |

Đường dẫn kiểu Windows (`D:/...`) trong config sẽ tự được bỏ qua trên Mac. Đường dẫn ảnh trong cột `image_paths` của file Excel phải là đường dẫn Mac, ví dụ `/Users/ten/Pictures/a.png`.

## Các file liên quan
- `app_paths.py`: xử lý đường dẫn chạy được trên cả Windows và macOS.
- `BOTSD_Studio_macOS.spec`: cấu hình đóng gói `.app` arm64, có icon, hỗ trợ Retina và Dark Mode.
- `build_macos.sh`: build app, ký, tạo DMG, và notarize nếu có cấu hình.
- `.github/workflows/build-macos.yml`: build tự động trên GitHub.
- `assets/`: icon app, entitlements, hướng dẫn đặt trong DMG.
- `run_macos.command`: chạy thẳng từ mã nguồn, dành cho dev.

Bản Windows vẫn build như cũ bằng `BOTSD_Studio.spec`.
