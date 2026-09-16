# G2-00 — Hướng dẫn đo đường nền hiệu năng

Mục tiêu của phép đo là ghi lại đúng cấu hình đang chạy và tách riêng tốc độ,
thời gian xử lý của camera, pose, preview JPEG, ghi video và FSR. Báo cáo chỉ
chứa số đo vận hành; không ghi tên hoặc thông tin định danh bệnh nhân.

## Chuẩn bị

1. Chạy backend và frontend như bình thường.
2. Kết nối đủ camera và hai bàn FSR sẽ dùng trong thực tế.
3. Mở cả hai preview camera trong ứng dụng.
4. Bắt đầu một phiên ghi thử. Đi đều trong vùng đo trong ít nhất 90 giây.

Nếu không mở preview, báo cáo sẽ không có mục `preview.*`. Nếu không bật ghi
hình, báo cáo sẽ không có mục `archive.*.write`. Đây là dữ liệu thiếu thật, công
cụ không tự điền số giả.

## Chạy phép đo 90 giây

Mở một cửa sổ PowerShell thứ hai tại thư mục dự án rồi chạy:

```powershell
cd backend
.\venv\Scripts\python.exe capture_performance_baseline.py --duration 90
```

Công cụ sẽ đặt lại bộ đếm, lấy mẫu mỗi giây và lưu một tệp JSON vào thư mục
`output`. Thư mục này được bỏ qua bởi Git vì đây là kết quả riêng của từng máy.

Muốn lưu vào vị trí cụ thể:

```powershell
.\venv\Scripts\python.exe capture_performance_baseline.py `
  --duration 90 `
  --output D:\du-lieu-do\g2-00-lan-1.json
```

Nên thực hiện ít nhất ba lần với cùng cấu hình. Không đổi độ phân giải, FPS,
chất lượng JPEG, cổng COM hoặc baudrate giữa các lần.

## Nội dung báo cáo

- `runtimeConfiguration`: hệ điều hành, Python, cấu hình camera/pose/preview,
  profile camera yêu cầu lẫn profile thiết bị thực trả về, FPS ghi hình đang
  dùng, ánh xạ camera, cổng/transport FSR, baudrate và tần số FSR kỳ vọng.
- `stages.camera.*.read`: FPS đọc camera, thời gian đọc và khoảng cách khung.
- `stages.camera.*.pose_inference`: FPS pose, thời gian suy luận và độ trễ từ
  lúc nhận khung camera.
- `stages.preview.*`: FPS preview, thời gian resize/JPEG và độ trễ từ camera.
- `stages.archive.*.write`: FPS ghi, thời gian ghi và độ trễ từ camera.
- `resources`: CPU của tiến trình và RAM working set theo median/p95/max.
- `fsr.bySide`: tần số thực nhận, khoảng cách mẫu, số mẫu mất ước tính và số
  payload liên tiếp giống nhau.
- `fsr.bySource`: tổng byte, kích thước chunk/datagram, số frame giải mã và số
  byte trung bình trên một frame cho từng nguồn serial/UDP. Nguồn serial còn có
  `uartComparison` để đối chiếu kích thước quan sát được với dung lượng lý
  thuyết của UART 8N1 tại baudrate đang cấu hình.

Mỗi nhóm thời gian có `median`, `p95` và `max`. FPS được tính bằng đồng hồ
monotonic để việc đổi giờ hệ thống không làm sai kết quả.

## Giới hạn cần ghi trong kết luận

Đường direct serial hiện tại không gửi sequence number. Đường UDP từ hai bản
transmitter trong dự án có `sequence` và `timestamp_ms`, nên công cụ ưu tiên
dùng các trường đó để đếm thiếu/lặp chính xác theo toàn thiết bị. Hai chân dùng
chung một bộ đếm sequence, nên nếu có gói mất thì chưa thể kết luận gói đó thuộc
chân trái hay chân phải; FPS và khoảng mẫu vẫn được báo riêng từng chân. Với
direct serial:

- `inferredMissingFrameCount` chỉ là ước tính từ khoảng cách thời gian so với
  20 Hz; nếu một lần đọc Bluetooth chứa nhiều frame thì giá trị này để `null`
  kèm lý do, vì batching có thể tạo khoảng trống giả;
- `consecutivePayloadRepeatCount` chỉ phát hiện payload liên tiếp giống hệt và
  có thể xảy ra khi người đo đứng yên;
- `averageWireBytesPerFrame` là tổng byte nhận chia cho số frame giải mã, không
  phải kích thước gói do firmware khai báo.

Không được dùng ba giá trị direct serial này như bằng chứng chắc chắn về
mất/trùng gói. Muốn kết luận chính xác trên direct serial, firmware cần bổ sung
sequence number và timestamp lấy mẫu.
So sánh UART cũng chỉ là ước tính dung lượng; cần kiểm tra thêm cách firmware
phát dữ liệu và cơ chế đệm/chuyển tiếp Bluetooth trước khi kết luận nút thắt.

## API phục vụ kiểm tra nhanh

- `GET /diagnostics/performance`: xem báo cáo hiện tại.
- `POST /diagnostics/performance/reset`: đặt lại toàn bộ cửa sổ đo.

Chỉ đánh dấu G2-00 hoàn tất sau khi đã lưu bảng cấu hình, ba lần đo phần cứng,
bộ dữ liệu tham chiếu và tiêu chí chấp nhận có số cụ thể.
