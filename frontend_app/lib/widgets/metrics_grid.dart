import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'dart:math';

import '../models/gait_data.dart';
import '../theme/app_theme.dart';

/// Bảng điều khiển chỉ số cho một đoạn dáng đi đã chọn.
/// Video, timeline và thư viện phiên được quản lý bởi TabAnalysis.
class MetricsGrid extends StatefulWidget {
  const MetricsGrid({
    super.key,
    required this.scan,
    required this.baseline,
    required this.patient,
  });

  final ScanResult scan;
  final ScanResult? baseline;
  final Patient? patient;

  @override
  State<MetricsGrid> createState() => _MetricsGridState();
}

class _MetricsGridState extends State<MetricsGrid> {
  int _activeGroup = 0;

  double _calculateRom(GaitCycleCurve? curve) {
    if (curve == null || curve.angles.isEmpty) return 0.0;
    return curve.angles.reduce(max) - curve.angles.reduce(min);
  }

  @override
  Widget build(BuildContext context) {
    final scan = widget.scan;
    final baseline = widget.baseline;
    final patient = widget.patient;

    double kneeSymmetry = 100.0;
    if (baseline != null) {
      final scanDiff =
          (_calculateRom(scan.leftKnee) - _calculateRom(scan.rightKnee)).abs();
      final baseDiff =
          (_calculateRom(baseline.leftKnee) - _calculateRom(baseline.rightKnee))
              .abs();
      kneeSymmetry = max(0.0, 100.0 - (scanDiff - baseDiff).abs() * 2);
      kneeSymmetry = min(100.0, kneeSymmetry);
    } else {
      final leftRom = _calculateRom(scan.leftKnee);
      final rightRom = _calculateRom(scan.rightKnee);
      if (leftRom > 0 && rightRom > 0) {
        kneeSymmetry = min(leftRom, rightRom) / max(leftRom, rightRom) * 100;
      }
    }

    final forceSymmetry = scan.plantarLoadSymmetry ?? 100.0;
    final leftHealthy = patient?.healthyLeg == LegSide.left;
    const groups = [
      ('knee', 'GỐI', Icons.directions_walk_outlined),
      ('hip', 'HÔNG', Icons.accessibility_new_outlined),
      ('pelvis', 'CHẬU', Icons.rotate_90_degrees_ccw_outlined),
    ];
    final active = groups[_activeGroup.clamp(0, groups.length - 1)];

    final kneeColor = kneeSymmetry < 75
        ? AppColors.critical
        : kneeSymmetry < 90
            ? AppColors.warning
            : AppColors.accentGreen;
    final kneeStatus = kneeSymmetry < 75
        ? 'cần kiểm tra'
        : kneeSymmetry < 90
            ? 'chấp nhận'
            : 'ổn định';
    final forceColor = scan.plantarLoadSymmetry == null
        ? AppColors.textSecondary
        : forceSymmetry < 70
            ? AppColors.critical
            : forceSymmetry < 85
                ? AppColors.warning
                : AppColors.accentGreen;

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
      child: Column(
        children: [
          _buildKpiBar(
            scan,
            kneeSymmetry,
            forceSymmetry,
            kneeColor,
            forceColor,
            kneeStatus,
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              const Icon(Icons.insights_outlined,
                  size: 16, color: AppColors.accent),
              const SizedBox(width: 7),
              const Text('ĐỘNG HỌC TỪ CAMERA',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
              const Spacer(),
              if (scan.fatigueFlag == 1) ...[
                const Icon(Icons.warning_amber_rounded,
                    size: 14, color: AppColors.warning),
                const SizedBox(width: 4),
                const Text('Có cờ mỏi cơ',
                    style: TextStyle(fontSize: 9, color: AppColors.warning)),
              ],
            ],
          ),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: Wrap(
              spacing: 7,
              children: List.generate(groups.length, (index) {
                final group = groups[index];
                return ChoiceChip(
                  selected: index == _activeGroup,
                  avatar: Icon(group.$3, size: 14),
                  label: Text(group.$2, style: const TextStyle(fontSize: 9)),
                  visualDensity: VisualDensity.compact,
                  onSelected: (_) => setState(() => _activeGroup = index),
                );
              }),
            ),
          ),
          const SizedBox(height: 6),
          Expanded(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 180),
              child: _kinematicGroup(
                key: ValueKey(active.$1),
                group: active.$1,
                scan: scan,
                baseline: baseline,
                leftHealthy: leftHealthy,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _kinematicGroup({
    required Key key,
    required String group,
    required ScanResult scan,
    required ScanResult? baseline,
    required bool leftHealthy,
  }) {
    if (group == 'pelvis') {
      return GaitChart(
        key: key,
        title: 'Nghiêng xương chậu',
        yAxisLabel: 'Góc nghiêng (°)',
        primaryCurve: scan.pelvicTilt,
        secondaryCurve: baseline?.pelvicTilt,
        lineColor: AppColors.accentGreen,
      );
    }

    final isKnee = group == 'knee';
    final label = isKnee ? 'Góc gập gối 2D' : 'Góc gập hông 2D';
    final leftCurve = isKnee ? scan.leftKnee : scan.leftHip;
    final rightCurve = isKnee ? scan.rightKnee : scan.rightHip;
    final baselineLeft = isKnee ? baseline?.leftKnee : baseline?.leftHip;
    final baselineRight = isKnee ? baseline?.rightKnee : baseline?.rightHip;

    return Row(
      key: key,
      children: [
        Expanded(
          child: GaitChart(
            title: '$label · trái${leftHealthy ? ' (lành)' : ' (giả)'}',
            yAxisLabel: '$label (°)',
            primaryCurve: leftCurve,
            secondaryCurve: baselineLeft,
            lineColor: AppColors.leftLeg,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: GaitChart(
            title: '$label · phải${leftHealthy ? ' (giả)' : ' (lành)'}',
            yAxisLabel: '$label (°)',
            primaryCurve: rightCurve,
            secondaryCurve: baselineRight,
            lineColor: AppColors.rightLeg,
          ),
        ),
      ],
    );
  }

  Widget _buildKpiBar(
    ScanResult scan,
    double kneeSymmetry,
    double forceSymmetry,
    Color kneeColor,
    Color forceColor,
    String kneeStatus,
  ) {
    return Row(
      children: [
        Expanded(
          child: _buildKpiCard(
            title: 'NHỊP ĐIỆU',
            value: scan.cadence != null
                ? '${scan.cadence!.toStringAsFixed(0)} bước/phút'
                : '—',
            icon: Icons.speed,
            color: AppColors.accent,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _buildKpiCard(
            title: 'SẢI CHÂN',
            value: scan.strideLength != null
                ? '${scan.strideLength!.toStringAsFixed(2)} m'
                : '—',
            icon: Icons.straighten,
            color: AppColors.accentGreen,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _buildKpiCard(
            title: 'ĐỐI XỨNG GỐI',
            value: '${kneeSymmetry.toStringAsFixed(1)}%',
            subtitle: kneeStatus,
            icon: Icons.balance_outlined,
            color: kneeColor,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _buildKpiCard(
            title: 'ĐỐI XỨNG INSOLE',
            value: scan.plantarLoadSymmetry == null
                ? '—'
                : '${forceSymmetry.toStringAsFixed(1)}%',
            subtitle: scan.plantarLoadSymmetry == null
                ? 'chưa có FSR'
                : 'tải trái–phải',
            icon: Icons.sensors_outlined,
            color: forceColor,
          ),
        ),
      ],
    );
  }

  Widget _buildKpiCard({
    required String title,
    required String value,
    String? subtitle,
    required IconData icon,
    required Color color,
  }) {
    return Container(
      height: 66,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.10),
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: color, size: 15),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(title,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 8.5,
                        color: AppColors.textSecondary,
                        fontWeight: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(value,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w700)),
                if (subtitle != null)
                  Text(subtitle,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 8.5, color: color)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Biểu đồ vẽ chuỗi 101 điểm chuẩn hóa chu kỳ dáng đi (0-100%)
class GaitChart extends StatelessWidget {
  const GaitChart({
    super.key,
    required this.title,
    required this.yAxisLabel,
    required this.primaryCurve,
    this.secondaryCurve,
    required this.lineColor,
  });

  final String title;
  final String yAxisLabel;
  final GaitCycleCurve? primaryCurve;
  final GaitCycleCurve? secondaryCurve;
  final Color lineColor;

  @override
  Widget build(BuildContext context) {
    final hasPrimary = primaryCurve != null && primaryCurve!.angles.isNotEmpty;
    final hasSecondary =
        secondaryCurve != null && secondaryCurve!.angles.isNotEmpty;

    if (!hasPrimary) {
      return Container(
        margin: const EdgeInsets.all(4),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.panel,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.show_chart, color: AppColors.border, size: 32),
              const SizedBox(height: 8),
              Text(
                '$title: Chưa có dữ liệu',
                style: const TextStyle(
                    color: AppColors.textSecondary, fontSize: 11),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    final List<FlSpot> spots1 = [];
    for (int i = 0; i < primaryCurve!.angles.length; i++) {
      spots1.add(FlSpot(i.toDouble(), primaryCurve!.angles[i]));
    }

    final List<FlSpot> spots2 = [];
    if (hasSecondary) {
      for (int i = 0; i < secondaryCurve!.angles.length; i++) {
        spots2.add(FlSpot(i.toDouble(), secondaryCurve!.angles[i]));
      }
    }

    // Determine min/max values for Y axis
    double minVal = primaryCurve!.angles.reduce(min);
    double maxVal = primaryCurve!.angles.reduce(max);
    if (hasSecondary) {
      minVal = min(minVal, secondaryCurve!.angles.reduce(min));
      maxVal = max(maxVal, secondaryCurve!.angles.reduce(max));
    }
    final range = maxVal - minVal;
    final double yMin = (minVal - range * 0.15).floorToDouble();
    final double yMax = (maxVal + range * 0.15).ceilToDouble();

    return Container(
      margin: const EdgeInsets.all(4),
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 6),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                      color: AppColors.textPrimary),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Row(
                children: [
                  _buildLegendIndicator('Quét', lineColor),
                  if (hasSecondary) ...[
                    const SizedBox(width: 8),
                    _buildLegendIndicator('Chuẩn', AppColors.baseline,
                        isDashed: true),
                  ],
                ],
              ),
            ],
          ),
          const SizedBox(height: 6),
          Expanded(
            child: LineChart(
              LineChartData(
                gridData: const FlGridData(
                  show: true,
                  drawVerticalLine: false,
                  horizontalInterval: 15,
                ),
                titlesData: FlTitlesData(
                  leftTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      reservedSize: 32,
                      getTitlesWidget: (val, meta) => Text(
                        '${val.toInt()}°',
                        style: const TextStyle(
                            fontSize: 9, color: AppColors.textSecondary),
                      ),
                    ),
                  ),
                  bottomTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      reservedSize: 18,
                      getTitlesWidget: (val, meta) {
                        if (val == 0) {
                          return const Text('0%',
                              style: TextStyle(
                                  fontSize: 9, color: AppColors.textSecondary));
                        }
                        if (val == 50) {
                          return const Text('50%',
                              style: TextStyle(
                                  fontSize: 9, color: AppColors.textSecondary));
                        }
                        if (val == 100) {
                          return const Text('100%',
                              style: TextStyle(
                                  fontSize: 9, color: AppColors.textSecondary));
                        }
                        return const SizedBox.shrink();
                      },
                    ),
                  ),
                  rightTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false)),
                  topTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false)),
                ),
                borderData: FlBorderData(show: false),
                minX: 0,
                maxX: 100,
                minY: yMin,
                maxY: yMax,
                lineBarsData: [
                  LineChartBarData(
                    spots: spots1,
                    isCurved: true,
                    color: lineColor,
                    barWidth: 2,
                    isStrokeCapRound: true,
                    dotData: const FlDotData(show: false),
                    belowBarData: BarAreaData(
                      show: true,
                      color: lineColor.withValues(alpha: 0.05),
                    ),
                  ),
                  if (hasSecondary)
                    LineChartBarData(
                      spots: spots2,
                      isCurved: true,
                      color: AppColors.baseline,
                      barWidth: 1.5,
                      dashArray: [4, 4],
                      isStrokeCapRound: true,
                      dotData: const FlDotData(show: false),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLegendIndicator(String label, Color color,
      {bool isDashed = false}) {
    return Row(
      children: [
        Container(
          width: 12,
          height: 3,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(1.5),
          ),
        ),
        const SizedBox(width: 4),
        Text(
          label,
          style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
        ),
      ],
    );
  }
}
