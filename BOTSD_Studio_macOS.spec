# -*- mode: python ; coding: utf-8 -*-
# Build trên macOS (Apple Silicon M1–M5):  pyinstaller --noconfirm BOTSD_Studio_macOS.spec
import os
import customtkinter
import certifi

ctk_path = os.path.dirname(customtkinter.__file__)
certifi_path = os.path.dirname(certifi.where())
app_version = os.environ.get('APP_VERSION', '1.1.0')

datas = [
    (ctk_path, 'customtkinter/'),
    (certifi_path, 'certifi/'),
]
# File mẫu: lần chạy đầu sẽ được copy sang ~/Library/Application Support/BOTSD Studio
for f in ('config.json', 'prompts_template.csv', 'prompts_template.xlsx'):
    if os.path.exists(f):
        datas.append((f, '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['pandas', 'openpyxl', 'rich', 'requests', 'customtkinter', 'certifi', 'darkdetect'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['streamlit'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BOTSD_Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BOTSD_Studio',
)
app = BUNDLE(
    coll,
    name='BOTSD Studio.app',
    icon='assets/icon.png' if os.path.exists('assets/icon.png') else None,
    bundle_identifier='pro.botsd.studio',
    info_plist={
        'CFBundleDisplayName': 'BOTSD Studio',
        'CFBundleName': 'BOTSD Studio',
        'CFBundleShortVersionString': app_version,
        'CFBundleVersion': app_version,
        'LSMinimumSystemVersion': '12.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)
