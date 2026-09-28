# Hiệu chỉnh thử từng ô hai chân — 28/09/2026

## Cập nhật sau log đo lại

Mở trực tiếp `FSR_Transmitter_2.py`, chọn Newton: bộ hệ số hai chân đã được
nhúng vào file, không cần nạp JSON hay dùng file chạy riêng. `--no-calibration`
tắt hiệu chỉnh. File chạy hai chân cũ cũng dùng bộ nhúng mới; file chạy chỉ chân
phải vẫn nạp profile cũ nếu cần đối chiếu.

85 ô cũ giữ nguyên. 11 ô còn lại bù theo trung vị của các trung vị từng lượt
đặt riêng 1468 g trong `hiệu chỉnh 2 chân.jsonl`; nền lấy giây 8–25. Khoảng đo,
giá trị từng lượt và SHA nguồn lưu ngay trong `RETEST_CALIBRATION_AUDIT` và
chú thích trong transmitter. Không nhân hệ số lần hai vào Newton đã hiệu chỉnh.

Đã có hệ số thử cho 96 ô, KHÔNG có nghĩa 96 ô đạt chuẩn: các trung vị từng lượt
sau bù vẫn khoảng 11,10–17,44 N cho cùng quả 1468 g. Nền cũ không phải zero trong
giày. Cần kiểm chứng độc lập, nhất là phải H1C2, H2C4, H4C2, H5C4 và trái H11C2.

Các phần bên dưới mô tả bộ profile v1 và quy trình ban đầu, được giữ để truy vết.

## Cách chạy

Đóng cửa sổ transmitter cũ để giải phóng cổng COM, mở
`chay_fsr_hieu_chinh_hai_chan.bat` tại thư mục dự án, chọn đơn vị Newton.
Nếu chỉ muốn bật chân phải như trước, dùng `chay_fsr_hieu_chinh_phai.bat`.
Đây là chế độ opt-in, chỉ dùng đúng hai miếng đã ghi log và cùng cách lắp.
Chạy `FSR_Transmitter_2.py` bình thường không có tham số sẽ dùng công thức cũ.
Hai profile chọn theo đúng bên; bên không nạp profile giữ nguyên. Không đổi
mapping, ADC thô hay log gốc. Không áp lại hệ số khi phát
lại log đã chứa Newton. Backend nhận Newton giữ nguyên giá trị gói tin.

## Kết quả chân phải và giới hạn chung

- Log nguồn: `fsr_logs/chân phải log.jsonl`, 26.942 mẫu chân phải, khoảng 22 phút 17 giây.
- 40 ô có hệ số sơ bộ; 8 ô để `null`, vẫn dùng công thức cũ, KHÔNG coi đã chuẩn.
- Mốc chuẩn: 1468 g = 14,3961622 N. Không nhân thêm hệ số 2.619.
- Tính trên công thức Newton hiện tại từ ADC đã EMA; nền riêng từng ô lấy trung vị giây 1–6.
- Lực thử = max(0, lực công thức cũ − nền) × hệ số ô.
- Trung vị đoạn dùng để khớp sẽ bằng mốc chuẩn theo định nghĩa. Đây KHÔNG phải
  bằng chứng độ chính xác trên lần đặt cân mới hoặc toàn dải tải.
- Đoạn chồng cân dùng tham chiếu danh định 333,3 g (~3,27 N); người đo chưa biết
  chính xác quả nào nên không dùng đoạn đó làm chuẩn tính gain.
- Sàng lọc thử: độ rộng P90−P10 đoạn đầu không quá 10% tín hiệu sau trừ nền,
  đáp ứng chồng cân lệch không quá 15% so với tải danh định. Đây là ngưỡng làm
  việc, không phải tiêu chuẩn nhà sản xuất hay chứng nhận độ chính xác.
- 40 ô còn lại có trung vị sau hiệu chỉnh khi chồng cân khoảng 15,99–20,10 N;
  chưa thể gọi là đo chính xác 17,67 N. Cần đo kiểm độc lập.
- Nền cũ không thay thế thao tác zero khi lắp giày. Nhiễu dương sau cắt về 0
  vẫn có thể cộng dồn; chưa giải quyết lọc nhiễu hoặc ép tổng hai chân theo cân nặng.
- Không áp bộ hệ số cho miếng lót khác. Chưa xác minh ID phần cứng tự động.
- `calibration_id` và `calibration_status` được ghi thêm trong log mới để truy vết;
  profile JSON có cửa sổ đo, hệ số và SHA-256 log nguồn.
- Gói UDP hiện chưa mang thông tin profile; bản ghi trong app chính không tự
  phân biệt được nguồn hiệu chỉnh thử. Khi kiểm chuẩn phải lưu log tại transmitter,
  không dùng kết quả thử làm kết luận lâm sàng.

## 8 ô chân phải cần đo lại

Đếm hàng từ trên xuống, cột từ trái sang phải trên bảng CHÂN PHẢI:

| Hàng | Cột | Lý do |
|---|---|---|
| 1 | 1 | Đoạn chồng cân sau bù lên ~21,79 N, không phù hợp mốc danh định |
| 1 | 2 | Bậc tải đầu ngắn, chưa tách chắc được lúc ổn định |
| 2 | 4 | Các đoạn đổi tải không tách rõ |
| 4 | 2, 3 | Có thêm cân thứ ba, nhiều bậc/dịch tải; giữ lại để đo xác nhận |
| 5 | 4 | Đáp ứng chồng cân sau bù ~21,36 N, không phù hợp mốc danh định |
| 10 | 3 | Dịch tải/đặt lại và lực biến thiên |
| 10 | 4 | Lực trôi liên tục, bậc thêm cân không rõ |

## Kết quả chân trái

- Log nguồn: `fsr_logs/chân trái log.jsonl`, 24.684 mẫu chân trái, khoảng 27 phút 21 giây.
- Người đo xác nhận vẫn dùng cân cũ; mốc tính là 1468 g, đoạn chồng quả nhỏ
  chỉ dùng sàng lọc danh định giống chân phải, không coi là mốc cân đã xác minh.
- 45/48 ô có hệ số sơ bộ; 3 ô để `null`, vẫn dùng công thức cũ.
- Nền riêng chân trái lấy trung vị giây 1–6 trong chính log chân trái.
- Hệ số bù các ô bật thử khoảng 0,966–1,870; không sao chép từ chân phải.
- Trung vị đoạn chồng cân sau bù của các ô bật thử khoảng 15,67–19,42 N,
  chưa phải bằng chứng chính xác ở mức tải thứ hai.
- Tổng hai bên: 85 ô bật thử, 11 ô chưa hiệu chỉnh. Chưa thể kết luận tổng lực đã chuẩn.

Các ô CHÂN TRÁI cần đo lại (đếm trực tiếp theo bảng hiển thị, không tự đảo cột):

| Hàng | Cột | Lý do |
|---|---|---|
| 1 | 1 | Đoạn đầu ngắn, khó chọn bậc 1468 g đủ ổn định |
| 1 | 3 | Sau bù, đoạn chồng cân ~20,78 N, vượt ngưỡng sàng lọc danh định |
| 11 | 2 | Nhiều bậc và lực biến thiên, chưa tách chắc lúc chỉ có 1468 g |

## Bước tiếp theo với người đo

1. Kiểm tra vài ô đã hiệu chỉnh bằng quả 1468 g: H1C3, H2C3, H5C3, H12C4.
   Đây là danh sách chân phải. Với chân trái, thử H1C2, H2C1, H5C2, H12C4.
   Nhấc ra đặt lại 3 lần; không dùng cùng đoạn log để tuyên bố chính xác.
2. Đo lại 8 ô phải và 3 ô trái ở trên: không tải → chỉ 1468 g → nhấc hết. Chưa cần quả nhỏ.
   Giữ mỗi mức khoảng 10 giây, cùng vị trí và điểm tì, lặp 3 lần.
3. Ghi rõ thứ tự ô, thời điểm và tên log. Không đổi cách lắp giữa các lượt.
4. Nếu đổi miếng hoặc lắp trong giày, không dùng nền cũ để kết luận lực tuyệt đối.

## Tái tạo

Chạy `backend/venv/Scripts/python.exe backend/analyze_right_calibration_20260928.py`
từ thư mục dự án. Script chỉ sinh lại profile, không sửa log nguồn. Cửa sổ đo là
khoảng thời gian đã xem xét cho riêng log này, không phải nhận dạng cân tự động.

Với chân trái, chạy `backend/venv/Scripts/python.exe backend/analyze_left_calibration_20260928.py`.
Mỗi script kiểm SHA-256 của log nguồn trước khi sinh profile, không dùng các cửa sổ
này cho log khác. Tái tạo profile chân phải sau khi bổ sung chân trái không đổi hệ số cũ.
