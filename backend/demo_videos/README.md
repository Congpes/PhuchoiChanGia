# Hai mẫu điện thoại — 08/09/2026

Trong Scan, mở menu chọn nguồn video và chọn **Mẫu điện thoại 1** hoặc **Mẫu điện thoại 2**.
Hai video dùng chung nút phát/dừng và thanh tua, phát tốc độ thực 1×.

- `phone-01`: cặp file người dùng gửi lại với hậu tố `(1)`; nội dung trùng cặp đầu. Bản phát chung lấy 8 giây đầu mỗi góc, chưa xác định độ lệch quay.
- `phone-02`: cặp file `...19831...` và `...53019...`. Bản phát chung 8 giây, chính diện cắt đầu 0,65 giây theo căn thử âm thanh, góc ngang bắt đầu 0 giây. Chưa xác nhận khớp từng bước.

Mỗi thư mục giữ video đầy đủ trong `originals/` và `manifest.json` chứa tên nguồn, SHA-256, mốc cắt của bản phát. Không thay đổi file ở Downloads.

Chưa chạy phân tích, chưa lưu kết quả góc/bước chân và chưa gắn FSR. Khi phân tích sau, dùng video gốc, xác minh cùng lượt quay và mốc đồng bộ trước khi phối hợp hai góc. FSR từ lượt khác chỉ là dữ liệu tham chiếu, không phải đo đồng thời.

Các mẫu này không thay thế mẫu tham chiếu cũ, không thuộc hồ sơ bệnh nhân hiện tại và không dùng đường cong/khung xương có sẵn của mẫu cũ.
