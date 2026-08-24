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
backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
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
flutter run -d chrome --no-web-resources-cdn
```

Phải khởi động backend trước frontend để các luồng MJPEG và API ở cổng `8000` sẵn sàng.

## 5. Chạy trong quá trình phát triển

Khi Flutter đang chạy, đặt con trỏ vào terminal Flutter và dùng:

- `r`: hot reload cho thay đổi giao diện đơn giản.
- `R`: hot restart khi sửa import, state khởi tạo, `main()`, HTML platform view hoặc luồng camera.
- `q`: dừng ứng dụng.

Nhấn `F5` trong Chrome chỉ tải lại bản JavaScript đã biên dịch gần nhất; nó không biên dịch lại mã Dart.

Không chạy `flutter clean` thường xuyên. Lệnh này xóa cache và khiến lần build tiếp theo lâu hơn. Chỉ dùng khi cache build thực sự bị lỗi.

## 6. Cấu hình và đồng bộ hai camera

Backend khởi động trước nhưng chỉ mở camera sau khi người dùng chọn thiết bị trong màn hình Scan:

- Camera chính diện: đặt ngang tầm hông, vuông góc hướng đi; cung cấp nghiêng chậu và số đo mặt phẳng trán.
- Camera mặt phẳng dọc: đặt ngang tầm hông, quay ngang 90 độ; cung cấp góc gập hông, gối và cổ chân.
- Hai camera chạy ở `640 × 480`, mục tiêu `30 FPS`; backend ghép khung theo timestamp với sai lệch tối đa `40 ms`.

Nhãn `SYNC xx ms` trên Tab Scan chuyển xanh khi hai camera cùng thấy pose và ghép được khung. Không mở đồng thời Zoom, Teams, Camera hoặc phần mềm khác đang chiếm webcam.

Nếu chỉ có một camera, chọn chế độ một camera trong hộp cấu hình. Hệ thống vẫn cho xem và ghi dữ liệu 2D nhưng không coi đó là kết quả stereo 3D.

### Hiệu chuẩn stereo 3D

1. Mở `http://127.0.0.1:8000/camera/calibration/board` và in A4 ngang ở `Actual size 100%`.
2. Đo một ô vuông, kích thước phải đúng `30 mm`.
3. Trong Tab Scan chọn `HIỆU CHUẨN 3D`.
4. Giữ bảng nghiêng khoảng 45 độ để cả hai camera cùng nhìn thấy; chụp ít nhất 12 vị trí và góc khác nhau.
5. Chọn `Tính calibration`. Calibration chỉ được dùng khi đúng cặp camera và sai số RMS đạt ngưỡng.

Không di chuyển camera sau khi hiệu chuẩn. Nếu camera bị xê dịch, thực hiện hiệu chuẩn lại.

## 7. Kết nối FSR

Backend tự tìm cổng Bluetooth serial chiều đi ra, đọc khung `LL`/`RR` ở `9600 baud` và chuyển ADC sang Newton cho phần phân tích. Có thể cấu hình thủ công trước khi chạy:

```powershell
$env:FSR_SERIAL_PORTS="COM4,COM6"
$env:FSR_SERIAL_BAUDRATE="9600"
backend\venv\Scripts\python.exe backend\main.py
```

Heatmap dùng ADC để giữ độ tương phản cảm biến; PeakFore và FSI dùng ma trận lực Newton. Nếu mới cắm một chân thì API chỉ báo bên đó kết nối, đây là hành vi bình thường.

## 8. Chạy nhanh trên Windows

Có thể dùng hai script ở thư mục gốc:

- `chay_backend.bat`
- `chay_frontend_nhanh.bat`

Script frontend đã tắt tải tài nguyên Flutter từ CDN để tránh lỗi `Failed to fetch` khi mạng chặn `gstatic.com`.

## 9. Khắc phục sự cố

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

## 10. Kiểm thử trước khi commit

```powershell
backend\venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py"
cd frontend_app
flutter analyze
flutter test
```
