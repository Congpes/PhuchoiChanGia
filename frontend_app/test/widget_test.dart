import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fl_chart/fl_chart.dart';

import 'package:ai_progait/l10n/app_language.dart';
import 'package:ai_progait/l10n/localized_text.dart' as localized;
import 'package:ai_progait/main.dart';
import 'package:ai_progait/widgets/analysis_section_switcher.dart';
import 'package:ai_progait/widgets/fsr_force_phase_dashboard.dart';
import 'package:ai_progait/widgets/gait_cycle_analysis.dart';
import 'package:ai_progait/widgets/smoothed_line_chart.dart';

void main() {
  testWidgets('opens the patient workspace', (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const AiProGaitApp());
    await tester.pump();

    expect(find.text('Hồ sơ người bệnh'), findsOneWidget);
    expect(find.text('Tìm kiếm người bệnh...'), findsOneWidget);
  });

  testWidgets('switches the full interface between Vietnamese and English',
      (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final languageController = AppLanguageController();
    addTearDown(languageController.dispose);
    await tester.pumpWidget(
      AiProGaitApp(languageController: languageController),
    );
    await tester.pump();

    await tester.tap(find.text('Kỹ thuật viên'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cài đặt'));
    await tester.pumpAndSettle();

    expect(find.text('Ngôn ngữ giao diện'), findsOneWidget);
    await tester.tap(find.text('English'));
    await tester.pumpAndSettle();

    expect(languageController.language, AppLanguage.english);
    expect(find.text('Settings'), findsOneWidget);
    expect(find.text('Interface language'), findsOneWidget);
    expect(find.text('Patient records'), findsWidgets);

    await tester.tap(find.text('CLOSE'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Clinician'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Add patient record'));
    await tester.pumpAndSettle();

    expect(find.text('Patient full name *'), findsOneWidget);
    expect(find.text('Sound biological foot:'), findsOneWidget);
  });

  test('uses the report glossary for clinical gait terminology', () {
    expect(
      AppTranslations.translate('Thì trụ', AppLanguage.english),
      'Stance phase',
    );
    expect(
      AppTranslations.translate('Đáp ứng tải', AppLanguage.english),
      'Loading response',
    );
    expect(
      AppTranslations.translate('Chân lành', AppLanguage.english),
      'Sound foot',
    );
    expect(
      AppTranslations.translate('Chân giả', AppLanguage.english),
      'Prosthetic foot',
    );
    expect(
      AppTranslations.translate(
        'ROM Gập duỗi gối',
        AppLanguage.vietnamese,
      ),
      'Biên độ vận động khớp gối (ROM)',
    );
  });

  test('translates acquisition controls, notifications and chart copy', () {
    const cases = <String, String>{
      'VỀ CAMERA THẬT': 'BACK TO LIVE CAMERA',
      'CHỌN MẪU · VIDEO MẪU 0,8×': 'SELECT SOURCE · REFERENCE VIDEO 0.8×',
      '2 biểu đồ đang hiển thị': '2 charts displayed',
      'BIỂU ĐỒ REALTIME': 'REAL-TIME CHARTS',
      'Phân bố áp lực FSR': 'FSR pressure distribution',
      'Dữ liệu cân nặng': 'Weight-scaled data',
      'Tổng lực từng chân (N)': 'Total force per foot (N)',
      '% thì trụ': 'Stance phase (%)',
      'Đỉnh T 592.8 · P 610.0 N': 'Peak L 592.8 · R 610.0 N',
      'Đang hiển thị cặp #3 · FSR QA · 3 cặp đạt':
          'Displaying pair #3 · FSR QA · 3 accepted pairs',
      'Không thể áp dụng camera: timeout':
          'Unable to apply camera configuration: timeout',
      'Không xóa được bộ video: timeout':
          'Unable to delete the video set: timeout',
      'Góc nghiêng thân (°) · trái–phải':
          'Trunk lean angle (°) · medial–lateral',
      'ID: p-123 | 19 tuổi | Chân giả: Trái':
          'ID: p-123 | 19 years old | Prosthetic side: Left',
      'Bệnh nhân có 2 phiên khám cũ trong lịch sử.':
          'Patient has 2 previous assessment sessions in history.',
      'Backend chưa chạy · không thể tải camera':
          'Backend is not running · unable to load camera',
      'FSR chưa kết nối · vẫn có thể quay chỉ với camera':
          'FSR disconnected · camera-only acquisition remains available',
      '2.0 giây': '2.0 seconds',
      'Hai vai trò phải dùng hai camera khác nhau.':
          'The two views must use different cameras.',
      'Chọn camera cho góc chính diện và mặt phẳng dọc. Có thể đổi ngay trong phiên; hai luồng hình sẽ tạm dừng vài giây khi áp dụng.':
          'Assign the frontal and sagittal cameras. Camera roles can be changed during the session; both video streams pause briefly while the configuration is applied.',
      'Chân giả bên TRÁI phải ở phía gần camera ngang. Chỉ các frame thấy rõ hông–gối–cổ chân với visibility ≥ 0,70 mới được dùng tính góc.':
          'The left prosthetic foot must be closest to the sagittal camera. Only frames with clearly visible hips, knees, and ankles and visibility ≥ 0.70 are used for angle calculations.',
    };

    for (final entry in cases.entries) {
      expect(
        AppTranslations.translate(entry.key, AppLanguage.english),
        entry.value,
        reason: entry.key,
      );
    }
  });

  test('translates presentation report metrics and chart envelopes', () {
    const cases = <String, String>{
      'Dữ liệu hai chân · Mean ± SD · 3 cặp bước · FSI 100% = cân bằng':
          'Bilateral data · Mean ± SD · 3 step pairs · FSI 100% = balanced',
      'Peak tổng lực (N)': 'Peak total force (N)',
      'Peak vùng gót (N)': 'Peak heel force (N)',
      'Peak vùng giữa bàn chân (N)': 'Peak midfoot force (N)',
      'Peak Fore (mũi / đẩy chân) (N)': 'Peak forefoot force (N)',
      'Lực trung bình pha chống (N)': 'Mean stance-phase force (N)',
      'Xung lực tải (N·s)': 'Loading impulse (N·s)',
      'Trái · dải hiển thị': 'Left foot · ± SD',
      'Phải · dải hiển thị': 'Right foot · ± SD',
    };

    for (final entry in cases.entries) {
      expect(
        AppTranslations.translate(entry.key, AppLanguage.english),
        entry.value,
        reason: entry.key,
      );
    }
  });

  testWidgets('does not partially translate patient-entered clinical text',
      (tester) async {
    final languageController = AppLanguageController(
      initialLanguage: AppLanguage.english,
    );
    addTearDown(languageController.dispose);

    await tester.pumpWidget(
      AppLanguageScope(
        controller: languageController,
        child: const MaterialApp(
          home: Scaffold(
            body: localized.Text(
              'Cụt chân trái',
              translate: false,
            ),
          ),
        ),
      ),
    );

    expect(find.text('Cụt chân trái'), findsOneWidget);
    expect(find.text('Cụt left foot'), findsNothing);
  });

  testWidgets('shows FSR measurement quality summary for saved analysis',
      (tester) async {
    reportSmoothing.value = false;
    addTearDown(() => reportSmoothing.value = true);
    tester.view.physicalSize = const Size(1100, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final curve = List<double>.generate(101, (index) => index.toDouble());
    final spread = List<double>.filled(101, 5);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FsrForcePhaseDashboard(
            analysis: {
              'unit': 'N_estimated',
              'qualityPolicy': 'measurement_artifacts_only_v2',
              'pairCount': 4,
              'qualityExcludedPairCount': 1,
              'steadyStateExcludedPairCount': 1,
              'acquisitionQuality': const {
                'qualityRejectedSteps': {'left': 1, 'right': 1},
              },
              'regions': {
                for (final region in ['heel', 'midfoot', 'forefoot'])
                  region: {
                    'left': {'mean': curve, 'sd': spread},
                    'right': {'mean': curve, 'sd': spread},
                  },
              },
            },
          ),
        ),
      ),
    );

    expect(
      find.text(
        'QA dữ liệu · 4 cặp đạt · 1 cặp lỗi đo bị loại · '
        '2 bước lỗi đo bị loại · 1 cặp chuyển tiếp bị loại',
      ),
      findsOneWidget,
    );
    expect(find.text('Hình dạng (%)'), findsNothing);
    expect(find.text('Lực gốc'), findsNothing);
    expect(find.textContaining('CHẾ ĐỘ'), findsNothing);
    final charts = tester.widgetList<LineChart>(find.byType(LineChart));
    expect(charts, hasLength(2));
    expect(find.text('Lực (N)'), findsNWidgets(2));
    expect(charts.every((chart) => chart.data.betweenBarsData.length == 3),
        isTrue);
    expect(
      charts.every(
        (chart) => chart.data.lineBarsData.every(
          (line) => !line.isCurved,
        ),
      ),
      isTrue,
    );
  });

  testWidgets('shows report-ready total force and FSI comparison table',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final curve = List<double>.generate(101, (index) => index.toDouble());
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FsrForcePhaseDashboard(
            analysis: {
              'unit': 'N',
              'healthySide': 'left',
              'pairCount': 3,
              'forceSummary': const {
                'pairCount': 3,
                'rows': [
                  {
                    'key': 'peakTotal',
                    'label': 'Peak tổng lực',
                    'unit': 'N',
                    'left': {'mean': 420.0, 'sd': 12.0, 'n': 3},
                    'right': {'mean': 399.0, 'sd': 15.0, 'n': 3},
                    'fsi': 95.0,
                    'asymmetry': 5.0,
                  },
                  {
                    'key': 'peakFore',
                    'label': 'Peak mũi / đẩy chân',
                    'unit': 'N',
                    'left': {'mean': 170.0, 'sd': 8.0, 'n': 3},
                    'right': {'mean': 153.0, 'sd': 9.0, 'n': 3},
                    'fsi': 90.0,
                    'asymmetry': 10.0,
                  },
                ],
              },
              'regions': {
                for (final region in ['heel', 'midfoot', 'forefoot'])
                  region: {
                    'left': {'mean': curve, 'sd': const <double>[]},
                    'right': {'mean': curve, 'sd': const <double>[]},
                  },
              },
            },
          ),
        ),
      ),
    );

    expect(find.text('BẢNG SO SÁNH LỰC FSR TRÁI–PHẢI'), findsOneWidget);
    expect(find.text('Chân trái'), findsWidgets);
    expect(find.text('Chân phải'), findsWidgets);
    expect(find.textContaining('LÀNH'), findsNothing);
    expect(find.textContaining('GIẢ'), findsNothing);
    expect(find.text('Đỉnh tổng lực (N)'), findsOneWidget);
    expect(find.text('420.0 ± 12.0'), findsOneWidget);
    expect(find.text('399.0 ± 15.0'), findsOneWidget);
    expect(find.text('95.0%'), findsOneWidget);
    expect(find.text('Peak mũi / đẩy chân (N)'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('saved FSR view preserves measured values on a shared axis',
      (tester) async {
    tester.view.physicalSize = const Size(1100, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    Map<String, dynamic> side(double peak) => {
          'mean': [0.0, peak],
        };
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FsrForcePhaseDashboard(
            analysis: {
              'unit': 'N',
              'displayMode': 'latest_pair',
              'regions': {
                'heel': {'left': side(100), 'right': side(96)},
                'midfoot': {'left': side(0), 'right': side(0)},
                'forefoot': {'left': side(0), 'right': side(0)},
              },
            },
          ),
        ),
      ),
    );

    final charts =
        tester.widgetList<LineChart>(find.byType(LineChart)).toList();
    final leftPeak = charts[0].data.lineBarsData[0].spots.last.y;
    final rightPeak = charts[1].data.lineBarsData[0].spots.last.y;
    expect(leftPeak, 100);
    expect(rightPeak, 96);
    expect(charts[0].data.maxY, charts[1].data.maxY);
  });

  testWidgets('saved FSR view does not compress a large measured gap',
      (tester) async {
    tester.view.physicalSize = const Size(430, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    Map<String, dynamic> side(double peak) => {
          'mean': [0.0, peak],
        };
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FsrForcePhaseDashboard(
            analysis: {
              'unit': 'N',
              'displayMode': 'latest_pair',
              'regions': {
                'heel': {'left': side(100), 'right': side(20)},
                'midfoot': {'left': side(0), 'right': side(0)},
                'forefoot': {'left': side(0), 'right': side(0)},
              },
            },
          ),
        ),
      ),
    );

    final charts =
        tester.widgetList<LineChart>(find.byType(LineChart)).toList();
    final leftPeak = charts[0].data.lineBarsData[0].spots.last.y;
    final rightPeak = charts[1].data.lineBarsData[0].spots.last.y;
    expect(leftPeak, 100);
    expect(rightPeak, 20);
    expect(rightPeak, lessThan(leftPeak));
    expect(charts[0].data.maxY, charts[1].data.maxY);
    expect(tester.takeException(), isNull);
  });

  testWidgets('both trunk views use one central body-axis series',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 760);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: GaitCycleAnalysis(
            assetPath: 'assets/demo/demo_gait_data.json',
            healthySideOverride: 'right',
          ),
        ),
      ),
    );
    await tester.pump();
    for (var attempt = 0;
        attempt < 30 && find.text('Nghiêng trước–sau').evaluate().isEmpty;
        attempt++) {
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 50)),
      );
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('Nghiêng trước–sau'), findsOneWidget);
    expect(find.text('Góc gối'), findsNWidgets(2));
    expect(find.textContaining('· lành'), findsNothing);
    expect(find.textContaining('· giả'), findsNothing);
    expect(find.textContaining('2D - PHÂN TÍCH'), findsNothing);

    Future<void> verifyCentralChart(
      String selector, {
      required bool hasDemoCurve,
    }) async {
      final selectorFinder = find.text(selector);
      await tester.ensureVisible(selectorFinder);
      final chip = tester.widget<ChoiceChip>(
        find.ancestor(of: selectorFinder, matching: find.byType(ChoiceChip)),
      );
      chip.onSelected?.call(true);
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      expect(
        tester
            .widget<ChoiceChip>(find.ancestor(
              of: selectorFinder,
              matching: find.byType(ChoiceChip),
            ))
            .selected,
        isTrue,
      );

      expect(find.text('Trục thân trung tâm · Mean'), findsOneWidget);
      expect(find.text('Góc nghiêng thân'), findsOneWidget);
      expect(
          find.textContaining(selector == 'Nghiêng trước–sau'
              ? 'Dương: nghiêng về phía trước · Âm: nghiêng về phía sau'
              : 'Dương: phải · Âm: trái (theo người được đo)'),
          findsOneWidget);
      expect(find.textContaining('Theo chu kỳ chân trái'), findsNothing);
      expect(find.textContaining('Theo chu kỳ chân phải'), findsNothing);

      if (hasDemoCurve) {
        final chart = tester.widget<LineChart>(find.byType(LineChart));
        // One invisible lower bound, one upper bound and one visible Mean line.
        expect(chart.data.lineBarsData, hasLength(3));
        expect(chart.data.betweenBarsData, hasLength(1));
      } else {
        expect(find.byType(LineChart), findsNothing);
        expect(
          find.text('Không đủ chu kỳ trong đoạn video'),
          findsOneWidget,
        );
      }
    }

    await verifyCentralChart(
      'Nghiêng trước–sau',
      hasDemoCurve: true,
    );
    await verifyCentralChart(
      'Nghiêng trái–phải',
      hasDemoCurve: false,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('analysis sections stay clear and selectable on desktop',
      (tester) async {
    tester.view.physicalSize = const Size(1366, 768);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var selected = AnalysisSection.jointAngles;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Align(
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: 380,
              child: StatefulBuilder(
                builder: (context, setState) => AnalysisSectionSwitcher(
                  selected: selected,
                  onChanged: (section) => setState(() => selected = section),
                ),
              ),
            ),
          ),
        ),
      ),
    );

    expect(find.text('Góc khớp'), findsOneWidget);
    expect(find.text('Lực FSR'), findsOneWidget);
    expect(find.text('Thăng bằng'), findsOneWidget);

    await tester.tap(find.text('Lực FSR'));
    await tester.pumpAndSettle();
    expect(selected, AnalysisSection.fsrForce);

    await tester.tap(find.text('Thăng bằng'));
    await tester.pumpAndSettle();
    expect(selected, AnalysisSection.balance);
    expect(tester.takeException(), isNull);
  });
}
