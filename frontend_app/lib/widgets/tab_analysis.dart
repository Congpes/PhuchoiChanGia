import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'metrics_grid.dart';

class TabAnalysis extends StatefulWidget {
  const TabAnalysis({super.key});

  @override
  State<TabAnalysis> createState() => _TabAnalysisState();
}

class _TabAnalysisState extends State<TabAnalysis> {
  final _degreesController = TextEditingController();
  final _notesController = TextEditingController();

  @override
  void dispose() {
    _degreesController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  void _saveAdjustment(BuildContext context, SessionProvider provider) async {
    final degrees = double.tryParse(_degreesController.text) ?? 0.0;
    final notes = _notesController.text;

    if (notes.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Vui lòng nhập mô tả căn chỉnh thực tế.')),
      );
      return;
    }

    await provider.saveActualAdjustment(degrees, notes);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Đã ghi nhận thông số căn chỉnh cơ khí thành công!')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;
    final session = provider.activeSession;

    if (patient == null || session == null) {
      return const Center(
        child: Text(
          'Chưa có dữ liệu phân tích. Vui lòng chọn bệnh nhân và thực hiện quét ở Tab Quét.',
          style: TextStyle(color: AppColors.textSecondary),
        ),
      );
    }

    // Check if we only have baseline
    final hasOnlyBaseline = session.baseline != null && session.scans.isEmpty;
    final activeScan = session.activeScan;

    // Prefill controllers if scan already has adjustment data saved
    if (activeScan != null && activeScan.id != 'baseline') {
      if (_notesController.text.isEmpty && activeScan.actualAdjustmentNotes.isNotEmpty) {
        _notesController.text = activeScan.actualAdjustmentNotes;
        _degreesController.text = activeScan.actualAdjustmentDegrees > 0
            ? activeScan.actualAdjustmentDegrees.toStringAsFixed(0)
            : '';
      }
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Left Panel: Charts & Metrics Grid
        Expanded(
          child: Column(
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: const BoxDecoration(
                  color: AppColors.panel,
                  border: Border(bottom: BorderSide(color: AppColors.border)),
                ),
                child: Text(
                  hasOnlyBaseline
                      ? 'Đồ thị nhịp điệu sinh học chuẩn (Baseline)'
                      : 'Đồ thị so sánh: Chân lành (Baseline) vs ${activeScan?.label ?? 'Chân giả'}',
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: AppColors.accent),
                ),
              ),
              const Expanded(child: MetricsGrid()),
            ],
          ),
        ),

        // Right Panel: Recommendations & Adjustment Logging Form
        Container(
          width: 340,
          decoration: const BoxDecoration(
            color: AppColors.sidebar,
            border: Border(left: BorderSide(color: AppColors.border)),
          ),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              const Text(
                'KẾT QUẢ PHÂN TÍCH',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppColors.textSecondary, letterSpacing: 0.8),
              ),
              const SizedBox(height: 12),

              // Baseline Loaded Info
              if (hasOnlyBaseline) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppColors.panel,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.check_circle, color: AppColors.accentGreen, size: 18),
                          SizedBox(width: 8),
                          Text('Đã nạp Baseline', style: TextStyle(fontWeight: FontWeight.bold)),
                        ],
                      ),
                      SizedBox(height: 8),
                      Text(
                        'Đã lưu thành công đồ thị chuẩn chân lành của bệnh nhân. Vui lòng chuyển sang Tab Quét và chọn "Đánh giá chân giả - Scan #1" để tiến hành đo lường.',
                        style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                FilledButton.icon(
                  onPressed: () => provider.setTabIndex(1), // go back to Tab 2
                  icon: const Icon(Icons.arrow_back),
                  label: const Text('QUAY LẠI TAB QUÉT'),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ] else ...[
                if (activeScan != null) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    margin: const EdgeInsets.only(bottom: 16),
                    decoration: BoxDecoration(
                      color: AppColors.panel,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: AppColors.border),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'THÔNG SỐ DI CHUYỂN',
                          style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: AppColors.textSecondary),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          '• Nhịp bước: ${activeScan.cadence?.toStringAsFixed(0) ?? "N/A"} bước/phút',
                          style: const TextStyle(fontSize: 12),
                        ),
                        Text(
                          '• Sải chân: ${activeScan.strideLength?.toStringAsFixed(2) ?? "N/A"} m',
                          style: const TextStyle(fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                ],
                const Text(
                  'Gợi ý tinh chỉnh từ AI',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                ...session.recommendations.map((r) => _buildRecommendationCard(r)),
                if (session.recommendations.isEmpty)
                  const Text(
                    'Chưa có đề xuất nào.',
                    style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
                  ),

                const SizedBox(height: 24),
                const Divider(),
                const SizedBox(height: 16),

                // Technician Adjustment Form
                const Text(
                  'Ghi nhận căn chỉnh cơ khí',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: AppColors.accent),
                ),
                const SizedBox(height: 4),
                const Text(
                  'Nhập thông số khớp đã điều chỉnh thực tế trên chân giả để so sánh kết quả sau khi quét lại.',
                  style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _degreesController,
                  decoration: const InputDecoration(
                    labelText: 'Số độ tinh chỉnh thực tế (độ)',
                    hintText: 'Ví dụ: 12',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                  keyboardType: TextInputType.number,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _notesController,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: 'Mô tả chi tiết chỉnh sửa',
                    hintText: 'Ví dụ: Nới lỏng khớp gối phải thêm 12 độ để cải thiện biên độ gập...',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: provider.isLoading ? null : () => _saveAdjustment(context, provider),
                  icon: const Icon(Icons.save_outlined, size: 18),
                  label: const Text('LƯU THÔNG SỐ CĂN CHỈNH', style: TextStyle(fontWeight: FontWeight.bold)),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.panel,
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: AppColors.border),
                  ),
                ),

                const SizedBox(height: 32),
                const Divider(),
                const SizedBox(height: 16),

                // Action controls: Rescan or view history
                const Text('Hành động tiếp theo', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AppColors.textSecondary)),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: () {
                    _degreesController.clear();
                    _notesController.clear();
                    provider.startRescan();
                  },
                  icon: const Icon(Icons.refresh, size: 18),
                  label: const Text('QUÉT LẠI CHÂN GIẢ (RESCAN)', style: TextStyle(fontWeight: FontWeight.bold)),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: () => provider.setTabIndex(3), // go to history
                  icon: const Icon(Icons.history, size: 18),
                  label: const Text('XEM LỊCH SỬ & BÁO CÁO'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.textSecondary,
                    side: const BorderSide(color: AppColors.border),
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildRecommendationCard(AdjustmentRecommendation r) {
    final color = switch (r.severity) {
      RecommendationSeverity.critical => AppColors.critical,
      RecommendationSeverity.warning => AppColors.warning,
      RecommendationSeverity.info => AppColors.accent,
    };

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            r.issue,
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: color),
          ),
          const SizedBox(height: 4),
          Text(r.suggestion, style: const TextStyle(fontSize: 11, color: Colors.white)),
          if (r.deltaDegrees > 0)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                'Δ sai lệch: ${r.deltaDegrees.toStringAsFixed(0)}°',
                style: TextStyle(fontSize: 10, color: color, fontWeight: FontWeight.bold),
              ),
            ),
        ],
      ),
    );
  }
}
