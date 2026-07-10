# Hướng dẫn khởi chạy hệ thống AI-ProGait

Tài liệu này hướng dẫn cách chạy song song Python Backend (MediaPipe Pose analysis) và Flutter Frontend (Giao diện phân tích dáng đi).

---

## 1. Khởi chạy Backend (Python FastAPI)

Backend chịu trách nhiệm mở Webcam, nhận dạng khung xương bằng AI (MediaPipe), tính toán góc khớp thời gian thực và cung cấp dữ liệu qua API.

1. Mở Terminal mới tại thư mục dự án.
2. Di chuyển vào thư mục `backend`:
   ```powershell
   cd backend
   ```
3. Khởi chạy máy chủ trực tiếp bằng python trong môi trường ảo (không cần bước activate):
   ```powershell
   .\venv\Scripts\python main.py
   ```
   *Khi chạy thành công, Terminal sẽ hiển thị dòng thông báo `🎥 Webcam capture thread started successfully.` và chạy ở cổng `http://127.0.0.1:8000`.*

---

## 2. Khởi chạy Frontend (Flutter Web)

Frontend chịu trách nhiệm hiển thị giao diện phân tích dáng đi kiểu phòng Lab, vẽ đồ thị so sánh góc khớp và đưa ra khuyến nghị điều chỉnh.

1. Mở một cửa sổ Terminal khác tại thư mục dự án.
2. Di chuyển vào thư mục `frontend_app`:
   ```powershell
   cd frontend_app
   ```
3. Khởi chạy ứng dụng trên trình duyệt Chrome:
   ```powershell
   flutter run -d chrome
   ```
   *Trình duyệt Chrome sẽ tự động mở trang ứng dụng dạng Web App.*

---

## 3. Các lưu ý & Khắc phục sự cố

### ⚠️ Lỗi camera sáng đèn nhưng màn hình đen
* **Nguyên nhân**: Do camera đang bị khóa bởi ứng dụng khác (ví dụ: Chrome chiếm dụng camera trước khi Python khởi động, hoặc có một tiến trình Python cũ chạy ngầm chưa tắt).
* **Giải quyết**: 
  1. Tắt hết các tab Chrome chạy ứng dụng.
  2. Mở Task Manager hoặc gõ lệnh sau ở PowerShell để tắt tiến trình Python cũ:
     ```powershell
     Stop-Process -Name python -Force
     ```
  3. Chạy lại Backend (`python main.py`) trước, sau đó mới khởi động Frontend trên Chrome.

### ⚠️ VS Code báo lỗi gạch đỏ ở các lệnh `import` trong `main.py`
* **Nguyên nhân**: VS Code đang dùng trình biên dịch Python của Windows thay vì môi trường ảo `venv`.
* **Giải quyết**: 
  1. Nhấn `Ctrl + Shift + P` (hoặc `F1`) để mở thanh lệnh trong VS Code.
  2. Gõ và chọn: **`Python: Select Interpreter`**.
  3. Chọn đường dẫn có chứa chữ **`venv`** (ví dụ: `.\venv\Scripts\python.exe`).
