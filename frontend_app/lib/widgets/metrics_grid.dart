import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';
import 'smoothed_line_chart.dart';
import 'package:fl_chart/fl_chart.dart';
import 'dart:math';

import '../models/gait_data.dart';
import '../theme/app_theme.dart';

const _cameraLeftColor = Color(0xFF1F77B4);
const _cameraRightColor = Color(0xFFE87522);
const _cameraGridColor = Color(0xFFD8DEE5);
const _cameraFrameColor = Color(0xFF9EABB7);

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

    return LayoutBuilder(
      builder: (context, constraints) {
        final body = Padding(
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
              Wrap(
                alignment: WrapAlignment.spaceBetween,
                crossAxisAlignment: WrapCrossAlignment.center,
                spacing: 12,
                runSpacing: 5,
                children: [
                  const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.insights_outlined,
                          size: 16, color: AppColors.accent),
                      SizedBox(width: 7),
                      Text('ĐỘNG HỌC TỪ CAMERA',
                          style: TextStyle(
                              fontSize: 11, fontWeight: FontWeight.w700)),
                    ],
                  ),
                  if (scan.fatigueFlag == 1)
                    const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.warning_amber_rounded,
                            size: 14, color: AppColors.warning),
                        SizedBox(width: 4),
                        Text('Có cờ mỏi cơ',
                            style: TextStyle(
                                fontSize: 9, color: AppColors.warning)),
                      ],
                    ),
                ],
              ),
              const SizedBox(height: 6),
              Align(
                alignment: Alignment.centerLeft,
                child: Wrap(
                  spacing: 7,
                  runSpacing: 4,
                  children: List.generate(groups.length, (index) {
                    final group = groups[index];
                    return ChoiceChip(
                      selected: index == _activeGroup,
                      avatar: Icon(group.$3, size: 14),
                      label:
                          Text(group.$2, style: const TextStyle(fontSize: 9)),
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
        if (constraints.maxHeight < 280) {
          return SingleChildScrollView(
            child: SizedBox(
              height: constraints.maxWidth < 300 ? 560 : 330,
              child: body,
            ),
          );
        }
        return body;
      },
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
        title: 'Góc nghiêng chậu',
        yAxisLabel: 'Góc nghiêng (°)',
        primaryCurve: scan.pelvicTilt,
        secondaryCurve: baseline?.pelvicTilt,
        primaryLabel: 'Bản ghi đang chọn',
        secondaryLabel: 'Mẫu tham chiếu',
        lineColor: AppColors.accentGreen,
        secondaryLineColor: AppColors.baseline,
      );
    }

    final isKnee = group == 'knee';
    final label = isKnee ? 'Góc gối' : 'Góc hông';
    final leftCurve = isKnee ? scan.leftKnee : scan.leftHip;
    final rightCurve = isKnee ? scan.rightKnee : scan.rightHip;
    final baselineLeft = isKnee ? baseline?.leftKnee : baseline?.leftHip;
    final baselineRight = isKnee ? baseline?.rightKnee : baseline?.rightHip;

    return GaitChart(
      key: key,
      title: label,
      yAxisLabel: '$label (°)',
      primaryCurve: leftCurve,
      secondaryCurve: rightCurve,
      referencePrimaryCurve: baselineLeft,
      referenceSecondaryCurve: baselineRight,
      primaryLabel: 'Chân trái',
      secondaryLabel: 'Chân phải',
      lineColor: _cameraLeftColor,
      secondaryLineColor: _cameraRightColor,
      secondaryDashed: true,
      axisCurves: [
        leftCurve,
        rightCurve,
        baselineLeft,
        baselineRight,
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
    final cards = [
      _buildKpiCard(
        title: 'NHỊP ĐIỆU',
        value: scan.cadence != null
            ? '${scan.cadence!.toStringAsFixed(0)} bước/phút'
            : '—',
        icon: Icons.speed,
        color: AppColors.accent,
      ),
      _buildKpiCard(
        title: 'SẢI CHÂN ƯỚC TÍNH',
        value: scan.strideLength != null
            ? '${scan.strideLength!.toStringAsFixed(2)} m'
            : '—',
        subtitle: 'chưa hiệu chuẩn thước đo mặt sàn',
        icon: Icons.straighten,
        color: AppColors.accentGreen,
      ),
      _buildKpiCard(
        title: 'ĐỐI XỨNG GỐI',
        value: '${kneeSymmetry.toStringAsFixed(1)}%',
        subtitle: kneeStatus,
        icon: Icons.balance_outlined,
        color: kneeColor,
      ),
      _buildKpiCard(
        title: 'ĐỐI XỨNG INSOLE',
        value: scan.plantarLoadSymmetry == null
            ? '—'
            : '${forceSymmetry.toStringAsFixed(1)}%',
        subtitle:
            scan.plantarLoadSymmetry == null ? 'chưa có FSR' : 'tải trái–phải',
        icon: Icons.sensors_outlined,
        color: forceColor,
      ),
    ];

    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 860
            ? 4
            : constraints.maxWidth >= 300
                ? 2
                : 1;
        final cardWidth = (constraints.maxWidth - (columns - 1) * 8) / columns;
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final card in cards) SizedBox(width: cardWidth, child: card),
          ],
        );
      },
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
    this.referencePrimaryCurve,
    this.referenceSecondaryCurve,
    this.axisCurves,
    required this.lineColor,
    this.secondaryLineColor = _cameraRightColor,
    this.primaryLabel = 'Bản ghi',
    this.secondaryLabel = 'Tham chiếu',
    this.secondaryDashed = true,
  });

  final String title;
  final String yAxisLabel;
  final GaitCycleCurve? primaryCurve;
  final GaitCycleCurve? secondaryCurve;
  final GaitCycleCurve? referencePrimaryCurve;
  final GaitCycleCurve? referenceSecondaryCurve;
  final List<GaitCycleCurve?>? axisCurves;
  final Color lineColor;
  final Color secondaryLineColor;
  final String primaryLabel;
  final String secondaryLabel;
  final bool secondaryDashed;

  bool _hasData(GaitCycleCurve? curve) =>
      curve != null && curve.angles.isNotEmpty;

  List<FlSpot> _spots(GaitCycleCurve curve) {
    if (curve.angles.length == 1) return [FlSpot(0, curve.angles.first)];
    final denominator = curve.angles.length - 1;
    return List.generate(
      curve.angles.length,
      (index) => FlSpot(
        index * 100 / denominator,
        curve.angles[index],
      ),
    );
  }

  double _niceInterval(double rawInterval) {
    if (!rawInterval.isFinite || rawInterval <= 0) return 1;
    final exponent = (log(rawInterval) / log(10)).floor();
    final magnitude = pow(10, exponent).toDouble();
    final normalized = rawInterval / magnitude;
    final factor = normalized <= 1
        ? 1.0
        : normalized <= 2
            ? 2.0
            : normalized <= 5
                ? 5.0
                : 10.0;
    return factor * magnitude;
  }

  ({double min, double max, double interval}) _axisScale(
    List<GaitCycleCurve> curves,
  ) {
    final values = curves
        .expand((curve) => curve.angles)
        .where((value) => value.isFinite)
        .toList();
    if (values.isEmpty) return (min: -5, max: 5, interval: 2);

    final dataMin = values.reduce(min);
    final dataMax = values.reduce(max);
    final span = max(0.5, dataMax - dataMin);
    final padding = max(0.5, span * 0.08);
    if (title.toLowerCase().contains('nghiêng')) {
      final paddedExtent =
          max(1.0, max(dataMin.abs(), dataMax.abs()) + padding);
      final interval = _niceInterval((paddedExtent * 2) / 5);
      final extent = max(
        interval * 2,
        (paddedExtent / interval).ceil() * interval,
      );
      return (min: -extent, max: extent, interval: interval);
    }

    final interval = _niceInterval((span + padding * 2) / 5);
    var minY = ((dataMin - padding) / interval).floor() * interval;
    var maxY = ((dataMax + padding) / interval).ceil() * interval;
    if (dataMin >= 0 && minY < 0) minY = 0;
    if (maxY - minY < interval * 2) maxY = minY + interval * 2;
    return (min: minY, max: maxY, interval: interval);
  }

  LineChartBarData _line(
    GaitCycleCurve curve,
    Color color, {
    bool dashed = false,
    bool reference = false,
  }) =>
      LineChartBarData(
        spots: _spots(curve),
        color: reference ? color.withValues(alpha: 0.38) : color,
        barWidth: reference ? 1.4 : 2.8,
        isCurved: false,
        preventCurveOverShooting: true,
        preventCurveOvershootingThreshold: double.infinity,
        isStrokeCapRound: true,
        isStrokeJoinRound: true,
        dashArray: dashed ? const [9, 6] : null,
        dotData: const FlDotData(show: false),
      );

  @override
  Widget build(BuildContext context) {
    final hasPrimary = _hasData(primaryCurve);
    final hasSecondary = _hasData(secondaryCurve);
    final hasReferencePrimary = _hasData(referencePrimaryCurve);
    final hasReferenceSecondary = _hasData(referenceSecondaryCurve);

    if (!hasPrimary && !hasSecondary) {
      return Container(
        margin: const EdgeInsets.all(4),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(10),
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

    final scaleCurves = (axisCurves ??
            [
              primaryCurve,
              secondaryCurve,
              referencePrimaryCurve,
              referenceSecondaryCurve,
            ])
        .whereType<GaitCycleCurve>()
        .where((curve) => curve.angles.isNotEmpty)
        .toList();
    final axis = _axisScale(scaleCurves);
    final yDecimals = axis.interval < 1 ? 1 : 0;
    final lines = <LineChartBarData>[
      if (hasReferencePrimary)
        _line(
          referencePrimaryCurve!,
          lineColor,
          dashed: true,
          reference: true,
        ),
      if (hasReferenceSecondary)
        _line(
          referenceSecondaryCurve!,
          secondaryLineColor,
          dashed: true,
          reference: true,
        ),
      if (hasPrimary) _line(primaryCurve!, lineColor),
      if (hasSecondary)
        _line(
          secondaryCurve!,
          secondaryLineColor,
          dashed: secondaryDashed,
        ),
    ];

    return Container(
      margin: const EdgeInsets.all(4),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: 6),
          Wrap(
            alignment: WrapAlignment.end,
            spacing: 10,
            runSpacing: 5,
            children: [
              if (hasPrimary) _buildLegendIndicator(primaryLabel, lineColor),
              if (hasSecondary)
                _buildLegendIndicator(
                  secondaryLabel,
                  secondaryLineColor,
                  isDashed: secondaryDashed,
                ),
              if (hasReferencePrimary)
                _buildLegendIndicator(
                  '$primaryLabel · tham chiếu',
                  lineColor.withValues(alpha: 0.45),
                  isDashed: true,
                ),
              if (hasReferenceSecondary)
                _buildLegendIndicator(
                  '$secondaryLabel · tham chiếu',
                  secondaryLineColor.withValues(alpha: 0.45),
                  isDashed: true,
                ),
            ],
          ),
          const SizedBox(height: 6),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxWidth < 520;
                return Semantics(
                  label: '$title theo phần trăm chu kỳ camera chuẩn hóa',
                  child: SmoothedLineChart(
                    LineChartData(
                      minX: 0,
                      maxX: 100,
                      minY: axis.min,
                      maxY: axis.max,
                      clipData: const FlClipData.all(),
                      lineBarsData: lines,
                      lineTouchData: const LineTouchData(enabled: false),
                      extraLinesData: axis.min < 0 && axis.max > 0
                          ? ExtraLinesData(
                              horizontalLines: [
                                HorizontalLine(
                                  y: 0,
                                  color: _cameraFrameColor,
                                  strokeWidth: 1,
                                ),
                              ],
                            )
                          : const ExtraLinesData(),
                      gridData: FlGridData(
                        show: true,
                        drawHorizontalLine: true,
                        drawVerticalLine: true,
                        horizontalInterval: axis.interval,
                        verticalInterval: 20,
                        getDrawingHorizontalLine: (_) => const FlLine(
                          color: _cameraGridColor,
                          strokeWidth: 0.65,
                        ),
                        getDrawingVerticalLine: (_) => const FlLine(
                          color: _cameraGridColor,
                          strokeWidth: 0.65,
                        ),
                      ),
                      borderData: FlBorderData(
                        show: true,
                        border: Border.all(
                          color: _cameraFrameColor,
                          width: 0.8,
                        ),
                      ),
                      titlesData: FlTitlesData(
                        topTitles: const AxisTitles(
                          sideTitles: SideTitles(showTitles: false),
                        ),
                        rightTitles: const AxisTitles(
                          sideTitles: SideTitles(showTitles: false),
                        ),
                        bottomTitles: AxisTitles(
                          axisNameSize: compact ? 23 : 27,
                          axisNameWidget: const Padding(
                            padding: EdgeInsets.only(top: 5),
                            child: Text(
                              '% chu kỳ camera chuẩn hóa',
                              style: TextStyle(
                                fontSize: 9,
                                fontWeight: FontWeight.w500,
                                color: AppColors.textPrimary,
                              ),
                            ),
                          ),
                          sideTitles: SideTitles(
                            showTitles: true,
                            interval: 20,
                            reservedSize: compact ? 22 : 25,
                            getTitlesWidget: (value, meta) => SideTitleWidget(
                              axisSide: meta.axisSide,
                              space: 5,
                              fitInside:
                                  SideTitleFitInsideData.fromTitleMeta(meta),
                              child: Text(
                                value.toInt().toString(),
                                style: const TextStyle(
                                  fontSize: 9,
                                  color: AppColors.textSecondary,
                                ),
                              ),
                            ),
                          ),
                        ),
                        leftTitles: AxisTitles(
                          axisNameSize: compact ? 22 : 28,
                          axisNameWidget: Text(
                            yAxisLabel,
                            style: const TextStyle(
                              fontSize: 9,
                              fontWeight: FontWeight.w500,
                              color: AppColors.textPrimary,
                            ),
                          ),
                          sideTitles: SideTitles(
                            showTitles: true,
                            interval: axis.interval,
                            reservedSize: compact ? 36 : 44,
                            getTitlesWidget: (value, meta) => SideTitleWidget(
                              axisSide: meta.axisSide,
                              space: 5,
                              fitInside:
                                  SideTitleFitInsideData.fromTitleMeta(meta),
                              child: Text(
                                value.toStringAsFixed(yDecimals),
                                style: const TextStyle(
                                  fontSize: 9,
                                  color: AppColors.textSecondary,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    duration: const Duration(milliseconds: 180),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLegendIndicator(
    String label,
    Color color, {
    bool isDashed = false,
  }) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: 24,
          height: 8,
          child: Row(
            children: List.generate(
              isDashed ? 3 : 1,
              (_) => Expanded(
                child: Container(
                  height: 2.6,
                  margin: EdgeInsets.symmetric(
                    horizontal: isDashed ? 1.2 : 0,
                  ),
                  color: color,
                ),
              ),
            ),
          ),
        ),
        const SizedBox(width: 5),
        Text(
          label,
          style: const TextStyle(fontSize: 9, color: AppColors.textPrimary),
        ),
      ],
    );
  }
}
