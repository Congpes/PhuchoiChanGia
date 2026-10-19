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
- Mặc định yêu cầu hai camera `1280 × 720`, MJPG, `20 FPS` (có fallback theo thiết bị); nhận diện Pose model Full/1 rộng `640`, mục tiêu `12 FPS` mỗi camera. Backend ghép khung theo timestamp với sai lệch tối đa `40 ms`.

Nhãn `SYNC xx ms` trên Tab Scan chuyển xanh khi hai camera cùng thấy pose và ghép được khung. Không mở đồng thời Zoom, Teams, Camera hoặc phần mềm khác đang chiếm webcam.

Nếu chỉ có một camera, chọn chế độ một camera trong hộp cấu hình. Hệ thống vẫn cho xem và ghi dữ liệu 2D nhưng không coi đó là kết quả stereo 3D.

### Hiệu năng cụm camera (cập nhật 19/10/2026)

- Chạy giao diện bằng `chay_frontend_nhanh.bat`: mặc định dùng bản `--release` để xem/ghi; mục phát triển ở trên vẫn dùng debug để hot reload.
- Xem trước mặc định rộng tối đa `854` pixel, giới hạn `15 FPS`, JPEG quality `78`. Ảnh gốc ghi lại và đầu vào tính góc không bị giảm theo kích thước xem trước. Scan có xương chỉ cập nhật khi có kết quả Pose mới, tối đa theo tốc độ nhận diện, không đảm bảo 15 khung khác nhau/giây.
- Backend dùng chung JPEG cho các lượt xem cùng một khung; bỏ việc sao chép khung cũ khi chờ, và giảm sao chép ở nhận diện/ghi hình. Màn Scan ẩn bỏ widget camera trực tiếp; video phát lại giữ cơ chế hiện tại. Cần kiểm tra việc đóng kết nối MJPEG của trình duyệt khi chuyển tab trên máy thật.
- Có thể khôi phục phần xem trước cũ trước khi mở backend bằng các biến `CAMERA_STREAM_WIDTH=1280`, `CAMERA_STREAM_FPS=20`, `CAMERA_STREAM_JPEG_QUALITY=84`. Các biến chỉ ảnh hưởng phiên backend mới.

Thử phần xem trước trên máy i5-6200U, 8 GB: 20 khung 720p/góc từ `phone-01`, hai góc và hai lượt xem/góc (80 lượt nhận), ba lượt luân phiên, OpenCV một luồng, bỏ thời gian chờ FPS. Số lần nén giảm 80→40, số lần sao chép ảnh ở đường phát giảm 80→0, dữ liệu multipart giảm 8.650.624→3.752.118 byte (~57%). CPU đo được chỉ giảm khoảng 3%; đây không phải phép đo FPS camera thật. Thử riêng hai mô hình Full đồng thời đạt khoảng 12–14 lượt/giây mỗi góc khi chưa có USB, vẽ, ghi và xem trước. Lite nhanh hơn nhưng bỏ sót thêm người trong góc chính diện của đoạn thử, nên chưa đổi mô hình mặc định.

Khi cắm đủ hai webcam ngoài, mở một lượt xem mỗi góc, thử đứng yên rồi di chuyển và lưu báo cáo 90 giây:

```powershell
backend\venv\Scripts\python.exe backend\capture_performance_baseline.py --duration 90
```

Đối chiếu `/camera-status` và `/diagnostics/performance`: FPS đọc camera, suy luận, pose đáng tin, độ trễ nén, CPU và FPS ghi; xem cả khi bắt đầu ghi video. `preview.*` giờ đếm lần nén duy nhất theo **slot vật lý** (trước đổi vai trò); lượt dùng chung JPEG nằm trong `runtimeConfiguration.previewMeasurement.jpegCache`. Bộ đếm cache tính từ lúc mở backend, không reset theo báo cáo. Chỉ số backend không đo thời điểm trình duyệt thực sự vẽ ảnh. Ngày thử tối ưu chưa cắm cụm webcam ngoài, nên chưa xác nhận hết lag trên thiết bị thật.

### Xử lý Scan trực tiếp (bổ sung 19/10/2026)

Scan lấy hướng dẫn nghiêng thân từ `/gait/lateral-trunk-feedback`, tránh chạy lại toàn bộ phân tích chu kỳ chỉ để lấy một dòng hướng dẫn. Phép thử 360 mẫu giả lập/30 giây, 10 lần gọi không dùng cache, cho trung vị khoảng 37,3 ms với đường phân tích cũ và 0,8 ms với đường mới, cùng kết quả hướng dẫn. Đây là thời gian của tác vụ này, không phải FPS nhận diện hoặc đo bằng webcam.

Hai worker Pose dùng RGB chỉ đọc. Báo cáo `/diagnostics/performance` bổ sung `camera.N.pose_pipeline` (chuẩn bị ảnh → nhận diện → tính/vẽ/ghép → công bố ảnh) và `camera.N.pose_postprocess` để phân biệt thời gian AI với phần xử lý sau. Timestamp capture được lấy ngay sau đọc ảnh, trước khi ghi chỉ số đo.

Ghép camera giữ giới hạn lệch thời điểm chụp 40 ms, nhưng cho kết quả nhận diện bên chậm tối đa 250 ms để tới trước khi trả mẫu thiếu bên. Kết quả mới của camera dọc không làm mất cặp cũ đang được camera trước xử lý. Timeout được kiểm tra khi vòng worker tiếp tục chạy, kể cả khi không nhận ra người; nếu hàm nhận diện/đọc bị treo, không bảo đảm deadline theo thời gian thực. Bộ đệm hữu hạn, hết chỗ sẽ trả mẫu thiếu bên thay vì âm thầm bỏ mẫu. Khi dừng ghi, các kết quả đã nhận nhưng còn chờ ghép được lưu một lần với trạng thái chất lượng tương ứng trước khi đóng dữ liệu. Việc này giảm mất cặp do thời gian suy luận khác nhau, không tăng tốc mô hình AI.

Có tuỳ chọn `CAMERA_POSE_GRAPH_THREADS=1` trước khi mở backend để giới hạn mỗi graph Pose còn một worker; `0` (mặc định) giữ bộ lập lịch gốc. Trạng thái hiển thị tại `posePipeline.graphThreads` và `runtimeConfiguration.poseGraphThreads`. Thử nhiều lượt trên máy Dell cho tốc độ dao động, chưa chứng minh giới hạn luồng luôn nhanh hơn nên chưa tự bật. So sánh 32 khung người thật từ hai video mẫu cho cùng landmark normalized/world giữa 0 và 1, nhưng không chứng minh độ chính xác sinh học. Mô hình Full, ngưỡng chất lượng và kích thước đầu vào vẫn giữ nguyên.

Helper giới hạn luồng dựa vào MediaPipe 0.10.9 trong requirements; cần kiểm tra lại khi nâng phiên bản. Asset mô hình phải có sẵn trong môi trường, thiếu sẽ báo lỗi tại máy thay vì tải ngầm lúc mở camera. Nếu thử cả hai cấu hình luồng, dùng cùng hai camera, ánh sáng, chuyển động và trạng thái ghi; lưu riêng báo cáo 90 giây. Chưa có phép đo cụm webcam ngoài trong lượt tối ưu này.

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
