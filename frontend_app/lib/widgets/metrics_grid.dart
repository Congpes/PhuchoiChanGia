import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'dart:math';

import '../models/gait_data.dart';
import '../theme/app_theme.dart';

/// Bảng điều khiển phân tích chi tiết dáng đi của bệnh nhân
class MetricsGrid extends StatelessWidget {
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
  Widget build(BuildContext context) {
    // Calculate Joint ROM Symmetry
    double kneeSymmetry = 100.0;
    if (baseline != null) {
      final double scanRomL = _calculateRom(scan.leftKnee);
      final double scanRomR = _calculateRom(scan.rightKnee);
      final double baseRomL = _calculateRom(baseline!.leftKnee);
      final double baseRomR = _calculateRom(baseline!.rightKnee);

      final double scanDiff = (scanRomL - scanRomR).abs();
      final double baseDiff = (baseRomL - baseRomR).abs();

      kneeSymmetry = max(0.0, 100.0 - (scanDiff - baseDiff).abs() * 2);
      if (kneeSymmetry > 100.0) kneeSymmetry = 100.0;
    } else {
      final double romL = _calculateRom(scan.leftKnee);
      final double romR = _calculateRom(scan.rightKnee);
      if (romL > 0 && romR > 0) {
        kneeSymmetry = (min(romL, romR) / max(romL, romR)) * 100.0;
      }
    }

    final double forceSymmetry = scan.plantarLoadSymmetry ?? 100.0;

    GaitCycleCurve? baselineHipLeft;
    GaitCycleCurve? baselineHipRight;
    GaitCycleCurve? baselineKneeLeft;
    GaitCycleCurve? baselineKneeRight;
    GaitCycleCurve? baselinePelvic;

    if (baseline != null && patient != null) {
      final isLeftHealthy = patient!.healthyLeg == LegSide.left;
      baselineHipLeft = isLeftHealthy ? baseline!.leftHip : null;
      baselineHipRight = !isLeftHealthy ? baseline!.rightHip : null;
      baselineKneeLeft = isLeftHealthy ? baseline!.leftKnee : null;
      baselineKneeRight = !isLeftHealthy ? baseline!.rightKnee : null;
      baselinePelvic = baseline!.pelvicTilt;
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Column(
        children: [
          _buildKpiBar(scan, kneeSymmetry, forceSymmetry),
          const SizedBox(height: 4),

          // Fatigue warning banner if detected
          if (scan.fatigueFlag == 1)
            Container(
              margin: const EdgeInsets.only(bottom: 8, left: 4, right: 4),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.orange.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: Colors.orange[800]!),
              ),
              child: Row(
                children: [
                  Icon(Icons.warning_amber_rounded,
                      color: Colors.orange[700], size: 20),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'AI Phát hiện Dấu hiệu Mỏi cơ (Fatigue Detected): Độ dốc biên độ dao động khớp giảm dần (Slope: ${scan.fatigueSlope.toStringAsFixed(3)}). Đề xuất giảm tải lực hoặc nghỉ ngơi.',
                      style: TextStyle(
                          color: Colors.orange[200],
                          fontSize: 12,
                          fontWeight: FontWeight.w500),
                    ),
                  ),
                ],
              ),
            ),

          Expanded(
            child: SingleChildScrollView(
              child: Padding(
                padding: const EdgeInsets.all(4.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Section 1: Hip & Pelvic angles
                    const SizedBox(height: 8),
                    const Text(
                      'Góc Khớp Hông & Nghiêng Xương Chậu (Sagittal / Frontal)',
                      style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                          color: AppColors.textPrimary),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 180,
                      child: Row(
                        children: [
                          Expanded(
                            child: GaitChart(
                              title: 'Hông trái (L)',
                              yAxisLabel: 'Góc hông (°)',
                              primaryCurve: scan.leftHip,
                              secondaryCurve: baselineHipLeft,
                              lineColor: AppColors.leftLeg,
                            ),
                          ),
                          Expanded(
                            child: GaitChart(
                              title: 'Hông phải (R)',
                              yAxisLabel: 'Góc hông (°)',
                              primaryCurve: scan.rightHip,
                              secondaryCurve: baselineHipRight,
                              lineColor: AppColors.rightLeg,
                            ),
                          ),
                          Expanded(
                            child: GaitChart(
                              title: 'Nghiêng xương chậu (Pelvic Tilt)',
                              yAxisLabel: 'Góc nghiêng (°)',
                              primaryCurve: scan.pelvicTilt,
                              secondaryCurve: baselinePelvic,
                              lineColor: AppColors.accentGreen,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 8),

                    // Section 2: Knee joint angles
                    const Divider(color: AppColors.border),
                    const SizedBox(height: 8),
                    const Text(
                      'Góc Khớp Gối (Knee Flexion/Extension)',
                      style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                          color: AppColors.textPrimary),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 180,
                      child: Row(
                        children: [
                          Expanded(
                            child: GaitChart(
                              title: 'Gối trái (L)',
                              yAxisLabel: 'Góc gối (°)',
                              primaryCurve: scan.leftKnee,
                              secondaryCurve: baselineKneeLeft,
                              lineColor: AppColors.leftLeg,
                            ),
                          ),
                          Expanded(
                            child: GaitChart(
                              title: 'Gối phải (R)',
                              yAxisLabel: 'Góc gối (°)',
                              primaryCurve: scan.rightKnee,
                              secondaryCurve: baselineKneeRight,
                              lineColor: AppColors.rightLeg,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 8),

                    // Section 4: Plantar pressure COP and Inverse Dynamics Socket moment (Restored UI templates)
                    const Divider(color: AppColors.border),
                    const SizedBox(height: 8),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'Phân tích áp áp lực Insole & Lực ổ mỏm cụt (FSR/CoP & Socket Torque)',
                        style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                            color: AppColors.textPrimary),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // CoP trajectories Left/Right
                        Expanded(
                          child: Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: AppColors.panel,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(color: AppColors.border),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text(
                                    'Quỹ đạo tâm áp lực (CoP Trajectory) - Cảm biến thật',
                                    style: TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.bold,
                                        color: AppColors.textSecondary)),
                                const SizedBox(height: 12),
                                Row(
                                  children: [
                                    Expanded(
                                      child: AspectRatio(
                                        aspectRatio: 0.6,
                                        child: CustomPaint(
                                          painter: _CopTrajectoryPainter(
                                              trajectory: scan.copTrajectory,
                                              isLeft: true),
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 16),
                                    Expanded(
                                      child: AspectRatio(
                                        aspectRatio: 0.6,
                                        child: CustomPaint(
                                          painter: _CopTrajectoryPainter(
                                              trajectory: scan.copTrajectory,
                                              isLeft: false),
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(width: 16),
                        // Socket torque / Inverse dynamics details
                        Expanded(
                          child: Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: AppColors.panel,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(color: AppColors.border),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text(
                                    'Mô-men lực khớp ổ mỏm cụt (Socket Torque)',
                                    style: TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.bold,
                                        color: AppColors.textSecondary)),
                                const SizedBox(height: 8),
                                const Text(
                                  'Tính toán dựa trên tải trọng GRF (Insole) & Lever Arm (CoP):',
                                  style: TextStyle(
                                      fontSize: 11,
                                      color: AppColors.textSecondary,
                                      height: 1.3),
                                ),
                                const SizedBox(height: 16),
                                _buildTorqueItem(
                                    'Socket Extension Moment (Max)',
                                    '-- N·m',
                                    'Chờ dữ liệu phần cứng Insole'),
                                _buildTorqueItem('Socket Flexion Moment (Max)',
                                    '-- N·m', 'Chờ dữ liệu phần cứng Insole'),
                                _buildTorqueItem('Mô-men nghiêng cẳng chân',
                                    '-- N·m', 'Chờ kết nối thiết bị'),
                                const SizedBox(height: 16),
                                Container(
                                  padding: const EdgeInsets.all(8),
                                  decoration: BoxDecoration(
                                    color: AppColors.surfaceMuted,
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: const Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text('AI AUTO-FLAG RULES (PRE-HARDWARE):',
                                          style: TextStyle(
                                              fontSize: 9,
                                              fontWeight: FontWeight.bold,
                                              color: AppColors.accent)),
                                      SizedBox(height: 4),
                                      Text(
                                          '• Cảnh báo lệch lực: Trục CoP chân giả lệch ngoài biên > 1.2cm',
                                          style: TextStyle(
                                              fontSize: 10,
                                              color: AppColors.textSecondary)),
                                      Text(
                                          '• Cảnh báo góc gối: ROM gối chân giả lăng < 45 độ ở pha swing',
                                          style: TextStyle(
                                              fontSize: 10,
                                              color: AppColors.textSecondary)),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 24),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  double _calculateRom(GaitCycleCurve? curve) {
    if (curve == null || curve.angles.isEmpty) return 0.0;
    final double maxVal = curve.angles.reduce(max);
    final double minVal = curve.angles.reduce(min);
    return maxVal - minVal;
  }

  Widget _buildKpiBar(
      ScanResult scan, double kneeSymmetry, double forceSymmetry) {
    final cadence = scan.cadence;
    final stride = scan.strideLength;

    Color kneeColor = AppColors.accentGreen;
    String kneeRating = 'Tối ưu';
    if (kneeSymmetry < 75) {
      kneeColor = AppColors.critical;
      kneeRating = 'Cần chỉnh';
    } else if (kneeSymmetry < 90) {
      kneeColor = AppColors.warning;
      kneeRating = 'Chấp nhận';
    }

    Color forceColor = AppColors.accentGreen;
    String forceRating = 'Chờ cảm biến';
    if (forceSymmetry < 70) {
      forceColor = AppColors.critical;
      forceRating = 'Lệch nặng';
    } else if (forceSymmetry < 85) {
      forceColor = AppColors.warning;
      forceRating = 'Lệch nhẹ';
    }

    return Padding(
      padding: const EdgeInsets.only(left: 4, right: 4, top: 8, bottom: 8),
      child: Row(
        children: [
          Expanded(
            child: _buildKpiCard(
              title: 'NHỊP ĐIỆU (CADENCE)',
              value: cadence != null
                  ? '${cadence.toStringAsFixed(0)} bước/phút'
                  : '--',
              icon: Icons.speed,
              color: AppColors.accent,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _buildKpiCard(
              title: 'SẢI CHÂN (STRIDE LENGTH)',
              value: stride != null ? '${stride.toStringAsFixed(2)} m' : '--',
              icon: Icons.straighten,
              color: AppColors.accentGreen,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _buildKpiCard(
              title: 'ĐỐI XỨNG KHỚP GỐI',
              value: '${kneeSymmetry.toStringAsFixed(1)}%',
              subtitle: kneeRating,
              icon: Icons.balance,
              color: kneeColor,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _buildKpiCard(
              title: 'ĐỐI XỨNG LỰC INSOLE',
              value: scan.plantarLoadSymmetry != null
                  ? '${forceSymmetry.toStringAsFixed(1)}%'
                  : '--%',
              subtitle: forceRating,
              icon: Icons.monitor_weight_outlined,
              color: scan.plantarLoadSymmetry != null
                  ? forceColor
                  : AppColors.textSecondary,
            ),
          ),
        ],
      ),
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
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: color.withValues(alpha: 0.1),
            child: Icon(icon, color: color, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                      fontSize: 10,
                      color: AppColors.textSecondary,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 0.5),
                ),
                const SizedBox(height: 4),
                Text(
                  value,
                  style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      color: AppColors.textPrimary),
                ),
                if (subtitle != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: TextStyle(
                        fontSize: 10,
                        color: color,
                        fontWeight: FontWeight.w500),
                  ),
                ]
              ],
            ),
          )
        ],
      ),
    );
  }

  Widget _buildTorqueItem(String title, String val, String status) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(title,
                  style: const TextStyle(
                      fontSize: 11, color: AppColors.textSecondary)),
              Text(val,
                  style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.bold,
                      color: AppColors.accent)),
            ],
          ),
          const SizedBox(height: 2),
          Text('Trạng thái: $status',
              style: const TextStyle(
                  fontSize: 10,
                  color: AppColors.baseline,
                  fontStyle: FontStyle.italic)),
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
      padding: const EdgeInsets.all(12),
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
          const SizedBox(height: 12),
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
                        if (val == 0)
                          return const Text('0%',
                              style: TextStyle(
                                  fontSize: 9, color: AppColors.textSecondary));
                        if (val == 50)
                          return const Text('50%',
                              style: TextStyle(
                                  fontSize: 9, color: AppColors.textSecondary));
                        if (val == 100)
                          return const Text('100%',
                              style: TextStyle(
                                  fontSize: 9, color: AppColors.textSecondary));
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

class _CopTrajectoryPainter extends CustomPainter {
  _CopTrajectoryPainter({required this.trajectory, required this.isLeft});
  final List<dynamic> trajectory;
  final bool isLeft;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // Draw background
    final bgPaint = Paint()
      ..color = AppColors.sidebar
      ..style = PaintingStyle.fill;
    canvas.drawRRect(
        RRect.fromRectAndRadius(
            Rect.fromLTWH(0, 0, w, h), const Radius.circular(8)),
        bgPaint);

    // Draw crosshair axes
    final axisPaint = Paint()
      ..color = AppColors.border
      ..strokeWidth = 1.0
      ..style = PaintingStyle.stroke;
    canvas.drawLine(Offset(w / 2, 10), Offset(w / 2, h - 10), axisPaint);
    canvas.drawLine(Offset(10, h / 2), Offset(w - 10, h / 2), axisPaint);

    // Draw foot contour (outline shape)
    final footPaint = Paint()
      ..color = AppColors.surfaceMuted
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0;
    final footPath = Path();
    if (isLeft) {
      footPath.moveTo(w * 0.4, h * 0.9);
      footPath.quadraticBezierTo(w * 0.25, h * 0.6, w * 0.35, h * 0.4);
      footPath.quadraticBezierTo(w * 0.2, h * 0.15, w * 0.5, h * 0.08);
      footPath.quadraticBezierTo(w * 0.75, h * 0.15, w * 0.65, h * 0.4);
      footPath.quadraticBezierTo(w * 0.75, h * 0.6, w * 0.6, h * 0.9);
      footPath.close();
    } else {
      footPath.moveTo(w * 0.6, h * 0.9);
      footPath.quadraticBezierTo(w * 0.75, h * 0.6, w * 0.65, h * 0.4);
      footPath.quadraticBezierTo(w * 0.8, h * 0.15, w * 0.5, h * 0.08);
      footPath.quadraticBezierTo(w * 0.25, h * 0.15, w * 0.35, h * 0.4);
      footPath.quadraticBezierTo(w * 0.25, h * 0.6, w * 0.4, h * 0.9);
      footPath.close();
    }
    canvas.drawPath(footPath, footPaint);

    // Map CoP coordinates (-3.5 to 3.5) to pixel coordinate space
    Offset mapCoord(double cx, double cy) {
      final px = w / 2 + (cx / 3.5) * (w * 0.35);
      final py = h / 2 - (cy / 3.5) * (h * 0.35);
      return Offset(px, py);
    }

    // Draw CoP points trace connected line
    final pathPaint = Paint()
      ..color = isLeft ? AppColors.leftLeg : AppColors.rightLeg
      ..strokeWidth = 2.5
      ..style = PaintingStyle.stroke;

    final copPath = Path();
    bool first = true;
    for (final pt in trajectory) {
      if (pt is Map) {
        final xKey = isLeft ? 'left_x' : 'right_x';
        final yKey = isLeft ? 'left_y' : 'right_y';
        final cx = (pt[xKey] as num?)?.toDouble() ?? 0.0;
        final cy = (pt[yKey] as num?)?.toDouble() ?? 0.0;
        if (cx == 0.0 && cy == 0.0) continue;
        final offset = mapCoord(cx, cy);
        if (first) {
          copPath.moveTo(offset.dx, offset.dy);
          first = false;
        } else {
          copPath.lineTo(offset.dx, offset.dy);
        }
      }
    }
    canvas.drawPath(copPath, pathPaint);

    // Draw start dot in green
    if (trajectory.isNotEmpty) {
      final startPt = trajectory.first;
      if (startPt is Map) {
        final xKey = isLeft ? 'left_x' : 'right_x';
        final yKey = isLeft ? 'left_y' : 'right_y';
        final sx = (startPt[xKey] as num?)?.toDouble() ?? 0.0;
        final sy = (startPt[yKey] as num?)?.toDouble() ?? 0.0;
        if (sx != 0.0 || sy != 0.0) {
          canvas.drawCircle(
              mapCoord(sx, sy), 4.0, Paint()..color = Colors.greenAccent);
        }
      }
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}
