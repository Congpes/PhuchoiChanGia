# Hướng dẫn cài đặt và chạy AI-ProGait

Tài liệu này hướng dẫn cài dự án trên một máy Windows mới, chạy FastAPI backend, Flutter Web frontend và cấu hình camera.

## 1. Yêu cầu hệ thống

Cài đặt các công cụ sau:

- Git.
- Python 3.10.
- Flutter SDK 3.44.4 hoặc phiên bản tương thích.
- Google Chrome.
- Webcam và quyền truy cập camera trên Windows.

Kiểm tra môi trường:

```powershell
git --version
python --version
flutter doctor
```

## 2. Clone dự án

Clone trực tiếp branch `Cong`:

```powershell
git clone -b Cong --single-branch https://github.com/Congpes/PhuchoiChanGia.git
cd PhuchoiChanGia
```

## 3. Cài đặt backend lần đầu

Môi trường ảo `backend/venv` không được lưu trên Git. Mỗi máy chỉ cần tạo và cài dependency một lần:

```powershell
python -m venv backend\venv
backend\venv\Scripts\python.exe -m pip install --upgrade pip
backend\venv\Scripts\python.exe -m pip install fastapi==0.139.0 uvicorn==0.50.0 opencv-contrib-python==5.0.0.93 mediapipe==0.10.9 numpy==2.2.6 scipy==1.15.3
```

Khởi động backend:

```powershell
backend\venv\Scripts\python.exe backend\main.py
```

Backend chạy tại:

```text
http://127.0.0.1:8000
```

Kiểm tra nhanh API và camera:

```text
http://127.0.0.1:8000/status
http://127.0.0.1:8000/video_feed_1
```

Luôn dùng Python trong `backend/venv`. Lệnh `python backend/main.py` có thể báo thiếu `cv2` nếu Python hệ thống chưa được cài dependency.

## 4. Cài đặt frontend lần đầu

Mở một terminal khác tại thư mục dự án:

```powershell
cd frontend_app
flutter pub get
flutter run -d chrome
```

Phải khởi động backend trước frontend để các luồng MJPEG và API ở cổng `8000` sẵn sàng.

## 5. Chạy trong quá trình phát triển

Khi Flutter đang chạy, đặt con trỏ vào terminal Flutter và dùng:

- `r`: hot reload cho thay đổi giao diện đơn giản.
- `R`: hot restart khi sửa import, state khởi tạo, `main()`, HTML platform view hoặc luồng camera.
- `q`: dừng ứng dụng.

Nhấn `F5` trong Chrome chỉ tải lại bản JavaScript đã biên dịch gần nhất; nó không biên dịch lại mã Dart.

Không chạy `flutter clean` thường xuyên. Lệnh này xóa cache và khiến lần build tiếp theo lâu hơn. Chỉ dùng khi cache build thực sự bị lỗi.

## 6. Chế độ một camera hiện tại

Backend mặc định chạy chế độ một camera:

- Camera laptop ở index `0`.
- Camera laptop là nguồn MediaPipe phân tích dáng đi.
- Hai endpoint `/video_feed_0` và `/video_feed_1` tạm dùng chung nguồn hình.
- OpenCV sử dụng DirectShow trên Windows để tránh lỗi MSMF không mở được webcam.

Không mở đồng thời Zoom, Teams, ứng dụng Camera hoặc phần mềm khác đang chiếm webcam.

## 7. Chuyển sang hai camera sau này

Khi đã gắn đủ hai camera, cấu hình trong PowerShell trước khi chạy backend:

```powershell
$env:SINGLE_CAMERA_MODE="false"
$env:CAMERA_FRONTAL_INDEX="0"
$env:CAMERA_SAGITTAL_INDEX="1"
backend\venv\Scripts\python.exe backend\main.py
```

Quy ước:

- Camera frontal: quay chính diện, dùng đánh giá cân bằng và độ nghiêng xương chậu.
- Camera sagittal: quay ngang 90 độ, dùng phân tích hông, gối và cổ chân.

Nếu thứ tự camera trên máy khác nhau, đổi hai giá trị index và chạy lại backend.

## 8. Khắc phục sự cố

### Backend báo `No module named cv2`

Đang dùng sai Python. Chạy lại bằng:

```powershell
backend\venv\Scripts\python.exe backend\main.py
```

### Camera không hiển thị

1. Kiểm tra backend còn chạy.
2. Mở trực tiếp `http://127.0.0.1:8000/video_feed_1` trên Chrome.
3. Đóng các ứng dụng khác đang sử dụng webcam.
4. Kiểm tra quyền camera trong Windows Settings.
5. Hot restart Flutter bằng `R` thay vì chỉ nhấn F5 trên Chrome.

### Flutter chạy lần đầu rất lâu

- Lần build Flutter Web đầu tiên có thể mất vài phút.
- Giữ terminal chạy và dùng hot reload/hot restart.
- Không chạy `flutter pub get` lại nếu `pubspec.yaml` không thay đổi.
- Không xóa thư mục `build` hoặc `.dart_tool` nếu không có lỗi cache.

### Máy mới không có dữ liệu bệnh nhân

Đây là hành vi bình thường. File SQLite là dữ liệu runtime cục bộ và không được đẩy lên Git. Backend sẽ tạo database mới khi khởi động lần đầu.
