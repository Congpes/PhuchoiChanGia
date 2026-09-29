# Hiệu chỉnh thử từng ô hai chân — 28/09/2026

## Zero đế / giày trong phiên đo

- Mặc định **Zero hết**: mang lót/giày, ngồi vững và nhấc cả hai chân khỏi sàn,
  thả lỏng, bấm nút rồi xác nhận. Có nút **Zero chân trái/phải** để làm riêng.
  Đừng đứng chịu tải khi lấy zero: phần mềm không thể phân biệt một tải tĩnh
  với lực ép nền. Lấy lại zero khi thay đổi cách mang/lắp giày.
- Thu khoảng 3 giây; cần ít nhất 20 mẫu mỗi bên, trải ít nhất 2,5 giây, không
  gián đoạn quá 0,5 giây. Zero hết yêu cầu đủ hai bên; lỗi không áp dụng nửa chừng.
- Nền mỗi ô là trung vị lực Newton đã hiệu chỉnh. Lực hiển thị/gửi/log là
  phần tăng so với nền, không âm. ADC và hệ số hiệu chuẩn gốc không thay đổi.
- Ngưỡng nhiễu từng ô = max(0,02 N, phân vị mẫu 95% độ lệch tuyệt đối quanh
  trung vị); dưới ngưỡng hiển thị 0, trên ngưỡng giữ đầy đủ phần lực tăng.
  Không cập nhật nền tự động khi chân đang đè. Đây là lọc thử, có thể mất lực
  rất nhẹ dưới ngưỡng; cần kiểm tra với dữ liệu giày thật.
- Sàng lọc ổn định thử nghiệm: khoảng P90–P10 mỗi ô không vượt max(1 N,
  20% nền), và chênh trung vị hai nửa không vượt max(0,3 N, 10% nền).
  Những ngưỡng này không chứng minh zero đúng hay độ chính xác lực.
- Nút chính thành **Huỷ zero** khi đang thu hoặc bất kỳ bên nào đã zero.
  Bấm sẽ huỷ toàn bộ nền/ngưỡng và về lực trước zero, không mất ADC/log cũ.
  Đóng/ngắt/kết nối lại FSR, đổi đơn vị hoặc EMA đều huỷ zero để lấy lại.
- Zero chỉ dùng dữ liệu FSR trực tiếp ở Newton; không dùng dữ liệu gửi thử
  hay áp lại cho log phát lại. Log giữ ADC gốc, ADC đã lọc, nền/ngưỡng và
  `zero_applied`, `zero_revision`, `zero_collecting` của chính mẫu đó.
  Dữ liệu trong lúc thu zero vẫn gửi với cờ đang thu; không bắt đầu phiên
  phân tích bước đi cho tới khi lấy zero thành công.

Test thực tế: kiểm tra trạng thái khi nhấc chân, đè rồi nhấc lại, thử riêng
từng chân, cuối cùng bấm Huỷ zero. Lưu log để kiểm tra độ trôi và lực nhẹ;
zero không thay thế hiệu chuẩn tải và không đảm bảo tổng lực đứng đã đúng.

## Cập nhật 29/09: thử ba mốc cho 18 ô chân phải

Mở trực tiếp `FSR_Transmitter_2.py` từ thư mục dự án và chọn Newton, không cần
nạp JSON. Đóng transmitter cũ trước khi mở lại. Profile phải đang dùng là
`right-20260929-three-point-v4`; trái giữ nguyên. Không cần file chạy riêng.

- Phạm vi: H1C1 đến H6C2, **trừ H2C1, H2C3, H5C4, H6C1**. Bốn ô này và các
  ô ngoài phạm vi giữ nguyên hệ số trước lần sửa này, không phải đã đạt chuẩn.
- Nguồn `fsr_logs/check.jsonl`; SHA-256 và cửa sổ từng mức lưu tại
  `RIGHT_THREE_POINT_20260929` trong transmitter. Tính từ ADC đã lọc qua công
  thức gốc rồi trừ nền cũ, không lấy Newton đã hiệu chỉnh để nhân bù lần nữa.
- Nội suy qua (0, 0), mốc quả 1468 g = 14,3961622 N và mốc chồng quả nhỏ
  khoảng 333,3 g = 17,664718645 N. Quả nhỏ chưa xác minh chính xác khối lượng.
  Nền cũ được giữ nguyên; đây **không phải zero mới trong giày**.
- Trên mốc cao nhất: tiếp tục tăng liên tục theo hệ số cũ, không chặn hoặc ép
  về số cân. Cả vùng ngoại suy lẫn vùng tải thấp chưa được kiểm chứng độc lập.
- Đoạn lấy quả nhỏ ra không dùng khớp đường cong; 18 ô có trung vị đoạn này
  lệch không quá 1 N so với quả lớn. Đây chỉ là sàng lọc trong cùng chu kỳ,
  không chứng minh độ chính xác khi đặt lại, đi bộ hay tổng lực người đứng.

Test lại: không tải → quả lớn → chồng quả nhỏ → lấy quả nhỏ ra → nhấc hết;
giữ mỗi mức khoảng 8–10 giây, giữ cách đặt và điểm tì nhất quán, lưu log mới.
Ưu tiên H1C1, H1C2, H4C3 rồi các ô còn lại; đo riêng bốn ô cần đo lại ở trên.
`--no-calibration` tắt hiệu chỉnh; cờ nạp JSON riêng vẫn dùng đúng profile đó.

Các mục bên dưới là lịch sử, không phải hướng dẫn chạy bộ ba mốc hiện tại.

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
