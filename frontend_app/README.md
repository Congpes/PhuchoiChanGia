# AI-ProGait — Frontend (Flutter)

Giao diện phân tích dáng đi kiểu lab (tham chiếu CONTEMPLAS): 2 camera, biểu đồ gối/cổ chân L/R, sidebar workflow tinh chỉnh chân giả.

## Yêu cầu

- [Flutter SDK](https://docs.flutter.dev/get-started/install/windows) 3.16+
- Windows desktop và/hoặc Android

## Chạy lần đầu

```powershell
cd frontend_app

# Tạo folder platform (windows, android...) nếu chưa có
flutter create . --project-name ai_progait

flutter pub get
flutter run -d windows
# hoặc: flutter run -d chrome   (demo nhanh trên web)
# hoặc: flutter run              (Android device/emulator)
```

## Luồng demo hiện tại (mock data)

1. Chọn **chân lành** và **chân giả** trên sidebar
2. Chọn phase **Baseline** → bấm **Record (10s)** → dữ liệu mẫu baseline
3. Phase **Quét đánh giá** → Record lần nữa → biểu đồ + **đề xuất tinh chỉnh**
4. **Đã chỉnh → Quét lại** → Record lần 2 → so sánh Before/After

Camera preview và pose tracking sẽ tích hợp ở bước sau (ML Kit / backend Python).

## Cấu trúc

```
lib/
  main.dart
  models/gait_data.dart       # Session, scan, recommendations
  services/mock_gait_service.dart
  providers/session_provider.dart
  screens/analysis_dashboard.dart
  widgets/
    camera_panel.dart
    gait_chart.dart
    metrics_grid.dart
    analysis_sidebar.dart
    timeline_bar.dart
  theme/app_theme.dart
```
