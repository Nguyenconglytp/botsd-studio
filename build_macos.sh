#!/usr/bin/env bash
# Đóng gói BOTSD Studio thành "BOTSD Studio.app" + file cài đặt .dmg cho macOS Apple Silicon (M1–M5).
# Chạy trên máy Mac:   bash build_macos.sh
# (Hoặc để GitHub Actions chạy tự động: .github/workflows/build-macos.yml)
#
# Biến môi trường tùy chọn:
#   APP_VERSION          Phiên bản ghi vào app/dmg (mặc định 1.1.0)
#   APPLE_SIGN_IDENTITY  "Developer ID Application: Ten (TEAMID)" -> ký chính thức, người dùng mở được ngay
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD  -> notarize với Apple (cần APPLE_SIGN_IDENTITY)
set -euo pipefail
cd "$(dirname "$0")"

export APP_VERSION="${APP_VERSION:-1.1.0}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "❌ Script này phải chạy trên macOS." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "⚠️  Máy không phải Apple Silicon (arm64). Bản build sẽ chỉ chạy trên Mac chip M." >&2
fi

# Tìm Python 3.10+ có Tk >= 8.6 (python3 mặc định của Xcode dùng Tk 8.5 -> giao diện lỗi/trắng)
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for cand in python3.13 python3.12 python3.11 python3.10 \
              /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
              /opt/homebrew/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" - <<'EOF' >/dev/null 2>&1
import sys, tkinter
assert sys.version_info >= (3, 10)
assert float(tkinter.TkVersion) >= 8.6
EOF
    then PYTHON="$(command -v "$cand")"; break; fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  cat >&2 <<'EOF'
❌ Không tìm thấy Python 3.10+ có Tkinter 8.6.
   Cách 1 (khuyên dùng): cài Python từ https://www.python.org/downloads/macos/ (bản "macOS 64-bit universal2 installer").
   Cách 2 (Homebrew):    brew install python@3.12 python-tk@3.12
EOF
  exit 1
fi
echo "✓ Dùng Python: $PYTHON ($("$PYTHON" -c 'import sys,tkinter;print(sys.version.split()[0], "Tk", tkinter.TkVersion)'))"

VENV=".venv-macos"
[[ -d "$VENV" ]] || "$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
# Pillow để PyInstaller chuyển assets/icon.png thành .icns
python -m pip install -r requirements-desktop.txt "pyinstaller>=6.6" pillow

rm -rf build/macos dist/macos
pyinstaller --noconfirm --clean --distpath dist/macos --workpath build/macos BOTSD_Studio_macOS.spec

APP="dist/macos/BOTSD Studio.app"
xattr -cr "$APP"

if [[ -n "${APPLE_SIGN_IDENTITY:-}" ]]; then
  echo "🔏 Ký bằng Developer ID: $APPLE_SIGN_IDENTITY"
  codesign --force --deep --timestamp --options runtime \
           --entitlements assets/entitlements.plist \
           --sign "$APPLE_SIGN_IDENTITY" "$APP"
else
  echo "🔏 Ký ad-hoc (chưa có Developer ID: người dùng cần bấm 'Open Anyway' 1 lần)"
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"

# Đóng gói DMG: app + lối tắt Applications + hướng dẫn mở lần đầu
STAGE="build/macos/dmg"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "assets/Huong dan cai dat.txt" "$STAGE/Hướng dẫn cài đặt.txt"

DMG="dist/macos/BOTSD_Studio_${APP_VERSION}_macOS_AppleSilicon.dmg"
hdiutil create -volname "BOTSD Studio" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

if [[ -n "${APPLE_SIGN_IDENTITY:-}" ]]; then
  codesign --force --timestamp --sign "$APPLE_SIGN_IDENTITY" "$DMG"
  if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PASSWORD:-}" ]]; then
    echo "📨 Gửi Apple notarize (vài phút)..."
    xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
          --password "$APPLE_APP_PASSWORD" --wait
    xcrun stapler staple "$DMG"
  fi
fi

echo ""
echo "✅ Xong!"
echo "   App: $APP"
echo "   DMG: $DMG"
