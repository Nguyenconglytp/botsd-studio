import os
import sys
import json
import time
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from typing import Dict, Any, Optional, List

from botsd_api import BOTSDClient, BOTSDAPIError
from batch_processor import BatchVideoProcessor
from sheet_auth import authenticate_sub_user, fetch_users_from_sheet
from app_paths import (DATA_DIR, MONO_FONT, data_path, resource_path,
                       resolve_output_dir, resolve_optional_dir)

# Set CustomTkinter Appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_DIR = DATA_DIR
CONFIG_FILE = data_path("config.json")


def load_config() -> dict:
    default_config = {
        "api_base_url": "https://botsd.pro",
        "admin_password": "admin123",
        "master_client_token": "",
        "google_sheet_url": "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit?usp=sharing",
        "output_dir": "outputs",
        "max_concurrent_jobs": 30,
        "poll_interval_seconds": 7,
        "retry_on_rate_limit": True,
        "default_model": "sd25",
        "default_seconds": 10,
        "default_ratio": "9:16",
        "default_resolution": "original"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
        except Exception:
            pass
    # Đường dẫn Windows (D:/...) trong config cũ không dùng được trên macOS -> tự chuyển về mặc định
    default_config["output_dir"] = resolve_output_dir(default_config.get("output_dir", ""))
    default_config["ref_char_dir"] = resolve_optional_dir(default_config.get("ref_char_dir", ""))
    return default_config

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

class AdminConfigDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: dict, on_save_callback):
        super().__init__(parent)
        self.title("⚙️ Cấu Hình Admin (Master Token, Sheet & Đa Luồng)")
        self.geometry("580x640")
        self.resizable(False, False)
        self.config = config
        self.on_save_callback = on_save_callback
        self.grab_set()

        lbl_title = ctk.CTkLabel(self, text="Cấu Hình Hệ Thống Admin", font=ctk.CTkFont(size=18, weight="bold"))
        lbl_title.pack(pady=(12, 8))

        # SECTION 1: Master BOTSD Credentials
        box_master = ctk.CTkFrame(self, corner_radius=8)
        box_master.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(box_master, text="🔐 Tài khoản BOTSD Chính (Nơi chứa Point thực):", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=15, pady=(8, 4))

        row_userpass = ctk.CTkFrame(box_master, fg_color="transparent")
        row_userpass.pack(fill="x", padx=15, pady=(0, 6))

        self.entry_m_user = ctk.CTkEntry(row_userpass, placeholder_text="Tên đăng nhập BOTSD chính")
        self.entry_m_user.insert(0, self.config.get("master_username", ""))
        self.entry_m_user.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.entry_m_pass = ctk.CTkEntry(row_userpass, placeholder_text="Mật khẩu BOTSD chính", show="•")
        self.entry_m_pass.insert(0, self.config.get("master_password", ""))
        self.entry_m_pass.pack(side="left", fill="x", expand=True, padx=(5, 0))

        row_token_btn = ctk.CTkFrame(box_master, fg_color="transparent")
        row_token_btn.pack(fill="x", padx=15, pady=(0, 6))

        btn_auto_token = ctk.CTkButton(row_token_btn, text="🔑 Tự Động Lấy Token Từ BOTSD", fg_color="#0288D1", hover_color="#0277BD", command=self.auto_fetch_master_token)
        btn_auto_token.pack(fill="x")

        ctk.CTkLabel(box_master, text="Master clientToken (UUID):", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=15, pady=(4, 2))
        self.entry_token = ctk.CTkEntry(box_master, placeholder_text="Token UUID của tài khoản BOTSD chính...")
        self.entry_token.insert(0, self.config.get("master_client_token", ""))
        self.entry_token.pack(fill="x", padx=15, pady=(0, 6))

        self.lbl_master_status = ctk.CTkLabel(box_master, text="Chưa kiểm tra token", font=ctk.CTkFont(size=11), text_color="#AAAAAA")
        self.lbl_master_status.pack(anchor="w", padx=15, pady=(0, 8))

        # SECTION 2: Sheet, Pass, Output & Thread Settings
        box_sheet = ctk.CTkFrame(self, corner_radius=8)
        box_sheet.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(box_sheet, text="📊 Google Sheet & Thông Số Hệ Thống:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=15, pady=(8, 2))
        self.entry_sheet = ctk.CTkEntry(box_sheet, placeholder_text="Dán link Google Sheet tại đây...")
        self.entry_sheet.insert(0, self.config.get("google_sheet_url", ""))
        self.entry_sheet.pack(fill="x", padx=15, pady=(0, 8))

        row_admin_out = ctk.CTkFrame(box_sheet, fg_color="transparent")
        row_admin_out.pack(fill="x", padx=15, pady=(0, 8))

        f_adm_pwd = ctk.CTkFrame(row_admin_out, fg_color="transparent")
        f_adm_pwd.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkLabel(f_adm_pwd, text="Mật khẩu bảo vệ Admin:", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self.entry_admin_pwd = ctk.CTkEntry(f_adm_pwd, show="•")
        self.entry_admin_pwd.insert(0, self.config.get("admin_password", "admin123"))
        self.entry_admin_pwd.pack(fill="x")

        f_out = ctk.CTkFrame(row_admin_out, fg_color="transparent")
        f_out.pack(side="left", fill="x", expand=True, padx=(5, 0))
        ctk.CTkLabel(f_out, text="Thư mục Video mặc định:", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self.entry_outdir = ctk.CTkEntry(f_out)
        self.entry_outdir.insert(0, self.config.get("output_dir", "outputs"))
        self.entry_outdir.pack(fill="x")

        # SECTION 3: Threads & Poll Interval
        row_threads = ctk.CTkFrame(box_sheet, fg_color="transparent")
        row_threads.pack(fill="x", padx=15, pady=(0, 8))

        f_threads = ctk.CTkFrame(row_threads, fg_color="transparent")
        f_threads.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkLabel(f_threads, text="⚡ Số luồng song song (Threads):", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        self.entry_threads = ctk.CTkEntry(f_threads)
        self.entry_threads.insert(0, str(self.config.get("max_concurrent_jobs", 30)))
        self.entry_threads.pack(fill="x")

        f_poll = ctk.CTkFrame(row_threads, fg_color="transparent")
        f_poll.pack(side="left", fill="x", expand=True, padx=(5, 0))
        ctk.CTkLabel(f_poll, text="⏱️ Khoảng Poll (giây):", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self.entry_poll = ctk.CTkEntry(f_poll)
        self.entry_poll.insert(0, str(self.config.get("poll_interval_seconds", 7)))
        self.entry_poll.pack(fill="x")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)

        btn_save = ctk.CTkButton(btn_frame, text="💾 Lưu Cấu Hình", fg_color="#2EA44F", hover_color="#2C974B", command=self.save)
        btn_save.pack(side="right", padx=5)

        btn_cancel = ctk.CTkButton(btn_frame, text="Hủy", fg_color="#6E7681", hover_color="#57606A", command=self.destroy)
        btn_cancel.pack(side="right", padx=5)

    def auto_fetch_master_token(self):
        m_user = self.entry_m_user.get().strip()
        m_pass = self.entry_m_pass.get().strip()
        
        if not m_user or not m_pass:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập Tên đăng nhập và Mật khẩu tài khoản BOTSD chính.")
            return

        self.lbl_master_status.configure(text="Đang kết nối tới BOTSD API...", text_color="#0288D1")
        self.update()

        try:
            client = BOTSDClient(base_url=self.config.get("api_base_url", "https://botsd.pro"))
            res = client.login(m_user, m_pass)
            token = res.get("clientToken")
            user_id = res.get("userId")
            balance = res.get("balance", 0)

            if token:
                self.entry_token.delete(0, "end")
                self.entry_token.insert(0, token)
                self.lbl_master_status.configure(text=f"✓ Đăng nhập thành công! User ID: {user_id} | Balance: {balance} Points", text_color="#2EA44F")
                messagebox.showinfo("Thành công", f"Đã lấy được clientToken cho tài khoản {user_id}!\nSố dư khả dụng: {balance} Points.")
            else:
                self.lbl_master_status.configure(text="❌ Không lấy được clientToken từ phản hồi.", text_color="#E53935")
        except Exception as e:
            self.lbl_master_status.configure(text=f"❌ Lỗi đăng nhập BOTSD: {e}", text_color="#E53935")
            messagebox.showerror("Lỗi Đăng Nhập BOTSD", f"Lỗi: {e}")

    def save(self):
        token = self.entry_token.get().strip()
        sheet = self.entry_sheet.get().strip()
        m_user = self.entry_m_user.get().strip()
        m_pass = self.entry_m_pass.get().strip()
        admin_pwd = self.entry_admin_pwd.get().strip() or "admin123"
        outdir = resolve_output_dir(self.entry_outdir.get().strip())

        try:
            threads = int(self.entry_threads.get().strip())
            threads = max(1, min(200, threads))
        except ValueError:
            threads = 30

        try:
            poll_sec = int(self.entry_poll.get().strip())
            poll_sec = max(1, min(60, poll_sec))
        except ValueError:
            poll_sec = 7

        self.config["master_username"] = m_user
        self.config["master_password"] = m_pass
        self.config["master_client_token"] = token
        self.config["google_sheet_url"] = sheet
        self.config["admin_password"] = admin_pwd
        self.config["output_dir"] = outdir
        self.config["max_concurrent_jobs"] = threads
        self.config["poll_interval_seconds"] = poll_sec
        save_config(self.config)

        if self.on_save_callback:
            self.on_save_callback(self.config)
        messagebox.showinfo("Thành công", "Đã lưu cấu hình hệ thống!")
        self.destroy()


class BOTSDDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BOTSD Studio - Video Generation Studio")
        self.geometry("980x750")
        self.minsize(900, 680)

        self.config = load_config()
        self.current_user_info: Optional[dict] = None
        self.is_processing = False
        self.selected_ref_images: List[str] = []
        self.queued_tasks: List[dict] = []

        self.check_and_refresh_master_token()
        self.create_widgets()
        self.show_studio_frame()

    def check_and_refresh_master_token(self):
        """Khởi động ngầm tự động lấy token nếu đã có master_username & master_password."""
        m_user = self.config.get("master_username", "").strip()
        m_pass = self.config.get("master_password", "").strip()
        if m_user and m_pass:
            def async_login():
                try:
                    client = BOTSDClient(base_url=self.config.get("api_base_url", "https://botsd.pro"))
                    res = client.login(m_user, m_pass)
                    token = res.get("clientToken")
                    if token:
                        self.config["master_client_token"] = token
                        save_config(self.config)
                except Exception:
                    pass
            threading.Thread(target=async_login, daemon=True).start()


    def create_widgets(self):
        # 1. LOGIN FRAME
        self.frame_login = ctk.CTkFrame(self, corner_radius=15)

        lbl_logo = ctk.CTkLabel(self.frame_login, text="🎬 BOTSD STUDIO", font=ctk.CTkFont(size=26, weight="bold"), text_color="#1E88E5")
        lbl_logo.pack(pady=(40, 5))
        
        lbl_sub = ctk.CTkLabel(self.frame_login, text="Phần mềm tạo Video AI trực tiếp qua BOTSD API", font=ctk.CTkFont(size=13), text_color="#888888")
        lbl_sub.pack(pady=(0, 25))

        self.entry_username = ctk.CTkEntry(self.frame_login, width=320, height=40, placeholder_text="Tên đăng nhập (Username)")
        self.entry_username.pack(pady=10)

        self.entry_password = ctk.CTkEntry(self.frame_login, width=320, height=40, placeholder_text="Mật khẩu (Password)", show="•")
        self.entry_password.pack(pady=10)

        self.btn_login = ctk.CTkButton(self.frame_login, text="🔑 ĐĂNG NHẬP", width=320, height=42, font=ctk.CTkFont(size=14, weight="bold"), command=self.handle_login)
        self.btn_login.pack(pady=(15, 20))

        self.lbl_login_status = ctk.CTkLabel(self.frame_login, text="", font=ctk.CTkFont(size=12))
        self.lbl_login_status.pack(pady=5)

        # 2. MAIN STUDIO FRAME
        self.frame_studio = ctk.CTkFrame(self, fg_color="transparent")

        # Top Header Bar
        self.header_bar = ctk.CTkFrame(self.frame_studio, height=55, corner_radius=10)
        self.header_bar.pack(fill="x", padx=10, pady=(10, 5))

        self.lbl_user_badge = ctk.CTkLabel(self.header_bar, text="🎬 BOTSD STUDIO PRO - BẢN ĐÓNG GÓI CHUẨN (ĐA LUỒNG SONG SONG)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#1E88E5")
        self.lbl_user_badge.pack(side="left", padx=15, pady=8)

        self.btn_admin_top = ctk.CTkButton(self.header_bar, text="⚙️ Cấu Hình Admin", width=140, fg_color="#0288D1", hover_color="#0277BD", command=self.open_admin_config)
        self.btn_admin_top.pack(side="right", padx=10)


        # Output Folder Selection (Shared)
        self.folder_box = ctk.CTkFrame(self.frame_studio, corner_radius=8)
        self.folder_box.pack(fill="x", padx=10, pady=(0, 8))

        folder_row = ctk.CTkFrame(self.folder_box, fg_color="transparent")
        folder_row.pack(fill="x", padx=12, pady=(6, 3))

        ctk.CTkLabel(folder_row, text="📁 Thư mục lưu Video:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 10))

        self.entry_output_dir = ctk.CTkEntry(folder_row, placeholder_text="Chọn thư mục lưu video...")
        self.entry_output_dir.insert(0, self.config.get("output_dir", "outputs"))
        self.entry_output_dir.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse_dir = ctk.CTkButton(folder_row, text="Chọn Thư Mục...", width=110, fg_color="#37474F", hover_color="#263238", command=self.browse_output_dir)
        btn_browse_dir.pack(side="right")

        folder_row2 = ctk.CTkFrame(self.folder_box, fg_color="transparent")
        folder_row2.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(folder_row2, text="👤 Thư mục ảnh Nhân vật:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 10))

        self.entry_ref_char_dir = ctk.CTkEntry(folder_row2, placeholder_text="Chọn thư mục chứa ảnh nhân vật (tự động ghép theo tên trong Excel)...")
        self.entry_ref_char_dir.insert(0, self.config.get("ref_char_dir", ""))
        self.entry_ref_char_dir.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse_char_dir = ctk.CTkButton(folder_row2, text="Chọn Thư Mục...", width=110, fg_color="#37474F", hover_color="#263238", command=self.browse_ref_char_dir)
        btn_browse_char_dir.pack(side="right")

        # Global Video Parameters Box
        self.param_box = ctk.CTkFrame(self.frame_studio, corner_radius=8)
        self.param_box.pack(fill="x", padx=10, pady=(0, 8))

        param_grid = ctk.CTkFrame(self.param_box, fg_color="transparent")
        param_grid.pack(fill="x", padx=10, pady=6)

        # Model AI
        f_model = ctk.CTkFrame(param_grid, fg_color="transparent")
        f_model.pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkLabel(f_model, text="Model AI:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        self.combo_model = ctk.CTkComboBox(f_model, values=["sd25", "sd20"], height=32)
        self.combo_model.set(self.config.get("default_model", "sd25"))
        self.combo_model.pack(fill="x")

        # Seconds
        f_sec = ctk.CTkFrame(param_grid, fg_color="transparent")
        f_sec.pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkLabel(f_sec, text="Thời lượng:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        self.combo_seconds = ctk.CTkComboBox(f_sec, values=["10", "5", "15", "30"], height=32)
        self.combo_seconds.set(str(self.config.get("default_seconds", 10)))
        self.combo_seconds.pack(fill="x")

        # Ratio
        f_ratio = ctk.CTkFrame(param_grid, fg_color="transparent")
        f_ratio.pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkLabel(f_ratio, text="Tỉ lệ khung hình:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        self.combo_ratio = ctk.CTkComboBox(f_ratio, values=["9:16", "16:9", "1:1", "3:4", "4:3", "21:9"], height=32)
        self.combo_ratio.set(self.config.get("default_ratio", "9:16"))
        self.combo_ratio.pack(fill="x")

        # Resolution
        f_res = ctk.CTkFrame(param_grid, fg_color="transparent")
        f_res.pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkLabel(f_res, text="Độ phân giải:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        self.combo_res = ctk.CTkComboBox(f_res, values=["original", "1080p", "1080p-real", "4k"], height=32)
        self.combo_res.set(self.config.get("default_resolution", "original"))
        self.combo_res.pack(fill="x")

        # Global Real Person Mode Checkboxes
        real_person_row = ctk.CTkFrame(self.param_box, fg_color="transparent")
        real_person_row.pack(fill="x", padx=10, pady=(2, 6))

        self.check_real_person = ctk.CTkCheckBox(real_person_row, text="Chế độ người thật (Real Person Mode)")
        if self.config.get("default_real_person", False):
            self.check_real_person.select()
        self.check_real_person.pack(side="left", padx=(5, 15))

        self.check_real_deep = ctk.CTkCheckBox(real_person_row, text="Chế độ người thật nâng cao (Deep Mode)")
        if self.config.get("default_real_person_deep", False):
            self.check_real_deep.select()
        self.check_real_deep.pack(side="left")

        # TABVIEW FOR MODES
        self.tabview = ctk.CTkTabview(self.frame_studio, corner_radius=10, height=220)
        self.tabview.pack(fill="x", padx=10, pady=(0, 8))

        self.tab_direct = self.tabview.add("✍️ Tạo Trực Tiếp Trên App")
        self.tab_csv = self.tabview.add("📊 Nhập Hàng Loạt Từ Excel / CSV")

        # --- TAB 1: DIRECT STUDIO ---
        # Prompt Textbox
        ctk.CTkLabel(self.tab_direct, text="Mô tả nội dung Video (Prompt):", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=5, pady=(2, 2))
        self.txt_prompt = ctk.CTkTextbox(self.tab_direct, height=75)
        self.txt_prompt.insert("1.0", "A cinematic shot of a sports car driving through Tokyo at night.")
        self.txt_prompt.pack(fill="x", padx=5, pady=(0, 6))

        # Options Row: Output name & Reference Images
        direct_opt_row = ctk.CTkFrame(self.tab_direct, fg_color="transparent")
        direct_opt_row.pack(fill="x", padx=5, pady=(0, 6))

        # File name
        ctk.CTkLabel(direct_opt_row, text="Tên file xuất:", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(0, 5))
        self.entry_direct_name = ctk.CTkEntry(direct_opt_row, width=160, placeholder_text="Tên video...")
        self.entry_direct_name.insert(0, "video_my_style")
        self.entry_direct_name.pack(side="left", padx=(0, 15))

        # Image picker
        btn_pick_img = ctk.CTkButton(direct_opt_row, text="📷 Chọn Ảnh Tham Chiếu (Max 10)", fg_color="#0288D1", hover_color="#0277BD", command=self.browse_ref_images)
        btn_pick_img.pack(side="left", padx=(0, 5))

        btn_clear_img = ctk.CTkButton(direct_opt_row, text="❌ Xóa Ảnh", width=70, fg_color="#78909C", hover_color="#607D8B", command=self.clear_ref_images)
        btn_clear_img.pack(side="left", padx=(0, 10))

        self.lbl_images_status = ctk.CTkLabel(direct_opt_row, text="Chưa chọn ảnh tham chiếu nào.", font=ctk.CTkFont(size=11), text_color="#AAAAAA")
        self.lbl_images_status.pack(side="left", fill="x", expand=True)

        # Direct Action Buttons
        btn_direct_row = ctk.CTkFrame(self.tab_direct, fg_color="transparent")
        btn_direct_row.pack(fill="x", padx=5, pady=(4, 2))

        self.btn_queue_add = ctk.CTkButton(btn_direct_row, text="➕ Thêm Vào Hàng Đợi", fg_color="#7B1FA2", hover_color="#6A1B9A", command=self.add_to_queue)
        self.btn_queue_add.pack(side="left", padx=(0, 10))

        self.lbl_queue_count = ctk.CTkLabel(btn_direct_row, text="Hàng đợi: 0 task", font=ctk.CTkFont(size=12, weight="bold"), text_color="#E0E0E0")
        self.lbl_queue_count.pack(side="left", padx=(0, 15))

        self.btn_direct_start = ctk.CTkButton(btn_direct_row, text="🚀 TẠO VIDEO NGAY", font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1E88E5", hover_color="#1565C0", command=self.start_direct_process)
        self.btn_direct_start.pack(side="right", expand=True, fill="x")

        # --- TAB 2: EXCEL / CSV MODE ---
        ctk.CTkLabel(self.tab_csv, text="📄 File danh sách Prompt (Excel .xlsx / CSV):", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=5, pady=(10, 4))
        
        csv_file_row = ctk.CTkFrame(self.tab_csv, fg_color="transparent")
        csv_file_row.pack(fill="x", padx=5, pady=(0, 10))

        default_tmpl = next((p for p in (resource_path("prompts_template.xlsx"), resource_path("prompts_template.csv")) if os.path.exists(p)), "")
        self.entry_file_path = ctk.CTkEntry(csv_file_row, placeholder_text="Chọn file prompts.xlsx hoặc prompts.csv...")
        self.entry_file_path.insert(0, default_tmpl)
        self.entry_file_path.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse_file = ctk.CTkButton(csv_file_row, text="Browse...", width=100, command=self.browse_file)
        btn_browse_file.pack(side="right")

        self.check_override = ctk.CTkCheckBox(self.tab_csv, text="Ép buộc áp dụng Cấu hình Model/Thời lượng trên cho tất cả dòng trong File")
        if self.config.get("override_with_ui_defaults"):
            self.check_override.select()
        self.check_override.pack(anchor="w", padx=5, pady=(5, 10))

        self.btn_csv_start = ctk.CTkButton(self.tab_csv, text="🚀 BẮT ĐẦU CHẠY FILE EXCEL / CSV", font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1E88E5", hover_color="#1565C0", command=self.start_csv_process)
        self.btn_csv_start.pack(fill="x", padx=5, pady=(5, 5))

        # Progress Bar & Output Area (Shared)
        self.action_box = ctk.CTkFrame(self.frame_studio, corner_radius=8)
        self.action_box.pack(fill="x", padx=10, pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(self.action_box)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=12, pady=(10, 4))

        self.lbl_progress_status = ctk.CTkLabel(self.action_box, text="Sẵn sàng thực thi.", font=ctk.CTkFont(size=12), text_color="#888888")
        self.lbl_progress_status.pack(pady=(0, 8))

        # Individual Task Progress Scrollable Box
        self.task_cards_box = ctk.CTkFrame(self.frame_studio, corner_radius=8)
        self.task_cards_box.pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkLabel(self.task_cards_box, text="📊 Tiến Trình Đa Luồng Song Song Từng Video:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(6, 2))

        self.scroll_tasks = ctk.CTkScrollableFrame(self.task_cards_box, height=130, fg_color="transparent")
        self.scroll_tasks.pack(fill="x", padx=8, pady=(0, 6))

        self.task_ui_map = {}

        # Log Output Box
        self.log_box = ctk.CTkFrame(self.frame_studio, corner_radius=8)
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        ctk.CTkLabel(self.log_box, text="📋 Nhật Ký Xử Lý (Log Output):", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(6, 4))

        self.textbox_log = ctk.CTkTextbox(self.log_box, font=ctk.CTkFont(family=MONO_FONT, size=11))
        self.textbox_log.pack(fill="both", expand=True, padx=12, pady=(0, 8))


        # Bottom Toolbar
        self.bottom_bar = ctk.CTkFrame(self.frame_studio, fg_color="transparent")
        self.bottom_bar.pack(fill="x", padx=10, pady=(0, 8))

        btn_open_folder = ctk.CTkButton(self.bottom_bar, text="📂 Mở Thư Mục Video Output", fg_color="#26A69A", hover_color="#00897B", command=self.open_output_folder)
        btn_open_folder.pack(side="left", padx=5)

        btn_open_report = ctk.CTkButton(self.bottom_bar, text="📊 Mở File Báo Cáo CSV", fg_color="#7E57C2", hover_color="#5E35B1", command=self.open_report_csv)
        btn_open_report.pack(side="left", padx=5)

    def show_login_frame(self):
        self.frame_studio.pack_forget()
        self.frame_login.pack(expand=True, padx=20, pady=20)

    def show_studio_frame(self):
        self.frame_login.pack_forget()
        self.frame_studio.pack(fill="both", expand=True)

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.textbox_log.insert("end", f"[{timestamp}] {message}\n")
        self.textbox_log.see("end")

    def handle_login(self):
        username = self.entry_username.get().strip()
        password = self.entry_password.get().strip()

        if not username or not password:
            self.lbl_login_status.configure(text="⚠️ Vui lòng nhập Username & Password", text_color="#FFB300")
            return

        self.lbl_login_status.configure(text="Đang kết nối Google Sheet...", text_color="#1E88E5")
        self.update()

        def do_auth():
            sheet_url = self.config.get("google_sheet_url", "")
            success, msg, user_info = authenticate_sub_user(username, password, sheet_url)
            
            def after_auth():
                if success:
                    self.current_user_info = user_info
                    self.lbl_login_status.configure(text="", text_color="white")
                    self.update_user_badge()
                    self.show_studio_frame()
                    self.log(f"Xin chào {username}! Quota của bạn: {user_info['remaining_points']} Points.")
                else:
                    self.lbl_login_status.configure(text=f"❌ {msg}", text_color="#E53935")

            self.after(0, after_auth)

        threading.Thread(target=do_auth, daemon=True).start()

    def handle_logout(self):
        self.current_user_info = None
        self.show_login_frame()
        self.entry_password.delete(0, "end")

    def update_user_badge(self):
        if self.current_user_info:
            u = self.current_user_info
            text = f"👤 User: {u['username']} | Quota Khả Dụng: {u['remaining_points']} / {u['quota_assigned']} Pts"
            self.lbl_user_badge.configure(text=text)

    def open_admin_config(self):
        if self.current_user_info and self.current_user_info.get("is_admin"):
            AdminConfigDialog(self, self.config, self.on_admin_config_saved)
            return

        dialog_pwd = ctk.CTkInputDialog(
            text="🔒 Nhập Mật Khẩu Admin để mở trang Cấu Hình:", 
            title="Xác Thực Quyền Admin"
        )
        pwd_input = dialog_pwd.get_input()

        if pwd_input is not None:
            expected_pwd = self.config.get("admin_password", "admin123")
            if pwd_input.strip() == expected_pwd:
                AdminConfigDialog(self, self.config, self.on_admin_config_saved)
            else:
                messagebox.showerror("Từ Chối Truy Cập", "❌ Mật khẩu Admin không chính xác!")

    def on_admin_config_saved(self, new_cfg):
        self.config = new_cfg
        self.log("Đã cập nhật cấu hình Admin thành công.")

    def browse_file(self):
        filepath = filedialog.askopenfilename(
            title="Chọn file danh sách Prompt (Excel / CSV)",
            filetypes=[
                ("Excel & CSV Files", ("*.xlsx", "*.xls", "*.csv")),
                ("Excel Files (*.xlsx, *.xls)", ("*.xlsx", "*.xls")),
                ("CSV Files (*.csv)", "*.csv"),
                ("All Files", "*")
            ]
        )
        if filepath:
            self.entry_file_path.delete(0, "end")
            self.entry_file_path.insert(0, filepath)

    def browse_output_dir(self):
        dirpath = filedialog.askdirectory(title="Chọn Thư Mục Lưu Video Dự Án")
        if dirpath:
            self.entry_output_dir.delete(0, "end")
            self.entry_output_dir.insert(0, dirpath)
            self.config["output_dir"] = dirpath
            save_config(self.config)

    def browse_ref_char_dir(self):
        dirpath = filedialog.askdirectory(title="Chọn Thư Mục Chứa Ảnh Nhân Vật Tham Chiếu")
        if dirpath:
            self.entry_ref_char_dir.delete(0, "end")
            self.entry_ref_char_dir.insert(0, dirpath)
            self.config["ref_char_dir"] = dirpath
            save_config(self.config)
            self.log(f"📁 Đã chọn thư mục ảnh nhân vật: {dirpath}")

    def browse_ref_images(self):
        paths = filedialog.askopenfilenames(
            title="Chọn Ảnh Tham Chiếu (Tối đa 10 ảnh)",
            filetypes=[("Image Files", ("*.jpg", "*.jpeg", "*.png", "*.webp")), ("All Files", "*")]
        )
        if paths:
            self.selected_ref_images = list(paths)[:10]
            count = len(self.selected_ref_images)
            names = ", ".join([os.path.basename(p) for p in self.selected_ref_images])
            self.lbl_images_status.configure(text=f"✓ {count} ảnh đã chọn: {names}", text_color="#2EA44F")

    def clear_ref_images(self):
        self.selected_ref_images = []
        self.lbl_images_status.configure(text="Chưa chọn ảnh tham chiếu nào.", text_color="#AAAAAA")

    def add_to_queue(self):
        prompt = self.txt_prompt.get("1.0", "end").strip()
        name = self.entry_direct_name.get().strip() or f"video_{len(self.queued_tasks)+1:02d}"
        
        if not prompt:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập mô tả Prompt.")
            return

        task_item = {
            "output_name": name,
            "prompt": prompt,
            "seconds": int(self.combo_seconds.get().strip()),
            "model": self.combo_model.get().strip(),
            "ratio": self.combo_ratio.get().strip(),
            "resolution": self.combo_res.get().strip(),
            "real_person_mode": bool(self.check_real_person.get()),
            "real_person_deep_mode": bool(self.check_real_deep.get()),
            "image_paths": list(self.selected_ref_images)
        }
        self.queued_tasks.append(task_item)
        self.lbl_queue_count.configure(text=f"Hàng đợi: {len(self.queued_tasks)} task")
        self.log(f"➕ Đã thêm task '{name}' vào hàng đợi.")

    def get_current_output_dir(self) -> str:
        out = resolve_output_dir(self.entry_output_dir.get().strip() or self.config.get("output_dir", ""))
        self.config["output_dir"] = out
        return out

    def open_output_folder(self):
        out_dir = os.path.abspath(self.get_current_output_dir())
        os.makedirs(out_dir, exist_ok=True)
        if os.name == 'nt':
            os.startfile(out_dir)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", out_dir])

    def open_report_csv(self):
        out_dir = os.path.abspath(self.get_current_output_dir())
        report_file = os.path.join(out_dir, "batch_report.csv")
        if os.path.exists(report_file):
            if os.name == 'nt':
                os.startfile(report_file)
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", report_file])
        else:
            messagebox.showinfo("Thông báo", "Chưa có file báo cáo batch_report.csv.")

    def save_ui_config(self):
        self.config["default_model"] = self.combo_model.get().strip() or "sd25"
        try:
            self.config["default_seconds"] = int(self.combo_seconds.get().strip())
        except ValueError:
            self.config["default_seconds"] = 10
        self.config["default_ratio"] = self.combo_ratio.get().strip() or "9:16"
        self.config["default_resolution"] = self.combo_res.get().strip() or "original"
        self.config["override_with_ui_defaults"] = bool(self.check_override.get())
        self.config["default_real_person"] = bool(self.check_real_person.get())
        self.config["default_real_person_deep"] = bool(self.check_real_deep.get())
        self.get_current_output_dir()
        save_config(self.config)

    def start_csv_process(self):
        file_path = self.entry_file_path.get().strip()
        if not os.path.exists(file_path):
            messagebox.showerror("Lỗi", f"Không tìm thấy file prompt: {file_path}")
            return
        
        self.save_ui_config()
        self.start_batch_runner(csv_path=file_path)

    def start_direct_process(self):
        prompt = self.txt_prompt.get("1.0", "end").strip()
        name = self.entry_direct_name.get().strip() or "video_01"

        if not self.queued_tasks and not prompt:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập mô tả Prompt hoặc thêm vào hàng đợi.")
            return

        self.save_ui_config()

        if not self.queued_tasks:
            # Chỉ có 1 task hiện tại
            single_task = {
                "index": 1,
                "output_name": name,
                "prompt": prompt,
                "seconds": int(self.combo_seconds.get().strip()),
                "model": self.combo_model.get().strip(),
                "ratio": self.combo_ratio.get().strip(),
                "resolution": self.combo_res.get().strip(),
                "real_person_mode": bool(self.check_real_person.get()),
                "real_person_deep_mode": bool(self.check_real_deep.get()),
                "image_paths": list(self.selected_ref_images)
            }
            direct_tasks = [single_task]
        else:
            # Thêm task hiện tại nếu có prompt
            if prompt:
                self.add_to_queue()
            direct_tasks = []
            for idx, t in enumerate(self.queued_tasks):
                t["index"] = idx + 1
                direct_tasks.append(t)
            self.queued_tasks = []
            self.lbl_queue_count.configure(text="Hàng đợi: 0 task")

        self.start_batch_runner(direct_tasks=direct_tasks)

    def start_batch_runner(self, csv_path: Optional[str] = None, direct_tasks: Optional[List[dict]] = None):
        if self.is_processing:
            messagebox.showwarning("Cảnh báo", "Đang có tiến trình chạy. Vui lòng chờ hoàn tất!")
            return

        master_token = self.config.get("master_client_token", "").strip()
        if not master_token:
            messagebox.showerror("Lỗi Admin", "Admin chưa cấu hình Master BOTSD Token! Vui lòng vào ⚙️ Admin Config để điền Token.")
            return

        self.is_processing = True
        self.btn_direct_start.configure(state="disabled", text="⏳ ĐANG XỬ LÝ...")
        self.btn_csv_start.configure(state="disabled")
        self.progress_bar.set(0.05)
        self.lbl_progress_status.configure(text="Đang xử lý sinh video...", text_color="#1E88E5")
        
        threading.Thread(target=self.run_batch_logic, args=(csv_path, direct_tasks), daemon=True).start()

    def init_task_progress_cards(self, tasks: List[dict]):
        """Khởi tạo danh sách thanh tiến trình riêng cho từng video kèm nút '🔄 Tạo lại'."""
        def _build():
            for widget in self.scroll_tasks.winfo_children():
                widget.destroy()
            self.task_ui_map = {}

            for t in tasks:
                idx = t.get("index", 1)
                name = t.get("output_name", f"video_{idx}")

                card = ctk.CTkFrame(self.scroll_tasks, corner_radius=6, fg_color="#1F2A38")
                card.pack(fill="x", padx=4, pady=3)

                top_row = ctk.CTkFrame(card, fg_color="transparent")
                top_row.pack(fill="x", padx=8, pady=(4, 2))

                lbl_title = ctk.CTkLabel(top_row, text=f"📹 Task #{idx}: {name}", font=ctk.CTkFont(size=11, weight="bold"))
                lbl_title.pack(side="left")

                btn_retry = ctk.CTkButton(
                    top_row,
                    text="🔄 Tạo lại",
                    width=75,
                    height=24,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    fg_color="#0288D1",
                    hover_color="#0277BD",
                    command=lambda task_obj=dict(t): self.retry_single_task(task_obj)
                )
                btn_retry.pack(side="right", padx=(8, 0))

                lbl_status = ctk.CTkLabel(top_row, text="Đang chờ...", font=ctk.CTkFont(size=11), text_color="#AAAAAA")
                lbl_status.pack(side="right")

                bar = ctk.CTkProgressBar(card, height=8)
                bar.set(0)
                bar.pack(fill="x", padx=8, pady=(0, 6))

                self.task_ui_map[idx] = {
                    "card": card,
                    "lbl_status": lbl_status,
                    "bar": bar,
                    "btn_retry": btn_retry
                }
        self.after(0, _build)

    def retry_single_task(self, task: dict):
        """Thực thi tạo lại 1 task đơn lẻ bất kỳ."""
        master_token = self.config.get("master_client_token", "").strip()
        if not master_token:
            messagebox.showerror("Lỗi Admin", "Admin chưa cấu hình Master BOTSD Token! Vui lòng vào ⚙️ Admin Config để điền Token.")
            return

        idx = task.get("index", 1)
        name = task.get("output_name", f"video_{idx}")

        if idx in self.task_ui_map:
            self.task_ui_map[idx]["btn_retry"].configure(state="disabled", text="⏳ Đang tạo...")

        self.update_task_progress_ui(idx, 0.05, f"🔄 Đang khởi tạo lại '{name}'...")
        self.log(f"🔄 [Tạo lại] Bắt đầu xử lý đơn lẻ Task #{idx}: '{name}'...")

        def _do_retry():
            try:
                client = BOTSDClient(
                    base_url=self.config.get("api_base_url", "https://botsd.pro"),
                    client_token=master_token
                )
                processor = BatchVideoProcessor(client, self.config)
                res = processor.process_single_task(
                    task,
                    update_cb=self.update_task_progress_ui,
                    log_cb=self.log
                )
                if res.get("status") == "SUCCESS":
                    self.log(f"✓ Task #{idx} ('{name}') tạo lại THÀNH CÔNG! Saved: {res.get('saved_path')}")
                else:
                    self.log(f"❌ Task #{idx} ('{name}') tạo lại THẤT BẠI: {res.get('error_message')}")
            except Exception as e:
                self.log(f"❌ Lỗi ngoài dự kiến khi tạo lại Task #{idx}: {e}")
                self.update_task_progress_ui(idx, 1.0, f"❌ Thất bại: {e}")
            finally:
                def _reenable():
                    if idx in self.task_ui_map:
                        self.task_ui_map[idx]["btn_retry"].configure(state="normal", text="🔄 Tạo lại")
                self.after(0, _reenable)

        threading.Thread(target=_do_retry, daemon=True).start()

    def update_task_progress_ui(self, idx: int, percent: float, status_text: str):
        """Cập nhật thanh tiến trình riêng của task idx trên UI thread."""
        def _update():
            if idx in self.task_ui_map:
                ui = self.task_ui_map[idx]
                ui["bar"].set(percent)
                ui["lbl_status"].configure(text=status_text)
                if percent >= 1.0:
                    if "✓" in status_text or "Completed" in status_text or "thành công" in status_text.lower():
                        ui["lbl_status"].configure(text_color="#2EA44F")
                    else:
                        ui["lbl_status"].configure(text_color="#E53935")
                elif percent >= 0.8:
                    ui["lbl_status"].configure(text_color="#29B6F6")
                elif percent >= 0.3:
                    ui["lbl_status"].configure(text_color="#FFCA28")

        self.after(0, _update)

    def run_batch_logic(self, csv_path: Optional[str], direct_tasks: Optional[List[dict]]):
        try:
            self.log("🚀 Bắt đầu quá trình sinh video...")
            
            master_token = self.config.get("master_client_token")
            master_client = BOTSDClient(
                base_url=self.config.get("api_base_url", "https://botsd.pro"),
                client_token=master_token
            )
            
            self.config["current_sub_username"] = self.current_user_info["username"] if self.current_user_info else ""

            char_dir = resolve_optional_dir(self.entry_ref_char_dir.get().strip() if hasattr(self, 'entry_ref_char_dir') else self.config.get("ref_char_dir", ""))
            if char_dir:
                self.config["ref_char_dir"] = char_dir
                save_config(self.config)

            processor = BatchVideoProcessor(master_client, self.config)

            if csv_path:
                tasks = processor.load_prompts_file(csv_path, ref_char_dir=char_dir)
                self.log(f"Đã tải {len(tasks)} video task từ file {os.path.basename(csv_path)}")
            else:
                tasks = direct_tasks or []

            self.init_task_progress_cards(tasks)
            results = processor.run_tasks_list(tasks, log_callback=self.log, task_update_callback=self.update_task_progress_ui)



            success_cnt = sum(1 for r in results if r.get("status") == "SUCCESS")
            total_cost = sum(r.get("cost", 0) for r in results)

            self.log(f"✓ Hoàn tất {success_cnt}/{len(results)} task! Tổng chi phí: {total_cost} Points.")

            if self.current_user_info:
                _, _, updated_info = authenticate_sub_user(
                    self.current_user_info["username"],
                    self.current_user_info.get("password", ""),
                    self.config.get("google_sheet_url", "")
                )
                if updated_info:
                    self.current_user_info = updated_info
                    self.after(0, self.update_user_badge)

            def on_complete():
                self.progress_bar.set(1.0)
                self.lbl_progress_status.configure(text=f"✓ Đã hoàn tất {success_cnt}/{len(results)} video!", text_color="#2EA44F")
                self.btn_direct_start.configure(state="normal", text="🚀 TẠO VIDEO NGAY")
                self.btn_csv_start.configure(state="normal")
                self.is_processing = False
                messagebox.showinfo("Thành công", f"Đã sinh xong {success_cnt}/{len(results)} video!\nVideo lưu tại: {self.config.get('output_dir', 'outputs')}")

            self.after(0, on_complete)

        except Exception as e:
            self.log(f"❌ Lỗi tiến trình: {e}")
            def on_error():
                self.lbl_progress_status.configure(text=f"❌ Thất bại: {e}", text_color="#E53935")
                self.btn_direct_start.configure(state="normal", text="🚀 TẠO VIDEO NGAY")
                self.btn_csv_start.configure(state="normal")
                self.is_processing = False
                messagebox.showerror("Lỗi Tiến Trình", f"Có lỗi xảy ra: {e}")
            self.after(0, on_error)

if __name__ == "__main__":
    app = BOTSDDesktopApp()
    app.mainloop()
