import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum AppLanguage {
  vietnamese('vi', 'Tiếng Việt', 'Vietnamese'),
  english('en', 'English', 'English');

  const AppLanguage(this.code, this.vietnameseName, this.englishName);

  final String code;
  final String vietnameseName;
  final String englishName;

  Locale get locale => Locale(code);
}

class AppLanguageController extends ChangeNotifier {
  AppLanguageController({
    AppLanguage initialLanguage = AppLanguage.vietnamese,
    SharedPreferencesAsync? preferences,
  })  : _language = initialLanguage,
        _preferences = preferences;

  static const _preferenceKey = 'ai_progait.interface_language';

  SharedPreferencesAsync? _preferences;
  AppLanguage _language;

  AppLanguage get language => _language;
  Locale get locale => _language.locale;

  static Future<AppLanguageController> load() async {
    try {
      final preferences = SharedPreferencesAsync();
      final savedCode = await preferences.getString(_preferenceKey);
      final language = AppLanguage.values.firstWhere(
        (candidate) => candidate.code == savedCode,
        orElse: () => AppLanguage.vietnamese,
      );
      return AppLanguageController(
        initialLanguage: language,
        preferences: preferences,
      );
    } catch (_) {
      return AppLanguageController();
    }
  }

  Future<void> setLanguage(AppLanguage language) async {
    if (_language == language) return;
    _language = language;
    notifyListeners();
    try {
      final preferences = _preferences ??= SharedPreferencesAsync();
      await preferences.setString(_preferenceKey, language.code);
    } catch (_) {
      // The interface still switches immediately if platform storage is
      // temporarily unavailable (for example, in an isolated widget test).
    }
  }
}

class AppLanguageScope extends InheritedNotifier<AppLanguageController> {
  const AppLanguageScope({
    super.key,
    required AppLanguageController controller,
    required super.child,
  }) : super(notifier: controller);

  static AppLanguageController? maybeControllerOf(BuildContext context) {
    return context
        .dependOnInheritedWidgetOfExactType<AppLanguageScope>()
        ?.notifier;
  }

  static AppLanguageController controllerOf(BuildContext context) {
    final controller = maybeControllerOf(context);
    assert(controller != null, 'No AppLanguageScope found in this context.');
    return controller!;
  }

  static AppLanguage languageOf(BuildContext context) {
    return maybeControllerOf(context)?.language ?? AppLanguage.vietnamese;
  }
}

extension AppTranslationContext on BuildContext {
  String tr(String source) {
    return AppTranslations.translate(source, AppLanguageScope.languageOf(this));
  }
}

extension LocalizedInputDecoration on InputDecoration {
  InputDecoration localized(BuildContext context) {
    String? translated(String? value) =>
        value == null ? null : context.tr(value);
    return copyWith(
      labelText: translated(labelText),
      hintText: translated(hintText),
      helperText: translated(helperText),
      errorText: translated(errorText),
      prefixText: translated(prefixText),
      suffixText: translated(suffixText),
      counterText: translated(counterText),
      semanticCounterText: translated(semanticCounterText),
    );
  }
}

class AppTranslations {
  AppTranslations._();

  static String translate(String source, AppLanguage language) {
    final exact = _exact[source];
    if (exact != null) {
      return language == AppLanguage.english ? exact.en : exact.vi;
    }

    var translated = source;
    for (final entry in _orderedSegments) {
      if (!translated.contains(entry.key)) continue;
      final replacement =
          language == AppLanguage.english ? entry.value.en : entry.value.vi;
      translated = translated.replaceAll(entry.key, replacement);
    }
    return translated;
  }

  static final List<MapEntry<String, ({String vi, String en})>>
      _orderedSegments = <String, ({String vi, String en})>{
    ..._exact,
    ..._fragments,
  }.entries.toList(growable: false)
        ..sort((a, b) => b.key.length.compareTo(a.key.length));

  static const Map<String, ({String vi, String en})> _exact = {
    // Application shell and settings.
    'PHÒNG LAB': (vi: 'PHÒNG THÍ NGHIỆM', en: 'LABORATORY'),
    'Kỹ thuật viên': (vi: 'Kỹ thuật viên', en: 'Clinician'),
    'Cài đặt': (vi: 'Cài đặt', en: 'Settings'),
    'CÀI ĐẶT': (vi: 'CÀI ĐẶT', en: 'SETTINGS'),
    'Ngôn ngữ giao diện': (vi: 'Ngôn ngữ giao diện', en: 'Interface language'),
    'Chọn ngôn ngữ sử dụng trong toàn bộ phần mềm.': (
      vi: 'Chọn ngôn ngữ sử dụng trong toàn bộ phần mềm.',
      en: 'Choose the language used throughout the application.'
    ),
    'Thuật ngữ lâm sàng và cơ sinh học được giữ nhất quán.': (
      vi: 'Thuật ngữ lâm sàng và cơ sinh học được giữ nhất quán.',
      en: 'Clinical and biomechanical terminology remains consistent.'
    ),
    'Lựa chọn được lưu tự động.': (
      vi: 'Lựa chọn được lưu tự động.',
      en: 'Your choice is saved automatically.'
    ),
    'Tiếng Việt': (vi: 'Tiếng Việt', en: 'Vietnamese'),
    'English': (vi: 'English', en: 'English'),
    'ĐÓNG': (vi: 'ĐÓNG', en: 'CLOSE'),
    'HỦY': (vi: 'HỦY', en: 'CANCEL'),
    'HỦY BỎ': (vi: 'HỦY BỎ', en: 'CANCEL'),
    'ÁP DỤNG': (vi: 'ÁP DỤNG', en: 'APPLY'),
    'Làm lại': (vi: 'Làm lại', en: 'Retry'),
    'Thu gọn': (vi: 'Thu gọn', en: 'Compact view'),
    'Phóng to': (vi: 'Phóng to', en: 'Enlarge'),
    'Đóng thông báo': (vi: 'Đóng thông báo', en: 'Dismiss notification'),
    'Sao chép dữ liệu JSON kèm nguồn gốc': (
      vi: 'Sao chép dữ liệu JSON kèm nguồn gốc',
      en: 'Copy JSON data with provenance'
    ),
    'Chọn nội dung phân tích': (
      vi: 'Chọn nội dung phân tích',
      en: 'Choose analysis content'
    ),
    'Về màn Scan': (vi: 'Về màn ghi dữ liệu', en: 'Back to acquisition'),
    'Trở lại bản phân tích': (
      vi: 'Trở lại bản phân tích',
      en: 'Return to analysis'
    ),
    'Trình bày báo cáo': (vi: 'Trình bày báo cáo', en: 'Present report'),
    'Tác vụ khác': (vi: 'Tác vụ khác', en: 'More actions'),
    'Pause': (vi: 'Tạm dừng', en: 'Pause'),
    'Play': (vi: 'Phát', en: 'Play'),
    'Mở thư viện phiên ghi': (
      vi: 'Mở thư viện phiên ghi',
      en: 'Open acquisition library'
    ),
    'Nạp lại danh sách': (vi: 'Nạp lại danh sách', en: 'Reload list'),
    'Thu gọn thư viện phiên ghi': (
      vi: 'Thu gọn thư viện phiên ghi',
      en: 'Collapse acquisition library'
    ),
    'Xóa trọn bộ video': (
      vi: 'Xóa trọn bộ video',
      en: 'Delete complete video set'
    ),
    'Quay lại Hồ sơ bệnh nhân': (
      vi: 'Quay lại hồ sơ người bệnh',
      en: 'Back to patient records'
    ),
    'Phát mẫu tham chiếu ở màn Scan': (
      vi: 'Phát mẫu tham chiếu tại màn ghi dữ liệu',
      en: 'Play the reference in acquisition view'
    ),
    'Mở menu': (vi: 'Mở menu', en: 'Open menu'),
    'Đóng menu': (vi: 'Đóng menu', en: 'Close menu'),
    'Về camera thật': (vi: 'Về camera trực tiếp', en: 'Return to live camera'),
    'Mở video mẫu': (vi: 'Mở video tham chiếu', en: 'Open reference video'),
    'Chọn mẫu để xem hoặc chuyển về camera thật': (
      vi: 'Chọn mẫu để xem hoặc chuyển về camera trực tiếp',
      en: 'Choose a reference or return to live camera'
    ),
    'Lùi 5 giây': (vi: 'Lùi 5 giây', en: 'Back 5 seconds'),
    'Tạm dừng': (vi: 'Tạm dừng', en: 'Pause'),
    'Phát': (vi: 'Phát', en: 'Play'),
    'Tiến 5 giây': (vi: 'Tiến 5 giây', en: 'Forward 5 seconds'),
    'Làm mượt đường biểu đồ camera và FSR ở mọi tab. Không đổi dữ liệu lưu, peak hoặc bảng chỉ số. Tắt để bỏ lọc hiển thị; không tắt tiền xử lý cảm biến.':
        (
      vi: 'Làm mượt đường biểu đồ camera và FSR ở mọi mục. Không thay đổi dữ liệu lưu, giá trị đỉnh hoặc bảng chỉ số. Tắt để bỏ lọc hiển thị; không tắt bước tiền xử lý cảm biến.',
      en: 'Smooth camera and FSR chart lines throughout the application. Stored measurements, peak values, and metric tables remain unchanged. Turn off to remove display filtering; sensor preprocessing remains active.'
    ),

    // Primary workflow.
    '1. Hồ sơ bệnh nhân': (vi: '1. Hồ sơ người bệnh', en: '1. Patient records'),
    '2. Chuẩn bị phiên khám': (
      vi: '2. Chuẩn bị phiên đánh giá',
      en: '2. Assessment setup'
    ),
    '3. Quét & Ghi hình': (
      vi: '3. Ghi dữ liệu và video',
      en: '3. Data and video acquisition'
    ),
    '4. Phân tích dáng đi': (
      vi: '4. Phân tích dáng đi',
      en: '4. Gait analysis'
    ),
    '5. Lịch sử & So sánh': (
      vi: '5. Lịch sử và so sánh',
      en: '5. History and comparison'
    ),
    'Hồ sơ bệnh nhân': (vi: 'Hồ sơ người bệnh', en: 'Patient records'),
    'Tìm kiếm bệnh nhân...': (
      vi: 'Tìm kiếm người bệnh...',
      en: 'Search patients...'
    ),
    'Vui lòng chọn hoặc thêm bệnh nhân để tiếp tục': (
      vi: 'Vui lòng chọn hoặc thêm người bệnh để tiếp tục',
      en: 'Select or add a patient to continue'
    ),
    'Hành động kiểm tra lâm sàng': (
      vi: 'Thao tác đánh giá lâm sàng',
      en: 'Clinical assessment actions'
    ),
    'Bệnh nhân gần đây': (vi: 'Người bệnh gần đây', en: 'Recent patients'),
    'Không tìm thấy kết quả': (
      vi: 'Không tìm thấy kết quả',
      en: 'No matching patients'
    ),
    'Chưa có bệnh nhân nào': (vi: 'Chưa có người bệnh', en: 'No patients yet'),
    'Mã định danh bệnh án': (vi: 'Mã định danh hồ sơ', en: 'Patient record ID'),
    'Tuổi': (vi: 'Tuổi', en: 'Age'),
    'Chiều cao': (vi: 'Chiều cao', en: 'Height'),
    'Cân nặng': (vi: 'Cân nặng', en: 'Weight'),
    'Dài chân trái': (vi: 'Chiều dài chân trái', en: 'Left leg length'),
    'Dài chân phải': (vi: 'Chiều dài chân phải', en: 'Right leg length'),
    'Chưa đo': (vi: 'Chưa đo', en: 'Not measured'),
    'Chân lành sinh học': (
      vi: 'Chân lành sinh học',
      en: 'Sound biological foot'
    ),
    'Chân giả lắp đặt': (vi: 'Bên lắp chân giả', en: 'Prosthetic side'),
    'Chân Trái (L)': (vi: 'Chân trái (L)', en: 'Left foot (L)'),
    'Chân Phải (R)': (vi: 'Chân phải (R)', en: 'Right foot (R)'),
    'Chưa có thông tin tiền sử bệnh lý.': (
      vi: 'Chưa có thông tin tiền sử bệnh lý.',
      en: 'No medical history has been recorded.'
    ),
    'Chưa có thông tin mục tiêu điều trị.': (
      vi: 'Chưa có thông tin mục tiêu phục hồi.',
      en: 'No rehabilitation goals have been recorded.'
    ),
    'Bắt đầu phiên kiểm định mới': (
      vi: 'Bắt đầu phiên đánh giá mới',
      en: 'Start a new assessment session'
    ),
    'BẮT ĐẦU PHIÊN KHÁM MỚI': (
      vi: 'BẮT ĐẦU PHIÊN ĐÁNH GIÁ MỚI',
      en: 'START NEW ASSESSMENT'
    ),
    'Khởi tạo phiên kiểm định mới thành công! Đang chuyển hướng...': (
      vi: 'Đã tạo phiên đánh giá mới. Đang chuyển màn hình...',
      en: 'New assessment created. Opening setup...'
    ),
    'Tạo hồ sơ bệnh án thành công!': (
      vi: 'Đã tạo hồ sơ người bệnh.',
      en: 'Patient record created.'
    ),
    'Thêm bệnh án mới': (vi: 'Thêm hồ sơ người bệnh', en: 'Add patient record'),
    'TẠO BỆNH ÁN': (vi: 'TẠO HỒ SƠ', en: 'CREATE RECORD'),
    'Thông tin Cơ sở dữ liệu': (
      vi: 'Thông tin cơ sở dữ liệu',
      en: 'Database information'
    ),
    'Kết nối Cơ sở dữ liệu SQLite': (
      vi: 'Kết nối cơ sở dữ liệu SQLite',
      en: 'SQLite database connection'
    ),
    'Công nghệ lưu trữ': (vi: 'Công nghệ lưu trữ', en: 'Storage technology'),
    'Vị trí Tệp dữ liệu': (vi: 'Vị trí tệp dữ liệu', en: 'Data file location'),
    'Bảng lưu trữ': (vi: 'Bảng dữ liệu', en: 'Database tables'),
    'Trạng thái kết nối': (vi: 'Trạng thái kết nối', en: 'Connection status'),
    'Số hồ sơ bệnh án hiện tại': (
      vi: 'Số hồ sơ hiện có',
      en: 'Current patient records'
    ),
    'Chuẩn bị phiên khám': (
      vi: 'Chuẩn bị phiên đánh giá',
      en: 'Assessment setup'
    ),
    'Vui lòng tạo phiên khám mới ở Tab Bệnh nhân.': (
      vi: 'Vui lòng tạo phiên đánh giá mới tại mục Hồ sơ người bệnh.',
      en: 'Create a new assessment session from Patient records.'
    ),
    'Tab 6: Chọn bài tập (Để sau)': (
      vi: 'Mục 6: Chọn bài tập (sắp có)',
      en: 'Section 6: Exercise selection (coming soon)'
    ),
    'Tab 7: Luyện tập phục hồi (Để sau)': (
      vi: 'Mục 7: Luyện tập phục hồi (sắp có)',
      en: 'Section 7: Rehabilitation training (coming soon)'
    ),
    'Tab 8: Tổng kết luyện tập (Để sau)': (
      vi: 'Mục 8: Tổng kết luyện tập (sắp có)',
      en: 'Section 8: Training summary (coming soon)'
    ),

    // Clinical profile terminology.
    'Chân lành': (vi: 'Chân lành', en: 'Sound foot'),
    'Chân giả': (vi: 'Chân giả', en: 'Prosthetic foot'),
    'Chân trái': (vi: 'Chân trái', en: 'Left foot'),
    'Chân phải': (vi: 'Chân phải', en: 'Right foot'),
    'Trái (Left)': (vi: 'Trái (L)', en: 'Left (L)'),
    'Phải (Right)': (vi: 'Phải (R)', en: 'Right (R)'),
    'Trái (L)': (vi: 'Trái (L)', en: 'Left (L)'),
    'Phải (R)': (vi: 'Phải (R)', en: 'Right (R)'),
    'Chân lành sinh học:': (
      vi: 'Chân lành sinh học:',
      en: 'Sound biological foot:'
    ),
    'Chân giả lắp đặt:': (vi: 'Bên lắp chân giả:', en: 'Prosthetic side:'),
    'Tiền sử bệnh lý & Chấn thương': (
      vi: 'Tiền sử bệnh lý và chấn thương',
      en: 'Medical and injury history'
    ),
    'Tiền sử chấn thương & Bệnh lý': (
      vi: 'Tiền sử chấn thương và bệnh lý',
      en: 'Injury and medical history'
    ),
    'Mục tiêu điều trị & Căn chỉnh van': (
      vi: 'Mục tiêu phục hồi và căn chỉnh',
      en: 'Rehabilitation and alignment goals'
    ),
    'Mục tiêu phục hồi / Điều chỉnh van': (
      vi: 'Mục tiêu phục hồi / Căn chỉnh',
      en: 'Rehabilitation / alignment goals'
    ),
    'Nhật ký Ghi chú Lâm sàng': (
      vi: 'Nhật ký ghi chú lâm sàng',
      en: 'Clinical notes log'
    ),
    'Tiền sử': (vi: 'Tiền sử', en: 'History'),
    'Triệu chứng': (vi: 'Triệu chứng', en: 'Symptoms'),
    'Lưu hồ sơ & số đo': (
      vi: 'Lưu hồ sơ và số đo',
      en: 'Save record and measurements'
    ),
    'Họ và tên bệnh nhân *': (
      vi: 'Họ và tên người bệnh *',
      en: 'Patient full name *'
    ),
    'Nhập họ tên đầy đủ': (vi: 'Nhập họ tên đầy đủ', en: 'Enter the full name'),
    'Tuổi *': (vi: 'Tuổi *', en: 'Age *'),
    'Chiều cao (cm) *': (vi: 'Chiều cao (cm) *', en: 'Height (cm) *'),
    'Cân nặng (kg) *': (vi: 'Cân nặng (kg) *', en: 'Weight (kg) *'),
    'Dài chân trái (cm) *': (
      vi: 'Chiều dài chân trái (cm) *',
      en: 'Left leg length (cm) *'
    ),
    'Dài chân phải (cm) *': (
      vi: 'Chiều dài chân phải (cm) *',
      en: 'Right leg length (cm) *'
    ),
    'Hông đến mắt cá': (vi: 'Từ hông đến mắt cá', en: 'Hip to ankle'),
    'Số đo dùng để hiệu chuẩn camera': (
      vi: 'Số đo dùng để hiệu chuẩn camera',
      en: 'Measurements used for camera calibration'
    ),
    'Họ tên không được để trống': (
      vi: 'Vui lòng nhập họ tên',
      en: 'Full name is required'
    ),
    'Tên quá ngắn (tối thiểu 3 ký tự)': (
      vi: 'Tên quá ngắn (tối thiểu 3 ký tự)',
      en: 'Name is too short (minimum 3 characters)'
    ),
    'Yêu cầu nhập tuổi': (vi: 'Vui lòng nhập tuổi', en: 'Age is required'),
    'Tuổi từ 1 - 120': (
      vi: 'Tuổi phải từ 1 đến 120',
      en: 'Age must be between 1 and 120'
    ),
    'Yêu cầu nhập chiều cao': (
      vi: 'Vui lòng nhập chiều cao',
      en: 'Height is required'
    ),
    'Chiều cao 30 - 250 cm': (
      vi: 'Chiều cao phải từ 30 đến 250 cm',
      en: 'Height must be between 30 and 250 cm'
    ),
    'Yêu cầu nhập cân nặng': (
      vi: 'Vui lòng nhập cân nặng',
      en: 'Weight is required'
    ),
    'Cân nặng 2 - 250 kg': (
      vi: 'Cân nặng phải từ 2 đến 250 kg',
      en: 'Weight must be between 2 and 250 kg'
    ),

    // Acquisition and camera terminology.
    'CÀI CAMERA': (vi: 'CÀI ĐẶT CAMERA', en: 'CAMERA SETUP'),
    'Thiết lập camera': (vi: 'Thiết lập camera', en: 'Camera setup'),
    'Thiết lập camera trước Scan': (
      vi: 'Thiết lập camera trước khi ghi',
      en: 'Camera setup before acquisition'
    ),
    'Hiệu chuẩn hình học 2 camera': (
      vi: 'Hiệu chuẩn hình học hai camera',
      en: 'Dual-camera geometric calibration'
    ),
    'Tính calibration': (
      vi: 'Tính thông số hiệu chuẩn',
      en: 'Compute calibration'
    ),
    'Camera chính diện': (vi: 'Camera chính diện', en: 'Frontal camera'),
    'Camera mặt phẳng dọc': (
      vi: 'Camera mặt phẳng dọc',
      en: 'Sagittal-view camera'
    ),
    'Chọn camera cho góc chính diện và mặt phẳng dọc. Có thể đổi ngay trong phiên; hai luồng hình sẽ tạm dừng vài giây khi áp dụng.':
        (
      vi: 'Chọn camera cho góc chính diện và mặt phẳng dọc. Có thể đổi ngay trong phiên; hai luồng hình sẽ tạm dừng vài giây khi áp dụng.',
      en: 'Assign the frontal and sagittal cameras. Camera roles can be changed during the session; both video streams pause briefly while the configuration is applied.'
    ),
    'Chân trái (cm)': (vi: 'Chân trái (cm)', en: 'Left leg (cm)'),
    'Chân phải (cm)': (vi: 'Chân phải (cm)', en: 'Right leg (cm)'),
    'Hông–mắt cá': (vi: 'Hông–mắt cá', en: 'Hip–ankle'),
    'Nhập thông tin chấn thương, năm phẫu thuật, tình trạng mỏm cụt...': (
      vi: 'Nhập thông tin chấn thương, năm phẫu thuật, tình trạng mỏm cụt...',
      en: 'Enter injury details, surgery year, and amputation stump condition...'
    ),
    'Mục tiêu căn chỉnh van (ví dụ: Giảm khập khiễng, tăng đối xứng lực...)': (
      vi: 'Mục tiêu căn chỉnh (ví dụ: giảm khập khiễng, tăng đối xứng tải...)',
      en: 'Alignment goals (for example: reduce limping, improve load symmetry...)'
    ),
    'Nhập ghi chú hoặc biểu hiện lâm sàng mới...': (
      vi: 'Nhập ghi chú hoặc biểu hiện lâm sàng mới...',
      en: 'Enter a new clinical note or finding...'
    ),
    'Camera thật': (vi: 'Camera trực tiếp', en: 'Live camera'),
    'Chụp mẫu': (vi: 'Ghi mẫu', en: 'Capture sample'),
    'Thu video mẫu tham chiếu': (
      vi: 'Thu video tham chiếu',
      en: 'Acquire reference video'
    ),
    'Video mẫu': (vi: 'Video tham chiếu', en: 'Reference video'),
    'LƯU VIDEO MẪU': (vi: 'LƯU VIDEO THAM CHIẾU', en: 'SAVE REFERENCE VIDEO'),
    'TẠO PHIÊN MẪU': (
      vi: 'TẠO PHIÊN THAM CHIẾU',
      en: 'CREATE REFERENCE SESSION'
    ),
    'Theo video': (vi: 'Theo video', en: 'Follow video'),
    'Thời gian video (giây)': (
      vi: 'Thời gian video (giây)',
      en: 'Video time (seconds)'
    ),
    'Thời gian cửa sổ (s)': (
      vi: 'Độ dài cửa sổ (s)',
      en: 'Window duration (s)'
    ),
    'DỪNG GHI': (vi: 'DỪNG GHI', en: 'STOP ACQUISITION'),
    'XÓA BỘ VIDEO': (vi: 'XÓA BỘ VIDEO', en: 'DELETE VIDEO SET'),
    'Xóa bộ video đã ghi?': (
      vi: 'Xóa bộ video đã ghi?',
      en: 'Delete the recorded video set?'
    ),
    'Không có video': (vi: 'Không có video', en: 'No video available'),
    'Video playback is not supported': (
      vi: 'Nền tảng không hỗ trợ phát video',
      en: 'Video playback is not supported'
    ),
    'Platform not supported': (
      vi: 'Nền tảng không được hỗ trợ',
      en: 'Platform not supported'
    ),
    '2 camera + khung xương + FSR · 0,8×': (
      vi: 'Hai camera + khung xương + FSR · 0,8×',
      en: 'Dual camera + pose skeleton + FSR · 0.8×'
    ),

    // Gait and biomechanics terminology from the supplied report.
    'Phân tích dáng đi': (vi: 'Phân tích dáng đi', en: 'Gait analysis'),
    'Chu kỳ dáng đi': (vi: 'Chu kỳ dáng đi', en: 'Gait cycle'),
    'Thì trụ': (vi: 'Thì trụ', en: 'Stance phase'),
    'Pha chống đỡ (%)': (vi: 'Thì trụ (%)', en: 'Stance phase (%)'),
    '% pha chuyển động của bước': (
      vi: '% chu kỳ dáng đi chuẩn hóa',
      en: 'Normalized gait cycle (%)'
    ),
    '% chu kỳ camera chuẩn hóa': (
      vi: '% chu kỳ camera chuẩn hóa',
      en: 'Normalized camera cycle (%)'
    ),
    'Đáp ứng tải': (vi: 'Đáp ứng tải', en: 'Loading response'),
    'Giữa thì trụ': (vi: 'Giữa thì trụ', en: 'Mid-stance'),
    'Cuối thì trụ': (vi: 'Cuối thì trụ', en: 'Terminal stance'),
    'Tiền đu đưa': (vi: 'Tiền đu đưa', en: 'Pre-swing'),
    'Gót': (vi: 'Gót', en: 'Heel'),
    'Giữa': (vi: 'Giữa', en: 'Midfoot'),
    'Trước': (vi: 'Trước', en: 'Forefoot'),
    'VÙNG BÀN CHÂN': (vi: 'VÙNG BÀN CHÂN', en: 'PLANTAR REGIONS'),
    'BẢN ĐỒ ÁP LỰC TỨC THỜI': (
      vi: 'BẢN ĐỒ ÁP LỰC TỨC THỜI',
      en: 'REAL-TIME PLANTAR PRESSURE MAP'
    ),
    'Tổng lực từng chân': (
      vi: 'Tổng lực từng chân',
      en: 'Total force per foot'
    ),
    'Lực vùng gót': (vi: 'Lực vùng gót', en: 'Heel force'),
    'Lực vùng giữa bàn chân': (
      vi: 'Lực vùng giữa bàn chân',
      en: 'Midfoot force'
    ),
    'Dữ liệu hai chân': (vi: 'Dữ liệu hai chân', en: 'Bilateral data'),
    'Peak tổng lực': (vi: 'Đỉnh tổng lực', en: 'Peak total force'),
    'Peak vùng gót': (vi: 'Đỉnh lực vùng gót', en: 'Peak heel force'),
    'Peak vùng giữa bàn chân': (
      vi: 'Đỉnh lực vùng giữa bàn chân',
      en: 'Peak midfoot force'
    ),
    'Peak Fore (mũi / đẩy chân)': (
      vi: 'Đỉnh lực vùng mũi bàn chân',
      en: 'Peak forefoot force'
    ),
    'Peak Fore (mũi / đáy chân)': (
      vi: 'Đỉnh lực vùng mũi bàn chân',
      en: 'Peak forefoot force'
    ),
    'Lực trung bình pha chống': (
      vi: 'Lực trung bình thì trụ',
      en: 'Mean stance-phase force'
    ),
    'Xung lực tải': (vi: 'Xung lực tải', en: 'Loading impulse'),
    'Xung force loading': (vi: 'Xung lực tải', en: 'Loading impulse'),
    'cân bằng': (vi: 'cân bằng', en: 'balanced'),
    'Trái · dải hiển thị': (vi: 'Trái · dải hiển thị', en: 'Left foot · ± SD'),
    'Phải · dải hiển thị': (vi: 'Phải · dải hiển thị', en: 'Right foot · ± SD'),
    'Lực vùng trước bàn chân': (
      vi: 'Lực vùng trước bàn chân',
      en: 'Forefoot force'
    ),
    'Lực FSR': (vi: 'Lực FSR', en: 'FSR force'),
    'Đang tải dữ liệu lực…': (
      vi: 'Đang tải dữ liệu lực…',
      en: 'Loading force data…'
    ),
    'Chưa có mẫu FSR ở thời điểm này': (
      vi: 'Chưa có mẫu FSR tại thời điểm này',
      en: 'No FSR sample is available at this time point'
    ),
    'Chưa đủ dữ liệu bước FSR': (
      vi: 'Chưa đủ dữ liệu bước FSR',
      en: 'Insufficient FSR step data'
    ),
    'BẢNG SO SÁNH LỰC FSR TRÁI–PHẢI': (
      vi: 'BẢNG SO SÁNH LỰC FSR TRÁI–PHẢI',
      en: 'LEFT–RIGHT FSR FORCE COMPARISON'
    ),
    'Thời gian trực tiếp (s)': (
      vi: 'Thời gian trực tiếp (s)',
      en: 'Live time (s)'
    ),
    'Góc khớp': (vi: 'Góc khớp', en: 'Joint angles'),
    'Góc gối': (vi: 'Góc gối', en: 'Knee angle'),
    'Góc hông': (vi: 'Góc hông', en: 'Hip angle'),
    'Góc nghiêng thân': (vi: 'Góc nghiêng thân', en: 'Trunk lean angle'),
    'Góc nghiêng chậu': (vi: 'Góc nghiêng chậu', en: 'Pelvic tilt'),
    'Góc gập lớn nhất (Flexion)': (
      vi: 'Góc gập lớn nhất',
      en: 'Peak flexion angle'
    ),
    'Góc duỗi thẳng nhất (Extension)': (
      vi: 'Góc duỗi lớn nhất',
      en: 'Peak extension angle'
    ),
    'ROM Gập duỗi gối': (
      vi: 'Biên độ vận động khớp gối (ROM)',
      en: 'Knee range of motion (ROM)'
    ),
    'Độ dao động hông (Pelvic Sway)': (
      vi: 'Độ dao động vùng chậu',
      en: 'Pelvic sway'
    ),
    'Nghiêng trước–sau': (
      vi: 'Nghiêng trước–sau',
      en: 'Anterior–posterior lean'
    ),
    'Nghiêng trái–phải': (vi: 'Nghiêng trái–phải', en: 'Medial–lateral lean'),
    'Trục thân trung tâm': (
      vi: 'Trục thân trung tâm',
      en: 'Central trunk axis'
    ),
    'ĐỘNG HỌC TỪ CAMERA': (
      vi: 'ĐỘNG HỌC TỪ CAMERA',
      en: 'CAMERA-DERIVED KINEMATICS'
    ),
    'BIỂU ĐỒ CHU KỲ': (vi: 'BIỂU ĐỒ CHU KỲ', en: 'CYCLE WAVEFORMS'),
    'Bảng thống kê chu kỳ camera': (
      vi: 'Bảng thống kê chu kỳ camera',
      en: 'Camera cycle statistics'
    ),
    'SAO CHÉP BẢNG': (vi: 'SAO CHÉP BẢNG', en: 'COPY TABLE'),
    'Đã sao chép bảng thống kê camera.': (
      vi: 'Đã sao chép bảng thống kê camera.',
      en: 'Camera statistics table copied.'
    ),
    'Không đủ chu kỳ trong clip': (
      vi: 'Không đủ chu kỳ trong đoạn video',
      en: 'Insufficient gait cycles in this clip'
    ),
    'Chưa đủ dữ liệu camera tại cặp này.': (
      vi: 'Chưa đủ dữ liệu camera cho cặp bước này.',
      en: 'Insufficient camera data for this step pair.'
    ),
    'So sánh từng cặp bước trái–phải': (
      vi: 'So sánh từng cặp bước trái–phải',
      en: 'Left–right step-pair comparison'
    ),
    'Đủ cặp tiếp theo sẽ tự chuyển': (
      vi: 'Tự chuyển khi đủ cặp bước tiếp theo',
      en: 'Advances automatically when the next pair is complete'
    ),
    'Thăng bằng': (vi: 'Thăng bằng', en: 'Balance'),
    'Nhịp bước (Cadence)': (vi: 'Nhịp bước', en: 'Cadence'),
    'NHỊP ĐIỆU': (vi: 'NHỊP BƯỚC', en: 'CADENCE'),
    'Sải chân ước tính (Stride Length)': (
      vi: 'Chiều dài sải chân ước tính',
      en: 'Estimated stride length'
    ),
    'SẢI CHÂN ƯỚC TÍNH': (
      vi: 'CHIỀU DÀI SẢI CHÂN ƯỚC TÍNH',
      en: 'ESTIMATED STRIDE LENGTH'
    ),
    'chưa hiệu chuẩn thước đo mặt sàn': (
      vi: 'chưa hiệu chuẩn theo thước đo mặt sàn',
      en: 'not calibrated against a floor scale'
    ),
    'ĐỐI XỨNG GỐI': (vi: 'ĐỐI XỨNG KHỚP GỐI', en: 'KNEE SYMMETRY'),
    'ĐỐI XỨNG INSOLE': (
      vi: 'ĐỐI XỨNG TẢI BÀN CHÂN',
      en: 'PLANTAR LOAD SYMMETRY'
    ),
    'tải trái–phải': (vi: 'tải tì trái–phải', en: 'left–right plantar loading'),
    'chưa có FSR': (vi: 'chưa có dữ liệu FSR', en: 'no FSR data'),
    'Có cờ mỏi cơ': (
      vi: 'Phát hiện dấu hiệu mỏi',
      en: 'Fatigue indicator detected'
    ),
    'Đầy đủ': (vi: 'Đầy đủ', en: 'Full view'),
    'Dữ liệu chuẩn': (vi: 'Dữ liệu tham chiếu', en: 'Reference data'),
    'Gối · đỉnh gập': (vi: 'Gối · đỉnh gập', en: 'Knee · peak flexion'),
    'Gối · góc cực tiểu': (
      vi: 'Gối · góc cực tiểu',
      en: 'Knee · minimum angle'
    ),
    'Gối · ROM': (vi: 'Gối · ROM', en: 'Knee · ROM'),
    'Hông · đỉnh gập': (vi: 'Hông · đỉnh gập', en: 'Hip · peak flexion'),
    'Hông · ROM': (vi: 'Hông · ROM', en: 'Hip · ROM'),
    'Thân trái–phải · lệch trung bình': (
      vi: 'Thân trái–phải · lệch trung bình',
      en: 'Medial–lateral trunk · mean deviation'
    ),
    'Thân trái–phải · đỉnh tuyệt đối': (
      vi: 'Thân trái–phải · đỉnh tuyệt đối',
      en: 'Medial–lateral trunk · absolute peak'
    ),
    'Thời gian chu kỳ': (vi: 'Thời gian chu kỳ', en: 'Cycle duration'),
    'Trục thân trung tâm · Mean': (
      vi: 'Trục thân trung tâm · Mean',
      en: 'Central trunk axis · Mean'
    ),
    'Trục thân · ±1 SD': (vi: 'Trục thân · ±1 SD', en: 'Trunk axis · ±1 SD'),
    'Dương: nghiêng về phía trước · Âm: nghiêng về phía sau': (
      vi: 'Dương: nghiêng về phía trước · Âm: nghiêng về phía sau',
      en: 'Positive: anterior lean · Negative: posterior lean'
    ),
    'Dương: phải · Âm: trái (theo người được đo)': (
      vi: 'Dương: phải · Âm: trái (theo người được đo)',
      en: 'Positive: right · Negative: left (participant perspective)'
    ),
    'Lực (N)': (vi: 'Lực (N)', en: 'Force (N)'),

    // Analysis, comparison and reports.
    'PHÂN TÍCH LẠI': (vi: 'PHÂN TÍCH LẠI', en: 'REANALYZE'),
    'Phân tích lại bằng thuật toán hiện tại?': (
      vi: 'Phân tích lại bằng thuật toán hiện tại?',
      en: 'Reanalyze using the current algorithm?'
    ),
    'XEM PHÂN TÍCH': (vi: 'XEM PHÂN TÍCH', en: 'VIEW ANALYSIS'),
    'ÁP DỤNG & MỞ SCAN': (
      vi: 'ÁP DỤNG VÀ MỞ LẦN GHI',
      en: 'APPLY AND OPEN ACQUISITION'
    ),
    'CHI TIẾT TINH CHỈNH KỸ THUẬT': (
      vi: 'CHI TIẾT CĂN CHỈNH KỸ THUẬT',
      en: 'TECHNICAL ALIGNMENT DETAILS'
    ),
    'Chỉ số khớp chân giả': (
      vi: 'Chỉ số khớp chân giả',
      en: 'Prosthetic-joint metrics'
    ),
    'Đã chỉnh → Quét lại': (
      vi: 'Đã căn chỉnh → Ghi lại',
      en: 'Adjusted → Reacquire'
    ),
    'Trước chỉnh (Scan #1)': (
      vi: 'Trước căn chỉnh (lần ghi 1)',
      en: 'Pre-alignment (acquisition 1)'
    ),
    'Sau chỉnh (Scan #2)': (
      vi: 'Sau căn chỉnh (lần ghi 2)',
      en: 'Post-alignment (acquisition 2)'
    ),
    'Lịch sử phiên khám': (
      vi: 'Lịch sử phiên đánh giá',
      en: 'Assessment history'
    ),
    'Chưa có lịch sử phiên khám nào': (
      vi: 'Chưa có lịch sử phiên đánh giá',
      en: 'No assessment history is available'
    ),
    'BẢNG ĐỐI CHIẾU SO SÁNH TRƯỚC VÀ SAU CĂN CHỈNH': (
      vi: 'BẢNG SO SÁNH TRƯỚC VÀ SAU CĂN CHỈNH',
      en: 'PRE- AND POST-ALIGNMENT COMPARISON'
    ),
    'XUẤT BÁO CÁO (PDF)': (vi: 'XUẤT BÁO CÁO (PDF)', en: 'EXPORT REPORT (PDF)'),
    'Xuất Báo Cáo Lâm Sàng (PDF)': (
      vi: 'Xuất báo cáo lâm sàng (PDF)',
      en: 'Export clinical report (PDF)'
    ),
    'IN / XUẤT BÁO CÁO': (vi: 'IN / XUẤT BÁO CÁO', en: 'PRINT / EXPORT REPORT'),
    'Report': (vi: 'Báo cáo', en: 'Report'),
    'Thiếu dữ liệu so sánh': (
      vi: 'Thiếu dữ liệu so sánh',
      en: 'Insufficient comparison data'
    ),
    'Ghi chú điều chỉnh thực tế:': (
      vi: 'Ghi chú căn chỉnh thực tế:',
      en: 'Actual alignment notes:'
    ),
    'Không có ghi chú nào.': (
      vi: 'Không có ghi chú.',
      en: 'No notes available.'
    ),
    'ĐỐI CHIẾU CHỈ SỐ ROM': (
      vi: 'SO SÁNH BIÊN ĐỘ VẬN ĐỘNG (ROM)',
      en: 'RANGE-OF-MOTION COMPARISON'
    ),
    'CHẨN ĐOÁN LÂM SÀNG CẢI THIỆN': (
      vi: 'NHẬN ĐỊNH CẢI THIỆN LÂM SÀNG',
      en: 'CLINICAL IMPROVEMENT ASSESSMENT'
    ),
    'VỀ HỒ SƠ BỆNH NHÂN': (
      vi: 'VỀ HỒ SƠ NGƯỜI BỆNH',
      en: 'BACK TO PATIENT RECORDS'
    ),

    // Complete acquisition, realtime, chart and notification coverage.
    'BIỂU ĐỒ REALTIME': (vi: 'BIỂU ĐỒ THỜI GIAN THỰC', en: 'REAL-TIME CHARTS'),
    'Phân bố áp lực FSR': (
      vi: 'Phân bố áp lực FSR',
      en: 'FSR pressure distribution'
    ),
    'Mức tải vùng gót': (vi: 'Mức tải vùng gót', en: 'Heel loading'),
    'Mức tải vùng giữa bàn chân': (
      vi: 'Mức tải vùng giữa bàn chân',
      en: 'Midfoot loading'
    ),
    'Mức tải vùng trước bàn chân': (
      vi: 'Mức tải vùng trước bàn chân',
      en: 'Forefoot loading'
    ),
    'Lực FSR 3 pha · chân trái/phải': (
      vi: 'Lực FSR ba vùng · chân trái/phải',
      en: 'Three-region FSR force · left/right feet'
    ),
    'Độ cao nhấc bàn chân': (vi: 'Độ cao nhấc bàn chân', en: 'Foot clearance'),
    'Lực từng chân và tổng lực': (
      vi: 'Lực từng chân và tổng lực',
      en: 'Individual-foot and total force'
    ),
    'Dữ liệu cân nặng': (vi: 'Dữ liệu theo cân nặng', en: 'Weight-scaled data'),
    'Dữ liệu mẫu': (vi: 'Dữ liệu mẫu', en: 'Sample data'),
    'Dữ liệu': (vi: 'Dữ liệu', en: 'Data'),
    'Đang nhận': (vi: 'Đang nhận', en: 'Receiving'),
    'FSR 1/2 chân': (vi: 'FSR 1/2 chân', en: 'FSR: one/two feet'),
    'Chưa có dữ liệu': (vi: 'Chưa có dữ liệu', en: 'No data'),
    'Backend chưa kết nối': (
      vi: 'Máy chủ chưa kết nối',
      en: 'Backend disconnected'
    ),
    'Đang thu chuyển động': (
      vi: 'Đang thu chuyển động',
      en: 'Capturing motion'
    ),
    'Chưa thấy toàn thân': (
      vi: 'Chưa thấy toàn thân',
      en: 'Full body not detected'
    ),
    '% thì trụ': (vi: '% thì trụ', en: 'Stance phase (%)'),
    '% pha bước chuẩn hóa': (
      vi: '% chu kỳ bước chuẩn hóa',
      en: 'Normalized gait cycle (%)'
    ),
    'Thời gian realtime (giây) · 3 giây gần nhất': (
      vi: 'Thời gian thực (giây) · 3 giây gần nhất',
      en: 'Real-time duration (seconds) · latest 3 seconds'
    ),
    'Góc gối (°) · 0° = duỗi thẳng': (
      vi: 'Góc gối (°) · 0° = duỗi thẳng',
      en: 'Knee angle (°) · 0° = full extension'
    ),
    'Góc hông (°) · góc đùi–thân 2D': (
      vi: 'Góc hông (°) · góc đùi–thân 2D',
      en: 'Hip angle (°) · 2D thigh–trunk angle'
    ),
    'Góc nghiêng thân (°) · trước–sau': (
      vi: 'Góc nghiêng thân (°) · trước–sau',
      en: 'Trunk lean angle (°) · anterior–posterior'
    ),
    'Góc nghiêng thân (°) · trái–phải': (
      vi: 'Góc nghiêng thân (°) · trái–phải',
      en: 'Trunk lean angle (°) · medial–lateral'
    ),
    'Chưa đủ một cặp bước trái–phải hợp lệ.': (
      vi: 'Chưa đủ một cặp bước trái–phải hợp lệ.',
      en: 'No valid left–right step pair is available yet.'
    ),
    'Chưa có dữ liệu realtime.': (
      vi: 'Chưa có dữ liệu thời gian thực.',
      en: 'No real-time data is available.'
    ),
    'VỀ CAMERA THẬT': (vi: 'VỀ CAMERA TRỰC TIẾP', en: 'BACK TO LIVE CAMERA'),
    'VIDEO MẪU': (vi: 'VIDEO THAM CHIẾU', en: 'REFERENCE VIDEO'),
    'TRẢ LẠI CAM': (vi: 'KHÔI PHỤC CAMERA', en: 'RESTORE CAMERAS'),
    'ĐẢO CAM 1 ↔ 2': (vi: 'ĐỔI CAMERA 1 ↔ 2', en: 'SWAP CAMERAS 1 ↔ 2'),
    'STEREO 3D ĐÃ CHUẨN': (
      vi: 'STEREO 3D ĐÃ HIỆU CHUẨN',
      en: '3D STEREO CALIBRATED'
    ),
    'HIỆU CHUẨN 3D': (vi: 'HIỆU CHUẨN 3D', en: '3D CALIBRATION'),
    '2 CAM ĐÃ SYNC': (
      vi: 'HAI CAMERA ĐÃ ĐỒNG BỘ',
      en: 'DUAL CAMERAS SYNCHRONIZED'
    ),
    'ĐANG GHÉP KHUNG': (vi: 'ĐANG GHÉP KHUNG HÌNH', en: 'SYNCHRONIZING FRAMES'),
    'CHỜ POSE 2 CAM': (
      vi: 'CHỜ TƯ THẾ TỪ HAI CAMERA',
      en: 'AWAITING DUAL-CAMERA POSE'
    ),
    'BẢNG SỐ LIỆU': (vi: 'BẢNG SỐ LIỆU', en: 'DATA TABLE'),
    'Chỉ số': (vi: 'Chỉ số', en: 'Metric'),
    'Đối xứng': (vi: 'Đối xứng', en: 'Symmetry'),
    'CV THỜI GIAN CHU KỲ': (vi: 'CV THỜI GIAN CHU KỲ', en: 'CYCLE-TIME CV'),
    'Các giá trị là thống kê mô tả từ camera; chưa thay thế phép đo lâm sàng chuẩn vàng.':
        (
      vi: 'Các giá trị là thống kê mô tả từ camera; chưa thay thế phép đo lâm sàng chuẩn vàng.',
      en: 'These values are camera-derived descriptive statistics and do not replace gold-standard clinical measurements.'
    ),
    'Clip này chưa đủ chu kỳ camera hợp lệ.': (
      vi: 'Đoạn video chưa đủ chu kỳ camera hợp lệ.',
      en: 'This clip does not contain enough valid camera gait cycles.'
    ),
    'Hoàn tất một bước trái và một bước phải để có cặp đầu tiên; từ 2 cặp mới tính SD.':
        (
      vi: 'Hoàn tất một bước trái và một bước phải để có cặp đầu tiên; từ 2 cặp mới tính SD.',
      en: 'Complete one left and one right step to form the first pair; at least two pairs are required to calculate SD.'
    ),
    'Dải mờ · ±1 SD': (vi: 'Dải mờ · ±1 SD', en: 'Shaded band · ±1 SD'),
    'CHỈ SỐ': (vi: 'CHỈ SỐ', en: 'METRIC'),
    'CHÊNH': (vi: 'CHÊNH LỆCH', en: 'DIFFERENCE'),
    'Khoảng 1–2 nhịp gần nhất': (
      vi: 'Khoảng 1–2 nhịp gần nhất',
      en: 'Latest 1–2 gait cycles'
    ),
    'Cặp bước gần nhất': (vi: 'Cặp bước gần nhất', en: 'Latest step pair'),
    'Mean ± SD theo cặp bước': (
      vi: 'Trung bình ± SD theo cặp bước',
      en: 'Step-pair mean ± SD'
    ),
    'Mean theo cặp bước': (
      vi: 'Trung bình theo cặp bước',
      en: 'Step-pair mean'
    ),
    'GÓT': (vi: 'GÓT', en: 'HEEL'),
    'GIỮA BÀN CHÂN': (vi: 'GIỮA BÀN CHÂN', en: 'MIDFOOT'),
    'TRƯỚC BÀN CHÂN': (vi: 'TRƯỚC BÀN CHÂN', en: 'FOREFOOT'),
    'TỔNG LỰC HAI CHÂN': (
      vi: 'TỔNG LỰC HAI CHÂN',
      en: 'TOTAL FORCE OF BOTH FEET'
    ),
    'LỰC VÙNG GÓT': (vi: 'LỰC VÙNG GÓT', en: 'HEEL FORCE'),
    'LỰC VÙNG GIỮA BÀN CHÂN': (
      vi: 'LỰC VÙNG GIỮA BÀN CHÂN',
      en: 'MIDFOOT FORCE'
    ),
    'LỰC VÙNG TRƯỚC BÀN CHÂN': (
      vi: 'LỰC VÙNG TRƯỚC BÀN CHÂN',
      en: 'FOREFOOT FORCE'
    ),
    'REPLAY FSR · DỮ LIỆU TỪNG THỜI ĐIỂM': (
      vi: 'PHÁT LẠI FSR · DỮ LIỆU TỪNG THỜI ĐIỂM',
      en: 'FSR REPLAY · TIME-SERIES DATA'
    ),
    'TOÀN BỘ THÔNG SỐ LỰC TỨC THỜI': (
      vi: 'TOÀN BỘ THÔNG SỐ LỰC TỨC THỜI',
      en: 'ALL INSTANTANEOUS FORCE METRICS'
    ),
    'CHÂN TRÁI': (vi: 'CHÂN TRÁI', en: 'LEFT FOOT'),
    'CHÂN PHẢI': (vi: 'CHÂN PHẢI', en: 'RIGHT FOOT'),
    'TRÁI': (vi: 'TRÁI', en: 'LEFT'),
    'PHẢI': (vi: 'PHẢI', en: 'RIGHT'),
    'Không tải': (vi: 'Không tải', en: 'Unloaded'),
    'Đang chạm': (vi: 'Đang tiếp xúc', en: 'In contact'),
    'Không có khung FSR': (
      vi: 'Không có khung FSR',
      en: 'No FSR frame available'
    ),
    'Chu kỳ lực quanh thời điểm đang xem': (
      vi: 'Chu kỳ lực quanh thời điểm đang xem',
      en: 'Force cycle around the current time point'
    ),
    'Mẫu lực gốc trong 4 giây gần thời điểm đang xem': (
      vi: 'Mẫu lực gốc trong 4 giây gần thời điểm đang xem',
      en: 'Raw force samples within four seconds of the current time point'
    ),
    'Clip này chưa có dữ liệu FSR phát lại theo thời điểm.': (
      vi: 'Đoạn video chưa có dữ liệu FSR phát lại theo thời điểm.',
      en: 'This clip has no time-synchronized FSR replay data.'
    ),
    'Hãy ghi clip mới khi hai tấm FSR đã kết nối.': (
      vi: 'Hãy ghi đoạn video mới khi hai tấm FSR đã kết nối.',
      en: 'Record a new clip after both FSR insoles are connected.'
    ),
    'Bản ghi đang chọn': (vi: 'Bản ghi đang chọn', en: 'Selected recording'),
    'Mẫu tham chiếu': (vi: 'Mẫu tham chiếu', en: 'Reference sample'),
    'GỐI': (vi: 'GỐI', en: 'KNEE'),
    'HÔNG': (vi: 'HÔNG', en: 'HIP'),
    'CHẬU': (vi: 'CHẬU', en: 'PELVIS'),
    'Góc nghiêng (°)': (vi: 'Góc nghiêng (°)', en: 'Tilt angle (°)'),
    'Bản ghi': (vi: 'Bản ghi', en: 'Recording'),
    'Tham chiếu': (vi: 'Tham chiếu', en: 'Reference'),
    'cần kiểm tra': (vi: 'cần kiểm tra', en: 'review required'),
    'chấp nhận': (vi: 'chấp nhận', en: 'acceptable'),
    'ổn định': (vi: 'ổn định', en: 'stable'),
    'GÓC KHỚP': (vi: 'GÓC KHỚP', en: 'JOINT ANGLES'),
    'Chu kỳ khớp · Mean ± SD': (
      vi: 'Chu kỳ khớp · Trung bình ± SD',
      en: 'Joint cycles · Mean ± SD'
    ),
    'LỰC FSR': (vi: 'LỰC FSR', en: 'FSR FORCE'),
    'Tổng hợp · FSI & 3 pha': (
      vi: 'Tổng hợp · FSI và ba vùng',
      en: 'Summary · FSI and three regions'
    ),
    'Theo 3 vùng · Mean ± SD': (
      vi: 'Theo ba vùng · Trung bình ± SD',
      en: 'Three regions · Mean ± SD'
    ),
    'Theo thời điểm video': (
      vi: 'Theo thời điểm video',
      en: 'Video-synchronized time series'
    ),
    'THĂNG BẰNG': (vi: 'THĂNG BẰNG', en: 'BALANCE'),
    'Chỉ số & đối xứng': (vi: 'Chỉ số và đối xứng', en: 'Metrics and symmetry'),
    'GÓC KHỚP · CHU KỲ': (
      vi: 'GÓC KHỚP · CHU KỲ',
      en: 'JOINT ANGLES · GAIT CYCLES'
    ),
    'THĂNG BẰNG · CHỈ SỐ': (vi: 'THĂNG BẰNG · CHỈ SỐ', en: 'BALANCE · METRICS'),
    'LỰC FSR · 3 VÙNG': (
      vi: 'LỰC FSR · BA VÙNG',
      en: 'FSR FORCE · THREE REGIONS'
    ),
    'LỰC FSR · TỔNG HỢP': (vi: 'LỰC FSR · TỔNG HỢP', en: 'FSR FORCE · SUMMARY'),
    'LỰC FSR · THEO THỜI ĐIỂM': (
      vi: 'LỰC FSR · THEO THỜI ĐIỂM',
      en: 'FSR FORCE · TIME SERIES'
    ),
    'TRÌNH BÀY BÁO CÁO': (vi: 'TRÌNH BÀY BÁO CÁO', en: 'PRESENT REPORT'),
    'THOÁT TRÌNH BÀY': (vi: 'THOÁT TRÌNH BÀY', en: 'EXIT PRESENTATION'),
    'PHÂN TÍCH DÁNG ĐI': (vi: 'PHÂN TÍCH DÁNG ĐI', en: 'GAIT ANALYSIS'),
    'BẢN PHÂN TÍCH': (vi: 'BẢN PHÂN TÍCH', en: 'ANALYSIS'),
    'TRÌNH BÀY': (vi: 'TRÌNH BÀY', en: 'PRESENT'),
    'DỮ LIỆU & VIDEO': (vi: 'DỮ LIỆU VÀ VIDEO', en: 'DATA AND VIDEO'),
    'Tổng hợp': (vi: 'Tổng hợp', en: 'Summary'),
    '3 vùng': (vi: 'Ba vùng', en: 'Three regions'),
    'Theo thời điểm': (vi: 'Theo thời điểm', en: 'Time series'),
    'THƯ VIỆN PHIÊN GHI': (vi: 'THƯ VIỆN PHIÊN GHI', en: 'ACQUISITION LIBRARY'),
    'Chưa chọn bản phân tích': (
      vi: 'Chưa chọn bản phân tích',
      en: 'No analysis selected'
    ),
    'Không nạp được video mẫu đã khóa nguồn.': (
      vi: 'Không nạp được video tham chiếu đã khóa nguồn.',
      en: 'Unable to load the source-locked reference video.'
    ),
    'Skeleton và các biểu đồ đã được nạp lại.': (
      vi: 'Khung xương và các biểu đồ đã được nạp lại.',
      en: 'Pose skeleton and charts reloaded.'
    ),
    'Đã xóa bộ video và dữ liệu liên quan.': (
      vi: 'Đã xóa bộ video và dữ liệu liên quan.',
      en: 'The video set and associated data were deleted.'
    ),
    'Đóng': (vi: 'Đóng', en: 'Close'),
    'BACKEND CHƯA KHỞI ĐỘNG': (
      vi: 'MÁY CHỦ CHƯA KHỞI ĐỘNG',
      en: 'BACKEND NOT STARTED'
    ),
    'CAMERA CHƯA NHẬN HÌNH': (
      vi: 'CAMERA CHƯA NHẬN HÌNH',
      en: 'NO CAMERA IMAGE'
    ),
    'CHƯA THẤY TOÀN THÂN': (
      vi: 'CHƯA THẤY TOÀN THÂN',
      en: 'FULL BODY NOT DETECTED'
    ),
    'CÀI FSR': (vi: 'CÀI ĐẶT FSR', en: 'FSR SETUP'),
    'BẮT ĐẦU GHI HÌNH': (vi: 'BẮT ĐẦU GHI HÌNH', en: 'START ACQUISITION'),
    'THU MẪU THAM CHIẾU': (vi: 'THU MẪU THAM CHIẾU', en: 'ACQUIRE REFERENCE'),
    'VÀO THU VIDEO MẪU': (
      vi: 'BẮT ĐẦU THU VIDEO THAM CHIẾU',
      en: 'OPEN REFERENCE ACQUISITION'
    ),
    'Camera đạt điều kiện ghi ổn định': (
      vi: 'Camera đạt điều kiện ghi ổn định',
      en: 'Camera is ready for stable acquisition'
    ),
    'Có thể quay · pose sẽ được sàng lọc khi phân tích': (
      vi: 'Có thể ghi · tư thế sẽ được sàng lọc khi phân tích',
      en: 'Ready to record · pose frames will be quality-filtered during analysis'
    ),
    'Chưa thể bắt đầu ghi': (
      vi: 'Chưa thể bắt đầu ghi',
      en: 'Acquisition cannot start yet'
    ),
    'Số đo hiệu chuẩn camera': (
      vi: 'Số đo hiệu chuẩn camera',
      en: 'Camera calibration measurements'
    ),
    'TIỀN SỬ': (vi: 'TIỀN SỬ', en: 'HISTORY'),
    'TRIỆU CHỨNG': (vi: 'TRIỆU CHỨNG', en: 'SYMPTOMS'),
    'Cần nhập số đo': (vi: 'Cần nhập số đo', en: 'Measurements required'),
    'Hãy chọn hồ sơ người làm mẫu trước khi thu video tham chiếu.': (
      vi: 'Hãy chọn hồ sơ người làm mẫu trước khi thu video tham chiếu.',
      en: 'Select the reference participant record before acquiring a reference video.'
    ),
    'Kết quả tìm thấy': (vi: 'Kết quả tìm thấy', en: 'Search results'),
    'Mã định danh bệnh án:': (
      vi: 'Mã định danh hồ sơ:',
      en: 'Patient record ID:'
    ),
    'Yêu cầu nhập số đo': (
      vi: 'Vui lòng nhập số đo',
      en: 'Measurement is required'
    ),
    'Chiều dài 20 - 150 cm': (
      vi: 'Chiều dài phải từ 20 đến 150 cm',
      en: 'Length must be between 20 and 150 cm'
    ),
    'Chuẩn Lành': (vi: 'Chuẩn chân lành', en: 'Sound-foot baseline'),
    'Không ghi nhận.': (vi: 'Không ghi nhận.', en: 'None recorded.'),
    'Chưa chọn bệnh nhân': (
      vi: 'Chưa chọn người bệnh',
      en: 'No patient selected'
    ),
    'QUAY LẠI HỒ SƠ BỆNH NHÂN': (
      vi: 'QUAY LẠI HỒ SƠ NGƯỜI BỆNH',
      en: 'BACK TO PATIENT RECORDS'
    ),
    'ĐẾN TAB PHÂN TÍCH': (vi: 'ĐẾN MỤC PHÂN TÍCH', en: 'GO TO ANALYSIS'),
    'Góc khớp gối (°)': (vi: 'Góc khớp gối (°)', en: 'Knee angle (°)'),
    'Nhóm phân tích': (vi: 'Nhóm phân tích', en: 'Analysis category'),
    'Đề xuất tinh chỉnh': (
      vi: 'Đề xuất căn chỉnh',
      en: 'Alignment recommendation'
    ),
    'Dừng quét': (vi: 'Dừng ghi', en: 'Stop acquisition'),
    'Trở về hai camera đang kết nối': (
      vi: 'Trở về hai camera đang kết nối',
      en: 'Return to the two connected cameras'
    ),
    'Hai camera đang được ghép theo thời điểm chụp; góc gập lấy từ camera dọc và nghiêng chậu lấy từ camera chính diện.':
        (
      vi: 'Hai camera đang được ghép theo thời điểm chụp; góc gập lấy từ camera mặt phẳng dọc và nghiêng chậu lấy từ camera chính diện.',
      en: 'The camera streams are synchronized by capture time; flexion is derived from the sagittal view and pelvic tilt from the frontal view.'
    ),
    'Cần thấy đủ cơ thể ở cả hai camera để ghép dữ liệu.': (
      vi: 'Cần thấy đủ cơ thể ở cả hai camera để ghép dữ liệu.',
      en: 'The full body must be visible in both cameras to synchronize the data.'
    ),
    'Nhịp tham khảo bản ghi. Mỗi chu kỳ 0 → khoảng 300 → khoảng 600 → khoảng 300 → 0 N.':
        (
      vi: 'Nhịp tham khảo bản ghi. Mỗi chu kỳ 0 → khoảng 300 → khoảng 600 → khoảng 300 → 0 N.',
      en: 'Reference recording profile. Each cycle progresses from 0 to approximately 300, 600, 300, then 0 N.'
    ),
    'Hai đường giữ lệch nhẹ; Mean và ±1 SD được tính lại từ 3 cặp bước đang hiển thị.':
        (
      vi: 'Hai đường giữ độ lệch nhẹ; trung bình và ±1 SD được tính lại từ ba cặp bước đang hiển thị.',
      en: 'The two curves retain a small offset; the mean and ±1 SD are recalculated from the three displayed step pairs.'
    ),
    'Clip này chưa có đủ dữ liệu FSR để dựng ba pha lực.': (
      vi: 'Đoạn video chưa đủ dữ liệu FSR để dựng ba vùng lực.',
      en: 'This clip does not contain enough FSR data to construct the three-region force analysis.'
    ),
    'Hãy ghi lại khi hai tấm FSR đã kết nối.': (
      vi: 'Hãy ghi lại khi hai tấm FSR đã kết nối.',
      en: 'Record again after both FSR insoles are connected.'
    ),
    'Dữ liệu FSR không đúng định dạng': (
      vi: 'Dữ liệu FSR không đúng định dạng',
      en: 'Invalid FSR data format'
    ),
    'Không phát hiện lỗi đo': (
      vi: 'Không phát hiện lỗi đo',
      en: 'No measurement errors detected'
    ),
    'Dữ liệu minh họa · 60 kg · hai chân lành · Mean ± SD': (
      vi: 'Dữ liệu minh họa · 60 kg · hai chân lành · Trung bình ± SD',
      en: 'Illustrative data · 60 kg · bilateral sound feet · Mean ± SD'
    ),
    'Dữ liệu minh họa · nhịp tham khảo bản ghi FSR.': (
      vi: 'Dữ liệu minh họa · nhịp tham khảo bản ghi FSR.',
      en: 'Illustrative data · reference FSR recording profile.'
    ),
    'Mỗi biểu đồ là dữ liệu thô theo thời gian video, không phải Mean ± SD hay chu kỳ đã gộp.':
        (
      vi: 'Mỗi biểu đồ là dữ liệu thô theo thời gian video, không phải trung bình ± SD hoặc chu kỳ đã gộp.',
      en: 'Each chart shows raw video-synchronized data, not mean ± SD or aggregated cycles.'
    ),
    'Không có dữ liệu — bấm Record để quét': (
      vi: 'Chưa có dữ liệu — bấm Ghi để bắt đầu',
      en: 'No data — select Record to start acquisition'
    ),
    'Chưa tải được dữ liệu góc của Mẫu 2.': (
      vi: 'Chưa tải được dữ liệu góc của mẫu 2.',
      en: 'Unable to load angle data for Sample 2.'
    ),
    'Góc (°) · thời gian (s)': (
      vi: 'Góc (°) · thời gian (s)',
      en: 'Angle (°) · time (s)'
    ),
    'Xanh: chân trái · Cam: chân phải · Góc (°)': (
      vi: 'Xanh: chân trái · Cam: chân phải · Góc (°)',
      en: 'Blue: left foot · Orange: right foot · Angle (°)'
    ),
    'CHÍNH DIỆN': (vi: 'CHÍNH DIỆN', en: 'FRONTAL VIEW'),
    'GÓC NGANG': (vi: 'MẶT PHẲNG DỌC', en: 'SAGITTAL VIEW'),
    'Video nguồn · đồng bộ chưa xác nhận · chưa có dữ liệu FSR': (
      vi: 'Video nguồn · chưa xác nhận đồng bộ · chưa có dữ liệu FSR',
      en: 'Source video · synchronization unverified · no FSR data'
    ),
    'Chưa tải được dữ liệu FSR.': (
      vi: 'Chưa tải được dữ liệu FSR.',
      en: 'Unable to load FSR data.'
    ),
    'Đã sao chép dữ liệu kèm nguồn gốc.': (
      vi: 'Đã sao chép dữ liệu kèm nguồn gốc.',
      en: 'Data and provenance copied.'
    ),
    'Chưa đủ mốc camera': (
      vi: 'Chưa đủ mốc camera',
      en: 'Insufficient camera events'
    ),
    'Hệ Thống Phân Tích & Căn Chỉnh Dáng Đi Sinh Học': (
      vi: 'Hệ thống phân tích và căn chỉnh dáng đi sinh học',
      en: 'Biomechanical Gait Analysis and Alignment System'
    ),
    'Đã ghi nhận dữ liệu lâm sàng thành công. Cần thực hiện scan lần 2 sau khi vặn cơ khí để hiển thị báo cáo đối chiếu đầy đủ.':
        (
      vi: 'Đã ghi nhận dữ liệu lâm sàng. Cần thực hiện lần ghi thứ hai sau khi căn chỉnh cơ khí để hiển thị báo cáo so sánh đầy đủ.',
      en: 'Clinical data recorded. Perform a second acquisition after mechanical alignment to generate the complete comparison report.'
    ),
    'Vui lòng chọn bệnh nhân ở Tab Bệnh nhân để xem lịch sử khám.': (
      vi: 'Vui lòng chọn người bệnh tại mục Hồ sơ người bệnh để xem lịch sử đánh giá.',
      en: 'Select a patient in Patient records to view assessment history.'
    ),
    'Chưa có ghi chú nào. Hãy thêm ghi chú mới bên dưới.': (
      vi: 'Chưa có ghi chú. Hãy thêm ghi chú mới bên dưới.',
      en: 'No notes are available. Add a new note below.'
    ),
    'Video vẫn được lưu đầy đủ; frame pose chưa đạt sẽ tự bị loại khỏi biểu đồ.':
        (
      vi: 'Video vẫn được lưu đầy đủ; khung hình tư thế không đạt sẽ tự bị loại khỏi biểu đồ.',
      en: 'The complete video is retained; low-quality pose frames are automatically excluded from charts.'
    ),
    'Đã dừng ghi. Hãy xem lại rồi bấm LƯU VIDEO MẪU nếu đạt.': (
      vi: 'Đã dừng ghi. Hãy xem lại rồi chọn LƯU VIDEO THAM CHIẾU nếu đạt.',
      en: 'Recording stopped. Review it, then select SAVE REFERENCE VIDEO if acceptable.'
    ),
    'Đã duyệt và lưu bộ video vào thư viện video mẫu.': (
      vi: 'Đã duyệt và lưu bộ video vào thư viện video tham chiếu.',
      en: 'The video set was approved and saved to the reference library.'
    ),
    'BẮT ĐẦU THU MẪU': (
      vi: 'BẮT ĐẦU THU MẪU',
      en: 'START REFERENCE ACQUISITION'
    ),
    'ĐÃ DUYỆT': (vi: 'ĐÃ DUYỆT', en: 'APPROVED'),
    'BẢN NHÁP': (vi: 'BẢN NHÁP', en: 'DRAFT'),
    'Chưa nhận được tư thế': (
      vi: 'Chưa nhận được tư thế',
      en: 'No pose detected'
    ),
    'Phát hiện thân nghiêng trái–phải.': (
      vi: 'Phát hiện thân nghiêng trái–phải.',
      en: 'Medial–lateral trunk lean detected.'
    ),
    'Đưa vai và lồng ngực về giữa hai hông.': (
      vi: 'Đưa vai và lồng ngực về giữa hai hông.',
      en: 'Center the shoulders and thorax over the hips.'
    ),
    'Bệnh nhân mẫu': (vi: 'Người bệnh mẫu', en: 'Sample patient'),
    'Hai chân lành; dữ liệu tham khảo.': (
      vi: 'Hai chân lành; dữ liệu tham khảo.',
      en: 'Bilateral sound feet; reference data.'
    ),
    'Cải thiện đối xứng tải và độ linh hoạt khi đi bộ.': (
      vi: 'Cải thiện đối xứng tải và độ linh hoạt khi đi bộ.',
      en: 'Improve load symmetry and walking mobility.'
    ),
    'Mẫu tham chiếu cân bằng': (
      vi: 'Mẫu tham chiếu cân bằng',
      en: 'Balanced reference sample'
    ),
    'Sai lệch nhẹ': (vi: 'Sai lệch nhẹ', en: 'Mild deviation'),
    'Nghiêng chậu': (vi: 'Nghiêng chậu', en: 'Pelvic tilt'),
    'N minh họa 50 kg': (vi: 'N minh họa 50 kg', en: 'N · 50 kg illustration'),
    'Gối trái': (vi: 'Gối trái', en: 'Left knee'),
    'Gối phải': (vi: 'Gối phải', en: 'Right knee'),
    'Cổ chân trái': (vi: 'Cổ chân trái', en: 'Left ankle'),
    'Cổ chân phải': (vi: 'Cổ chân phải', en: 'Right ankle'),
    'Hông trái': (vi: 'Hông trái', en: 'Left hip'),
    'Hông phải': (vi: 'Hông phải', en: 'Right hip'),
    'Nghiêng hông': (vi: 'Nghiêng hông', en: 'Pelvic obliquity'),
    'Đánh dấu của Bác sĩ': (vi: 'Đánh dấu của bác sĩ', en: 'Clinician marker'),
    'Không nhận được phản hồi backend. Hãy khởi động lại backend.': (
      vi: 'Không nhận được phản hồi từ máy chủ. Hãy khởi động lại máy chủ.',
      en: 'No response was received from the backend. Restart the backend.'
    ),
    'Chưa có phiên đo.': (
      vi: 'Chưa có phiên đo.',
      en: 'No measurement session is available.'
    ),
    'Không lưu được đoạn phân tích.': (
      vi: 'Không lưu được đoạn phân tích.',
      en: 'Unable to save the analysis segment.'
    ),
    'Thiếu góc gập gối': (
      vi: 'Thiếu góc gập gối',
      en: 'Missing knee-flexion angle'
    ),
    'Bất đối xứng biên độ gập gối': (
      vi: 'Bất đối xứng biên độ gập gối',
      en: 'Knee-flexion range asymmetry'
    ),
    'Kiểm tra alignment socket và phân bố trọng lượng.': (
      vi: 'Kiểm tra căn chỉnh ổ mỏm cụt và phân bố tải.',
      en: 'Review socket alignment and weight distribution.'
    ),
    'Chưa cải thiện; cần kiểm tra lại hướng điều chỉnh.': (
      vi: 'Chưa cải thiện; cần kiểm tra lại hướng căn chỉnh.',
      en: 'No improvement; review the alignment direction.'
    ),
    'Biên độ gập gối gần như không đổi.': (
      vi: 'Biên độ gập gối gần như không đổi.',
      en: 'Knee-flexion range is essentially unchanged.'
    ),
    'Phiên tinh chỉnh': (vi: 'Phiên căn chỉnh', en: 'Alignment session'),
    '3. Phân tích & đề xuất': (
      vi: '3. Phân tích và đề xuất',
      en: '3. Analysis and recommendation'
    ),
    'Cấu hình': (vi: 'Cấu hình', en: 'Configuration'),
    'Xuất báo cáo — sẽ tích hợp ở bước sau': (
      vi: 'Xuất báo cáo — sẽ tích hợp ở bước sau',
      en: 'Report export — coming in a later step'
    ),
    'N mô phỏng': (vi: 'N mô phỏng', en: 'Simulated N'),
    'N (ước tính)': (vi: 'N (ước tính)', en: 'N (estimated)'),
    'N ước tính': (vi: 'N ước tính', en: 'Estimated N'),
    'Lực gót': (vi: 'Lực gót', en: 'Heel force'),
    'Lực giữa bàn chân': (vi: 'Lực giữa bàn chân', en: 'Midfoot force'),
    'Lực trước bàn chân': (vi: 'Lực trước bàn chân', en: 'Forefoot force'),
    'Không đủ mẫu FSR trong clip': (
      vi: 'Không đủ mẫu FSR trong đoạn video',
      en: 'Insufficient FSR samples in this clip'
    ),
    'Không có dữ liệu': (vi: 'Không có dữ liệu', en: 'No data'),
    'Tổng': (vi: 'Tổng', en: 'Total'),
    'Trái': (vi: 'Trái', en: 'Left'),
    'Phải': (vi: 'Phải', en: 'Right'),
    'Đỉnh': (vi: 'Đỉnh', en: 'Peak'),
    'Đỉnh đo': (vi: 'Đỉnh đo', en: 'Measured peak'),
    'nghiêng thân': (vi: 'nghiêng thân', en: 'trunk lean'),
    'nghiêng': (vi: 'nghiêng', en: 'tilt'),
    'tải': (vi: 'tải', en: 'loading'),
    'lực': (vi: 'lực', en: 'force'),
    'Thời gian ghi trực tiếp': (
      vi: 'Thời gian ghi trực tiếp',
      en: 'Live acquisition time'
    ),
    'Chờ mốc cuối': (vi: 'Chờ mốc cuối', en: 'Awaiting end marker'),
    'Đoạn phân tích': (vi: 'Đoạn phân tích', en: 'Analysis segment'),
    'Phân tích lại': (vi: 'Phân tích lại', en: 'Reanalyze'),
    'FSR mẫu đã lưu': (vi: 'FSR mẫu đã lưu', en: 'Saved reference FSR'),
    'CAM 1 · CHÍNH DIỆN': (
      vi: 'CAMERA 1 · CHÍNH DIỆN',
      en: 'CAMERA 1 · FRONTAL VIEW'
    ),
    'CAM 2 · MẶT PHẲNG DỌC': (
      vi: 'CAMERA 2 · MẶT PHẲNG DỌC',
      en: 'CAMERA 2 · SAGITTAL VIEW'
    ),
    'BẢN PHÂN TÍCH ĐÃ LƯU': (vi: 'BẢN PHÂN TÍCH ĐÃ LƯU', en: 'SAVED ANALYSES'),
    'Chưa có bộ video nào.': (
      vi: 'Chưa có bộ video.',
      en: 'No video sets are available.'
    ),
    'Gồm bản ghi đầy đủ và các đoạn cắt theo mốc.': (
      vi: 'Gồm bản ghi đầy đủ và các đoạn cắt theo mốc.',
      en: 'Includes the full recording and marker-defined clips.'
    ),

    'không phát hiện lỗi đo': (
      vi: 'không phát hiện lỗi đo',
      en: 'no measurement errors detected'
    ),
    'Clip này chưa có dữ liệu FSR.': (
      vi: 'Đoạn video chưa có dữ liệu FSR.',
      en: 'This clip contains no FSR data.'
    ),
    'Hãy ghi một phiên mới sau khi kết nối tấm FSR.': (
      vi: 'Hãy ghi một phiên mới sau khi kết nối tấm FSR.',
      en: 'Record a new session after connecting the FSR insoles.'
    ),
    'Mẫu 2 · CAMERA + FSR · con trỏ theo video.': (
      vi: 'Mẫu 2 · CAMERA + FSR · con trỏ theo video.',
      en: 'Sample 2 · CAMERA + FSR · video-synchronized cursor.'
    ),
    'Nghiêng trước–sau · dương: trước': (
      vi: 'Nghiêng trước–sau · dương: trước',
      en: 'Anterior–posterior lean · positive: anterior'
    ),
    'Dữ liệu FSR minh họa · chưa hiệu chuẩn. Góc camera giữ nguyên nguồn; chưa xác nhận đồng bộ hai góc quay.':
        (
      vi: 'Dữ liệu FSR minh họa · chưa hiệu chuẩn. Góc camera giữ nguyên nguồn; chưa xác nhận đồng bộ hai góc quay.',
      en: 'Illustrative FSR data · uncalibrated. Camera angles retain their source values; synchronization between views is unverified.'
    ),
    'Thử lại': (vi: 'Thử lại', en: 'Retry'),
    'Chọn biểu đồ từ menu bên trái để hiển thị và so sánh dữ liệu.': (
      vi: 'Chọn biểu đồ từ menu bên trái để hiển thị và so sánh dữ liệu.',
      en: 'Select charts from the left menu to display and compare data.'
    ),
    'Backend không trả được thư viện video.': (
      vi: 'Máy chủ không trả được thư viện video.',
      en: 'The backend could not return the video library.'
    ),
    'NHẬN ĐỊNH THAM KHẢO · Hai chân lệch nhẹ khoảng 2–4%.': (
      vi: 'NHẬN ĐỊNH THAM KHẢO · Hai chân lệch nhẹ khoảng 2–4%.',
      en: 'REFERENCE INTERPRETATION · Mild bilateral difference of approximately 2–4%.'
    ),
    'Nhịp đi · đối xứng · xương chậu': (
      vi: 'Nhịp bước · đối xứng · xương chậu',
      en: 'Cadence · symmetry · pelvis'
    ),
    'Chưa có bản phân tích nào. Hãy ghi hình hoặc đặt mốc để tạo đoạn cắt.': (
      vi: 'Chưa có bản phân tích. Hãy ghi hình hoặc đặt mốc để tạo đoạn cắt.',
      en: 'No analysis is available. Record video or set markers to create a clip.'
    ),
    'quay, cắt đoạn và phân tích như phiên thường.': (
      vi: 'ghi hình, cắt đoạn và phân tích như phiên thông thường.',
      en: 'record, trim, and analyze it as a standard session.'
    ),
    'Đã mở kết nối FSR. Hệ thống sẽ tự nhận khi hai tấm bắt đầu gửi dữ liệu.': (
      vi: 'Đã mở kết nối FSR. Hệ thống sẽ tự nhận khi hai tấm bắt đầu gửi dữ liệu.',
      en: 'FSR connection opened. The system will detect both insoles when they begin transmitting data.'
    ),
    'Tăng ánh sáng và đóng Camera/Zoom/Meet.': (
      vi: 'Tăng ánh sáng và đóng Camera/Zoom/Meet.',
      en: 'Increase lighting and close Camera, Zoom, or Meet.'
    ),
    'Đã đề xuất hai camera ngoài theo thứ tự Windows; webcam laptop chỉ dự phòng. Cổng có thể đổi nên hãy xác nhận lại bằng ảnh thử.':
        (
      vi: 'Đã đề xuất hai camera ngoài theo thứ tự Windows; webcam laptop chỉ dự phòng. Cổng có thể đổi nên hãy xác nhận lại bằng ảnh thử.',
      en: 'Two external cameras are suggested in Windows order; the laptop webcam is a fallback. Port order may change, so verify using test images.'
    ),
    'Ứng dụng đề xuất hai camera ngoài theo thứ tự Windows; webcam laptop chỉ dự phòng. Cổng có thể đổi nên hãy xác nhận bằng ảnh thử.':
        (
      vi: 'Ứng dụng đề xuất hai camera ngoài theo thứ tự Windows; webcam laptop chỉ dự phòng. Cổng có thể đổi nên hãy xác nhận bằng ảnh thử.',
      en: 'The application suggests two external cameras in Windows order; the laptop webcam is a fallback. Port order may change, so verify using test images.'
    ),
    'Chỉ dùng một camera (mặt phẳng dọc)': (
      vi: 'Chỉ dùng một camera (mặt phẳng dọc)',
      en: 'Use one camera only (sagittal view)'
    ),
    'Chỉ dùng một camera (đặt ở mặt phẳng dọc)': (
      vi: 'Chỉ dùng một camera (đặt ở mặt phẳng dọc)',
      en: 'Use one camera only (positioned in the sagittal plane)'
    ),
    'Hãy đóng Camera/Zoom/Meet, rút cắm lại USB rồi thử một lần nữa.': (
      vi: 'Hãy đóng Camera/Zoom/Meet, kết nối lại USB rồi thử lại.',
      en: 'Close Camera, Zoom, or Meet, reconnect the USB cable, and try again.'
    ),
    'Xem trước góc quay Camera & Đo lường sinh học': (
      vi: 'Xem trước góc camera và số đo sinh học',
      en: 'Camera View and Anthropometric Measurement Preview'
    ),
    'Góc chụp trước (Frontal Camera)': (
      vi: 'Góc chính diện (camera trước)',
      en: 'Frontal view camera'
    ),
    'Góc chụp ngang (Sagittal Camera)': (
      vi: 'Góc mặt phẳng dọc (camera ngang)',
      en: 'Sagittal view camera'
    ),
    'Chọn vai trò theo ảnh thử, không dựa vào vị trí cắm USB. Camera mặt phẳng dọc cần thấy liên tục vai–hông–gối–cổ chân.':
        (
      vi: 'Chọn vai trò theo ảnh thử, không dựa vào vị trí cắm USB. Camera mặt phẳng dọc cần thấy liên tục vai–hông–gối–cổ chân.',
      en: 'Assign camera roles from the test images, not USB port position. The sagittal camera must continuously show the shoulders, hips, knees, and ankles.'
    ),
    'Đã gán camera. Kiểm tra hai khung hình rồi bắt đầu ghi.': (
      vi: 'Đã gán camera. Kiểm tra hai khung hình rồi bắt đầu ghi.',
      en: 'Camera roles assigned. Verify both views before starting acquisition.'
    ),
    'Đã đổi: camera vật lý 2 là chính diện, camera vật lý 1 là mặt phẳng dọc.':
        (
      vi: 'Đã đổi: camera vật lý 2 là chính diện, camera vật lý 1 là mặt phẳng dọc.',
      en: 'Swapped: physical camera 2 is frontal and physical camera 1 is sagittal.'
    ),
    'Đã trả camera về cấu hình ban đầu.': (
      vi: 'Đã trả camera về cấu hình ban đầu.',
      en: 'The original camera configuration was restored.'
    ),
    'Không đọc được trạng thái hiệu chuẩn.': (
      vi: 'Không đọc được trạng thái hiệu chuẩn.',
      en: 'Unable to read calibration status.'
    ),
    '1. In bảng ChArUco trên A4 ngang ở Actual size 100% (ô vuông 30 mm; không co giãn).':
        (
      vi: '1. In bảng ChArUco trên A4 ngang ở kích thước thực 100% (ô vuông 30 mm; không co giãn).',
      en: '1. Print the ChArUco board on landscape A4 at 100% actual size (30 mm squares; no scaling).'
    ),
    '2. Giữ bảng nghiêng khoảng 45° để cả hai camera cùng thấy.': (
      vi: '2. Giữ bảng nghiêng khoảng 45° để cả hai camera cùng thấy.',
      en: '2. Hold the board at approximately 45° so both cameras can see it.'
    ),
    '3. Di chuyển bảng tới nhiều vị trí và góc khác nhau; mỗi vị trí bấm Chụp mẫu một lần.':
        (
      vi: '3. Di chuyển bảng tới nhiều vị trí và góc khác nhau; tại mỗi vị trí, chọn Chụp mẫu một lần.',
      en: '3. Move the board through different positions and orientations; capture one sample at each position.'
    ),
    'Bảng in:': (vi: 'Bảng in:', en: 'Printable board:'),
    'Phiên ghi đã dừng. Mốc đầu cuối cùng chưa có mốc cuối nên không được lưu.':
        (
      vi: 'Phiên ghi đã dừng. Mốc đầu cuối cùng chưa có mốc cuối nên không được lưu.',
      en: 'Acquisition stopped. The last start marker has no end marker and was not saved.'
    ),
    'Đã lưu Bản ghi đầy đủ để phân tích. Các mốc được lưu thành đoạn cắt riêng.':
        (
      vi: 'Đã lưu bản ghi đầy đủ để phân tích. Các mốc được lưu thành đoạn cắt riêng.',
      en: 'The complete recording was saved for analysis. Marked intervals were saved as separate clips.'
    ),
    'Đang ghi': (vi: 'Đang ghi', en: 'Recording'),
    'Mẫu ·': (vi: 'Mẫu tham chiếu ·', en: 'Reference ·'),
    'Cài đặt camera và thiết bị sẽ được bổ sung tại đây.': (
      vi: 'Cài đặt camera và thiết bị sẽ được bổ sung tại đây.',
      en: 'Camera and device settings will be available here.'
    ),
    'trái': (vi: 'trái', en: 'left'),
    'phải': (vi: 'phải', en: 'right'),
    'mới': (vi: 'mới', en: 'new'),
    'Các đoạn phân tích và biểu đồ đã cắt từ bộ này cũng sẽ bị xóa. Thao tác này không thể hoàn tác.':
        (
      vi: 'Các đoạn phân tích và biểu đồ đã cắt từ bộ này cũng sẽ bị xóa. Thao tác này không thể hoàn tác.',
      en: 'Analysis clips and charts derived from this set will also be deleted. This action cannot be undone.'
    ),
    'Video raw, ADC FSR và timeline gốc sẽ được giữ nguyên. Hệ thống tạo revision mới cho skeleton, nhận bước chân, Newton/PeakFore/FSI và toàn bộ biểu đồ.':
        (
      vi: 'Video gốc, ADC FSR và dòng thời gian gốc sẽ được giữ nguyên. Hệ thống tạo phiên bản mới cho khung xương, nhận diện bước, Newton/PeakFore/FSI và toàn bộ biểu đồ.',
      en: 'Raw video, FSR ADC values, and the original timeline are preserved. A new revision is created for pose skeletons, step detection, Newton/PeakFore/FSI metrics, and all charts.'
    ),
    'Đây là bản ghi cũ đã đóng skeleton lên video. Hệ thống vẫn có thể phân tích lại ở chế độ best-effort, nhưng không thể gỡ hoàn toàn khung xương cũ khỏi ảnh.':
        (
      vi: 'Đây là bản ghi cũ đã ghép khung xương vào video. Hệ thống vẫn có thể phân tích lại ở chế độ tốt nhất có thể, nhưng không thể loại bỏ hoàn toàn khung xương cũ khỏi hình ảnh.',
      en: 'This legacy recording has the pose skeleton embedded in the video. Best-effort reanalysis is available, but the previous skeleton cannot be fully removed from the image.'
    ),
    'Chọn một đoạn ở danh sách bên phải để xem kết quả.': (
      vi: 'Chọn một đoạn trong danh sách bên phải để xem kết quả.',
      en: 'Select a segment from the list on the right to view its results.'
    ),
    'Chân giả: Trái': (vi: 'Chân giả: Trái', en: 'Prosthetic side: Left'),
    'Chân giả: Phải': (vi: 'Chân giả: Phải', en: 'Prosthetic side: Right'),
    'Chỉ các frame thấy rõ hông–gối–cổ chân với visibility ≥ 0,70 mới được dùng tính góc.':
        (
      vi: 'Chỉ các khung hình thấy rõ hông–gối–cổ chân với độ hiển thị ≥ 0,70 mới được dùng để tính góc.',
      en: 'Only frames with clearly visible hips, knees, and ankles and visibility ≥ 0.70 are used for angle calculations.'
    ),
    'Chân lành sinh học: Trái': (
      vi: 'Chân lành sinh học: Trái',
      en: 'Sound biological foot: Left'
    ),
    'Chân lành sinh học: Phải': (
      vi: 'Chân lành sinh học: Phải',
      en: 'Sound biological foot: Right'
    ),
    'Chân giả lắp đặt: Trái': (
      vi: 'Bên lắp chân giả: Trái',
      en: 'Prosthetic side: Left'
    ),
    'Chân giả lắp đặt: Phải': (
      vi: 'Bên lắp chân giả: Phải',
      en: 'Prosthetic side: Right'
    ),
    'Mỗi phiên khám sẽ tạo một ID phiên riêng biệt. Quy trình bắt đầu bằng việc quét Baseline chân lành 10 giây để lấy dữ liệu chuẩn sinh học riêng của bệnh nhân.':
        (
      vi: 'Mỗi phiên đánh giá sẽ tạo một mã phiên riêng. Quy trình bắt đầu bằng lần ghi chuẩn chân lành trong 10 giây để thu dữ liệu sinh học tham chiếu riêng của người bệnh.',
      en: 'Each assessment creates a unique session ID. The workflow begins with a 10-second sound-foot baseline acquisition to establish the patient-specific biomechanical reference.'
    ),
    'Chân giả bên TRÁI phải ở phía gần camera ngang.': (
      vi: 'Chân giả bên trái phải ở phía gần camera mặt phẳng dọc.',
      en: 'The left prosthetic foot must be closest to the sagittal camera.'
    ),
    'Chân giả bên PHẢI phải ở phía gần camera ngang.': (
      vi: 'Chân giả bên phải phải ở phía gần camera mặt phẳng dọc.',
      en: 'The right prosthetic foot must be closest to the sagittal camera.'
    ),
    'Backend chưa chạy · không thể tải camera': (
      vi: 'Máy chủ chưa chạy · không thể tải camera',
      en: 'Backend is not running · unable to load camera'
    ),
    'Chưa nhận đủ hai camera. Bấm CÀI CAMERA để chọn chính diện và mặt phẳng dọc.':
        (
      vi: 'Chưa nhận đủ hai camera. Chọn CÀI ĐẶT CAMERA để cấu hình góc chính diện và mặt phẳng dọc.',
      en: 'Both cameras are not available. Select CAMERA SETUP to assign the frontal and sagittal views.'
    ),
    'FSR chưa kết nối · vẫn có thể quay chỉ với camera': (
      vi: 'FSR chưa kết nối · vẫn có thể ghi chỉ với camera',
      en: 'FSR disconnected · camera-only acquisition remains available'
    ),
    'WORKSPACE': (vi: 'KHÔNG GIAN LÀM VIỆC', en: 'WORKSPACE'),
    'Tự động lưu video của tất cả phiên thuộc bệnh nhân.': (
      vi: 'Tự động lưu video của tất cả phiên thuộc người bệnh.',
      en: 'Videos from all patient sessions are saved automatically.'
    ),
    'Mô tả trực quan so sánh Before / After (trước và sau khi căn chỉnh kỹ thuật).':
        (
      vi: 'Mô tả trực quan so sánh trước và sau khi căn chỉnh kỹ thuật.',
      en: 'Visual comparison of pre- and post-alignment results.'
    ),
    'Phiên khám này hiện chỉ có 1 lần quét đánh giá. Hãy thực hiện lưu thông số căn chỉnh cơ khí ở Tab Phân Tích, sau đó chọn "Quét Lại (Rescan)" để ghi nhận lần quét số 2.':
        (
      vi: 'Phiên đánh giá này hiện chỉ có một lần ghi dữ liệu. Hãy lưu thông số căn chỉnh cơ khí tại mục Phân tích, sau đó chọn "Ghi lại" để thực hiện lần ghi thứ hai.',
      en: 'This assessment currently contains only one acquisition. Save the mechanical alignment parameters in Gait analysis, then select Reacquire to record the second acquisition.'
    ),

    // Error and status copy.
    'Lỗi kết nối': (vi: 'Lỗi kết nối', en: 'Connection error'),
    'Lỗi khởi tạo phiên': (
      vi: 'Lỗi khởi tạo phiên',
      en: 'Session initialization error'
    ),
    'Không đọc được ảnh thử': (
      vi: 'Không đọc được ảnh thử',
      en: 'Unable to read test image'
    ),
  };

  static const Map<String, ({String vi, String en})> _fragments = {
    // Dynamic acquisition and chart copy. Longer phrases intentionally appear
    // before their shorter components.
    'Chân giả: Trái': (vi: 'Chân giả: Trái', en: 'Prosthetic side: Left'),
    'Chân giả: Phải': (vi: 'Chân giả: Phải', en: 'Prosthetic side: Right'),
    'CHỌN MẪU': (vi: 'CHỌN NGUỒN', en: 'SELECT SOURCE'),
    'VIDEO MẪU': (vi: 'VIDEO THAM CHIẾU', en: 'REFERENCE VIDEO'),
    'Video mẫu': (vi: 'Video tham chiếu', en: 'Reference video'),
    '0,8×': (vi: '0,8×', en: '0.8×'),
    'Phát bộ ': (vi: 'Phát bộ ', en: 'Play '),
    ' như nguồn camera trực tiếp': (
      vi: ' như nguồn camera trực tiếp',
      en: ' as a live camera source'
    ),
    'biểu đồ đang hiển thị': (
      vi: 'biểu đồ đang hiển thị',
      en: 'charts displayed'
    ),
    'Đang hiển thị cặp #': (vi: 'Đang hiển thị cặp #', en: 'Displaying pair #'),
    'Bước camera · có mốc FSR': (
      vi: 'Bước camera · có mốc FSR',
      en: 'Camera-derived steps · FSR events available'
    ),
    'Bước camera · chưa có mốc FSR': (
      vi: 'Bước camera · chưa có mốc FSR',
      en: 'Camera-derived steps · no FSR events'
    ),
    'Đã nhận chạm chân · chờ nhấc chân để chốt biểu đồ lực pha chống': (
      vi: 'Đã nhận tiếp xúc chân · chờ nhấc chân để hoàn tất biểu đồ lực thì trụ',
      en: 'Foot contact detected · awaiting toe-off to complete the stance-force chart'
    ),
    'Đã nhận bước · T ': (vi: 'Đã nhận bước · T ', en: 'Step detected · L '),
    ' · P ': (vi: ' · P ', en: ' · R '),
    ' · chờ hai bên kế tiếp': (
      vi: ' · chờ hai bên kế tiếp',
      en: ' · awaiting the next bilateral pair'
    ),
    'Bước thiếu bên đối diện vẫn được giữ; không lấy bước ở lượt sau ghép bù.':
        (
      vi: 'Bước thiếu bên đối diện vẫn được giữ; không lấy bước ở lượt sau ghép bù.',
      en: 'An unmatched step is retained; a later step is not used to complete the pair.'
    ),
    'Đủ cặp tiếp theo sẽ tự chuyển': (
      vi: 'Tự chuyển khi đủ cặp bước tiếp theo',
      en: 'Advances automatically when the next pair is complete'
    ),
    'cặp đạt QA': (vi: 'cặp đạt QA', en: 'QA-accepted pairs'),
    'cặp đạt': (vi: 'cặp đạt', en: 'accepted pairs'),
    'cặp lỗi đo bị loại': (
      vi: 'cặp lỗi đo bị loại',
      en: 'measurement-error pairs excluded'
    ),
    'bước lỗi đo bị loại': (
      vi: 'bước lỗi đo bị loại',
      en: 'measurement-error steps excluded'
    ),
    'cặp chuyển tiếp bị loại': (
      vi: 'cặp chuyển tiếp bị loại',
      en: 'transition pairs excluded'
    ),
    'loại ': (vi: 'loại ', en: 'excluded '),
    'bước lẻ': (vi: 'bước lẻ', en: 'unpaired steps'),
    'Đã loại ': (vi: 'Đã loại ', en: 'Excluded '),
    'frame pose chưa đạt': (
      vi: 'khung hình tư thế chưa đạt',
      en: 'low-quality pose frames'
    ),
    'frame pose/visibility chưa đạt': (
      vi: 'khung hình không đạt chất lượng tư thế/độ hiển thị',
      en: 'frames failing pose/visibility quality checks'
    ),
    'cặp bước · cần kiểm tra': (
      vi: 'cặp bước · cần kiểm tra',
      en: 'step pairs · review required'
    ),
    'Đỉnh đo T ': (vi: 'Đỉnh đo T ', en: 'Measured peak L '),
    'Đỉnh T ': (vi: 'Đỉnh T ', en: 'Peak L '),
    'Tổng lực từng chân': (
      vi: 'Tổng lực từng chân',
      en: 'Total force per foot'
    ),
    'Lực từng chân và tổng lực': (
      vi: 'Lực từng chân và tổng lực',
      en: 'Individual-foot and total force'
    ),
    'Lực vùng giữa bàn chân': (
      vi: 'Lực vùng giữa bàn chân',
      en: 'Midfoot force'
    ),
    'Lực vùng trước bàn chân': (
      vi: 'Lực vùng trước bàn chân',
      en: 'Forefoot force'
    ),
    'Lực vùng gót': (vi: 'Lực vùng gót', en: 'Heel force'),
    'Mức tải vùng giữa bàn chân': (
      vi: 'Mức tải vùng giữa bàn chân',
      en: 'Midfoot loading'
    ),
    'Mức tải vùng trước bàn chân': (
      vi: 'Mức tải vùng trước bàn chân',
      en: 'Forefoot loading'
    ),
    'Mức tải vùng gót': (vi: 'Mức tải vùng gót', en: 'Heel loading'),
    'Pha chống đỡ (%)': (vi: 'Thì trụ (%)', en: 'Stance phase (%)'),
    '% thì trụ': (vi: '% thì trụ', en: 'Stance phase (%)'),
    'Lực (': (vi: 'Lực (', en: 'Force ('),
    'Độ cao nhấc bàn chân': (vi: 'Độ cao nhấc bàn chân', en: 'Foot clearance'),
    'Cần thấy rõ hông, gối, gót và mũi chân.': (
      vi: 'Cần thấy rõ hông, gối, gót và mũi chân.',
      en: 'The hips, knees, heels, and toes must remain clearly visible.'
    ),
    'Nhập chiều dài chân trái/phải trong hồ sơ để đổi pixel sang cm.': (
      vi: 'Nhập chiều dài chân trái/phải trong hồ sơ để đổi pixel sang cm.',
      en: 'Enter left/right leg lengths in the patient record to convert pixels to centimetres.'
    ),
    'gần nhất · cm ước tính theo chiều dài chân': (
      vi: 'gần nhất · cm ước tính theo chiều dài chân',
      en: 'latest · centimetres estimated from leg length'
    ),
    'Đang chờ trục vai–hông từ camera ngang để vẽ realtime.': (
      vi: 'Đang chờ trục vai–hông từ camera ngang để vẽ thời gian thực.',
      en: 'Awaiting the shoulder–hip axis from the sagittal camera for real-time plotting.'
    ),
    'Đang chờ trục vai–hông từ camera chính diện để vẽ realtime.': (
      vi: 'Đang chờ trục vai–hông từ camera chính diện để vẽ thời gian thực.',
      en: 'Awaiting the shoulder–hip axis from the frontal camera for real-time plotting.'
    ),
    'Backend chưa chạy hoặc chưa phản hồi.': (
      vi: 'Máy chủ chưa chạy hoặc chưa phản hồi.',
      en: 'The backend is not running or is not responding.'
    ),
    'Camera dọc chưa thấy đủ toàn thân. Hãy đứng lùi để thấy từ vai đến bàn chân.':
        (
      vi: 'Camera mặt phẳng dọc chưa thấy đủ toàn thân. Hãy đứng lùi để thấy từ vai đến bàn chân.',
      en: 'The sagittal camera cannot see the full body. Step back until the shoulders and feet are visible.'
    ),
    'Hãy hoàn tất ít nhất một bước trái và một bước phải.': (
      vi: 'Hãy hoàn tất ít nhất một bước trái và một bước phải.',
      en: 'Complete at least one left step and one right step.'
    ),
    'Mẫu tham khảo': (vi: 'Mẫu tham khảo', en: 'Reference sample'),
    'MTC ước tính': (vi: 'MTC ước tính', en: 'Estimated MTC'),
    'Đang tải dữ liệu lực': (
      vi: 'Đang tải dữ liệu lực',
      en: 'Loading force data'
    ),
    'Trái ': (vi: 'Trái ', en: 'Left '),
    'Phải ': (vi: 'Phải ', en: 'Right '),
    'Tổng ': (vi: 'Tổng ', en: 'Total '),
    'cùng thời điểm video': (
      vi: 'cùng thời điểm video',
      en: 'video-synchronized'
    ),
    'giây': (vi: 'giây', en: 'seconds'),

    // Dynamic records, setup, alerts and reports.
    'Bệnh nhân có ': (vi: 'Người bệnh có ', en: 'Patient has '),
    'Bệnh nhân:': (vi: 'Người bệnh:', en: 'Patient:'),
    ' phiên khám cũ trong lịch sử.': (
      vi: ' phiên đánh giá trước trong lịch sử.',
      en: ' previous assessment sessions in history.'
    ),
    'Không thể bắt đầu ghi:': (
      vi: 'Không thể bắt đầu ghi:',
      en: 'Unable to start acquisition:'
    ),
    'Không thể dừng ghi:': (
      vi: 'Không thể dừng ghi:',
      en: 'Unable to stop acquisition:'
    ),
    'Cải thiện rõ: gập gối +': (
      vi: 'Cải thiện rõ: gập gối +',
      en: 'Clear improvement: knee flexion +'
    ),
    'Cải thiện nhẹ: +': (vi: 'Cải thiện nhẹ: +', en: 'Mild improvement: +'),
    'đỉnh Mean': (vi: 'đỉnh trung bình', en: 'mean peak'),
    'cặp song phương': (vi: 'cặp song phương', en: 'bilateral pairs'),
    'đối xứng đỉnh': (vi: 'đối xứng đỉnh', en: 'peak symmetry'),
    'đỉnh T ': (vi: 'đỉnh T ', en: 'left peak '),
    'Khung FSR gần nhất theo thanh phát video': (
      vi: 'Khung FSR gần nhất theo thanh phát video',
      en: 'Nearest FSR frame on the video timeline'
    ),
    'CHÂN ': (vi: 'CHÂN ', en: 'FOOT '),
    'CV thời gian chu kỳ': (vi: 'CV thời gian chu kỳ', en: 'Cycle-time CV'),
    'Bản ghi dùng xử lý cũ': (
      vi: 'Bản ghi dùng xử lý cũ',
      en: 'Recording uses legacy processing'
    ),
    'bấm PHÂN TÍCH LẠI': (vi: 'chọn PHÂN TÍCH LẠI', en: 'select REANALYZE'),
    'để nhận bước và bỏ làm mượt từ dữ liệu gốc.': (
      vi: 'để nhận diện bước và xử lý lại từ dữ liệu gốc.',
      en: 'to redetect steps and reprocess the raw data.'
    ),
    'Mean ± SD': (vi: 'Trung bình ± SD', en: 'Mean ± SD'),
    'Mean ·': (vi: 'Trung bình ·', en: 'Mean ·'),
    'cặp đã thu': (vi: 'cặp đã thu', en: 'acquired pairs'),
    'chu kỳ · trục thân trung tâm · dữ liệu camera 2D': (
      vi: 'chu kỳ · trục thân trung tâm · dữ liệu camera 2D',
      en: 'cycles · central trunk axis · 2D camera data'
    ),
    'chu kỳ · trục thân trung tâm · chưa đủ tính SD': (
      vi: 'chu kỳ · trục thân trung tâm · chưa đủ tính SD',
      en: 'cycles · central trunk axis · insufficient data for SD'
    ),
    'trái n=': (vi: 'trái n=', en: 'left n='),
    'phải n=': (vi: 'phải n=', en: 'right n='),
    'dữ liệu camera 2D': (vi: 'dữ liệu camera 2D', en: '2D camera data'),
    'chưa đủ tính SD': (vi: 'chưa đủ tính SD', en: 'insufficient data for SD'),
    'theo phần trăm pha chuyển động của từng bước': (
      vi: 'theo phần trăm chu kỳ dáng đi của từng bước',
      en: 'by normalized gait-cycle percentage for each step'
    ),
    'theo phần trăm chu kỳ camera chuẩn hóa': (
      vi: 'theo phần trăm chu kỳ camera chuẩn hóa',
      en: 'by normalized camera-cycle percentage'
    ),
    'tham chiếu': (vi: 'tham chiếu', en: 'reference'),
    'Cặp ': (vi: 'Cặp ', en: 'Pair '),
    'đoạn đã lưu': (vi: 'đoạn đã lưu', en: 'saved segments'),
    'Bộ video này bị gián đoạn trước khi hoàn tất nên không thể phát ổn định.':
        (
      vi: 'Bộ video bị gián đoạn trước khi hoàn tất nên không thể phát ổn định.',
      en: 'This video set was interrupted before completion and cannot be played reliably.'
    ),
    'Hãy xóa bộ này và ghi lại, sau đó bấm DỪNG GHI trước khi tắt backend.': (
      vi: 'Hãy xóa bộ này và ghi lại, sau đó chọn DỪNG GHI trước khi tắt máy chủ.',
      en: 'Delete this set and record again, then select STOP ACQUISITION before shutting down the backend.'
    ),
    'Không tìm thấy phiên gốc của bộ video này.': (
      vi: 'Không tìm thấy phiên gốc của bộ video này.',
      en: 'The source session for this video set was not found.'
    ),
    'BỘ VIDEO ĐÃ LƯU': (vi: 'BỘ VIDEO ĐÃ LƯU', en: 'SAVED VIDEO SET'),
    'Bộ ': (vi: 'Bộ ', en: 'Set '),
    ' · Phiên ': (vi: ' · Phiên ', en: ' · Session '),
    ' · chờ duyệt': (vi: ' · chờ duyệt', en: ' · pending review'),
    ' · MẪU': (vi: ' · MẪU', en: ' · REFERENCE'),
    ' · gián đoạn': (vi: ' · gián đoạn', en: ' · interrupted'),
    ' · FSR đã lưu': (vi: ' · FSR đã lưu', en: ' · FSR saved'),
    ' · thiếu FSR': (vi: ' · thiếu FSR', en: ' · FSR missing'),
    'ĐẦY ĐỦ ·': (vi: 'ĐẦY ĐỦ ·', en: 'FULL ·'),
    'ĐOẠN CẮT ·': (vi: 'ĐOẠN CẮT ·', en: 'CLIP ·'),
    'Đang nạp dữ liệu đoạn...': (
      vi: 'Đang nạp dữ liệu đoạn...',
      en: 'Loading segment data...'
    ),
    'Hồ sơ:': (vi: 'Hồ sơ:', en: 'Record:'),
    'KẾT QUẢ SO SÁNH LÂM SÀNG: PHIÊN KHÁM': (
      vi: 'KẾT QUẢ SO SÁNH LÂM SÀNG: PHIÊN ĐÁNH GIÁ',
      en: 'CLINICAL COMPARISON RESULTS: ASSESSMENT SESSION'
    ),
    'nới lỏng': (vi: 'nới lỏng', en: 'loosen'),
    'khóa lại': (vi: 'khóa lại', en: 'tighten'),
    'Kết quả tìm thấy (': (vi: 'Kết quả tìm thấy (', en: 'Search results ('),
    'Mã định danh bệnh án:': (
      vi: 'Mã định danh hồ sơ:',
      en: 'Patient record ID:'
    ),
    'Không thể khởi động kết nối FSR:': (
      vi: 'Không thể khởi động kết nối FSR:',
      en: 'Unable to start the FSR connection:'
    ),
    'Camera mới đạt ': (
      vi: 'Camera mới đạt ',
      en: 'Camera frame rate is only '
    ),
    'Chưa thấy ổn định toàn thân ở cả hai góc': (
      vi: 'Chưa thấy ổn định toàn thân ở cả hai góc',
      en: 'Stable full-body visibility has not been achieved in both views'
    ),
    'Nhận diện toàn thân mới đạt ': (
      vi: 'Nhận diện toàn thân mới đạt ',
      en: 'Full-body detection is only '
    ),
    'Pose có chất lượng mới đạt ': (
      vi: 'Tư thế đạt chất lượng mới đạt ',
      en: 'Quality-approved pose rate is only '
    ),
    'frame (cần ≥ 70%).': (
      vi: 'khung hình (cần ≥ 70%).',
      en: 'of frames (required ≥ 70%).'
    ),
    '% frame': (vi: '% khung hình', en: '% of frames'),
    'Hãy thấy trọn vai–hông–gối–cổ chân.': (
      vi: 'Hãy bảo đảm thấy trọn vai–hông–gối–cổ chân.',
      en: 'Ensure the shoulders, hips, knees, and ankles are fully visible.'
    ),
    'FSR 2/2 · trái ': (vi: 'FSR 2/2 · trái ', en: 'FSR 2/2 · left '),
    'phải ': (vi: 'phải ', en: 'right '),
    'FSR 1/2 · chưa nhận chân': (
      vi: 'FSR 1/2 · chưa nhận chân',
      en: 'FSR 1/2 · awaiting '
    ),
    'Cổng FSR đang bị ứng dụng khác giữ': (
      vi: 'Cổng FSR đang bị ứng dụng khác sử dụng',
      en: 'The FSR port is in use by another application'
    ),
    'dò danh sách camera': (vi: 'dò danh sách camera', en: 'detecting cameras'),
    'áp dụng cấu hình hai camera': (
      vi: 'áp dụng cấu hình hai camera',
      en: 'applying dual-camera configuration'
    ),
    'Quá thời gian khi ': (vi: 'Quá thời gian khi ', en: 'Timed out while '),
    'Backend có thể vẫn đang kiểm tra driver camera.': (
      vi: 'Máy chủ có thể vẫn đang kiểm tra trình điều khiển camera.',
      en: 'The backend may still be checking the camera driver.'
    ),
    'Hồ sơ lâm sàng:': (vi: 'Hồ sơ lâm sàng:', en: 'Clinical record:'),
    'Giả Trái': (vi: 'Giả trái', en: 'Left prosthesis'),
    'Giả Phải': (vi: 'Giả phải', en: 'Right prosthesis'),
    'Chân giả bên ': (vi: 'Chân giả bên ', en: 'The '),
    ' phải ở phía gần camera ngang.': (
      vi: ' phải ở phía gần camera ngang.',
      en: ' prosthetic foot must be closest to the sagittal camera.'
    ),
    'Ảnh thử · chính diện': (
      vi: 'Ảnh thử · chính diện',
      en: 'Test image · frontal view'
    ),
    'Ảnh thử · một camera': (
      vi: 'Ảnh thử · một camera',
      en: 'Test image · single camera'
    ),
    'Ảnh thử · mặt phẳng dọc': (
      vi: 'Ảnh thử · mặt phẳng dọc',
      en: 'Test image · sagittal view'
    ),
    'Không thể đảo camera:': (
      vi: 'Không thể đổi camera:',
      en: 'Unable to swap cameras:'
    ),
    'Không kết nối được backend hiệu chuẩn:': (
      vi: 'Không kết nối được máy chủ hiệu chuẩn:',
      en: 'Unable to connect to the calibration backend:'
    ),
    'Đã chụp ': (vi: 'Đã chụp ', en: 'Captured '),
    ' mẫu': (vi: ' mẫu', en: ' samples'),
    'Calibration đang dùng được': (
      vi: 'Thông số hiệu chuẩn đang dùng được',
      en: 'Calibration is valid'
    ),
    'Đang lưu video raw. Lưu ý:': (
      vi: 'Đang lưu video gốc. Lưu ý:',
      en: 'Saving raw video. Note:'
    ),
    'Đã lưu video. Lưu ý dữ liệu:': (
      vi: 'Đã lưu video. Lưu ý dữ liệu:',
      en: 'Video saved. Data note:'
    ),
    'Không lưu được video mẫu:': (
      vi: 'Không lưu được video tham chiếu:',
      en: 'Unable to save the reference video:'
    ),
    'Mốc đầu đoạn ': (vi: 'Mốc đầu đoạn ', en: 'Segment start marker '),
    'Mốc cuối ': (vi: 'Mốc cuối ', en: 'End marker '),
    'Đoạn mẫu ': (vi: 'Đoạn mẫu ', en: 'Reference segment '),
    'Đoạn phân tích ': (vi: 'Đoạn phân tích ', en: 'Analysis segment '),
    'Đã lưu ': (vi: 'Đã lưu ', en: 'Saved '),
    'Đang thu video mẫu': (
      vi: 'Đang thu video tham chiếu',
      en: 'Acquiring reference video'
    ),
    'đã duyệt': (vi: 'đã duyệt', en: 'approved'),
    'chờ duyệt': (vi: 'chờ duyệt', en: 'pending review'),
    'Video đã lưu': (vi: 'Video đã lưu', en: 'Saved video'),
    'Phiên ghi đã dừng': (vi: 'Phiên ghi đã dừng', en: 'Acquisition stopped'),
    'ĐẶT MỐC ĐẦU': (vi: 'ĐẶT MỐC ĐẦU', en: 'SET START MARKER'),
    'MỐC CUỐI & LƯU': (vi: 'MỐC CUỐI VÀ LƯU', en: 'END MARKER AND SAVE'),
    'BẮT ĐẦU GHI': (vi: 'BẮT ĐẦU GHI', en: 'START ACQUISITION'),
    'VIDEO ĐÃ LƯU': (vi: 'VIDEO ĐÃ LƯU', en: 'SAVED VIDEO'),
    'CAMERA THẬT': (vi: 'CAMERA TRỰC TIẾP', en: 'LIVE CAMERA'),
    'CHÍNH DIỆN · CAM ': (
      vi: 'CHÍNH DIỆN · CAMERA ',
      en: 'FRONTAL VIEW · CAMERA '
    ),
    'MẶT PHẲNG DỌC · CAM ': (
      vi: 'MẶT PHẲNG DỌC · CAMERA ',
      en: 'SAGITTAL VIEW · CAMERA '
    ),
    'Đang kết nối': (vi: 'Đang kết nối', en: 'Connecting'),
    'Đang hoạt động': (vi: 'Đang hoạt động', en: 'Active'),
    'Mất tín hiệu': (vi: 'Mất tín hiệu', en: 'Signal lost'),
    'FSR video mẫu': (vi: 'FSR video tham chiếu', en: 'Reference-video FSR'),
    'Biểu đồ': (vi: 'Biểu đồ', en: 'Charts'),
    'BỎ CHỌN': (vi: 'BỎ CHỌN', en: 'DESELECT'),
    'Thông tin phiên': (vi: 'Thông tin phiên', en: 'Session information'),
    'Thời lượng:': (vi: 'Thời lượng:', en: 'Duration:'),
    'Server phản hồi mã lỗi:': (
      vi: 'Máy chủ phản hồi mã lỗi:',
      en: 'Server returned error code:'
    ),
    'Backend trả mã ': (vi: 'Máy chủ trả mã ', en: 'Backend returned status '),
    'Không thể kết nối API hoặc Server đang ngoại tuyến. Chi tiết lỗi:': (
      vi: 'Không thể kết nối API hoặc máy chủ đang ngoại tuyến. Chi tiết lỗi:',
      en: 'Unable to connect to the API, or the server is offline. Error details:'
    ),
    'Vui lòng khởi chạy FastAPI server.': (
      vi: 'Vui lòng khởi chạy máy chủ FastAPI.',
      en: 'Start the FastAPI server.'
    ),
    'Không thể ghi nhận bệnh án lên Database. Chi tiết lỗi:': (
      vi: 'Không thể lưu hồ sơ vào cơ sở dữ liệu. Chi tiết lỗi:',
      en: 'Unable to save the patient record to the database. Error details:'
    ),
    'Vui lòng kiểm tra kết nối với FastAPI server.': (
      vi: 'Vui lòng kiểm tra kết nối với máy chủ FastAPI.',
      en: 'Check the connection to the FastAPI server.'
    ),
    'hồ sơ': (vi: 'hồ sơ', en: 'records'),
    'tuổi': (vi: 'tuổi', en: 'years old'),
    'phiên khám': (vi: 'phiên đánh giá', en: 'assessment sessions'),
    'Phiên khám': (vi: 'Phiên đánh giá', en: 'Assessment session'),
    'Tạo phiên thu mẫu cho ': (
      vi: 'Tạo phiên thu mẫu cho ',
      en: 'Create a reference acquisition for '
    ),
    'Đã tạo phiên mẫu. Đang chuyển sang chuẩn bị camera.': (
      vi: 'Đã tạo phiên tham chiếu. Đang chuyển sang chuẩn bị camera.',
      en: 'Reference session created. Opening camera setup.'
    ),
    'Không tạo được phiên mẫu:': (
      vi: 'Không tạo được phiên tham chiếu:',
      en: 'Unable to create the reference session:'
    ),
    'Chưa có phiên khám nào. Vui lòng bắt đầu tại Tab 1.': (
      vi: 'Chưa có phiên đánh giá. Vui lòng bắt đầu tại mục 1.',
      en: 'No assessment session is available. Start from Patient records.'
    ),
    'Vui lòng chọn bệnh nhân': (
      vi: 'Vui lòng chọn người bệnh',
      en: 'Select a patient'
    ),
    'bệnh nhân': (vi: 'người bệnh', en: 'patient'),
    'Bệnh nhân': (vi: 'Người bệnh', en: 'Patient'),
    'Scan': (vi: 'lần ghi', en: 'acquisition'),
    'Quét': (vi: 'Ghi dữ liệu', en: 'Acquire'),
    'quét': (vi: 'ghi dữ liệu', en: 'acquire'),
    'Ghi hình': (vi: 'Ghi hình', en: 'Video acquisition'),
    'BẮT ĐẦU PHIÊN KHÁM MỚI': (
      vi: 'BẮT ĐẦU PHIÊN ĐÁNH GIÁ MỚI',
      en: 'START NEW ASSESSMENT'
    ),
    'Mỗi phiên khám sẽ tạo một ID phiên riêng biệt.': (
      vi: 'Mỗi phiên đánh giá sẽ tạo một mã phiên riêng.',
      en: 'Each assessment creates a unique session ID.'
    ),
    'Không thể dò camera:': (
      vi: 'Không thể dò camera:',
      en: 'Unable to detect cameras:'
    ),
    'Không tìm thấy camera. Kiểm tra cáp USB và đóng ứng dụng đang chiếm camera.':
        (
      vi: 'Không tìm thấy camera. Kiểm tra cáp USB và đóng ứng dụng đang sử dụng camera.',
      en: 'No camera was detected. Check the USB cable and close any application using the camera.'
    ),
    'Hai vai trò phải dùng hai camera khác nhau.': (
      vi: 'Hai vai trò phải dùng hai camera khác nhau.',
      en: 'The two views must use different cameras.'
    ),
    'Không thể áp dụng camera:': (
      vi: 'Không thể áp dụng camera:',
      en: 'Unable to apply camera configuration:'
    ),
    'Đã áp dụng cài đặt camera. Kiểm tra hai góc quay trước khi ghi hình.': (
      vi: 'Đã áp dụng cài đặt camera. Kiểm tra hai góc quay trước khi ghi hình.',
      en: 'Camera settings applied. Verify both views before recording.'
    ),
    'Backend chưa chạy': (
      vi: 'Máy chủ chưa chạy',
      en: 'Backend is not running'
    ),
    'không thể tải camera': (
      vi: 'không thể tải camera',
      en: 'unable to load camera'
    ),
    'vẫn có thể quay chỉ với camera': (
      vi: 'vẫn có thể ghi chỉ với camera',
      en: 'camera-only acquisition remains available'
    ),
    'Backend chưa phản hồi': (
      vi: 'Máy chủ chưa phản hồi',
      en: 'Backend is not responding'
    ),
    'Đang chờ khung hình từ camera': (
      vi: 'Đang chờ khung hình từ camera',
      en: 'Awaiting camera frames'
    ),
    'Chất lượng hình chưa đạt': (
      vi: 'Chất lượng hình chưa đạt',
      en: 'Image quality is insufficient'
    ),
    'hình quá tối hoặc nắp camera đang đóng': (
      vi: 'hình quá tối hoặc nắp camera đang đóng',
      en: 'image is too dark or the camera shutter is closed'
    ),
    'hình bị cháy sáng': (vi: 'hình bị cháy sáng', en: 'image is overexposed'),
    'hình quá mờ/mất nét': (
      vi: 'hình quá mờ/mất nét',
      en: 'image is blurred or out of focus'
    ),
    'CẢNH BÁO: hình tối': (
      vi: 'CẢNH BÁO: hình tối',
      en: 'WARNING: image too dark'
    ),
    'CẢNH BÁO: cháy sáng': (
      vi: 'CẢNH BÁO: cháy sáng',
      en: 'WARNING: overexposed image'
    ),
    'CẢNH BÁO: hình mờ': (
      vi: 'CẢNH BÁO: hình mờ',
      en: 'WARNING: blurred image'
    ),
    'hình OK': (vi: 'hình đạt', en: 'image OK'),
    'Đã nhận dữ liệu lực từ cả hai chân ngay trong AI-ProGait.': (
      vi: 'Đã nhận dữ liệu lực từ cả hai chân trong AI-ProGait.',
      en: 'AI-ProGait is receiving force data from both feet.'
    ),
    'Kết nối FSR quá thời gian.': (
      vi: 'Kết nối FSR quá thời gian.',
      en: 'FSR connection timed out.'
    ),
    'FSR chưa kết nối': (vi: 'FSR chưa kết nối', en: 'FSR disconnected'),
    'Chưa thấy FSR': (vi: 'Chưa thấy FSR', en: 'FSR not detected'),
    'đang kết nối': (vi: 'đang kết nối', en: 'connecting'),
    'đang chờ': (vi: 'đang chờ', en: 'awaiting'),
    'Sẵn sàng ghi': (vi: 'Sẵn sàng ghi', en: 'Ready to record'),
    'Chưa nhận đủ hai camera.': (
      vi: 'Chưa nhận đủ hai camera.',
      en: 'Both cameras are not available.'
    ),
    'Chưa nhận camera mặt phẳng dọc.': (
      vi: 'Chưa nhận camera mặt phẳng dọc.',
      en: 'The sagittal camera is not available.'
    ),
    'Đã cập nhật số đo hiệu chuẩn và thông tin lâm sàng.': (
      vi: 'Đã cập nhật số đo hiệu chuẩn và thông tin lâm sàng.',
      en: 'Calibration measurements and clinical information updated.'
    ),
    'Đã thêm ghi chú lâm sàng thành công.': (
      vi: 'Đã thêm ghi chú lâm sàng.',
      en: 'Clinical note added.'
    ),
    'Không phân tích lại được:': (
      vi: 'Không thể phân tích lại:',
      en: 'Unable to reanalyze:'
    ),
    'Không nạp được archive': (
      vi: 'Không nạp được dữ liệu lưu trữ',
      en: 'Unable to load archive'
    ),
    'Hãy kiểm tra backend rồi thử lại.': (
      vi: 'Hãy kiểm tra máy chủ rồi thử lại.',
      en: 'Check the backend and try again.'
    ),
    'Không giải mã được video đã lưu': (
      vi: 'Không giải mã được video đã lưu',
      en: 'Unable to decode the saved video'
    ),
    'Không xóa được bộ video:': (
      vi: 'Không xóa được bộ video:',
      en: 'Unable to delete the video set:'
    ),
    'Đã tạo revision ': (vi: 'Đã tạo phiên bản ', en: 'Created revision '),
    'từ cùng bản quay gốc.': (
      vi: 'từ cùng bản quay gốc.',
      en: 'from the same raw recording.'
    ),
    'Tuổi:': (vi: 'Tuổi:', en: 'Age:'),
    'Chiều cao:': (vi: 'Chiều cao:', en: 'Height:'),
    'Cân nặng:': (vi: 'Cân nặng:', en: 'Weight:'),
    'Chân lành sinh học:': (
      vi: 'Chân lành sinh học:',
      en: 'Sound biological foot:'
    ),
    'Chân giả lắp đặt:': (vi: 'Bên lắp chân giả:', en: 'Prosthetic side:'),
    'Phiên kiểm định:': (vi: 'Phiên đánh giá:', en: 'Assessment session:'),
    'Tạo ngày:': (vi: 'Ngày tạo:', en: 'Created:'),
    'Ghi chú kỹ thuật viên:': (
      vi: 'Ghi chú kỹ thuật viên:',
      en: 'Clinician notes:'
    ),
    'Căn chỉnh cơ khí thực tế:': (
      vi: 'Căn chỉnh cơ khí thực tế:',
      en: 'Actual mechanical alignment:'
    ),
    'Đang kết nối máy in để xuất bản báo cáo PDF...': (
      vi: 'Đang kết nối máy in để xuất báo cáo PDF...',
      en: 'Connecting to the printer to export the PDF report...'
    ),
    'Phiên khám này hiện chỉ có 1 lần quét đánh giá.': (
      vi: 'Phiên đánh giá này hiện chỉ có một lần ghi dữ liệu.',
      en: 'This assessment currently contains only one acquisition.'
    ),
    'Thiếu dữ liệu so sánh': (
      vi: 'Thiếu dữ liệu so sánh',
      en: 'Insufficient comparison data'
    ),
    'Gập duỗi khớp gối trái': (
      vi: 'Gập duỗi khớp gối trái',
      en: 'Left knee flexion–extension'
    ),
    'Gập duỗi khớp gối phải': (
      vi: 'Gập duỗi khớp gối phải',
      en: 'Right knee flexion–extension'
    ),
    'Đồ thị so sánh:': (vi: 'Biểu đồ so sánh:', en: 'Comparison chart:'),
    'Trước chỉnh': (vi: 'Trước căn chỉnh', en: 'Pre-alignment'),
    'Sau chỉnh': (vi: 'Sau căn chỉnh', en: 'Post-alignment'),
    'Góc gập gối max': (vi: 'Góc gập gối lớn nhất', en: 'Maximum knee flexion'),
    'Góc duỗi thẳng max': (
      vi: 'Góc duỗi gối lớn nhất',
      en: 'Maximum knee extension'
    ),
    'Nhịp điệu Cadence': (vi: 'Nhịp bước', en: 'Cadence'),
    'Sải chân ước tính': (
      vi: 'Chiều dài sải chân ước tính',
      en: 'Estimated stride length'
    ),
    'BỆNH NHÂN:': (vi: 'NGƯỜI BỆNH:', en: 'PATIENT:'),
    'Phiên khám:': (vi: 'Phiên đánh giá:', en: 'Assessment session:'),
    'Ngày:': (vi: 'Ngày:', en: 'Date:'),
    'Scans:': (vi: 'Lần ghi:', en: 'Acquisitions:'),
    'Đang quét:': (vi: 'Đang ghi:', en: 'Acquiring:'),
    'Cặp bước': (vi: 'Cặp bước', en: 'Step pair'),
    'cặp bước': (vi: 'cặp bước', en: 'step pairs'),
    'cặp chu kỳ': (vi: 'cặp chu kỳ', en: 'cycle pairs'),
    'bước/phút': (vi: 'bước/phút', en: 'steps/min'),
    ' b/p': (vi: ' bước/phút', en: ' steps/min'),
    'Chân trái': (vi: 'Chân trái', en: 'Left foot'),
    'Chân phải': (vi: 'Chân phải', en: 'Right foot'),
    'chân trái': (vi: 'chân trái', en: 'left foot'),
    'chân phải': (vi: 'chân phải', en: 'right foot'),
    'chân lành': (vi: 'chân lành', en: 'sound foot'),
    'chân giả': (vi: 'chân giả', en: 'prosthetic foot'),
    'Góc khớp gối': (vi: 'Góc khớp gối', en: 'Knee angle'),
    'góc khớp gối': (vi: 'góc khớp gối', en: 'knee angle'),
    'Góc khớp hông': (vi: 'Góc khớp hông', en: 'Hip angle'),
    'góc khớp hông': (vi: 'góc khớp hông', en: 'hip angle'),
    'Góc nghiêng thân': (vi: 'Góc nghiêng thân', en: 'Trunk lean angle'),
    'Nhịp bước': (vi: 'Nhịp bước', en: 'Cadence'),
    'Sải chân': (vi: 'Chiều dài sải chân', en: 'Stride length'),
    'Quét lại': (vi: 'Ghi lại', en: 'Reacquire'),
    'Quét Lại': (vi: 'Ghi lại', en: 'Reacquire'),
    'Quét đánh giá': (vi: 'Ghi dữ liệu đánh giá', en: 'Assessment acquisition'),
    'Quét xác minh': (
      vi: 'Ghi dữ liệu xác minh',
      en: 'Verification acquisition'
    ),
    'Quét xong': (vi: 'Ghi xong', en: 'After acquisition'),
    'Scan #1': (vi: 'lần ghi 1', en: 'acquisition 1'),
    'Scan #2': (vi: 'lần ghi 2', en: 'acquisition 2'),
    'Before / After': (
      vi: 'trước / sau căn chỉnh',
      en: 'pre- / post-alignment'
    ),
    'Before/After': (vi: 'trước/sau căn chỉnh', en: 'pre-/post-alignment'),
    'Recording': (vi: 'Ghi dữ liệu', en: 'Data acquisition'),
    'Dashboard Analysis': (
      vi: 'Bảng phân tích dáng đi',
      en: 'Gait analysis dashboard'
    ),
    'Trước–sau': (vi: 'Trước–sau', en: 'Anterior–posterior'),
    'Trái–phải': (vi: 'Trái–phải', en: 'Left–right'),
    'Dương: nghiêng về phía trước · Âm: nghiêng về phía sau': (
      vi: 'Dương: nghiêng về phía trước · Âm: nghiêng về phía sau',
      en: 'Positive: anterior lean · Negative: posterior lean'
    ),
    'Dương: phải · Âm: trái (theo người được đo)': (
      vi: 'Dương: phải · Âm: trái (theo người được đo)',
      en: 'Positive: right · Negative: left (participant perspective)'
    ),
  };
}
