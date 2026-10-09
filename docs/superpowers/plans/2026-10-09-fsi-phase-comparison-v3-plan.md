# FSI Phase Comparison V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo `FSR_Transmitter_3.py` giữ nguyên `FSR_Transmitter_2.py`, bổ sung ghi nhận chu kỳ từng chân và so sánh FSI theo các cửa sổ pha bằng các vùng ô FSR được đăng ký cố định.

**Architecture:** Bản `_3` bắt đầu từ bản `_2` và giữ nguyên luồng đọc serial, chuyển đổi đơn vị, zero, hiệu chuẩn, hiển thị ma trận và gửi dữ liệu. Lớp phân tích mới lưu mẫu 48 ô theo timestamp, xác định các khoảng tiếp xúc riêng của từng chân, sau đó tính FSI từ cùng nhóm ô và cùng loại đại lượng ở các pha tương ứng. Toàn bộ 48 ô dùng để phát hiện trạng thái và kiểm tra chất lượng; FSI dùng các ROI đã cấu hình, không dùng tổng lực giả định của toàn bàn chân.

**Tech Stack:** Python 3, Tkinter hiện có, `unittest`, `backend.fsr_force.matrix_to_newton`, cấu trúc ma trận 12×4 và ánh xạ trái phải hiện có.

**Spec:** `D:/Phuchochucnang/PhuchoiChanGia/tmp/fsr_phase_selection/primary_sources_report.md` và quyết định nghiên cứu trong cuộc trò chuyện ngày 09/10/2026. Tấm cố định 48 ô cỡ khoảng 38; vùng gót thử ban đầu có thể là `42,43,46,47` nhưng chỉ hợp lệ sau khi xác nhận dấu gót trên tấm. Mã ô đầu bàn/ngón không được đoán từ hình ảnh.

## Global Constraints

- Cập nhật ngày 09/10/2026: người dùng xác nhận nhóm mũi thực tế theo nhãn ảnh là `6,7,8,10,11,12,14,15,16` (9 ô), thay nhóm ứng viên trước đây. Nhóm gót `42,43,46,47` (4 ô) vẫn là cấu hình thử có điều kiện. Nhóm gót–mũi là hợp của hai nhóm, gồm 13 ô không trùng nhau. Đây là mã ô vật lý trên ảnh, không phải index gói serial; phải xác minh ánh xạ và vùng tương ứng riêng cho từng chân trước khi tính FSI hợp lệ.

- Không sửa hoặc ghi đè `FSR_Transmitter_2.py`.
- Tạo bản mới tại `D:/Phuchochucnang/PhuchoiChanGia/FSR_Transmitter_3.py`.
- Giữ nguyên các chức năng cũ của `_2`: đọc serial, 48 giá trị, ánh xạ trái phải, zero, hiệu chuẩn, hiển thị ma trận, ghi log và gửi packet.
- FSI dùng đúng công thức: `100 * min(left, right) / max(left, right)`; 100% nghĩa là hai giá trị bằng nhau.
- Không tính FSI lực cho pha vung khi cả hai giá trị đều bằng 0; trả về `None` hoặc trạng thái `không tải`.
- Vùng ngoài mép, ô lỗi, ô bão hòa, mất gói hoặc chưa đăng ký giải phẫu phải là `missing/invalid`, không chuyển thành 0.
- Không gọi tổng các ROI được chọn là tổng lực toàn bàn chân; tên hiển thị phải nói rõ `FSI tải mẫu` hoặc `FSI vùng đo`.
- Pha giữa bắt buộc báo riêng `FSI_mid_heel` và `FSI_mid_forefoot`. Chỉ số gộp gót–mũi là `FSI_mid_sampled_heel_forefoot` dạng phụ; không được dùng nó làm FSI pha giữa duy nhất vì sự bù trừ tải giữa hai vùng có thể làm kết quả giả cân bằng.
- Chỉ số pha đẩy từ ROI mũi là tải pháp tuyến vùng mũi được lấy mẫu (`FSI_push_forefoot`), không được đặt tên hoặc diễn giải là lực đẩy trước/sức mạnh đẩy khi chưa có lực tiếp tuyến hay dữ liệu động lực học phù hợp.
- Toàn bộ 48 ô vẫn được giữ để phát hiện tiếp xúc, kiểm tra chân vượt mép và chất lượng; ROI gót/mũi chỉ dùng cho chỉ số so sánh đã đăng ký.
- Kết quả phải có hai tầng: bảng chi tiết từng cặp bước (`BT1–BP1`, `BT2–BP2`...) và bảng tổng hợp toàn phiên.
- Bảng tổng hợp phải tính từ các FSI của từng cặp bước hợp lệ, không tính một lần từ hai giá trị trung bình toàn phiên.
- Không chọn lại ô mạnh nhất theo từng bước; ROI phải cố định sau khi đăng ký.
- Pha được so trong chu kỳ riêng của từng chân, không so hai chân tại cùng timestamp đồng hồ.
- Chưa có HO thì không gán 65% cuối stance thành HO; chỉ ghi `terminal stance window`.
- Không thêm dependency mới nếu không cần thiết.

## Review Focus

- **Hai chân lệch thời điểm:** chu kỳ trái và phải bắt đầu khác nhau nhưng FSI phải so cùng pha tương đối; kiểm tra bằng timestamp không trùng nhau.
- **Chân vượt mép tấm:** ROI thiếu một bên phải làm FSI không hợp lệ, không tạo kết quả lệch giả.
- **Hai ô đều không tải:** FSI phải là `None`, không phải 100%.
- **Cảm biến thô khác nhau:** ADC chưa hiệu chuẩn liên kênh chỉ là tín hiệu, không được diễn giải thành lực đối xứng.
- **HO chưa xác định hoặc dáng đi bất thường:** không ép trạng thái pha; đánh dấu cửa sổ chưa xác định và loại khỏi FSI pha sinh cơ học.
- **Bù trừ giữa vùng:** ca gót bên trái thấp nhưng mũi bên trái cao phải vẫn hiện bất đối xứng riêng theo từng vùng, dù FSI gộp gót–mũi có thể gần 100%.

## File Map

- Create: `FSR_Transmitter_3.py` — bản sao độc lập của transmitter `_2` và giao diện FSI mới.
- Create: `backend/fsi_phase_metrics.py` — các hàm thuần cho FSI, ROI, cửa sổ pha và kiểm tra chất lượng; không phụ thuộc Tkinter.
- Create: `backend/test_fsi_phase_metrics.py` — kiểm thử công thức, pha, ROI và dữ liệu thiếu.
- Modify only if required by imports: không sửa `_2`; nếu cần dùng module chung thì chỉ đọc các API hiện có trong `backend/fsr_force.py`.
- Reference only: `backend/fsr_step_pipeline.py`, `backend/step_events.py`, `backend/fsr_force.py`.

### Task 1: Tạo bản V3 bảo toàn hành vi cũ

**Files:**
- Create: `FSR_Transmitter_3.py`
- Test: `backend/test_fsi_phase_metrics.py` smoke import test

**Interfaces:**
- Consumes: ma trận 12×4, nhãn `left/right`, đơn vị packet và timestamp từ luồng `_2`.
- Produces: module chạy độc lập với các hàm cũ của `_2` chưa bị đổi tên.

- [x] **Step 1: Chụp hành vi nền của `_2`**

  Ghi nhận các điểm vào chính: ma trận mẫu, ánh xạ LL/RR, `matrix_for_unit`, `matrix_region_totals`, packet JSON, nút zero và cửa sổ hiển thị. Không sửa file.

- [x] **Step 2: Viết smoke test import cho V3**

  Kiểm tra `FSR_Transmitter_3.py` import được khi backend sẵn có và khi chạy standalone fallback giống `_2`.

- [x] **Step 3: Sao chép `_2` thành `_3`**

  Giữ nguyên hành vi cũ trước khi thêm FSI; đổi tiêu đề cửa sổ và tên log tối thiểu để người dùng phân biệt bản V3.

- [x] **Step 4: Chạy smoke test**

  Run: `backend\\venv\\Scripts\\python.exe -m unittest backend.test_fsi_phase_metrics -v`

  Expected: test import bản `_3` pass; bản `_2` không bị thay đổi.

### Task 2: Xây API ROI và FSI thuần

**Files:**
- Create: `backend/fsi_phase_metrics.py`
- Test: `backend/test_fsi_phase_metrics.py`

**Interfaces:**
- `force_symmetry_index(left: float | None, right: float | None) -> float | None`
- `validate_roi(roi: dict[str, list[tuple[int, int]]], rows: int = 12, columns: int = 4) -> None`
- `roi_series(matrix_series: list[dict], roi_cells: list[tuple[int, int]]) -> list[float]`
- `phase_summary(samples: list[dict], start: float, end: float, roi_cells: list[tuple[int, int]]) -> dict`
- `phase_fsi(left_summary: dict, right_summary: dict, metric: str = "mean") -> dict`
- `phase_fsi` phải nhận rõ `region`/ROI đang so sánh để không trộn FSI gót, mũi và chỉ số gộp trong cùng một dòng.

- [x] **Step 1: Viết test công thức FSI**

  Kiểm tra `420,420 -> 100.0`; `300,400 -> 75.0`; `0,400 -> 0.0`; `0,0 -> None`; giá trị âm hoặc không hữu hạn -> invalid.

- [x] **Step 2: Viết test ROI không trùng ô**

  `validate_roi` phải từ chối ô ngoài 12×4, ROI rỗng và một ô xuất hiện đồng thời trong hai vùng khi cấu hình yêu cầu vùng loại trừ.

- [x] **Step 3: Viết test tổng tại cùng timestamp**

  Kiểm tra nhóm gót + mũi được cộng theo từng mẫu trước khi tính mean, peak hoặc impulse; không cộng các peak riêng lẻ xảy ra khác mẫu.

- [x] **Step 4: Viết test chống bù trừ vùng**

  Với trái `(gót=100, mũi=300)` và phải `(gót=300, mũi=100)`, kiểm tra FSI gót và FSI mũi đều khoảng `33.33`, trong khi FSI gộp có thể là `100`; UI và bảng tổng hợp vẫn phải giữ hai dòng vùng riêng.

- [x] **Step 5: Viết test dữ liệu thiếu**

  Một ROI thiếu bên trái, mất gói, bão hòa hoặc cờ invalid phải trả trạng thái `invalid/missing` và FSI `None`.

- [x] **Step 6: Implement các hàm thuần**

  Dùng timestamp thật để tích phân impulse; trả về `mean`, `peak`, `impulse`, `duration`, `valid_sample_count`, `quality` và `reason`.

- [x] **Step 7: Chạy test module**

  Run: `backend\\venv\\Scripts\\python.exe -m unittest backend.test_fsi_phase_metrics -v`

  Expected: tất cả test FSI và ROI pass.

### Task 3: Chu kỳ và cửa sổ pha

**Files:**
- Modify: `FSR_Transmitter_3.py`
- Modify: `backend/fsi_phase_metrics.py`
- Test: `backend/test_fsi_phase_metrics.py`

**Interfaces:**
- `detect_contact_interval(samples: list[dict], threshold: float, debounce: int) -> dict`
- `build_stride(contact_intervals: list[dict], side: str) -> dict`
- `phase_windows(stride: dict, opposite_stride: dict | None) -> dict`

- [x] **Step 1: Viết test hai chân lệch timestamp**

  Tạo chân trái chạm 0.00–0.65 s và chân phải chạm 0.50–1.18 s; kiểm tra FSI dùng cửa sổ tương ứng chứ không lấy cùng khoảng đồng hồ.

- [x] **Step 2: Viết test chu kỳ IC→IC**

  Hai lần IC của cùng chân phải tạo một stride; đoạn swing được giữ trong chu kỳ thay vì bỏ sau TO.

- [x] **Step 3: Implement bộ lưu mẫu 48 ô**

  Mỗi mẫu lưu `timestamp`, `side`, `matrix`, `unit`, `valid`, `quality`; không chỉ lưu tổng vùng.

- [x] **Step 4: Implement nhận tiếp xúc**

  Dùng thông tin cả 48 ô và debounce; tạo `IC`/`TO` đo được. Nếu vùng ngoài tấm có thể tiếp xúc mà không có tín hiệu, đánh dấu giới hạn bao phủ.

- [x] **Step 5: Implement cửa sổ pha**

  Cửa sổ nghiên cứu chính:

  - `loading`: IC chân đang xét → TO chân đối diện.
  - `midstance`: TO chân đối diện → HO chân đang xét.
  - `terminal_stance`: HO chân đang xét → IC chân đối diện.
  - `pre_swing`: IC chân đối diện → TO chân đang xét.
  - `swing`: TO chân đang xét → IC kế tiếp của chính chân đó.

  Nếu thiếu HO, trả `terminal_stance_window` theo cửa sổ thay thế đã cấu hình, không gắn nhãn midstance/terminal stance chính thức.

- [x] **Step 6: Chạy test pha**

  Run: `backend\\venv\\Scripts\\python.exe -m unittest backend.test_fsi_phase_metrics -v`

  Expected: chu kỳ, cửa sổ lệch thời gian và nhãn thiếu mốc pass.

### Task 4: Cấu hình ROI FSI cho tấm 48 ô

**Files:**
- Modify: `FSR_Transmitter_3.py`
- Modify: `backend/fsi_phase_metrics.py`
- Test: `backend/test_fsi_phase_metrics.py`

**Interfaces:**
- `DEFAULT_FSI_ROIS = {"heel": [...], "forefoot": [...], "stance_sampled": [...]}`
- `set_fsi_rois(roi_config: dict) -> None`
- `get_fsi_rois() -> dict`

**Physical cell IDs:**
- `FOREFOOT_CELL_IDS = (6, 7, 8, 10, 11, 12, 14, 15, 16)` — nhóm mũi do người dùng xác nhận.
- `HEEL_CELL_IDS = (42, 43, 46, 47)` — nhóm gót thử có điều kiện.
- `STANCE_CELL_IDS = (6, 7, 8, 10, 11, 12, 14, 15, 16, 42, 43, 46, 47)` — hợp hai nhóm, không cộng trùng.
- Chuyển các mã này thành tọa độ ma trận riêng cho trái/phải bằng ánh xạ được kiểm tra; không dùng trực tiếp `id - 1` làm index serial. Không tự phản chiếu thêm nếu luồng đầu vào đã phản chiếu.

- [x] **Step 1: Viết test cấu hình ROI**

  Kiểm tra ROI gót thử `42,43,46,47` chỉ được bật sau khi biểu diễn đúng tọa độ ma trận; không coi nhãn ảnh và index mảng là cùng thứ tự.

  Thêm kiểm tra nhóm mũi chứa đúng 9 mã trên, gót chứa 4 mã, hợp chứa 13 mã. Dùng mẫu chỉ có một ô mang giá trị khác 0 để kiểm tra ánh xạ từng mã ở cả hai chân; ô ngoài ROI không được góp vào tổng ROI. Nhóm giữa bước phải bằng tổng gót và mũi tại cùng timestamp.

- [x] **Step 2: Implement cấu hình có trạng thái chưa đăng ký**

  Điền sẵn nhóm mũi bằng 9 mã người dùng đã xác nhận; giữ trạng thái đăng ký/bao phủ riêng từng chân. Việc xác nhận nhóm vật lý không tự chứng minh ánh xạ serial hoặc độ bao phủ tương đương giữa hai chân. Không tự gán nhóm ngón riêng; nhóm gót thử vẫn có cờ `conditional`. Chỉ bật FSI hợp lệ sau khi kiểm tra ánh xạ và đăng ký vùng đo cho cả hai bên.

- [x] **Step 3: Implement các chỉ số theo vùng và pha**

  - `FSI_contact_heel`: ROI gót, metric mean/peak trong cửa sổ loading; chỉ hợp lệ khi sự kiện tiếp đất thực sự được xác định và ROI gót còn nằm trên tấm.
  - `FSI_mid_heel`: ROI gót, metric mean/impulse trong cửa sổ midstance; đây là dòng bắt buộc.
  - `FSI_mid_forefoot`: ROI mũi, metric mean/impulse trong cửa sổ midstance; đây là dòng bắt buộc để phát hiện bù trừ tải.
  - `FSI_mid_sampled_heel_forefoot`: hợp ROI gót + mũi, metric mean/impulse trong cùng cửa sổ midstance; chỉ dùng như chỉ số phụ/tổng quan, không thay thế hai dòng trên.
  - `FSI_push_forefoot`: ROI mũi, metric mean/peak/impulse trong terminal stance hoặc cửa sổ cuối stance; nhãn hiển thị là `FSI tải pháp tuyến vùng mũi`, không gọi là FSI lực đẩy.
  - Nếu sau này đăng ký được ROI midfoot riêng, cho phép thêm `FSI_mid_midfoot` và chỉ số phụ `FSI_mid_sampled_HMF`; không tự suy ra midfoot từ các ô chưa đăng ký.

- [x] **Step 4: Chạy test ROI**

  Run: `backend\\venv\\Scripts\\python.exe -m unittest backend.test_fsi_phase_metrics -v`

  Expected: không trùng ô, ROI chưa đăng ký không tạo FSI hợp lệ, ROI hợp lệ tạo đúng các dòng gót, mũi, gộp phụ và tải mũi cuối stance.

### Task 5: Tích hợp vào giao diện V3 và lưu kết quả

**Files:**
- Modify: `FSR_Transmitter_3.py`
- Test: `backend/test_fsi_phase_metrics.py` và smoke test thủ công Tkinter

**Interfaces:**
- Packet FSI: `{"cycle_id": str, "side": str, "phase": str, "metric": str, "value": float | None, "quality": str, "reason": str | None}`
- Summary FSI: `{"phase": str, "left": dict, "right": dict, "fsi": float | None, "higher_side": str | None}`
- StepPairRow: `{"pair_id": str, "left_cycle_id": str, "right_cycle_id": str, "phase": str, "region": str, "left_value": float | None, "right_value": float | None, "fsi": float | None, "higher_side": str | None, "quality": str}`
- SessionSummaryRow: `{"phase": str, "region": str, "fsi_mean": float | None, "fsi_median": float | None, "fsi_sd": float | None, "valid_pair_count": int, "max_asymmetry": float | None, "interpretation": str}`

- [x] **Step 1: Viết test output summary**

  Kiểm tra output luôn có giá trị trái, phải, FSI, bên lớn hơn, quality và reason; không chỉ trả FSI đơn độc.

- [x] **Step 2: Thêm bảng FSI theo pha**

  Hiển thị bảng chi tiết cho từng cặp bước theo thứ tự `BT1–BP1`, `BT2–BP2`, `BT3–BP3`... Mỗi cặp có các dòng `Tiếp đất gót`, `Pha giữa gót`, `Pha giữa mũi`, `Pha giữa gót–mũi mẫu (phụ)`, `Tải pháp tuyến mũi cuối stance`; cột trái, phải, FSI, bên tải lớn hơn, chất lượng. Hai chu kỳ được ghép theo thứ tự thời gian hợp lệ, không yêu cầu timestamp bắt đầu giống nhau.

- [x] **Step 3: Thêm bảng FSI theo vùng**

  Cho phép xem thêm trong từng cặp bước: `FSI gót`, `FSI mũi`, `FSI gót–mũi mẫu (phụ)`. Ở pha giữa, gót và mũi luôn là hai dòng độc lập. ROI chưa đăng ký, thiếu vùng đo hoặc dữ liệu lỗi phải hiện `Chưa đủ dữ liệu`, không hiện 0%.

- [x] **Step 4: Thêm bảng tổng hợp toàn phiên**

  Từ các dòng cặp bước hợp lệ, tính riêng cho từng pha và vùng: FSI trung bình, FSI trung vị, độ lệch chuẩn, số cặp hợp lệ và độ lệch lớn nhất. Bảng gồm `Tiếp đất gót`, `Pha giữa gót`, `Pha giữa mũi`, `Pha giữa gót–mũi mẫu (phụ)`, `Tải pháp tuyến mũi cuối stance`; không lấy hai lực trung bình toàn phiên rồi mới áp dụng công thức FSI.

- [x] **Step 5: Thêm biểu đồ xu hướng FSI**

  Vẽ FSI của từng pha theo số cặp bước; đánh dấu điểm thiếu dữ liệu và giữ ID cặp bước để truy ngược bảng chi tiết.

- [x] **Step 6: Thêm trạng thái dữ liệu**

  Hiển thị `Đang chờ cặp bước`, `Đang phân tích`, `Thiếu vùng đo`, `Không tải`, `Mốc pha chưa xác định`.

- [x] **Step 7: Giữ chức năng cũ**

  Chạy các thao tác đọc serial, zero, xem ma trận, chỉnh đơn vị và ghi log trên V3; so sánh kết quả hiển thị cơ bản với V2.

### Task 6: Kiểm thử hồi quy và xác nhận bản V3

**Files:**
- Test: `backend/test_fsi_phase_metrics.py`
- Reference: `FSR_Transmitter_2.py` và `FSR_Transmitter_3.py`

- [ ] **Step 1: Chạy test FSI mới**

  `backend\\venv\\Scripts\\python.exe -m unittest backend.test_fsi_phase_metrics -v`

- [ ] **Step 2: Chạy toàn bộ test backend**

  `backend\\venv\\Scripts\\python.exe -m unittest discover -s backend -p "test_*.py"`

- [ ] **Step 3: Kiểm tra sao chép không làm đổi V2**

  So sánh hash hoặc diff có chủ đích của `FSR_Transmitter_2.py`; file không được thay đổi.

- [ ] **Step 4: Kiểm thử dữ liệu giả lập**

  Chạy các ca: hai chân bằng nhau, một bên tải nhỏ hơn, hai chân lệch thời gian, chân vượt mép, mất gói, cả hai không tải và thiếu HO.

- [ ] **Step 5: Kiểm thử bảng theo cặp và bảng tổng hợp**

  Dùng ít nhất ba cặp bước giả lập với FSI pha khác nhau; kiểm tra bảng chi tiết giữ đúng `BT1–BP1`, `BT2–BP2`, `BT3–BP3`, còn bảng tổng hợp có đúng mean, median, SD, số cặp hợp lệ và độ lệch lớn nhất từ các dòng hợp lệ. Một cặp thiếu ROI không được đi vào mẫu số tổng hợp.

- [ ] **Step 6: Kiểm thử thủ công với tấm thật**

  Đăng ký dấu chân cỡ khoảng 38, xác nhận nhóm gót và các ROI đầu bàn, ghi ít nhất 5 cặp bước; lưu raw 48 ô và bảng FSI cùng quality.

- [ ] **Step 7: Xác nhận giao diện V3**

  Kiểm tra cửa sổ, nút zero, ma trận, log, FSI theo pha, FSI theo vùng và cảnh báo thiếu dữ liệu không bị cắt hoặc gây nhầm.

- [ ] **Step 8: Commit bản V3**

  ```bash
  git add FSR_Transmitter_3.py backend/fsi_phase_metrics.py backend/test_fsi_phase_metrics.py
  git commit -m "feat: add phase-based FSI comparison transmitter v3"
  ```

## Self Review

- Bảo toàn bản `_2`: Task 1 và Task 6 kiểm tra trực tiếp.
- FSI đúng công thức phần mềm: Task 2 và Task 5.
- So cùng pha dù timestamp khác: Task 3.
- Vùng gót–mũi và ROI cố định: Task 4.
- Thiếu vùng do chân vượt mép không bị biến thành 0: Review Focus và Task 2/4.
- Chưa có HO không bị gán giả: Task 3.
- Bản kế hoạch chưa triển khai mã nguồn; mọi bước code đều có test trước.
