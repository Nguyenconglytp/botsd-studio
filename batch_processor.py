import os
import time
import pandas as pd
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table

from botsd_api import BOTSDClient, BOTSDAPIError
from sheet_auth import record_user_consumption
from app_paths import resolve_output_dir

console = Console()
logger = logging.getLogger("BatchProcessor")


import re

def build_character_image_map(char_dir: str) -> Dict[str, str]:
    """Tạo bảng tra cứu từ tên nhân vật (viết thường & chuẩn hóa) -> đường dẫn ảnh đầy đủ trong thư mục."""
    img_map = {}
    if not char_dir or not os.path.exists(char_dir):
        return img_map

    valid_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
    for root, _, files in os.walk(char_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts:
                filename_no_ext = os.path.splitext(f)[0].strip().lower()
                full_path = os.path.join(root, f)
                img_map[filename_no_ext] = full_path
    return img_map

def extract_character_names(char_cell_value: str, prompt_text: str = "") -> List[str]:
    """Trích xuất danh sách tên nhân vật từ ô Excel hoặc từ dòng CHARACTER: trong prompt."""
    names = []
    if char_cell_value and str(char_cell_value).strip():
        lines = re.split(r'[\r\n;,]+', str(char_cell_value))
        for line in lines:
            cleaned = line.strip()
            if cleaned and cleaned not in names:
                names.append(cleaned)

    if not names and prompt_text:
        match = re.search(r'CHARACTER:\s*([^\r\n]+)', prompt_text, re.IGNORECASE)
        if match:
            char_line = match.group(1).strip()
            items = re.split(r'[,;]+', char_line)
            for item in items:
                cleaned = item.strip()
                if cleaned and cleaned not in names:
                    names.append(cleaned)
    return names

def match_character_images(char_names: List[str], img_map: Dict[str, str]) -> List[str]:
    """Tìm kiếm ảnh tương ứng cho danh sách tên nhân vật từ img_map."""
    matched = []
    if not img_map or not char_names:
        return matched

    for name in char_names:
        raw_name = name.strip().lower()
        if not raw_name:
            continue
        
        # 1. Trận đấu chính xác
        if raw_name in img_map:
            path = img_map[raw_name]
            if path not in matched:
                matched.append(path)
            continue

        # 2. Trận đấu chuẩn hóa ký tự Alphanumeric
        norm_name = re.sub(r'[^a-z0-9]', '', raw_name)
        found = False
        for key, path in img_map.items():
            norm_key = re.sub(r'[^a-z0-9]', '', key)
            if norm_name and norm_name == norm_key:
                if path not in matched:
                    matched.append(path)
                found = True
                break

        # 3. Trận đấu chứa chuỗi (Partial Containment)
        if not found:
            for key, path in img_map.items():
                if raw_name in key or key in raw_name:
                    if path not in matched:
                        matched.append(path)
                    break
    return matched


import io

def read_prompts_dataframe(file_path: str) -> pd.DataFrame:
    """Đọc file CSV/Excel đa định dạng và tự động thử nhiều bảng mã (encoding) để tránh lỗi UnicodeDecodeError."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in ['.xlsx', '.xls']:
        try:
            return pd.read_excel(file_path)
        except Exception:
            try:
                return pd.read_excel(file_path, engine='openpyxl')
            except Exception:
                pass

    try:
        return pd.read_excel(file_path, engine='openpyxl')
    except Exception:
        pass

    with open(file_path, 'rb') as f:
        raw_bytes = f.read()

    # Ưu tiên mã UTF-8 và các bảng mã tiếng Trung (gb18030, gbk, gb2312, big5) trước các bảng mã Latin
    encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'gb2312', 'big5', 'cp1258', 'cp1252', 'latin-1']
    if raw_bytes.startswith(b'\xff\xfe') or raw_bytes.startswith(b'\xfe\xff') or b'\x00' in raw_bytes[:100]:
        encodings.insert(0, 'utf-16')
    else:
        encodings.extend(['utf-16', 'utf-16le', 'utf-16be'])

    for enc in encodings:
        try:
            text = raw_bytes.decode(enc)
            for sep_opt in [None, ',', ';', '\t']:
                try:
                    df = pd.read_csv(io.StringIO(text), sep=sep_opt, engine='python')
                    if df is not None and not df.empty and len(df.columns) >= 1:
                        return df
                except Exception:
                    pass
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            pass

    for fallback_enc in ['utf-8', 'gb18030', 'gbk', 'cp1258', 'cp1252', 'latin-1']:
        try:
            text = raw_bytes.decode(fallback_enc, errors='replace')
            for sep_opt in [None, ',', ';', '\t']:
                try:
                    df = pd.read_csv(io.StringIO(text), sep=sep_opt, engine='python')
                    if df is not None:
                        return df
                except Exception:
                    pass
        except Exception:
            pass

    raise ValueError(f"Không thể đọc file {os.path.basename(file_path)}. Vui lòng kiểm tra lại định dạng file Excel/CSV.")


class BatchVideoProcessor:
    def __init__(self, api_client: BOTSDClient, config: Dict[str, Any]):
        self.api_client = api_client
        self.config = config
        self.output_dir = resolve_output_dir(config.get("output_dir", ""))
        self.max_concurrent = config.get("max_concurrent_jobs", 30)
        self.poll_interval = config.get("poll_interval_seconds", 7)
        self.retry_on_429 = config.get("retry_on_rate_limit", True)
        os.makedirs(self.output_dir, exist_ok=True)

    def load_prompts_file(self, file_path: str, ref_char_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Đọc danh sách prompt từ file CSV hoặc Excel và tự động ghép ảnh nhân vật tham chiếu."""
        df = read_prompts_dataframe(file_path)
        df = df.fillna('')

        # Xử lý ghép ảnh nhân vật tham chiếu từ thư mục
        char_dir = ref_char_dir or self.config.get("ref_char_dir", "")
        img_map = build_character_image_map(char_dir)

        # Mapping linh hoạt các tên cột Excel
        def get_col_val(row, candidates, default=""):
            for cand in candidates:
                for col in row.index:
                    if str(col).strip().lower() == cand.strip().lower():
                        return row[col]
            for cand in candidates:
                for col in row.index:
                    if cand.strip().lower() in str(col).strip().lower():
                        return row[col]
            return default

        tasks = []
        for idx, row in df.iterrows():
            output_name_val = get_col_val(row, ['output_name', 'tên output', 'tên ouput', 'ten output', 'output', 'stt', 'video_name'], '')
            output_name = str(output_name_val).strip() or f"video_{idx+1:03d}"

            prompt_val = get_col_val(row, ['prompt', 'câu lệnh', 'mô tả', 'nội dung', 'script'], '')
            prompt = str(prompt_val).strip()
            if not prompt:
                continue

            def_seconds = int(self.config.get("default_seconds", 10))
            def_model = str(self.config.get("default_model", "sd25")).strip() or "sd25"
            def_ratio = str(self.config.get("default_ratio", "9:16")).strip() or "9:16"
            def_resolution = str(self.config.get("default_resolution", "original")).strip() or "original"
            def_real_person = bool(self.config.get("default_real_person", False))
            def_real_person_deep = bool(self.config.get("default_real_person_deep", False))

            override = self.config.get("override_with_ui_defaults", False)

            sec_val = get_col_val(row, ['seconds', 'thời lượng', 'thoi luong', 'giây'], str(def_seconds))
            seconds = def_seconds if override else (int(sec_val) if str(sec_val).isdigit() and int(sec_val) > 0 else def_seconds)

            model_val = get_col_val(row, ['model', 'model ai'], def_model)
            model = def_model if override else (str(model_val).strip() or def_model)

            ratio_val = get_col_val(row, ['ratio', 'tỉ lệ', 'ti le', 'khung hình'], def_ratio)
            ratio = def_ratio if override else (str(ratio_val).strip() or def_ratio)

            res_val = get_col_val(row, ['resolution', 'độ phân giải', 'do phan giai', 'chất lượng'], def_resolution)
            resolution = def_resolution if override else (str(res_val).strip() or def_resolution)

            rp_val = get_col_val(row, ['real_person_mode', 'người thật', 'nguoi that'], '')
            if override or str(rp_val).strip() == '':
                real_person = def_real_person
            else:
                real_person = str(rp_val).lower() in ['true', '1', 'yes', 'có', 'x']

            rpd_val = get_col_val(row, ['real_person_deep_mode', 'người thật nâng cao', 'nguoi that nang cao'], '')
            if override or str(rpd_val).strip() == '':
                real_person_deep = def_real_person_deep
            else:
                real_person_deep = str(rpd_val).lower() in ['true', '1', 'yes', 'có', 'x']

            img_paths_raw = str(get_col_val(row, ['image_paths', 'ảnh tham chiếu', 'anh tham chieu'], '')).strip()
            image_paths = [p.strip() for p in img_paths_raw.split(';') if p.strip()] if img_paths_raw else []

            # NẾU chưa có image_paths trực tiếp, TỰ ĐỘNG KHỚP ảnh từ thư mục ảnh nhân vật!
            if not image_paths and img_map:
                char_col_val = str(get_col_val(row, ['nhân vật tham chiếu', 'tên nhân vật tham chiếu', 'tên nhân vật', 'nhân vật', 'characters', 'character', 'char'], '')).strip()
                char_names = extract_character_names(char_col_val, prompt)
                matched_images = match_character_images(char_names, img_map)
                if matched_images:
                    image_paths = matched_images
                    logger.info(f"✓ Task #{idx+1} ('{output_name}'): Tự động ghép {len(matched_images)} ảnh nhân vật ({', '.join(char_names)})")

            tasks.append({
                "index": idx + 1,
                "output_name": output_name,
                "prompt": prompt,
                "seconds": seconds,
                "model": model,
                "ratio": ratio,
                "resolution": resolution,
                "real_person_mode": real_person,
                "real_person_deep_mode": real_person_deep,
                "image_paths": image_paths
            })
        return tasks

    def process_single_task(self, task: Dict[str, Any], progress: Progress = None, task_id: Any = None, update_cb = None, log_cb = None) -> Dict[str, Any]:
        """Thực thi một task từ tạo job -> poll trạng thái -> tải file video."""
        out_filename = f"{task['output_name']}.mp4" if not task['output_name'].endswith('.mp4') else task['output_name']
        save_path = os.path.join(self.output_dir, out_filename)
        
        def notify(pct: float, desc: str):
            if progress and task_id is not None:
                try:
                    progress.update(task_id, description=desc)
                except Exception:
                    pass
            if update_cb:
                try:
                    update_cb(task.get("index", 1), pct, desc)
                except Exception:
                    pass

        result = {
            "index": task["index"],
            "output_name": task["output_name"],
            "prompt": task["prompt"],
            "seconds": task["seconds"],
            "model": task["model"],
            "job_id": None,
            "cost": 0,
            "status": "FAILED",
            "saved_path": None,
            "error_message": None
        }

        # Stagger nhẹ 0.3s giữa các worker để tránh bị ngắt socket kết nối khi gửi song song
        stagger_delay = ((task.get("index", 1) - 1) % max(1, self.max_concurrent)) * 0.3
        if stagger_delay > 0:
            time.sleep(stagger_delay)

        # 1. Tạo task (Thử lại liên tục khi gặp lỗi kết nối/mạng/API cho tới khi thành công)
        notify(0.1, f"Sending task #{task['index']} ({task['output_name']})...")
        create_res = None
        retry_count = 0
        
        while True:
            try:
                create_res = self.api_client.create_video(
                    prompt=task["prompt"],
                    seconds=task["seconds"],
                    model=task["model"],
                    ratio=task["ratio"],
                    resolution=task["resolution"],
                    real_person_mode=task["real_person_mode"],
                    real_person_deep_mode=task["real_person_deep_mode"],
                    image_paths=task["image_paths"]
                )
                if retry_count > 0:
                    msg = f"✓ Gửi task '{task['output_name']}' thành công sau {retry_count} lần thử lại!"
                    notify(0.15, msg)
                    if log_cb:
                        log_cb(msg)
                break
            except BOTSDAPIError as e:
                err_msg = str(e).lower()
                # Kiểm tra các lỗi không thể thử lại (Fatal: không đủ point, token hỏng)
                if e.status_code in [400, 401, 403] and ("không đủ point" in err_msg or "point" in err_msg or "token" in err_msg or "unauthorized" in err_msg):
                    err_txt = f"Lỗi tạo task: {e}"
                    result["error_message"] = err_txt
                    notify(1.0, f"❌ Task #{task['index']} thất bại: {e}")
                    if log_cb:
                        log_cb(f"❌ Task '{task['output_name']}' thất bại do lỗi tài khoản/point: {e}")
                    return result
                
                retry_count += 1
                wait_time = e.retry_after if (e.status_code == 429 and e.retry_after) else 5
                log_msg = f"⚠️ [Lần {retry_count}] Task '{task['output_name']}' gửi lỗi API ({e}). Đang thử lại sau {wait_time}s..."
                notify(0.1, f"⚠️ Đang thử lại lần {retry_count} sau {wait_time}s...")
                if log_cb:
                    log_cb(log_msg)
                logger.warning(log_msg)
                time.sleep(wait_time)
            except Exception as e:
                retry_count += 1
                wait_time = 5
                log_msg = f"⚠️ [Lần {retry_count}] Task '{task['output_name']}' lỗi kết nối ({e}). Đang thử lại sau {wait_time}s..."
                notify(0.1, f"⚠️ Đang thử lại lần {retry_count} sau {wait_time}s...")
                if log_cb:
                    log_cb(log_msg)
                logger.warning(log_msg)
                time.sleep(wait_time)

        job_data = create_res.get("job", {})
        job_id = job_data.get("id") or job_data.get("taskId")
        result["job_id"] = job_id
        result["cost"] = job_data.get("cost", 0)

        if not job_id:
            result["error_message"] = "Không nhận được job.id từ phản hồi API"
            notify(1.0, f"❌ Task #{task['index']} thất bại: No job.id")
            if log_cb:
                log_cb(f"❌ Task '{task['output_name']}' không nhận được job.id từ API")
            return result

        notify(0.3, f"Job: {job_id[:14]}... Generating GPU")

        # 2. Polling trạng thái
        while True:
            time.sleep(self.poll_interval)
            try:
                status_res = self.api_client.poll_job_status(job_id)
                job_info = status_res.get("job", {})
                
                if job_info.get("failed"):
                    err_msg = job_info.get("message", "Tạo video thất bại.")
                    result["error_message"] = err_msg
                    notify(1.0, f"❌ Task #{task['index']} thất bại: {err_msg}")
                    return result
                
                if job_info.get("completed") and job_info.get("videoReady"):
                    notify(0.8, f"Task #{task['index']} ready! Downloading...")
                    break
                
                status_msg = job_info.get("message") or job_info.get("status") or "Generating"
                notify(0.5, f"Generating: {status_msg}")

            except BOTSDAPIError as e:
                if e.status_code == 429 and self.retry_on_429:
                    time.sleep(e.retry_after or 10)
                    continue
                else:
                    logger.warning(f"Lỗi khi poll job {job_id}: {e}")
            except Exception as e:
                logger.warning(f"Ngoại lệ khi poll job {job_id}: {e}")

        # 3. Tải video (với retry khi gặp lỗi kết nối/tải file)
        dl_retry = 0
        while True:
            try:
                downloaded_file = self.api_client.download_video(job_id, save_path)
                result["status"] = "SUCCESS"
                result["saved_path"] = downloaded_file
                
                # Ghi nhận trừ quota cho sub_user
                sub_user = task.get("sub_username") or self.config.get("current_sub_username")
                if sub_user and result["cost"] > 0:
                    record_user_consumption(sub_user, result["cost"])

                notify(1.0, f"✓ Completed! Saved {out_filename}")
                break
            except Exception as e:
                dl_retry += 1
                if dl_retry > 10:
                    result["error_message"] = f"Lỗi tải video: {e}"
                    notify(1.0, f"❌ Task #{task['index']} error downloading file")
                    if log_cb:
                        log_cb(f"❌ Task '{task['output_name']}' tải file thất bại sau {dl_retry} lần thử lại: {e}")
                    break
                notify(0.9, f"⚠️ Thử lại tải file (lần {dl_retry})...")
                if log_cb:
                    log_cb(f"⚠️ Task '{task['output_name']}' lỗi tải file ({e}). Đang thử lại lần {dl_retry}...")
                time.sleep(5)

        return result


    def run_tasks_list(self, tasks: List[Dict[str, Any]], log_callback=None, task_update_callback=None) -> List[Dict[str, Any]]:
        """Chạy xử lý đa luồng song song (ThreadPoolExecutor) cho danh sách task dicts."""
        if not tasks:
            return []

        max_workers = min(len(tasks), self.max_concurrent)
        if log_callback:
            log_callback(f"⚡ Bắt đầu thực thi {len(tasks)} task song song (Đa luồng {max_workers} workers)...")

        results = []
        
        class DummyProgress:
            def update(self, *args, **kwargs):
                pass

        progress = DummyProgress()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {}
            for t in tasks:
                if log_callback:
                    log_callback(f"🚀 [Đa luồng] Gửi task '{t['output_name']}'...")
                future = executor.submit(self.process_single_task, t, progress, 0, task_update_callback, log_callback)
                future_to_task[future] = t

            for future in as_completed(future_to_task):
                t_info = future_to_task[future]
                try:
                    res = future.result()
                    results.append(res)
                    if log_callback:
                        if res.get("status") == "SUCCESS":
                            log_callback(f"✓ Task '{res['output_name']}' hoàn tất! Saved: {res.get('saved_path')}")
                        else:
                            log_callback(f"❌ Task '{res['output_name']}' thất bại: {res.get('error_message')}")
                except Exception as e:
                    logger.error(f"Lỗi task '{t_info.get('output_name')}': {e}")
                    results.append({
                        "index": t_info.get("index", 1),
                        "output_name": t_info.get("output_name", "task"),
                        "prompt": t_info.get("prompt", ""),
                        "status": "FAILED",
                        "error_message": str(e)
                    })

        self.export_report(results)
        return results


    def run_batch(self, file_path: str) -> List[Dict[str, Any]]:
        """Chạy xử lý hàng loạt tất cả task trong file."""
        tasks = self.load_prompts_file(file_path)

        if not tasks:
            console.print("[bold red]Không có task hợp lệ nào để xử lý![/bold red]")
            return []

        console.print(f"\n[bold green]Bắt đầu chạy batch với {len(tasks)} video (Tối đa {self.max_concurrent} luồng song song)...[/bold green]\n")

        results = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console
        ) as progress:

            main_task_id = progress.add_task("[bold blue]Tổng tiến độ", total=len(tasks))
            
            with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
                future_to_task = {}
                for t in tasks:
                    sub_task_id = progress.add_task(f"Task #{t['index']}: Khởi tạo...", total=100)
                    future = executor.submit(self.process_single_task, t, progress, sub_task_id)
                    future_to_task[future] = (t, sub_task_id)

                for future in as_completed(future_to_task):
                    task_info, sub_task_id = future_to_task[future]
                    try:
                        res = future.result()
                        results.append(res)
                        if res["status"] == "SUCCESS":
                            progress.update(sub_task_id, completed=100)
                        else:
                            progress.update(sub_task_id, completed=100)
                    except Exception as e:
                        logger.error(f"Lỗi ngoài dự kiến ở Task #{task_info['index']}: {e}")
                        results.append({
                            "index": task_info["index"],
                            "output_name": task_info["output_name"],
                            "prompt": task_info["prompt"],
                            "seconds": task_info["seconds"],
                            "model": task_info["model"],
                            "status": "FAILED",
                            "error_message": str(e)
                        })
                    finally:
                        progress.advance(main_task_id)

        self.export_report(results)
        self.print_summary_table(results)
        return results

    def export_report(self, results: List[Dict[str, Any]]):
        """Xuất file báo cáo kết quả chi tiết."""
        report_path = os.path.join(self.output_dir, "batch_report.csv")
        df_report = pd.DataFrame(results)
        df_report.to_csv(report_path, index=False, encoding='utf-8-sig')
        console.print(f"\n[bold green]Đã xuất báo cáo chi tiết tại:[/bold green] {report_path}")

    def print_summary_table(self, results: List[Dict[str, Any]]):
        """Hiển thị bảng tổng kết trên terminal."""
        table = Table(title="TỔNG KẾT BATCH TẠO VIDEO")
        table.add_column("#", style="cyan", justify="right")
        table.add_column("Tên file", style="magenta")
        table.add_column("Job ID", style="dim")
        table.add_column("Trạng thái", justify="center")
        table.add_column("Chi phí (Point)", justify="right")
        table.add_column("Đường dẫn / Ghi chú lỗi", style="yellow")

        success_count = 0
        total_cost = 0

        for r in sorted(results, key=lambda x: x["index"]):
            is_success = r["status"] == "SUCCESS"
            status_str = "[bold green]THÀNH CÔNG[/bold green]" if is_success else "[bold red]THẤT BẠI[/bold red]"
            if is_success:
                success_count += 1
                total_cost += r.get("cost", 0)
                note = r.get("saved_path") or ""
            else:
                note = r.get("error_message") or "Unknown error"

            table.add_row(
                str(r["index"]),
                r["output_name"],
                str(r.get("job_id") or "N/A"),
                status_str,
                str(r.get("cost", 0)),
                note
            )

        console.print(table)
        console.print(f"\n[bold yellow]Hoàn tất {success_count}/{len(results)} video | Tổng chi phí: {total_cost} Points[/bold yellow]\n")
