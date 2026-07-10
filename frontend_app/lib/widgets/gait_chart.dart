import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../models/gait_data.dart';
import '../theme/app_theme.dart';

class GaitChart extends StatelessWidget {
  const GaitChart({
    super.key,
    required this.title,
    required this.yAxisLabel,
    required this.primaryCurve,
    this.secondaryCurve,
    required this.lineColor,
    this.unit = '°',
  });

  final String title;
  final String yAxisLabel;
  final GaitCycleCurve? primaryCurve;
  final GaitCycleCurve? secondaryCurve;
  final Color lineColor;
  final String unit;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.all(4),
      padding: const EdgeInsets.fromLTRB(8, 8, 12, 8),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 3,
                height: 14,
                color: lineColor,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (primaryCurve != null)
                Text(
                  'max ${primaryCurve!.maxAngle.toStringAsFixed(0)}$unit',
                  style: TextStyle(fontSize: 10, color: lineColor),
                ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            yAxisLabel,
            style: const TextStyle(fontSize: 10, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 4),
          Expanded(
            child: primaryCurve == null
                ? const Center(
                    child: Text(
                      'Chưa có dữ liệu — bấm Record để quét',
                      style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
                      textAlign: TextAlign.center,
                    ),
                  )
                : LineChart(
                    _buildChartData(primaryCurve!, secondaryCurve),
                    duration: Duration.zero,
                  ),
          ),
        ],
      ),
    );
  }

  LineChartData _buildChartData(
    GaitCycleCurve primary,
    GaitCycleCurve? secondary,
  ) {
    final spots = _toSpots(primary.angles);
    final secondarySpots =
        secondary != null ? _toSpots(secondary.angles) : <FlSpot>[];

    final allY = [...primary.angles, if (secondary != null) ...secondary.angles];
    final minY = (allY.reduce((a, b) => a < b ? a : b) - 5).floorToDouble();
    final maxY = (allY.reduce((a, b) => a > b ? a : b) + 5).ceilToDouble();

    return LineChartData(
      minX: 0,
      maxX: 100,
      minY: minY,
      maxY: maxY,
      gridData: FlGridData(
        show: true,
        drawVerticalLine: true,
        horizontalInterval: 10,
        verticalInterval: 20,
        getDrawingHorizontalLine: (_) => FlLine(
          color: AppColors.border.withValues(alpha: 0.4),
          strokeWidth: 0.5,
        ),
        getDrawingVerticalLine: (_) => FlLine(
          color: AppColors.border.withValues(alpha: 0.4),
          strokeWidth: 0.5,
        ),
      ),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        leftTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            reservedSize: 28,
            interval: 20,
            getTitlesWidget: (value, _) => Text(
              value.toInt().toString(),
              style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
            ),
          ),
        ),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            reservedSize: 20,
            interval: 25,
            getTitlesWidget: (value, _) => Text(
              '${value.toInt()}%',
              style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
            ),
          ),
        ),
      ),
      borderData: FlBorderData(
        show: true,
        border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
      ),
      lineBarsData: [
        LineChartBarData(
          spots: spots,
          isCurved: true,
          color: lineColor,
          barWidth: 2,
          dotData: const FlDotData(show: false),
          belowBarData: BarAreaData(
            show: true,
            color: lineColor.withValues(alpha: 0.08),
          ),
        ),
        if (secondarySpots.isNotEmpty)
          LineChartBarData(
            spots: secondarySpots,
            isCurved: true,
            color: AppColors.baseline,
            barWidth: 1.5,
            dashArray: [6, 4],
            dotData: const FlDotData(show: false),
          ),
      ],
      lineTouchData: const LineTouchData(enabled: false),
    );
  }

  List<FlSpot> _toSpots(List<double> angles) {
    return List.generate(
      angles.length,
      (i) => FlSpot(i * 100 / (angles.length - 1), angles[i]),
    );
  }
}
