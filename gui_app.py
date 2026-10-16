import os
import json
import time
import pandas as pd
import streamlit as st
from typing import List, Dict, Any

from botsd_api import BOTSDClient, BOTSDAPIError
from batch_processor import BatchVideoProcessor
from sheet_auth import authenticate_sub_user, record_user_consumption, fetch_users_from_sheet

# Cấu hình trang Streamlit
st.set_page_config(
    page_title="BOTSD Sub-Web Video Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E88E5;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.0rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
    .user-badge {
        background-color: #e3f2fd;
        border-left: 4px solid #1976d2;
        padding: 10px 15px;
        border-radius: 6px;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

CONFIG_FILE = "config.json"

def load_config() -> dict:
    default_config = {
        "api_base_url": "https://botsd.pro",
        "master_client_token": "",
        "google_sheet_url": "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit?usp=sharing",
        "output_dir": "outputs",
        "max_concurrent_jobs": 30,
        "poll_interval_seconds": 7,
        "retry_on_rate_limit": True
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
        except Exception:
            pass
    return default_config

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

config = load_config()

# Session states
if "sub_user" not in st.session_state:
    st.session_state["sub_user"] = None
if "master_balance" not in st.session_state:
    st.session_state["master_balance"] = None
if "master_user_id" not in st.session_state:
    st.session_state["master_user_id"] = None

# Master Client Connection
master_token = config.get("master_client_token", "").strip()
master_client = BOTSDClient(base_url=config.get("api_base_url", "https://botsd.pro"), client_token=master_token)

# ================= SIDEBAR: CẤU HÌNH ADMIN =================
with st.sidebar:
    st.image("https://img.icons8.com/color/96/video-editing.png", width=64)
    st.title("BOTSD Studio")
    st.caption("Hệ thống sinh Video AI đa luồng song song")
    st.markdown("---")

    with st.expander("🛠️ Cấu hình Engine & Admin", expanded=False):
        st.write("**1. Master BOTSD Token:**")
        new_master_token = st.text_input("Master clientToken", value=master_token, type="password", key="admin_master_token")
        
        if st.button("Kiểm tra Master Token", key="check_master_btn"):
            if new_master_token:
                try:
                    master_client.client_token = new_master_token
                    sess = master_client.get_session()
                    st.session_state["master_balance"] = sess.get("balance", 0)
                    st.session_state["master_user_id"] = sess.get("userId")
                    config["master_client_token"] = new_master_token
                    save_config(config)
                    st.success(f"✓ Hợp lệ! Balance BOTSD thực: {sess.get('balance')} Pts")
                except Exception as e:
                    st.error(f"Lỗi Token Master: {e}")

        if st.session_state["master_balance"] is not None:
            st.caption(f"Master Balance: **{st.session_state['master_balance']} Pts** | User ID: `{st.session_state['master_user_id']}`")

        st.markdown("---")
        st.write("**2. Thông số Engine:**")
        max_concurrent = st.number_input("Số luồng song song", min_value=1, max_value=200, value=config.get("max_concurrent_jobs", 30))
        poll_interval = st.number_input("Khoảng thời gian Poll (giây)", min_value=3, max_value=30, value=config.get("poll_interval_seconds", 7))
        output_folder = st.text_input("Thư mục xuất Video", value=config.get("output_dir", "outputs"))

        if (max_concurrent != config.get("max_concurrent_jobs") or 
            poll_interval != config.get("poll_interval_seconds") or 
            output_folder != config.get("output_dir")):
            config["max_concurrent_jobs"] = max_concurrent
            config["poll_interval_seconds"] = poll_interval
            config["output_dir"] = output_folder
            save_config(config)

# ================= MAIN CONTENT =================
st.markdown('<div class="main-title">🎬 BOTSD Video Studio</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Hệ thống sinh Video AI đa luồng song song tự động qua BOTSD API</div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 Batch Generator", "🎬 Video Gallery"])

# ---------- TAB 1: BATCH GENERATOR ----------
with tab1:
    st.subheader("1. Chuẩn bị danh sách Video")
    
    col_upload, col_template = st.columns([3, 1])
    with col_upload:
        uploaded_file = st.file_uploader("Upload file CSV hoặc Excel danh sách prompt", type=["csv", "xlsx"])
    with col_template:
        st.markdown("**File mẫu chuẩn:**")
        if os.path.exists("prompts_template.csv"):
            with open("prompts_template.csv", "rb") as f:
                st.download_button("📥 Tải CSV Mẫu", f, "prompts_template.csv", "text/csv", use_container_width=True)

    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith(".xlsx"):
                df_input = pd.read_excel(uploaded_file)
            else:
                df_input = pd.read_csv(uploaded_file)
        except Exception as e:
            st.error(f"Lỗi đọc file: {e}")
            df_input = pd.DataFrame()
    else:
        if os.path.exists("prompts_template.csv"):
            df_input = pd.read_csv("prompts_template.csv")
        else:
            df_input = pd.DataFrame(columns=[
                "output_name", "prompt", "seconds", "model", "ratio", "resolution", "real_person_mode", "real_person_deep_mode", "image_paths"
            ])
    df_input = df_input.fillna("").astype(str)

    st.write("✏️ **Chỉnh sửa danh sách prompt trực tiếp:**")
    edited_df = st.data_editor(
        df_input,
        num_rows="dynamic",
        column_config={
            "output_name": st.column_config.TextColumn("Tên File Xuất", required=True),
            "prompt": st.column_config.TextColumn("Prompt Mô Tả", required=True, width="large"),
            "seconds": st.column_config.SelectboxColumn("Thời lượng (s)", options=[5, 10, 15, 30], default=10),
            "model": st.column_config.SelectboxColumn("Model AI", options=["sd25", "sd20"], default="sd25"),
            "ratio": st.column_config.SelectboxColumn("Tỉ lệ", options=["9:16", "16:9", "1:1", "3:4", "4:3", "21:9"], default="9:16"),
            "resolution": st.column_config.SelectboxColumn("Độ phân giải", options=["original", "1080p", "1080p-real", "4k"], default="original"),
            "real_person_mode": st.column_config.CheckboxColumn("Chế độ Người thật", default=False),
            "real_person_deep_mode": st.column_config.CheckboxColumn("Người thật nâng cao", default=False),
            "image_paths": st.column_config.TextColumn("Đường dẫn ảnh tham chiếu (dấu ;)")
        },
        use_container_width=True,
        key="reseller_data_editor"
    )

    st.markdown("---")
    st.subheader("2. Khởi chạy Tiến trình")

    if st.button("🚀 Bắt Đầu Tạo Video Hàng Loạt", type="primary", use_container_width=True):
        if not config.get("master_client_token"):
            st.error("❌ Chưa cấu hình Master BOTSD Token. Vui lòng vào sidebar Cấu hình Admin để cài đặt.")
        elif edited_df.empty:
            st.warning("⚠️ Bảng prompt đang trống.")
        else:
            temp_csv = "temp_batch_prompts.csv"
            edited_df.to_csv(temp_csv, index=False)

            master_client.client_token = config["master_client_token"]
            processor = BatchVideoProcessor(master_client, config)

            progress_bar = st.progress(0, text="Khởi động tiến trình...")

            try:
                results = processor.run_batch(temp_csv)
                progress_bar.progress(100, text="✓ Hoàn tất!")
                st.balloons()
                st.success("🎉 Sinh video hoàn tất!")
                st.rerun()

            except Exception as e:
                st.error(f"Lỗi khi thực thi batch: {e}")

# ---------- TAB 2: VIDEO GALLERY ----------
with tab2:
    st.subheader("🎬 Thư Viện Video Của Bạn")
    out_dir = config.get("output_dir", "outputs")
    
    if not os.path.exists(out_dir):
        st.info(f"Chưa có thư mục output: `{out_dir}`")
    else:
        video_files = [f for f in os.listdir(out_dir) if f.endswith(".mp4")]
        if not video_files:
            st.info("Chưa có video nào trong thư mục xuất.")
        else:
            cols = st.columns(3)
            for idx, vid_name in enumerate(video_files):
                vid_path = os.path.join(out_dir, vid_name)
                col = cols[idx % 3]
                with col:
                    st.markdown(f"**📹 {vid_name}**")
                    with open(vid_path, "rb") as vf:
                        st.video(vf.read())
                    file_size_mb = os.path.getsize(vid_path) / (1024 * 1024)
                    st.caption(f"Dung lượng: {file_size_mb:.2f} MB")
                    with open(vid_path, "rb") as vf:
                        st.download_button(
                            label=f"⬇️ Tải {vid_name}",
                            data=vf,
                            file_name=vid_name,
                            mime="video/mp4",
                            key=f"dl_reseller_{vid_name}"
                        )
