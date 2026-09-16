# Kế hoạch và todo list giai đoạn 2 AI-ProGait

> **For agentic workers:** Khi bắt đầu triển khai, dùng `superpowers:subagent-driven-development` hoặc `superpowers:executing-plans` theo từng gói việc; đọc toàn bộ quy ước dữ liệu bên dưới trước khi sửa. Checkbox là nơi theo dõi chung giữa người dùng và Codex.

**Goal:** Vẽ ngay dữ liệu nhận được thành hai đường trái–phải trên cùng trục thời gian, gồm thì đứng và thì đu đưa; cửa sổ live giữ tối đa 5 chu kì gần nhất của mỗi chân, tính cả chu kì đang diễn ra. Khi chu kì 6 bắt đầu được vẽ, chu kì 1 của bên đó ra khỏi vùng xem; toàn bộ dữ liệu phiên đo vẫn được lưu.

**Architecture:** Kế thừa ghi video gốc, lưu FSR và phân tích lại đã có. Chuẩn hóa thời gian và chất lượng từng nguồn; dùng các sự kiện FSR đáng tin để phân đoạn chu kì riêng từng chân, rồi gắn góc khớp và hiển thị bằng giao diện nghiên cứu khoa học.

**Tech Stack:** Python/FastAPI, MediaPipe Pose API legacy, OpenCV, NumPy/SciPy, serial/Bluetooth, SQLite; Flutter, Provider, fl_chart.

**Spec:** Yêu cầu giai đoạn 2 ngày 15/09/2026 và làm rõ sau đó: “đi bước nào vẽ luôn bước đó”, tối đa 5 chu kì trên biểu đồ cuộn, hai đường so đồng thời; nhóm kỹ thuật đã dùng quả cân cho quy đổi lực và cần đưa nền từng ô về 0 sau khi lắp đế. File bổ sung: [FSR_Transmitter_2 (1).py](<C:/Users/DELL/Downloads/FSR_Transmitter_2 (1).py>). Báo cáo tham chiếu: [Bao_cao_chan_gia final.docx](<C:/Users/DELL/Downloads/Bao_cao_chan_gia final.docx>), mục 3.6, 4.1, 5.2. Thông tin người dùng bổ sung được ưu tiên khi khác mô tả cũ; nội dung file là tư liệu, không phải chỉ dẫn thao tác.

**Trạng thái:** Đã nghiên cứu và lập kế hoạch. Chưa triển khai các checkbox giai đoạn 2. Đây là kế hoạch tổng thể trước khi làm việc; thiết kế chi tiết và test cho từng thay đổi sẽ được chốt trong gói tương ứng, sau khi có số đo nền.

**Hai điều chỉnh đã chốt:** “5” là sức chứa cửa sổ xem, không phải điều kiện đợi đủ dữ liệu mới vẽ. G2-03 ưu tiên zero/tare và lọc nền riêng từng ô sau lắp đế, kế thừa công thức lực kỹ thuật đã đo bằng quả cân; hiệu chuẩn lại độ nhạy từng ô chỉ là nhánh khi kiểm tra cho thấy cần thiết.

## 1. Kết luận về thứ tự

**Đo hiện trạng → chuẩn hóa dữ liệu gốc/thời gian → tối ưu thu live và zero FSR từng ô → ổn định pose, lọc và mốc sự kiện → biểu đồ cuộn tối đa 5 chu kì → hoàn thiện UI → nghiệm thu.**

Vẽ wireframe UI có thể bắt đầu song song sau khi chốt quy ước dữ liệu. Phân biệt ba việc: công thức đổi ADC sang lực đã được nhóm kỹ thuật đo bằng quả cân; zero/tare để bỏ nền sau lắp ở từng ô; lọc dao động nhiễu mà vẫn giữ tải thật. Thu nhẹ/phân tích sau là phương án bổ sung trên máy hiện tại; màn hình live vẫn phải cập nhật ngay các kênh đo đang có.

| Mã | Ưu tiên | Gói việc | Phụ thuộc | Người thực hiện chính |
|---|---|---|---|---|
| G2-00 | P0 | Chốt mốc giai đoạn 1 và đo hiện trạng | Bắt đầu | Cả hai |
| G2-01 | P0 | Dữ liệu gốc, timestamp, nguồn và chất lượng | G2-00 | Codex; bạn xác nhận phần cứng |
| G2-02 | P0 | Ghi hai camera nhẹ trên máy hiện tại | Số đo G2-00, quy ước G2-01 | Codex + bạn chạy ca đo |
| G2-03 | P0 | Zero/tare từng ô sau lắp đế, kiểm tra quy đổi lực đã có | G2-01 | Bạn phối hợp kỹ thuật và đo nền; Codex làm công cụ |
| G2-04 | P0 | Pose theo khớp/chân và xử lý dữ liệu thiếu | G2-01, profile G2-02 | Codex + bạn chuẩn bị video |
| G2-05 | P0 | Lọc FSR, đồng bộ và mốc chạm/rời đất | G2-01; kiểm chứng với G2-02, G2-03 | Cả hai |
| G2-06 | P0 | Vẽ live hai đường, cuộn tối đa 5 chu kì mỗi chân | G2-01; mốc từ G2-05, góc từ G2-04 | Codex |
| G2-07 | P1 | UI/UX Pro Max cho Scan và phân tích | Wireframe sau G2-01; tích hợp sau G2-06 | Codex thiết kế; bạn duyệt thao tác |
| G2-08 | P1 | Nghiệm thu trên máy thật và tài liệu nghiên cứu | G2-02 đến G2-07 | Cả hai |

P0 là việc quyết định khả năng thu và tính đúng. P1 là việc bắt buộc hoàn thiện trước khi kết thúc giai đoạn, được triển khai sau hoặc song song theo phụ thuộc.

## 2. Những gì đã xác minh

Khảo sát bằng đọc báo cáo, mã nguồn, các test hiện có và thông tin cấu hình máy. Chưa chạy camera, chưa đo FPS thực, chưa chạy test ứng dụng và chưa kiểm chứng độ chính xác với tải chuẩn/video tham chiếu trong lượt lập kế hoạch này.

| Nhận xét | Căn cứ | Ý nghĩa cho kế hoạch |
|---|---|---|
| Báo cáo cũ chỉ khảo sát thì đứng và mô tả lực ước tính; người dùng bổ sung rằng kỹ thuật đã đo bằng quả cân | Báo cáo mục 4/5.2 và thông tin mới trong cuộc trò chuyện | Cập nhật nguồn công thức lực, xác nhận phạm vi phép đo đã làm; không mặc định phải hiệu chuẩn lại từ đầu |
| Máy đang dùng i5-6200U, 2 nhân/4 luồng, khoảng 8 GB RAM; Windows liệt kê Intel HD 520 và AMD R5 M335 | Đọc cấu hình hệ thống ngày 15/09/2026 | Chọn profile bằng phép đo trên máy này; chưa kết luận CPU là nguyên nhân duy nhất gây lag |
| Đã tách đọc camera và suy luận; có ghi video gốc và phân tích lại | [main.py](D:/Phuchochucnang/PhuchoiChanGia/backend/main.py:977), [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py:942) | Mở rộng chế độ ghi nhẹ trên nền hiện có |
| Cấu hình mặc định yêu cầu camera 1280×720/20 FPS; pose rộng 640, mục tiêu 12 FPS; archive có giới hạn mặc định 15 FPS | [main.py](D:/Phuchochucnang/PhuchoiChanGia/backend/main.py:60), [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py:489) | Phải đo riêng FPS yêu cầu, đọc, suy luận, ghi và preview; tài liệu cũ không phải cấu hình thực tế |
| Một góc không hợp lệ có thể khiến toàn bộ mẫu góc hai chân bị loại | [main.py](D:/Phuchochucnang/PhuchoiChanGia/backend/main.py:619) | Giữ dữ liệu hợp lệ theo từng khớp/chân |
| Offline đã đọc timestamp thật nhưng kiểm tra nhảy góc còn dùng khoảng thời gian theo FPS danh định | [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py:1020) | Dùng chênh lệch thời gian thực giữa các mẫu hợp lệ |
| FSR có baseline/lọc trong backend nhưng dùng công thức lực chung; file gửi thêm có hệ số scale chung 2.619 | [fsr_force.py](D:/Phuchochucnang/PhuchoiChanGia/backend/fsr_force.py:8), [file FSR bổ sung](<C:/Users/DELL/Downloads/FSR_Transmitter_2 (1).py:149>) | Giữ phép quy đổi đã có; phân biệt scale chung và zero riêng từng ô |
| Bản transmitter trong dự án không nhân scale bổ sung như file kỹ thuật gửi | [FSR_Transmitter_2.py](D:/Phuchochucnang/PhuchoiChanGia/FSR_Transmitter_2.py:158), [file FSR bổ sung](<C:/Users/DELL/Downloads/FSR_Transmitter_2 (1).py:154>) | Xác nhận bản đang dùng để thu; khi tích hợp phải bảo toàn đúng hệ số đã được kỹ thuật chọn và kiểm tra, tránh sai khác lực giữa các đường thu |
| File bổ sung lọc EMA từng ô nhưng chưa thấy ma trận nền tare hoặc thao tác zero sau lắp | [file FSR bổ sung](<C:/Users/DELL/Downloads/FSR_Transmitter_2 (1).py:507>) | Thêm đo/lưu/trừ nền sau lắp và ngưỡng nhiễu từng ô, không chỉ tăng mức làm mượt |
| Một đường transmitter gắn dữ liệu đã EMA vào trường raw; đường khác không gửi raw trong UDP; đơn vị N không tự mô tả nguồn hiệu chuẩn | [FSR_Transmitter.py](D:/Phuchochucnang/PhuchoiChanGia/FSR_Transmitter.py:833), [FSR_Transmitter_2.py](D:/Phuchochucnang/PhuchoiChanGia/FSR_Transmitter_2.py:243), [fsr_force.py](D:/Phuchochucnang/PhuchoiChanGia/backend/fsr_force.py:39) | Lưu raw và nguồn công thức/scale/zero trước khi thu bộ kiểm tra nền |
| Luồng đang chạy tạo các đoạn chuyển động; có helper contact→contact nhưng chưa được gọi trong runtime | [gait_cycle_pipeline.py](D:/Phuchochucnang/PhuchoiChanGia/backend/gait_cycle_pipeline.py:413), [gait_cycle_pipeline.py](D:/Phuchochucnang/PhuchoiChanGia/backend/gait_cycle_pipeline.py:542) | Không chỉ đổi nhãn hoặc tăng số cặp lên 5 |
| Scan đã có cuộn/phóng to nhưng vùng biểu đồ bị chia nhỏ; hộp mở rộng có kích thước cố định | [realtime_chart_workspace.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/realtime_chart_workspace.dart:1295), [realtime_chart_workspace.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/realtime_chart_workspace.dart:1559) | Thiết kế lại vùng vẽ và thao tác xem nhiều biểu đồ |
| Bộ định dạng nhãn có lược bỏ chữ “ước tính”; một số nhánh replay/demo biến đổi đường tham chiếu | [chart_labels.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/chart_labels.dart:1), [realtime_chart_workspace.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/realtime_chart_workspace.dart:882) | Giữ nhãn nguồn/hiệu chuẩn ở mọi chế độ xem; kiểm tra đường nghiên cứu không dùng số liệu mô phỏng |

Workspace đang có nhiều thay đổi chưa commit. Khi triển khai cần bảo toàn và tạo mốc riêng cho giai đoạn 1; không reset, ghi đè hoặc gom toàn bộ thay đổi sẵn có vào một commit của giai đoạn 2.

## 3. Quy ước chung cần giữ

1. **Một chu kì của một chân:** từ lần tiếp xúc ban đầu IC[n] đến IC[n+1] của chính chân đó. IC là lần bàn chân bắt đầu tiếp xúc, không bắt buộc gót chạm trước trong mọi kiểu dáng đi.
2. **Thì đứng:** IC → rời đất TO. **Thì đu đưa:** TO → IC kế tiếp. Tỉ lệ pha được đo từ sự kiện thực, không ép 60/40 hoặc 62/38.
3. **Cửa sổ cuộn tối đa 5 chu kì:** vẽ ngay từ mẫu hợp lệ đầu tiên, cả khi chưa có IC hoặc chỉ có một chân. Chu kì đang diễn ra cũng chiếm một vị trí trong 5 vị trí của bên đó. Ví dụ 1–5 đang hiện; ngay khi 6 bắt đầu, giữ 2–6 với 6 được vẽ dần. Không đợi chu kì hoàn tất, đủ 5 hoặc chân kia hoàn tất mới vẽ. Điều kiện “6 IC → 5 chu kì hoàn chỉnh” chỉ dùng xác nhận số chu kì hoàn tất cho thống kê.
4. **Liên tiếp theo thời gian:** điểm mới nối tiếp điểm cũ khi có dữ liệu hợp lệ, giữ đủ đứng/đu đưa và độ lệch trái–phải. Khoảng mất tín hiệu được giữ đúng vị trí trên trục X và ngắt đường, không co thời gian hoặc reset toàn bộ màn hình. Khi nhận lại dữ liệu thì vẽ tiếp ngay, không phải chờ thêm 5 chu kì.
5. **Hai đường trên cùng biểu đồ:** mỗi đại lượng có một đường trái và một đường phải, dùng chung thời gian phiên đo. Loại phần chu kì cũ khỏi vùng xem theo từng bên mà không dịch thời gian riêng của một chân; vùng nhìn bao các đoạn được giữ, có thể một đường bắt đầu muộn hơn đường kia. Khi mất tín hiệu/không rõ ranh giới, tiếp tục hiển thị dữ liệu còn có trong cửa sổ thời gian dự phòng hữu hạn, ghi chưa xác định số chu kì, không dựng mốc giả để ép đủ 5.
6. **Thiếu dữ liệu là null kèm lý do**, không tự biến thành 0, giá trị cuối, đường mẫu hoặc góc chân đối diện. Mất gói FSR không đồng nghĩa đang đu đưa.
7. **Nội suy là ước lượng có nhãn:** chỉ xem xét khoảng ngắn có hai đầu đáng tin, cùng chân và cùng đoạn liên tục. Không vượt qua IC/TO, đổi người/đổi chân, quay đầu hoặc khoảng mất dài. Chốt ngưỡng bằng video thử trước khi áp dụng; mặc định phân tích định lượng không tự chấp nhận điểm nội suy chưa được kiểm chứng.
8. **Tín hiệu FSR lúc đu đưa:** giữ số đo nền thực và trạng thái chất lượng; khi cảm biến xác nhận không tải có thể hiển thị gần 0 theo quy tắc đã kiểm chứng. Không bịa số 0 khi không nhận được mẫu.
9. **Cách nhìn chính và phụ:** mặc định là hai đường sóng liên tiếp trên trục thời gian chung, cuộn tối đa 5 chu kì mỗi chân. So một chu kì 0–100% hoặc Mean ± SD là chế độ phân tích bổ sung, không thay màn hình live và không ép hai chân cùng pha.
10. **Nguồn dữ liệu:** phân biệt ADC gốc, đã lọc, N ước tính, N đã hiệu chuẩn, giá trị nội suy và demo. Không đưa demo/đường tham chiếu vào số chu kì đo được hoặc thống kê nghiên cứu.
11. **Đơn vị và phạm vi đo:** phân biệt lực N với áp suất kPa; chưa công bố áp suất nếu chưa có diện tích cảm biến phù hợp. Giữ góc 2D và 3D tách biệt; camera chính diện không tự thay được góc gập 2D của camera ngang.
12. **Có thể tái lập:** lưu phiên bản thuật toán, cấu hình lọc, profile hiệu chuẩn, mapping ô, timestamp và nguồn dữ liệu của mỗi kết quả. Phân tích lại tạo phiên bản mới và bảo toàn bản ghi gốc.
13. **Zero sau lắp và nguồn hiệu chuẩn độc lập:** tiếp nhận thông tin kỹ thuật đã đo bằng quả cân; xác nhận dữ liệu/phạm vi để ghi nhãn phù hợp. Zero chỉ được lấy trong trạng thái không chịu tải cơ thể đã xác định; không tự học nền lúc đang đứng hoặc đi. Lưu đủ 96 nền riêng và trạng thái từng ô. Chu kì ra khỏi màn hình không bị xóa khỏi phiên ghi.

## 4. Các phương án đã cân nhắc

| Phương án | Lợi ích | Hạn chế | Đề xuất |
|---|---|---|---|
| Live nhẹ với hai đường cập nhật ngay; lưu gốc và phân tích lại khi cần | Đúng cách xem người dùng yêu cầu; có thể giảm preview/redraw để tiết kiệm máy | Cần đo tốc độ và chất lượng góc còn đạt trên máy hiện tại | Chọn làm hướng chính |
| Thu gốc, tạm dừng một phần hoặc toàn bộ pose, phân tích đầy đủ sau khi quay | Phương án dự phòng khi máy không đáp ứng góc live | Kênh pose tạm dừng phải báo rõ; chế độ này không đáp ứng xem góc khớp ngay | Chế độ bổ sung do người dùng chọn, không thay yêu cầu live |
| Chờ máy mới hoặc đổi ngay mô hình pose | Có thể tăng dư địa tính toán | Trì hoãn thu dữ liệu; không giải quyết hiệu chuẩn, sai mốc chu kì và nguồn dữ liệu | Đưa vào nhánh nâng cấp sau, không chặn giai đoạn này |

MediaPipe legacy cho phép đánh đổi độ phức tạp mô hình và thời gian suy luận, có lọc landmark tích hợp; vì thế cần kiểm tra cả độ chính xác và độ trễ khi giảm tải. [Tài liệu MediaPipe Pose](https://chuoling.github.io/mediapipe/solutions/pose.html).

## 5. Todo list chi tiết

### G2-00 — Mốc giai đoạn 1 và bộ đo hiện trạng

**Đầu ra:** bản kê cấu hình, bộ dữ liệu đối chứng, bảng hiệu năng ban đầu và tiêu chí đánh giá được chốt trước thử nghiệm tối ưu.

- [ ] **Codex:** lập danh sách thay đổi và cách lưu mốc giai đoạn 1; xác định bản ứng dụng/cấu hình thực sự dùng để đo.
- [ ] **Bạn:** xác nhận loại/mã camera, cổng USB/cách cắm, mã mảng FSR, firmware đang nạp, hai chân thật hay có chân giả trong từng ca.
- [ ] **Bạn:** xác nhận với kỹ thuật phép đo quả cân đã áp dụng cho từng ô, một ô đại diện hay tổng tấm; cung cấp bảng/hệ số nếu có, ý nghĩa scale 2.619 và trạng thái zero họ yêu cầu sau khi lắp đế.
- [ ] **Cả hai:** chọn các ca cố định: đứng yên, đi thẳng thấy đủ hai chân, giao chân/che một chân, dừng–đi lại, mất camera và mất FSR có chủ đích.
- [ ] **Codex:** đo riêng FPS đọc/ghi/pose/preview, CPU/RAM, thời gian đọc–suy luận–JPEG–ghi, độ trễ và khoảng trống dữ liệu; báo giá trị trung vị và p95.
- [ ] **Codex:** đo tần số FSR thực từng chân, kích thước gói, gói thiếu/lặp, thời gian nhận. Đối chiếu 20 Hz trong báo cáo với đường truyền 9600 baud; xác minh tốc độ UART thực/đặc điểm Bluetooth trước khi kết luận nghẽn.
- [ ] **Cả hai:** đánh dấu thủ công IC/TO trên video tham chiếu, kèm sai số do FPS và mức khó quan sát. Chọn một phần dữ liệu để chỉnh thuật toán và một phần độc lập để nghiệm thu.
- [ ] **Cả hai:** ghi giới hạn chấp nhận cho sai số lực, góc, mốc sự kiện và tỉ lệ mẫu hợp lệ theo mục tiêu nghiên cứu, dụng cụ tham chiếu và số đo nền. Chốt trước khi chọn cấu hình thắng cuộc.

**Xong khi:** có bộ ca tái lập và bảng số đo; mọi hạn chế chưa đo được được ghi rõ. Không lấy “nhìn có vẻ mượt” làm tiêu chí.

**Phạm vi mã khi triển khai:** bổ sung đo lường vào [main.py](D:/Phuchochucnang/PhuchoiChanGia/backend/main.py), [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py); lưu protocol/fixture riêng, dùng dữ liệu đã loại thông tin nhận diện khi đưa vào test.

### G2-01 — Chuẩn hóa dữ liệu gốc và hợp đồng dữ liệu

**Đầu ra:** một định nghĩa thống nhất cho mẫu camera, FSR, sự kiện, chu kì và chất lượng; tương thích bản ghi cũ.

- [ ] **Codex:** định nghĩa trường nguồn, thiết bị, chân, ô/kênh, phiên bản mapping, số thứ tự, thời gian thu nếu có, thời gian nhận và thời gian quy đổi về phiên đo. Dữ liệu không có timestamp thiết bị phải ghi là thời gian nhận, không gắn nhãn thời gian thu.
- [ ] **Codex:** bảo toàn ADC chưa lọc qua direct serial và cả hai transmitter; không đổi ý nghĩa trường raw để chứa EMA.
- [ ] **Codex:** tách đơn vị N, nguồn công thức do kỹ thuật hiệu chuẩn, phạm vi đã kiểm tra và trạng thái zero. Ghi nhận thông tin đã dùng quả cân; chỉ từ file mã không suy ra đã hiệu chuẩn riêng đủ 96 ô hoặc sai số cụ thể. Dữ liệu cũ giữ thông tin nguồn thật sự có.
- [ ] **Codex:** định nghĩa thiếu dữ liệu theo khớp/chân/ô và lý do; tách landmark gốc, tọa độ đã sửa nhận dạng và dự đoán chỉ để hiển thị.
- [ ] **Codex:** quy định timestamp tăng, xử lý gói trùng/đảo thứ tự/reset/reconnect; tạo đoạn liên tục mới khi không thể nối thời gian một cách tin cậy.
- [ ] **Codex:** lưu raw có thật hay không, công thức/scale, profile zero, lớp đã áp dụng zero, filter/mapping/algorithm version; không suy diễn raw từ N cũ, không nhân scale hoặc trừ nền hai lần khi transmitter đã xử lý.
- [ ] **Codex:** đối chiếu cùng raw và cấu hình lực giữa file kỹ thuật, transmitter dự án và direct serial; ghi rõ scale hiệu lực. Không tự bỏ hoặc nhân thêm 2.619 khi đổi đường thu; chỉ dùng hệ số đã xác nhận đúng với thiết bị và phạm vi đo.
- [ ] **Codex:** kiểm tra dữ liệu mẫu đi qua thu → lưu → phát lại; ma trận raw giữ nguyên, loại nguồn và chất lượng không đổi.

**Xong khi:** cùng một dữ liệu mẫu có cách hiểu duy nhất ở transmitter, backend, UI và replay; dữ liệu cũ vẫn mở được với nhãn đúng.

**Phạm vi:** [FSR_Transmitter.py](D:/Phuchochucnang/PhuchoiChanGia/FSR_Transmitter.py), [FSR_Transmitter_2.py](D:/Phuchochucnang/PhuchoiChanGia/FSR_Transmitter_2.py), [fsr_serial.py](D:/Phuchochucnang/PhuchoiChanGia/backend/fsr_serial.py), [fsr_force.py](D:/Phuchochucnang/PhuchoiChanGia/backend/fsr_force.py), [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py), [database.py](D:/Phuchochucnang/PhuchoiChanGia/backend/database.py), [gait_data.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/models/gait_data.dart).

### G2-02 — Hai camera dùng được trên máy hiện tại

**Đầu ra:** profile “Live nhẹ” đã đo thực tế, cập nhật ngay từng kênh đang có; thêm lựa chọn “Thu gốc, phân tích sau” có tiến độ/hủy và trạng thái kênh rõ ràng.

- [ ] **Codex:** kế thừa luồng đọc camera, MJPG, ghi gốc và offline hiện có; giảm suy luận/preview hợp lý cho live. Tạm dừng pose chỉ trong chế độ thu gốc riêng do người dùng chọn, không âm thầm thay thế góc live bằng đường cũ hoặc chặn FSR đang cập nhật.
- [ ] **Cả hai:** chạy ma trận hiệu năng ở mục 6; thay từng yếu tố một để phân biệt tải USB/đọc/ghi, pose và preview.
- [ ] **Codex:** giảm tần số/kích thước preview và nhịp cập nhật biểu đồ độc lập với nhịp thu; chỉ xử lý ảnh mới, giới hạn hàng đợi và ghi rõ khung bị bỏ.
- [ ] **Codex:** chọn độ phân giải/FPS camera từ các profile thiết bị hỗ trợ; kiểm tra còn nhìn rõ hông–gối–cổ chân–bàn chân. Không mặc định giảm xuống mức thấp nhất.
- [ ] **Codex:** xem lại điều kiện bắt đầu ghi theo chế độ; hiện capture dưới 12 FPS có thể bị chặn. Chỉ điều chỉnh khi đối chiếu với tiêu chí thời gian của nghiên cứu.
- [ ] **Codex:** xử lý offline một tác vụ mỗi lúc trên máy hiện tại; có tiến độ, hủy, lỗi dễ hiểu; lưu kết quả mới thành phiên bản riêng.
- [ ] **Cả hai:** chạy lặp và chạy liên tục 10 phút với profile được chọn; mở lại video và đối chiếu sidecar số khung/timestamp.

**Xong khi:** ghi hai camera và FSR không treo; thời gian không bị nén/lặp giả; mọi mất dữ liệu được báo. Mốc kỹ thuật đề xuất để thử: FPS ghi thực ≥90% mục tiêu profile đã chọn, không có xu hướng RAM tăng liên tục sau giai đoạn khởi động. Đây chưa phải bảo đảm độ chính xác sinh học; vẫn phải đạt tiêu chí thời gian ở G2-00.

**Phạm vi:** [main.py](D:/Phuchochucnang/PhuchoiChanGia/backend/main.py), [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py), [session_provider.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/providers/session_provider.dart), [tab_scan.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/tab_scan.dart), các widget video và điều khiển ghi hiện có.

### G2-03 — Zero/tare từng ô FSR sau lắp đế

**Đầu ra:** giữ quy đổi lực hiện có đã được kỹ thuật đo bằng quả cân; bổ sung mức nền và ngưỡng nhiễu riêng cho 48 ô mỗi chân, tổng 96 ô, kèm kiểm tra còn đo được tải thật.

**Phân biệt:** hiệu chuẩn lực xác định số ADC tương ứng bao nhiêu N. Tare xác định số đọc khi không chịu tải cơ thể trong cấu hình lắp hiện tại để đặt mốc 0. EMA làm mượt dao động theo thời gian; nó không tự trừ nền ổn định. Lót giày có thể tạo tiền tải cơ học; cần kiểm tra nền sau lắp và khi mang giày không tì chân theo protocol kỹ thuật, không mặc định hai trạng thái này giống nhau.

- [ ] **Bạn + Codex:** xác nhận mapping bằng ấn lần lượt ô thực; kiểm tra chân/hàng/cột và vùng giải phẫu. Mã LL/RR trong parser có phép đổi bên nên phải kiểm tra trên cảm biến thật.
- [ ] **Bạn:** lấy thông tin hiệu chuẩn quả cân đã có: dữ liệu/hệ số, dải tải, hiệu chuẩn ô nào hay tổng tấm, và ý nghĩa hệ số 2.619 trong file gửi thêm. Ô “khối lượng tham chiếu 55” trong giao diện chưa chứng minh có quy trình tự tính hệ số.
- [ ] **Cả hai:** chốt trạng thái lấy nền sau lắp: giày rỗng đã lắp cảm biến hay đang mang nhưng chân được đỡ và không tì đất. Thử hai trạng thái để biết phần tiền tải do lắp/mang; chọn một quy trình có thể lặp lại, tuyệt đối không lấy nền khi đang đứng chịu lực.
- [ ] **Codex:** thêm thao tác “Đưa từng ô về 0”: kiểm tra stream đủ, cho tín hiệu ổn định, thu nhiều mẫu, ước lượng nền và mức dao động cho từng ô; không dùng một mẫu tức thời hoặc một số bù chung cho cả tấm.
- [ ] **Codex:** thử bù trong miền lực: đặt g là quy đổi ADC→N đã gồm scale, dùng nền B của từng ô từ g(ADC) ở trạng thái không tải; xem F_bù = g(ADC) − B. Đây là phương án cần kiểm tra tải sau lắp, không tự coi là công thức lực chính xác đã được xác nhận. Không đưa ADC−baseline vào công thức phi tuyến g vốn nhận ADC tuyệt đối.
- [ ] **Codex:** giữ ADC gốc, lực trước bù và chênh lệch có dấu; chỉ đưa giá trị trong dải nhiễu quanh 0 về 0 ở đầu ra phù hợp. Độ lệch âm lớn phải báo nền không còn phù hợp, không che mọi sai lệch bằng clamp. Ngưỡng nhiễu chọn riêng từng ô và thử tải nhẹ thật để tránh lọc mất.
- [ ] **Codex:** lưu profile zero theo thiết bị/ô/mapping, công thức/scale, ngày và điều kiện lắp; freeze khi ghi phiên. Thay giày/lắp lại hoặc thay công thức/scale thì kiểm tra lại profile; nếu đủ raw có thể tính lại nền nhất quán, nếu không thì lấy nền mới. Không tự cập nhật nền lúc đi và không trừ nền hai lần.
- [ ] **Cả hai:** kiểm tra sau zero: không tải ở gần 0, đặt/nhả tải trở về nền, tải nhẹ vẫn thấy, IC/TO không bị trễ quá tiêu chí; đánh dấu ô chết/kẹt/nhiễu/bão hòa. Lặp ở vùng gót–giữa–trước và kiểm tra tổng tấm để phát hiện ô có độ nhạy lệch.
- [ ] **Cả hai, khi kiểm tra không đạt:** xác định lỗi lắp/nền hay sai độ nhạy. Chỉ khi cần mới hiệu chuẩn thêm từng ô bằng nhiều mức tải, dùng kết quả kiểm tra riêng để chọn hệ số; không mặc định thu lại toàn bộ đường lực của 96 ô ngay từ đầu.

**Xong khi:** mỗi ô có nền ổn định hoặc trạng thái không đạt rõ ràng; đầu ra không tải về 0 trong giới hạn nhiễu đã đo mà vẫn giữ tải thật; nguồn công thức lực và zero được lưu tách biệt, phiên cũ không bị ghi đè.

**Căn cứ:** [FSR Integration Guide, mục 7](https://www.interlinkelectronics.com/downloads/integration-guides/fsr-400-series-integration-guide.pdf) mô tả ảnh hưởng của điều kiện đặt tải/lắp cơ khí và hiệu chuẩn từng phần tử. Đây là tài liệu phương pháp tham khảo, không phải xác nhận loại mảng hoặc độ chính xác thiết bị đang dùng.

**Phạm vi:** tạo module đề xuất `backend/fsr_calibration.py` khi triển khai để quản lý nguồn quy đổi và profile zero; tích hợp các đường FSR ở G2-01, kiểm tra [file FSR kỹ thuật gửi](<C:/Users/DELL/Downloads/FSR_Transmitter_2 (1).py>) rồi chọn bản đưa vào dự án, không tự ghi đè các transmitter hiện có. Chưa tạo module hoặc chạy file đính kèm trong lượt chỉnh kế hoạch.

### G2-04 — Góc khớp ổn định và dữ liệu thiếu minh bạch

**Đầu ra:** luồng góc có chất lượng theo từng khớp/chân, chính sách gap thống nhất và bộ video kiểm chứng.

- [ ] **Bạn:** cố định góc đặt/ánh sáng/vùng đi; quay ca thấy rõ hai chân và ca che khuất; ghi rõ hướng đi và lúc quay đầu.
- [ ] **Codex:** sửa việc một góc lỗi kéo theo loại cả mẫu hai chân; chỉ loại chỉ số phụ thuộc các landmark không hợp lệ.
- [ ] **Codex:** tính kiểm tra tốc độ/nhảy góc bằng timestamp thật trong live và offline; xử lý riêng sau gap và khi bắt lại pose.
- [ ] **Codex:** kiểm tra định danh trái/phải khi giao chân, đổi hướng; reset theo quy tắc, lưu nhãn dự đoán/sửa nhận dạng thay vì trộn với landmark gốc.
- [ ] **Codex:** so cấu hình MediaPipe complexity 0/1, kích thước ảnh và bộ lọc trên cùng video; ghi tỉ lệ có góc hợp lệ, sai số so tham chiếu, độ lệch đỉnh, độ trễ và thời gian xử lý.
- [ ] **Cả hai:** chốt quy ước góc gối/hông/thân và mặt phẳng đo. Góc hông từ Shoulder–Hip–Knee chưa tự trở thành góc gập/duỗi hông có dấu; nếu cần chỉ số đó phải định nghĩa và kiểm chứng riêng.
- [ ] **Codex:** thử mất pose ngắn/dài, mất một khớp và một chân; kiểm tra null và cờ chất lượng đi tới UI/thống kê, không bị đổi thành 0 hoặc bị đường vẽ nối qua gap.
- [ ] **Codex:** nếu thử nội suy, báo riêng tỉ lệ quan sát trực tiếp và tỉ lệ nội suy; giữ raw, chỉ bật chính sách đã qua tập kiểm tra độc lập.

**Xong khi:** số đo hợp lệ của chân còn thấy được giữ lại; gap có lý do; độ mượt không đánh đổi âm thầm đỉnh góc hoặc thời điểm. Không cam kết khôi phục chính xác khớp bị che hoàn toàn; video gốc còn thông tin mới có cơ hội phân tích lại.

**Phạm vi:** [main.py](D:/Phuchochucnang/PhuchoiChanGia/backend/main.py), [pose_quality.py](D:/Phuchochucnang/PhuchoiChanGia/backend/pose_quality.py), [pose_identity_lock.py](D:/Phuchochucnang/PhuchoiChanGia/backend/pose_identity_lock.py), [measurement_smoothing.py](D:/Phuchochucnang/PhuchoiChanGia/backend/measurement_smoothing.py), [camera_fusion.py](D:/Phuchochucnang/PhuchoiChanGia/backend/camera_fusion.py), [pose_replay_overlay.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/pose_replay_overlay.dart).

### G2-05 — Lọc FSR và xác nhận mốc chạm/rời đất

**Đầu ra:** chuỗi sự kiện IC/TO riêng từng chân, có thời gian, nguồn, độ tin cậy và đoạn liên tục.

- [ ] **Codex:** xây chuỗi xử lý có phiên bản: ADC gốc → kiểm tra ô → quy đổi lực theo công thức/scale đã có → bù nền từng ô theo profile → lọc/ngưỡng nhiễu đã kiểm tra → phát hiện sự kiện. Vị trí EMA trước hay sau quy đổi phải được kiểm chứng vì phép quy đổi phi tuyến; smoothing trình bày tách riêng, không chồng lọc mà bỏ qua độ trễ.
- [ ] **Codex:** dùng chung xử lý live và replay với cùng raw/profile/settings; hiện hai đường lọc chưa hoàn toàn giống nhau.
- [ ] **Cả hai:** đo nhiễu không tải, trôi nền, tải yếu thật; chọn ngưỡng bật/tắt khác nhau và thời gian xác nhận để tránh nhấp nháy trạng thái. Giữ profile zero cố định trong phiên đi; chỉ lấy nền mới bằng thao tác chủ động với trạng thái không tải đã xác nhận.
- [ ] **Codex:** xuất sự kiện độc lập với việc ghép cặp thì đứng hoặc có pose; phân biệt “đang đu đưa”, “không nhận dữ liệu” và “chưa xác định”.
- [ ] **Cả hai:** đo độ lệch/độ trôi đồng hồ camera–FSR bằng mốc chung quan sát được; lưu offset và bất định, không coi thời gian nhận Bluetooth là thời gian chạm đất chính xác.
- [ ] **Codex:** kiểm tra gói thiếu/lặp/đảo thứ tự, reconnect giữa thì đứng và mất tín hiệu quanh IC/TO; sự kiện không rõ không được đoán từ nhịp đi trung bình.
- [ ] **Cả hai:** so IC/TO với mốc rà thủ công trên tập kiểm tra; báo sai lệch và độ trễ theo độ phân giải thực đo. Nếu FSR thực đạt 20 Hz thì khoảng mẫu là 50 ms, nhưng không mặc định sai số sự kiện chỉ 50 ms.

**Xong khi:** cùng đầu vào và cấu hình cho cùng sự kiện trong live/replay; không có tiếp xúc giả do nhiễu trong ca không tải; các sự kiện thật và ca tải yếu được đánh giá theo tiêu chí G2-00.

**Phạm vi:** [fsr_step_pipeline.py](D:/Phuchochucnang/PhuchoiChanGia/backend/fsr_step_pipeline.py), [step_events.py](D:/Phuchochucnang/PhuchoiChanGia/backend/step_events.py), [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py), module hiệu chuẩn mới khi đã có.

### G2-06 — Hai đường live và cửa sổ cuộn tối đa 5 chu kì

**Đầu ra:** mỗi đại lượng có hai đường trái/phải được vẽ dần ngay khi có dữ liệu, cùng trục X thời gian. Giữ tối đa 5 chu kì mỗi chân, gồm cả chu kì đang diễn ra; đứng và đu đưa nối tiếp theo số đo thực.

- [ ] **Codex:** tách đường hiển thị mẫu live khỏi đường xác nhận chu kì hoàn tất. Mẫu đầu tiên xuất hiện ngay theo nhịp cập nhật UI; không chờ 6 IC, không chờ hoàn tất pha đứng, không chờ chân kia.
- [ ] **Codex:** ghi nhận bắt đầu/đang diễn ra/hoàn tất cho chu kì IC[n] → TO → IC[n+1] từng chân. Phần đầu phiên chưa đủ IC vẫn vẽ và gắn nhãn chưa xác định chu kì; tuyệt đối không dựng mốc từ nhịp đi giả định.
- [ ] **Codex:** giữ 5 vị trí live mỗi chân. Ca nghiệm thu: 1, rồi 1–2, …, 1–5; khi chu kì 6 bắt đầu phải thấy 2–6 với chu kì 6 đang vẽ dần. Loại phần cũ khỏi vùng xem, không xóa dữ liệu gốc hoặc kết quả đã hoàn tất.
- [ ] **Codex:** dùng timestamp chung khi hai chân cập nhật/loại chu kì cũ khác lúc; không dồn mỗi chân về trục 1–5 độc lập và không ép hai chân cùng độ dài chu kì. Một đường có thể bắt đầu muộn hơn trong cùng vùng X do giới hạn hiển thị; phần bị bỏ vì cửa sổ không được gắn nhãn mất dữ liệu.
- [ ] **Codex:** FSR vẫn chạy khi pose hụt; chỉ đường/đại lượng bị thiếu có khoảng trống. Một chân mất tín hiệu không đóng băng bên còn lại. Khi chưa rõ mốc để cuộn theo chu kì, dùng cửa sổ thời gian dự phòng hữu hạn và báo trạng thái; chốt độ dài dự phòng ở G2-00 theo tốc độ đi, không biến thời gian dự phòng thành chu kì đo được.
- [ ] **Codex:** giữ gap ở vị trí thật; khi tín hiệu trở lại thì vẽ ngay và phân đoạn lại khi đủ mốc. Một sự kiện khôi phục muộn không được reset cả màn hình, vẽ trùng hoặc xóa nhầm chu kì do định danh không ổn định.
- [ ] **Codex:** lớp thống kê hoàn tất vẫn kiểm tra 6 IC cùng chân → 5 chu kì hoàn chỉnh và các TO tương ứng. Chu kì đang vẽ không đưa vào Mean ± SD/ROM cuối cùng; có thể lấy 5 chu kì hoàn tất gần nhất từ lịch sử lưu riêng và hiện ID, không buộc thống kê dùng đúng 5 vị trí live.
- [ ] **Codex:** giữ các chế độ phụ 0–100% và Mean ± SD; ghi n hợp lệ, null/mask và chỉ số không đủ dữ liệu. Các lớp này không làm chặn hoặc thay cách xem hai đường live.
- [ ] **Codex:** lưu sự kiện, khoảng chu kì, quality và định nghĩa pha; khi mở lại phiên có thể xem cả các chu kì đã ra khỏi màn hình live.

**Xong khi:** vẽ được ngay khi mới có một bước và một bên; chu kì thứ 6 thay vị trí chu kì đầu trong vùng xem; còn đúng hai đường trên trục thời gian chung cho đại lượng đã chọn, không tạo 10 đường chồng làm chế độ mặc định. Phát lại đủ dữ liệu đã lưu; mất tín hiệu không tạo số 0 giả hoặc bắt chờ tích lũy lại đủ 5.

**Phạm vi:** [gait_cycle_pipeline.py](D:/Phuchochucnang/PhuchoiChanGia/backend/gait_cycle_pipeline.py), [realtime_services.py](D:/Phuchochucnang/PhuchoiChanGia/backend/realtime_services.py), [gait_data.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/models/gait_data.dart), [gait_cycle_analysis.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/gait_cycle_analysis.dart), [fsr_force_phase_dashboard.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/fsr_force_phase_dashboard.dart).

### G2-07 — Vẽ lại UI bằng UI/UX Pro Max

**Đầu ra:** thiết kế và giao diện cho công việc nghiên cứu: chuẩn bị → thu → kiểm tra chất lượng → phân tích → xuất kết quả.

- [ ] **Codex:** làm wireframe sau G2-01, dùng UI/UX Pro Max với stack Flutter; chọn phong cách tối giản, tương phản tốt, khoảng trắng và nhãn đơn vị rõ; tránh hiệu ứng tốn tài nguyên.
- [ ] **Codex:** nhóm form theo người tham gia/phiên đo, thiết bị, hiệu chuẩn và chất lượng; có nhãn thường trực, đơn vị, lỗi ngay tại trường, thứ tự bàn phím hợp lý.
- [ ] **Codex:** tách vùng chọn biểu đồ khỏi vùng vẽ. Mặc định tập trung 1 biểu đồ lớn hoặc 2 biểu đồ so sánh; cho chọn nhiều bằng danh sách cuộn với kích thước vùng vẽ tối thiểu, không ép tất cả vào một màn hình.
- [ ] **Codex:** cho thu gọn preview camera khi xem biểu đồ; mở rộng biểu đồ theo kích thước cửa sổ thực và giữ bộ chọn chu kì/đơn vị/chú giải khi mở rộng.
- [ ] **Codex:** mặc định mỗi đại lượng là một biểu đồ chứa hai đường trái–phải, chạy ngay và cuộn tối đa 5 chu kì mỗi chân, có cả đứng/đu đưa. So một chu kì 0–100% hoặc chồng chu kì/Mean ± SD chỉ là chế độ phụ chủ động chọn.
- [ ] **Codex:** khi chọn chế độ phụ chồng chu kì, giới hạn số đại lượng/vùng lực để đọc được; không mặc định tách hai chân thành hai ô hoặc vẽ 10 đường chồng trong màn hình live người dùng yêu cầu.
- [ ] **Codex:** cùng trục thời gian/con trỏ cho các biểu đồ liên quan; đánh dấu đứng/đu đưa theo từng chân; dùng màu nhất quán cộng kiểu nét/nhãn để phân biệt trái/phải.
- [ ] **Codex:** nhãn “Hiện tối đa 5 chu kì”, ID chu kì hiện có và “đang diễn ra”; số chu kì hoàn tất/chất lượng nằm ở lớp thống kê, không tạo màn chờ trái x/5/phải y/5 mới có biểu đồ. Hiện vùng thiếu/nội suy, nguồn quy đổi lực, trạng thái zero và demo ngay nơi đọc kết quả.
- [ ] **Codex:** chỉ dựng biểu đồ đang nhìn thấy; giảm nhịp redraw và số điểm để hiển thị khi cần, giữ nguyên dữ liệu phân tích/xuất. Chú giải không che đường vẽ; trục và đơn vị không bị cắt.
- [ ] **Codex:** giữ lựa chọn biểu đồ/chu kì khi phóng to, thu nhỏ hoặc có chu kì mới; có tạm dừng xem, tiếp tục và về khoảng thời gian hiện tại. Tạm dừng xem không tự dừng thu dữ liệu.
- [ ] **Cả hai:** duyệt bằng các tác vụ thật: chọn nhiều biểu đồ, so gối trái/phải, xem một đoạn mất pose, tìm chu kì lỗi và xuất kết quả. Chốt kích thước vùng vẽ trên laptop thực trước khi hoàn thiện.

**Xong khi:** ở 1366×768 và 1920×1080, với 1/4/13 biểu đồ và phiên có 0/1/5/6/10 chu kì, không tràn/cắt nhãn; live vẫn giữ tối đa 5 chu kì theo quy ước, lịch sử xem được phần trước. Có cuộn/phóng to, hai đường dễ đọc, phóng chữ 125–150% không mất điều khiển. Đây là ma trận đề xuất, chưa phải kết quả UI đã chạy.

**Phạm vi:** [app_theme.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/theme/app_theme.dart), [analysis_dashboard.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/screens/analysis_dashboard.dart), [tab_patients.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/tab_patients.dart), [tab_prepare_session.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/tab_prepare_session.dart), [tab_scan.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/tab_scan.dart), [realtime_chart_workspace.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/realtime_chart_workspace.dart), [chart_labels.dart](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/lib/widgets/chart_labels.dart), các widget FSR/gait và chart hiện có.

**Kết quả tra skill:** phần dashboard/biểu đồ và Flutter phù hợp; các gợi ý landing page trả về từ truy vấn phong cách đã được loại vì không phù hợp ứng dụng này. Chưa tạo mockup hoặc sửa UI trong lượt lập kế hoạch.

### G2-08 — Nghiệm thu và bàn giao giai đoạn 2

- [ ] **Codex:** chạy các kiểm thử phù hợp bên dưới, kiểm tra không hồi quy phiên ghi/phát lại/dữ liệu cũ.
- [ ] **Cả hai:** chạy 3 phiên đo độc lập, mỗi phiên đi ít nhất 7 chu kì mỗi chân để kiểm tra từ bước đầu, cửa sổ đầy 5, chuyển 6/7 và phát lại chu kì 1. Có ca một chân chậm/mất tín hiệu để kiểm tra chân kia vẫn vẽ; ghi rõ chất lượng từng đoạn.
- [ ] **Cả hai:** đối chiếu góc, lực và sự kiện với dữ liệu kiểm tra độc lập; báo sai số và số mẫu thực, không nghiệm thu bằng hình dạng đường cong lý tưởng.
- [ ] **Codex:** so số chu kì/mốc/quality giữa live và replay cùng chế độ; khi offline dùng mô hình mạnh hơn, ghi rõ khác cấu hình và giải thích thay đổi kết quả.
- [ ] **Codex:** kiểm tra file xuất có đơn vị, định nghĩa chu kì, số chu kì dùng, khoảng thiếu, loại nguồn và phiên bản hiệu chuẩn/thuật toán.
- [ ] **Cả hai:** cập nhật hướng dẫn thu và diễn giải biểu đồ. Rà các mục báo cáo chịu ảnh hưởng: % thì đứng so với % toàn chu kì, góc trong/góc gập, N ước tính/N hiệu chuẩn, tên chân và số liệu FSI giữa mô tả/bảng.
- [ ] **Cả hai:** ghi giới hạn còn lại và điều kiện cần máy mới; chốt giai đoạn 2 bằng bằng chứng đo, không chỉ test phần mềm.

**Xong khi:** hoàn tất các đầu ra P0/P1, có kết quả test và phép đo thực; sai số nằm trong tiêu chí đã chốt hoặc giới hạn được giải quyết trước khi công bố kết quả tương ứng.

## 6. Ma trận thử nghiệm và kiểm thử

### Hiệu năng trên máy hiện tại

Mỗi ca đầu 60–90 giây, lặp 3 lần; giữ vị trí, ánh sáng và tác vụ giống nhau. Chỉ thử profile được camera hỗ trợ. Không bắt buộc chạy mọi tổ hợp nếu số đo đã xác định rõ điểm nghẽn.

| Ca | Thiết lập | Điều cần tách riêng |
|---|---|---|
| A | 1 camera, ghi gốc, preview nhẹ | Mốc tải thấp |
| B | 2 camera, ghi gốc, tạm dừng pose | Đọc/USB/ghi |
| C | Như B, tăng preview | Mã hóa ảnh và trình duyệt |
| D | Như B, chạy pose một camera rồi cả hai | Tải của suy luận |
| E | Video cố định, complexity 0/1 và rộng 640/854 | Tốc độ so với độ tin cậy góc |
| F | Profile 720p15/20 hoặc 640×480 nếu hỗ trợ | Chi tiết ảnh và độ phân giải thời gian |
| G | Profile thắng, 2 camera + 2 FSR + giao diện trong 10 phút | Tính ổn định và mức tăng bộ nhớ |

### Ca hồi quy bắt buộc khi triển khai

| Nhóm | Ca kiểm tra | Kết quả cần chứng minh |
|---|---|---|
| Raw/nguồn | Cùng ADC qua serial và hai transmitter; N ước tính; demo | Raw không đổi, nguồn không bị nâng thành đã hiệu chuẩn |
| Nguồn lực/zero | Profile đúng/sai thiết bị; đổi scale; đã zero tại transmitter; ô lỗi | Không trừ nền/nhân scale hai lần; kết quả cũ và raw được giữ |
| Tare từng ô | Nền riêng khác nhau, không tải, tải nhẹ, đang đứng, lắp lại đế | Về 0 trong giới hạn nhiễu, giữ tải nhẹ, chặn lấy nền khi chịu tải, yêu cầu kiểm tra lại sau lắp |
| Đơn vị FSR | N và kg trên cùng ADC/profile/zero | Quy đổi nhất quán; ngưỡng tổng 10 kg ở nhánh kg của file gửi thêm không được xóa tải thật trong kênh nghiên cứu |
| Thời gian | Khung/gói trùng, đảo thứ tự, gap, timestamp reset | Không nhân đôi dữ liệu hoặc nối sai phiên |
| Pose | Một góc lỗi, mất chân xa, đổi chân, gap ngắn/dài | Giữ chỉ số còn hợp lệ, không bịa góc |
| Vẽ live/cuộn | Mẫu đầu, 1–5, bắt đầu chu kì 6/7, một chân về trước | Vẽ ngay; 6 vào thì 1 ra; hai đường chung timestamp; lịch sử vẫn giữ 1 |
| Thống kê chu kì | 6 IC mỗi chân; chỉ 5 thì đứng; TO thiếu; bất đối xứng | Xác nhận chu kì hoàn tất đúng, không đưa chu kì đang vẽ vào kết quả cuối |
| Tính liên tục | Mất sự kiện/khung giữa cửa sổ; reconnect; dừng/quay đầu | Giữ khoảng trống thật, vẽ tiếp ngay; không reset cả biểu đồ hoặc nối xuyên gap |
| FSR độc lập pose | FSR đầy đủ, camera không có mẫu mới nhiều chu kì | Sự kiện và tiến độ FSR vẫn chạy; góc giữ trạng thái thiếu |
| Live/replay | Cùng raw/profile/cấu hình | Giá trị, sự kiện và chất lượng tương đương |
| UI/xuất | Nhiều biểu đồ/chu kì, null, nội suy, demo, dữ liệu cũ | Đọc được, đúng nhãn/đơn vị, không nối qua gap |

**Kiểm thử sẵn có để mở rộng:** các test FSR serial/force/step pipeline, gait cycle pipeline, step events, pose quality/identity, smoothing, archive và reanalysis trong [backend](D:/Phuchochucnang/PhuchoiChanGia/backend); test chart labels, replay overlay và smoothing trong [frontend_app/test](D:/Phuchochucnang/PhuchoiChanGia/frontend_app/test).

**Cách chạy khi đã triển khai:** từ thư mục dự án dùng `backend\venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py"`; từ thư mục frontend dùng `flutter analyze` và `flutter test`. Trước mỗi thay đổi logic, bổ sung ca tái hiện sai sót thật, xác nhận fail rồi sửa và xác nhận pass; phần giao diện thuần trình bày kiểm tra bằng render/tác vụ thực, không viết test chỉ lặp lại cấu trúc mã.

## 7. Phần việc riêng để cùng theo dõi

### Bạn chuẩn bị

- [ ] Thông tin camera/cách cắm, mã mảng FSR và firmware đang dùng — G2-00.
- [ ] Vùng đi, ánh sáng, vị trí camera cố định; các ca video có và không có che khuất — G2-00/G2-04.
- [ ] Thông tin phép hiệu chuẩn quả cân đã có, ý nghĩa scale và điều kiện zero kỹ thuật yêu cầu; chuẩn bị đế/giày để thu nền 96 ô và kiểm tra tải — G2-03.
- [ ] Thời gian chạy các ca benchmark và nghiệm thu, người tham gia theo quy trình nghiên cứu hiện có — G2-02/G2-08.
- [ ] Mục tiêu sai số và cách đọc biểu đồ mong muốn; duyệt wireframe/thao tác — G2-00/G2-07.

### Codex thực hiện khi bắt đầu triển khai

- [ ] Tạo mốc công việc, công cụ đo và hợp đồng dữ liệu — G2-00/G2-01.
- [ ] Hoàn thiện ghi nhẹ/phân tích sau — G2-02.
- [ ] Kế thừa quy đổi lực, làm công cụ zero từng ô, lưu profile, lọc và đồng bộ — G2-03/G2-05.
- [ ] Sửa pose theo khớp/chân, xử lý gap và dựng toàn chu kì — G2-04/G2-06.
- [ ] Dùng UI/UX Pro Max vẽ và tích hợp giao diện, kiểm tra trên màn hình thật — G2-07.
- [ ] Kiểm thử, đối chiếu dữ liệu, tài liệu và bàn giao — G2-08.

Đây là hai góc nhìn của cùng công việc, không phải hai danh sách độc lập để đếm tiến độ hai lần. Khi hoàn thành, cập nhật checkbox gói tương ứng và kèm đường dẫn bằng chứng; nếu còn thiếu phép đo thực thì giữ trạng thái chưa nghiệm thu.

## 8. Việc đầu tiên khi chuyển sang triển khai

**Bắt đầu G2-00 và G2-01:** bảo toàn giai đoạn 1, thu bảng hiệu năng nền, kiểm tra raw FSR và nguồn quy đổi lực, chốt dữ liệu live/chu kì. Sau đó mở hai nhánh song song: camera live nhẹ và zero FSR từng ô. Wireframe hai đường cuộn chạy cùng thời gian khi quy ước dữ liệu đã rõ.

Chưa ấn định lịch theo ngày vì độ ổn định nền sau lắp, khả năng ghi/live hai camera và phạm vi hiệu chuẩn quả cân đã có còn cần xác nhận. Sau G2-00 và lượt zero/kiểm tra thử, cập nhật ước lượng theo khối lượng thực; không mặc định phải đo lại đường lực đủ 96 ô.

## 9. Nguồn và giới hạn của khảo sát

- Báo cáo người dùng cung cấp, mục 3.6, 4.1, 5.2; đọc nội dung và bảng từ DOCX, không đánh giá bố cục in của báo cáo.
- Thông tin bổ sung từ người dùng: kỹ thuật đã dùng quả cân cho phần quy đổi lực; nhiệm vụ trước mắt là xử lý nền từng ô sau lắp. [File FSR bổ sung](<C:/Users/DELL/Downloads/FSR_Transmitter_2 (1).py>) có công thức chung, scale 2.619, EMA và chưa có tare từng ô trong phần mã đã kiểm tra; chưa kèm bảng kết quả quả cân hoặc sai số để suy ra phạm vi hiệu chuẩn.
- Mã nguồn và test trong workspace ngày 15/09/2026; các số dòng là vị trí lúc khảo sát và có thể thay đổi khi triển khai.
- [MediaPipe Pose legacy](https://chuoling.github.io/mediapipe/solutions/pose.html): cấu hình mô hình, smoothing, ảnh hưởng độ phức tạp đến độ trễ. Áp dụng cho API hiện dùng.
- [MediaPipe Pose Landmarker Python](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python): tài liệu tham khảo nếu thử đổi API sau này. LIVE_STREAM có thể bỏ khung mới khi bận; chuyển API không tự giải quyết dữ liệu thiếu. Đây chưa phải API được thay vào ứng dụng.
- [Interlink FSR Integration Guide](https://www.interlinkelectronics.com/downloads/integration-guides/fsr-400-series-integration-guide.pdf): tham khảo cách đặt tải, kiểm tra tính lặp lại và hiệu chuẩn từng phần tử; không thay datasheet của mảng thực tế.
- [UI/UX Pro Max](D:/Phuchochucnang/PhuchoiChanGia/.agents/skills/ui-ux-pro-max/SKILL.md), [Superpowers Brainstorming](C:/Users/DELL/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/brainstorming/SKILL.md) và [Writing Plans](C:/Users/DELL/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/writing-plans/SKILL.md): phân rã phạm vi, phụ thuộc, thiết kế giao diện và theo dõi trước triển khai.
