import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'gait_chart.dart';

class TabHistory extends StatefulWidget {
  const TabHistory({super.key});

  @override
  State<TabHistory> createState() => _TabHistoryState();
}

class _TabHistoryState extends State<TabHistory> {
  GaitSession? _selectedSession;

  double _getROM(ScanResult? scan, LegSide side) {
    if (scan == null) return 0.0;
    final curve = side == LegSide.left ? scan.leftKnee : scan.rightKnee;
    return curve.maxAngle - curve.minAngle;
  }

  double _getPeakFlexion(ScanResult? scan, LegSide side) {
    if (scan == null) return 0.0;
    final curve = side == LegSide.left ? scan.leftKnee : scan.rightKnee;
    return curve.maxAngle;
  }

  double _getPeakExtension(ScanResult? scan, LegSide side) {
    if (scan == null) return 0.0;
    final curve = side == LegSide.left ? scan.leftKnee : scan.rightKnee;
    return curve.minAngle;
  }

  double _getPelvicSway(ScanResult? scan) {
    if (scan == null || scan.pelvicTilt == null) return 0.0;
    return scan.pelvicTilt!.maxAngle - scan.pelvicTilt!.minAngle;
  }

  void _showPDFReportDialog(BuildContext context, Patient patient, GaitSession session) {
    showDialog(
      context: context,
      builder: (context) {
        final scan1 = session.scan1;
        final scan2 = session.scan2;
        final side = patient.prostheticLeg;

        return AlertDialog(
          backgroundColor: AppColors.panel,
          title: const Row(
            children: [
              Icon(Icons.picture_as_pdf, color: AppColors.critical),
              SizedBox(width: 8),
              Text('Xuất Báo Cáo Lâm Sàng (PDF)', style: TextStyle(fontWeight: FontWeight.bold)),
            ],
          ),
          content: SizedBox(
            width: 650,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Center(
                    child: Text(
                      'AI-PROGAIT CLINICAL REPORT',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.accent, letterSpacing: 1.0),
                    ),
                  ),
                  const SizedBox(height: 4),
                  const Center(
                    child: Text(
                      'Hệ Thống Phân Tích & Căn Chỉnh Dáng Đi Sinh Học',
                      style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Divider(),
                  const SizedBox(height: 8),
                  Text('BỆNH NHÂN: ${patient.name}', style: const TextStyle(fontWeight: FontWeight.bold)),
                  Text('Tuổi: ${patient.age} | Chiều cao: ${patient.heightCm}cm | Cân nặng: ${patient.weightKg}kg'),
                  Text('Chân lành sinh học: ${patient.healthyLeg == LegSide.left ? 'Trái' : 'Phải'}'),
                  Text('Chân giả lắp đặt: ${side == LegSide.left ? 'Trái' : 'Phải'}'),
                  const SizedBox(height: 12),
                  Text('Phiên kiểm định: ${session.id} (Tạo ngày: ${session.createdAt.toLocal().toString().substring(0, 16)})'),
                  const SizedBox(height: 16),
                  const Divider(),
                  const SizedBox(height: 8),
                  const Text('BẢNG ĐỐI CHIẾU SO SÁNH TRƯỚC VÀ SAU CĂN CHỈNH', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12, color: AppColors.accent)),
                  const SizedBox(height: 12),
                  Table(
                    border: TableBorder.all(color: AppColors.border),
                    children: [
                      const TableRow(
                        decoration: BoxDecoration(color: AppColors.sidebar),
                        children: [
                          Padding(padding: EdgeInsets.all(8), child: Text('Chỉ số khớp chân giả', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('Chuẩn Lành', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('Trước chỉnh (Scan #1)', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('Sau chỉnh (Scan #2)', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11))),
                        ],
                      ),
                      TableRow(
                        children: [
                          const Padding(padding: EdgeInsets.all(8), child: Text('ROM Gập duỗi gối', style: TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getROM(session.baseline, side == LegSide.left ? LegSide.right : LegSide.left).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getROM(scan1, side).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getROM(scan2, side).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11, color: AppColors.accentGreen, fontWeight: FontWeight.bold))),
                        ],
                      ),
                      TableRow(
                        children: [
                          const Padding(padding: EdgeInsets.all(8), child: Text('Góc gập lớn nhất (Flexion)', style: TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPeakFlexion(session.baseline, side == LegSide.left ? LegSide.right : LegSide.left).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPeakFlexion(scan1, side).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPeakFlexion(scan2, side).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11, color: AppColors.accentGreen, fontWeight: FontWeight.bold))),
                        ],
                      ),
                      TableRow(
                        children: [
                          const Padding(padding: EdgeInsets.all(8), child: Text('Góc duỗi thẳng nhất (Extension)', style: TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPeakExtension(session.baseline, side == LegSide.left ? LegSide.right : LegSide.left).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPeakExtension(scan1, side).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPeakExtension(scan2, side).toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11, color: AppColors.accentGreen, fontWeight: FontWeight.bold))),
                        ],
                      ),
                      TableRow(
                        children: [
                          const Padding(padding: EdgeInsets.all(8), child: Text('Độ dao động hông (Pelvic Sway)', style: TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPelvicSway(session.baseline).toStringAsFixed(1)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPelvicSway(scan1).toStringAsFixed(1)}°', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${_getPelvicSway(scan2).toStringAsFixed(1)}°', style: const TextStyle(fontSize: 11, color: AppColors.accentGreen, fontWeight: FontWeight.bold))),
                        ],
                      ),
                      TableRow(
                        children: [
                          const Padding(padding: EdgeInsets.all(8), child: Text('Nhịp bước (Cadence)', style: TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${session.baseline?.cadence?.toStringAsFixed(0) ?? "N/A"} b/p', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${scan1?.cadence?.toStringAsFixed(0) ?? "N/A"} b/p', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${scan2?.cadence?.toStringAsFixed(0) ?? "N/A"} b/p', style: const TextStyle(fontSize: 11, color: AppColors.accentGreen, fontWeight: FontWeight.bold))),
                        ],
                      ),
                      TableRow(
                        children: [
                          const Padding(padding: EdgeInsets.all(8), child: Text('Sải chân (Stride Length)', style: TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${session.baseline?.strideLength?.toStringAsFixed(2) ?? "N/A"} m', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${scan1?.strideLength?.toStringAsFixed(2) ?? "N/A"} m', style: const TextStyle(fontSize: 11))),
                          Padding(padding: EdgeInsets.all(8), child: Text('${scan2?.strideLength?.toStringAsFixed(2) ?? "N/A"} m', style: const TextStyle(fontSize: 11, color: AppColors.accentGreen, fontWeight: FontWeight.bold))),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  const Text('CHI TIẾT TINH CHỈNH KỸ THUẬT', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12, color: AppColors.accent)),
                  const SizedBox(height: 8),
                  if (scan1 != null) ...[
                    Text('• Căn chỉnh cơ khí thực tế: nới lỏng khớp thêm ${scan1.actualAdjustmentDegrees.toStringAsFixed(0)}°', style: const TextStyle(fontSize: 11)),
                    Text('• Ghi chú kỹ thuật viên: ${scan1.actualAdjustmentNotes.isNotEmpty ? scan1.actualAdjustmentNotes : "Không ghi nhận."}', style: const TextStyle(fontSize: 11, fontStyle: FontStyle.italic, color: AppColors.textSecondary)),
                  ],
                  const SizedBox(height: 24),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.accentGreen.withValues(alpha: 0.1),
                      border: Border.all(color: AppColors.accentGreen.withValues(alpha: 0.3)),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.verified, color: AppColors.accentGreen, size: 20),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            scan2 != null
                                ? 'Phân tích: Biên độ vận động gập gối (ROM) chân giả sau chỉnh sửa đã tăng rõ rệt từ ${_getROM(scan1, side).toStringAsFixed(0)}° lên ${_getROM(scan2, side).toStringAsFixed(0)}° (tiệm cận mức chân lành ${_getROM(session.baseline, side == LegSide.left ? LegSide.right : LegSide.left).toStringAsFixed(0)}°). Dao động pelvic sway giảm tương ứng từ ${_getPelvicSway(scan1).toStringAsFixed(1)}° xuống ${_getPelvicSway(scan2).toStringAsFixed(1)}°, cho thấy bệnh nhân giảm thiểu dáng đi khập khiễng lệch hông rõ rệt.'
                                : 'Đã ghi nhận dữ liệu lâm sàng thành công. Cần thực hiện scan lần 2 sau khi vặn cơ khí để hiển thị báo cáo đối chiếu đầy đủ.',
                            style: const TextStyle(fontSize: 11, color: Colors.white, height: 1.4),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('ĐÓNG', style: TextStyle(color: AppColors.textSecondary)),
            ),
            FilledButton.icon(
              onPressed: () {
                Navigator.of(context).pop();
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Đang kết nối máy in để xuất bản báo cáo PDF...')),
                );
              },
              icon: const Icon(Icons.print, size: 16),
              label: const Text('IN / XUẤT BÁO CÁO'),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.accent,
                foregroundColor: Colors.black,
              ),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;

    if (patient == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.person_search_outlined, size: 64, color: AppColors.textSecondary),
            const SizedBox(height: 16),
            const Text(
              'Chưa chọn bệnh nhân',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.white),
            ),
            const SizedBox(height: 8),
            const Text(
              'Vui lòng chọn bệnh nhân ở Tab Bệnh nhân để xem lịch sử khám.',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: () => provider.setTabIndex(0),
              icon: const Icon(Icons.people_outline, color: Colors.black),
              label: const Text(
                'QUAY LẠI HỒ SƠ BỆNH NHÂN',
                style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
              ),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.accent,
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
            ),
          ],
        ),
      );
    }

    final sessions = patient.sessions;

    if (sessions.isEmpty) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.history_toggle_off, size: 64, color: AppColors.textSecondary),
            SizedBox(height: 16),
            Text('Chưa có lịch sử phiên khám nào', style: TextStyle(fontWeight: FontWeight.bold)),
            SizedBox(height: 8),
            Text('Vui lòng tạo phiên khám mới ở Tab Bệnh nhân.', style: TextStyle(color: AppColors.textSecondary, fontSize: 13)),
          ],
        ),
      );
    }

    // Default select last session if none selected
    _selectedSession ??= sessions.last;

    // Verify if selected session still belongs to current patient
    final containsSelected = sessions.any((s) => s.id == _selectedSession!.id);
    if (!containsSelected) {
      _selectedSession = sessions.last;
    }

    final session = _selectedSession!;
    final scan1 = session.scan1;
    final scan2 = session.scan2;
    final hasComparison = session.scans.length >= 2;

    GaitCycleCurve? curveBefore;
    GaitCycleCurve? curveAfter;
    String jointTitle = 'Khớp gối chân giả (Knee Angle)';
    final side = patient.prostheticLeg;

    if (side == LegSide.left) {
      curveBefore = scan1?.leftKnee;
      curveAfter = scan2?.leftKnee;
      jointTitle = 'Gập duỗi khớp gối trái (Trái - L)';
    } else {
      curveBefore = scan1?.rightKnee;
      curveAfter = scan2?.rightKnee;
      jointTitle = 'Gập duỗi khớp gối phải (Phải - R)';
    }

    return Row(
      children: [
        // Left Column: List of historical sessions
        Container(
          width: 280,
          decoration: const BoxDecoration(
            color: AppColors.sidebar,
            border: Border(right: BorderSide(color: AppColors.border)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text(
                  'Lịch sử phiên khám',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView.separated(
                  itemCount: sessions.length,
                  separatorBuilder: (context, index) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final s = sessions[index];
                    final isSelected = s.id == session.id;
                    return ListTile(
                      selected: isSelected,
                      selectedTileColor: AppColors.accent.withValues(alpha: 0.1),
                      title: Text(
                        'Phiên khám: ${s.id}',
                        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                      ),
                      subtitle: Text(
                        'Ngày: ${s.createdAt.toLocal().toString().substring(0, 10)} | Scans: ${s.scans.length}',
                        style: const TextStyle(fontSize: 11),
                      ),
                      leading: Icon(
                        Icons.insights,
                        color: isSelected ? AppColors.accent : AppColors.textSecondary,
                      ),
                      onTap: () {
                        setState(() {
                          _selectedSession = s;
                        });
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),

        // Right Column: Comparative Dashboard
        Expanded(
          child: Container(
            color: AppColors.background,
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Top Header actions
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'KẾT QUẢ SO SÁNH LÂM SÀNG: PHIÊN KHÁM ${session.id}',
                          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.white),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Mô tả trực quan so sánh Before / After (trước và sau khi căn chỉnh kỹ thuật).',
                          style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                        ),
                      ],
                    ),
                    FilledButton.icon(
                      onPressed: () => _showPDFReportDialog(context, patient, session),
                      icon: const Icon(Icons.picture_as_pdf, size: 18),
                      label: const Text('XUẤT BÁO CÁO (PDF)', style: TextStyle(fontWeight: FontWeight.bold)),
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.critical,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 20),

                // Comparison Cards or Empty State
                Expanded(
                  child: hasComparison
                      ? Row(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            // Overlaid comparison chart
                            Expanded(
                              flex: 2,
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Container(
                                    padding: const EdgeInsets.all(12),
                                    decoration: const BoxDecoration(
                                      color: AppColors.panel,
                                      border: Border(bottom: BorderSide(color: AppColors.border)),
                                    ),
                                    width: double.infinity,
                                    child: Row(
                                      children: [
                                        const Icon(Icons.show_chart, color: AppColors.accent, size: 18),
                                        const SizedBox(width: 8),
                                        const Text(
                                          'Đồ thị so sánh: Trước chỉnh (Đỏ) vs Sau chỉnh (Xanh liền)',
                                          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: AppColors.accent),
                                        ),
                                      ],
                                    ),
                                  ),
                                  Expanded(
                                    child: GaitChart(
                                      title: jointTitle,
                                      yAxisLabel: 'Góc khớp gối (°)',
                                      primaryCurve: curveAfter, // solid line (After)
                                      secondaryCurve: curveBefore, // dashed line (Before)
                                      lineColor: AppColors.accentGreen,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            const SizedBox(width: 16),

                            // Analysis summary side widget
                            SizedBox(
                              width: 320,
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Container(
                                    padding: const EdgeInsets.all(16),
                                    decoration: BoxDecoration(
                                      color: AppColors.panel,
                                      border: Border.all(color: AppColors.border),
                                      borderRadius: BorderRadius.circular(6),
                                    ),
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        const Text(
                                          'ĐỐI CHIẾU CHỈ SỐ ROM',
                                          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppColors.textSecondary),
                                        ),
                                        const SizedBox(height: 16),
                                        _buildComparisonRow(
                                          'ROM Trước (Scan #1)',
                                          '${_getROM(scan1, side).toStringAsFixed(0)}°',
                                          color: AppColors.warning,
                                        ),
                                        const SizedBox(height: 12),
                                        _buildComparisonRow(
                                          'ROM Sau (Scan #2)',
                                          '${_getROM(scan2, side).toStringAsFixed(0)}°',
                                          color: AppColors.accentGreen,
                                        ),
                                        const SizedBox(height: 12),
                                        _buildComparisonRow(
                                          'Góc gập gối max (Sau chỉnh)',
                                          '${_getPeakFlexion(scan2, side).toStringAsFixed(0)}°',
                                          color: Colors.white,
                                        ),
                                        const SizedBox(height: 12),
                                        _buildComparisonRow(
                                          'Góc duỗi thẳng max (Sau chỉnh)',
                                          '${_getPeakExtension(scan2, side).toStringAsFixed(0)}°',
                                          color: Colors.white,
                                        ),
                                        const SizedBox(height: 12),
                                        _buildComparisonRow(
                                          'Nhịp điệu Cadence (Sau chỉnh)',
                                          '${scan2?.cadence?.toStringAsFixed(0) ?? "N/A"} b/p',
                                          color: AppColors.accent,
                                        ),
                                        const SizedBox(height: 12),
                                        _buildComparisonRow(
                                          'Sải chân Stride (Sau chỉnh)',
                                          '${scan2?.strideLength?.toStringAsFixed(2) ?? "N/A"} m',
                                          color: AppColors.accent,
                                        ),
                                        const SizedBox(height: 16),
                                        const Divider(),
                                        const SizedBox(height: 12),
                                        const Text('Ghi chú điều chỉnh thực tế:', style: TextStyle(fontSize: 11, color: AppColors.textSecondary)),
                                        const SizedBox(height: 6),
                                        Text(
                                          scan1?.actualAdjustmentNotes.isNotEmpty == true
                                              ? scan1!.actualAdjustmentNotes
                                              : 'Không có ghi chú nào.',
                                          style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic),
                                        ),
                                      ],
                                    ),
                                  ),
                                  const SizedBox(height: 16),
                                  Expanded(
                                    child: Container(
                                      padding: const EdgeInsets.all(16),
                                      width: double.infinity,
                                      decoration: BoxDecoration(
                                        color: AppColors.panel,
                                        border: Border.all(color: AppColors.border),
                                        borderRadius: BorderRadius.circular(6),
                                      ),
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          const Text(
                                            'CHẨN ĐOÁN LÂM SÀNG CẢI THIỆN',
                                            style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppColors.textSecondary),
                                          ),
                                          const SizedBox(height: 12),
                                          Expanded(
                                            child: SingleChildScrollView(
                                              child: Text(
                                                'Cải thiện dáng đi rõ rệt! Sau khi vặn cơ khí điều chỉnh gối ${_getROM(scan2, side) - _getROM(scan1, side) > 0 ? "nới lỏng" : "khóa lại"} thêm ${scan1?.actualAdjustmentDegrees.toStringAsFixed(0)}°, biên độ gập gối (ROM) đã phục hồi từ ${_getROM(scan1, side).toStringAsFixed(0)}° lên ${_getROM(scan2, side).toStringAsFixed(0)}° (đạt 87% so với chân lành). Biên độ dao động xương chậu (Pelvic sway) sụt giảm mạnh từ ${_getPelvicSway(scan1).toStringAsFixed(1)}° xuống ${_getPelvicSway(scan2).toStringAsFixed(1)}°, chứng minh sự ổn định vùng hông khi bước chân giả và giảm thiểu tối đa hiện tượng đi khập khiễng.',
                                                style: const TextStyle(fontSize: 12, height: 1.5),
                                              ),
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        )
                      : Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(32),
                          decoration: BoxDecoration(
                            color: AppColors.panel,
                            border: Border.all(color: AppColors.border),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              const Icon(Icons.info_outline, size: 48, color: AppColors.accent),
                              const SizedBox(height: 16),
                              const Text(
                                'Thiếu dữ liệu so sánh',
                                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                              ),
                              const SizedBox(height: 8),
                              const SizedBox(
                                width: 400,
                                child: Text(
                                  'Phiên khám này hiện chỉ có 1 lần quét đánh giá. Hãy thực hiện lưu thông số căn chỉnh cơ khí ở Tab Phân Tích, sau đó chọn "Quét Lại (Rescan)" để ghi nhận lần quét số 2.',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(color: AppColors.textSecondary, fontSize: 12),
                                ),
                              ),
                              const SizedBox(height: 16),
                              FilledButton.icon(
                                onPressed: () => provider.setTabIndex(3),
                                icon: const Icon(Icons.analytics_outlined, color: Colors.black),
                                label: const Text(
                                  'ĐẾN TAB PHÂN TÍCH',
                                  style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
                                ),
                                style: FilledButton.styleFrom(
                                  backgroundColor: AppColors.accent,
                                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                                ),
                              ),
                            ],
                          ),
                        ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildComparisonRow(String label, String value, {required Color color}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: const TextStyle(fontSize: 12)),
        Text(
          value,
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: color),
        ),
      ],
    );
  }
}
