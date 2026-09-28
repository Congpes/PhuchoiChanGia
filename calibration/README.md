# Hiệu chỉnh thử chân phải — 28/09/2026

## Cách chạy

Đóng cửa sổ transmitter cũ để giải phóng cổng COM, mở
`chay_fsr_hieu_chinh_phai.bat` tại thư mục dự án, chọn đơn vị Newton.
Đây là chế độ opt-in, chỉ dùng đúng miếng chân phải đã ghi log và cùng cách lắp.
Chạy `FSR_Transmitter_2.py` bình thường không có tham số sẽ dùng công thức cũ.
Không thay đổi chân trái, mapping, ADC thô hay log gốc. Không áp lại hệ số khi phát
lại log đã chứa Newton. Backend nhận Newton giữ nguyên giá trị gói tin.

## Kết quả và giới hạn

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

## 8 ô cần đo lại

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

## Bước tiếp theo với người đo

1. Kiểm tra vài ô đã hiệu chỉnh bằng quả 1468 g: H1C3, H2C3, H5C3, H12C4.
   Nhấc ra đặt lại 3 lần; không dùng cùng đoạn log để tuyên bố chính xác.
2. Đo lại 8 ô ở trên: không tải → chỉ 1468 g → nhấc hết. Chưa cần quả nhỏ.
   Giữ mỗi mức khoảng 10 giây, cùng vị trí và điểm tì, lặp 3 lần.
3. Ghi rõ thứ tự ô, thời điểm và tên log. Không đổi cách lắp giữa các lượt.
4. Nếu đổi miếng hoặc lắp trong giày, không dùng nền cũ để kết luận lực tuyệt đối.

## Tái tạo

Chạy `backend/venv/Scripts/python.exe backend/analyze_right_calibration_20260928.py`
từ thư mục dự án. Script chỉ sinh lại profile, không sửa log nguồn. Cửa sổ đo là
khoảng thời gian đã xem xét cho riêng log này, không phải nhận dạng cân tự động.
