# antigravity-human-control

[![Windows CI](https://github.com/Daosi-dev/agent-eye/actions/workflows/ci.yml/badge.svg)](https://github.com/Daosi-dev/agent-eye/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-cyan.svg)](LICENSE)

[English Documentation (README.md)](README.md)

**Skill điều khiển máy tính Windows & Trình duyệt tốc độ cao** dành cho **Antigravity**, **Codex CLI**, **Gemini CLI** và **Claude Code**.

Tổng hợp sức mạnh của cả **Computer Use** (nhìn màn hình + điều khiển chuột chính xác) lẫn **`agent-desktop`** (cây Accessibility + quản lý cửa sổ/ứng dụng), đồng thời khắc phục triệt để độ trễ qua **Warm Daemon chạy nền (`<10ms` IPC)**, **Bộ định tuyến thông minh 5 tầng**, **WinRT OCR (`~50ms`)** cho app tự vẽ giao diện (CapCut, Godot, Blender), **Lưới Thước Viền `1000×1000`**, **Kéo 1 mạch Bézier + Hậu kiểm bù sai số (`>4px`)**, và **Dán Clipboard Atomic chuẩn Tiếng Việt có dấu**.

---

## So Sánh Nhanh: Computer Use vs. `agent-desktop` vs. `antigravity-human-control`

| Tính năng | Computer Use (Chỉ nhìn ảnh) | `agent-desktop` (Chỉ UIA) | `antigravity-human-control` (Lai 5 Tầng) |
| :--- | :--- | :--- | :--- |
| **Chạy ngầm Browser / Hộp thoại** | Không (chiếm chuột thật) | Một phần (chậm khi Chromium settle) | **Có** (Tier 1 Raw CDP `<20ms` + Tier 2 `#32770` Fast-Path) |
| **Cây UIA & Quản lý cửa sổ** | Không | Có (`snapshot`, `launch`, `focus`, `close`) | **Có** (`windows`, `launch`, `focus`, `close`, `wait`, `clipboard`, `snapshot --mode auto\|tree\|vision`) |
| **App tự vẽ (CapCut, Godot, Game)** | Chậm (4–7s/lần gọi AI nhìn ảnh) | Lỗi / Rỗng (`UIA` không đọc được) | **Siêu nhanh** (`~50ms` Tier 2.5 WinRT OCR + Lưới Thước Viền `1000×1000`) |
| **Kéo thả thanh trượt / Timeline** | Kéo mù 1 lần dễ lệch | Khóa `mouse-down`/`drag` khi chạy ngầm | **Kéo 3 pha** (Bézier/Fitts + NCC hậu kiểm + micro-drag bù sai số `>4px`) |
| **Gõ Tiếng Việt có dấu** | Dễ lỗi dấu với UniKey | `set-value` hạn chế; `type` cần `--headed` | **Atomic UTF-16LE Clipboard Paste** (tự trả lại clipboard cũ) |
| **Tốc độ phản hồi lệnh** | Cao (chờ khởi động/LLM) | Trung bình | **Warm Daemon (`<10ms` IPC)** + gộp chuỗi `batch` |

---

## Cài Đặt 1 Chạm (Không cần quyền Admin)

```powershell
git clone https://github.com/Daosi-dev/agent-eye.git
cd agent-eye
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Gỡ cài đặt sạch sẽ:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

---

## Điều Khiển Cửa Sổ Quyền Administrator (Chuẩn UAC Windows)

Cơ chế bảo mật UIPI của Windows chặn tiến trình thường gửi input vào cửa sổ chạy quyền Administrator. Dự án **không** vượt quyền UAC ngầm mà giải quyết minh bạch theo chuẩn Windows:

- **Tách biệt Daemon theo mức quyền:** Phiên thường dùng `daemon_medium.json` + `session_medium.key`; phiên Administrator dùng `daemon_high.json` + `session_high.key` (khóa ACL chỉ cho phép Administrators và SYSTEM đọc).
- **Mở phiên Admin khi cần:** Khi gặp lỗi `ELEVATION_REQUIRED`, người dùng chạy lệnh sau để bật hộp thoại UAC chuẩn của Windows:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\open_elevated_shell.ps1
  ```

---

## Ví Dụ Sử Dụng Nhanh

```powershell
# Kiểm tra hệ thống & liệt kê cửa sổ đang mở
.\.venv\Scripts\python.exe scripts\cli.py doctor
.\.venv\Scripts\python.exe scripts\cli.py windows

# Mở app, focus, đợi chữ, đóng app an toàn
.\.venv\Scripts\python.exe scripts\cli.py launch --target "notepad.exe" --wait-title "Notepad"
.\.venv\Scripts\python.exe scripts\cli.py focus --title "Notepad"
.\.venv\Scripts\python.exe scripts\cli.py close --title "Notepad"

# Snapshot linh hoạt: auto (tự chọn UIA tree hoặc Vision) / vision / tree
.\.venv\Scripts\python.exe scripts\cli.py snapshot --mode auto --window "Notepad"
.\.venv\Scripts\python.exe scripts\cli.py snapshot --mode vision

# Click tự động chọn tầng nhanh nhất; kéo 1 mạch + hậu kiểm bù sai số
.\.venv\Scripts\python.exe scripts\cli.py click --text "Export" --title "CapCut"
.\.venv\Scripts\python.exe scripts\cli.py drag --x1 200 --y1 500 --x2 650 --y2 500

# Gõ tiếng Việt có dấu an toàn qua Atomic Clipboard
.\.venv\Scripts\python.exe scripts\cli.py type --text "Xin chào Việt Nam — Đắk Lắk!" --enter
```

Phát hành theo giấy phép [MIT License](LICENSE).
