#!/usr/bin/env bash
# Chạy BOTSD Studio trực tiếp từ mã nguồn trên macOS (double-click file này trong Finder).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for cand in python3.13 python3.12 python3.11 python3.10 \
              /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
              /opt/homebrew/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys,tkinter; assert sys.version_info>=(3,10) and float(tkinter.TkVersion)>=8.6' >/dev/null 2>&1; then
      PYTHON="$(command -v "$cand")"; break
    fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  echo "❌ Cần Python 3.10+ có Tkinter 8.6. Cài từ https://www.python.org/downloads/macos/ rồi chạy lại."
  read -r -p "Nhấn Enter để đóng..."
  exit 1
fi

VENV=".venv-macos"
if [[ ! -d "$VENV" ]]; then
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -r requirements-desktop.txt
fi
exec "$VENV/bin/python" main.py
