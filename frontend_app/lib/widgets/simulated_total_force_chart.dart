import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme/app_theme.dart';
import 'smoothed_line_chart.dart';

/// Both sides share video timestamps; the third result is their exact sum.
List<List<FlSpot>> simultaneousForceSpots(List frames, bool filtered) {
  List<FlSpot> side(String key) => frames.map<FlSpot>((frame) {
        final value = frame[key];
        return value is Map && value['total'] is num
            ? FlSpot((frame['time'] as num).toDouble(),
                (value['total'] as num).toDouble())
            : FlSpot.nullSpot;
      }).toList();
  final left = filtered ? smoothReportSpots(side('left')) : side('left');
  final right = filtered ? smoothReportSpots(side('right')) : side('right');
  final total = List<FlSpot>.generate(
      frames.length,
      (i) => left[i].isNull() || right[i].isNull()
          ? FlSpot.nullSpot
          : FlSpot(left[i].x, left[i].y + right[i].y));
  return [left, right, total];
}

class SimulatedTotalForceChart extends StatelessWidget {
  const SimulatedTotalForceChart(
      {super.key, required this.frames, required this.position});
  final List frames;
  final double position;
  @override
  Widget build(BuildContext context) => ValueListenableBuilder<bool>(
      valueListenable: reportSmoothing,
      builder: (context, filtered, _) {
        if (frames.isEmpty) {
          return const Center(child: Text('Đang tải dữ liệu lực…'));
        }
        final series = simultaneousForceSpots(frames, filtered);
        final currentIndex =
            (position * 60).round().clamp(0, frames.length - 1);
        final hasCurrent = !series[0][currentIndex].isNull() &&
            !series[1][currentIndex].isNull();
        final leftNow = hasCurrent ? series[0][currentIndex].y : null;
        final rightNow = hasCurrent ? series[1][currentIndex].y : null;
        final totalNow = hasCurrent ? leftNow! + rightNow! : null;
        return Column(children: [
          Text(
              hasCurrent
                  ? 'Trái ${leftNow!.toStringAsFixed(0)} N  +  Phải ${rightNow!.toStringAsFixed(0)} N  =  Tổng ${totalNow!.toStringAsFixed(0)} N'
                  : 'Trái —  +  Phải —  =  Tổng —',
              textAlign: TextAlign.center,
              style:
                  const TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
          const Text('FSR · cùng thời điểm video',
              style: TextStyle(fontSize: 9, color: Colors.black54)),
          const SizedBox(height: 8),
          Expanded(
              child: LineChart(
                  LineChartData(
                    minX: 0,
                    maxX: 8,
                    minY: 0,
                    maxY: 950,
                    extraLinesData: ExtraLinesData(verticalLines: [
                      VerticalLine(
                          x: position.clamp(0, 8),
                          color: Colors.grey,
                          strokeWidth: 1,
                          dashArray: [4, 4])
                    ]),
                    lineBarsData: List.generate(
                        2,
                        (i) => LineChartBarData(
                            spots: series[i],
                            color:
                                i == 0 ? AppColors.leftLeg : AppColors.rightLeg,
                            barWidth: 2.4,
                            isCurved: true,
                            curveSmoothness: .15,
                            preventCurveOverShooting: true,
                            isStrokeCapRound: true,
                            dashArray: i == 1 ? [6, 4] : null,
                            dotData: const FlDotData(show: false))),
                    titlesData: FlTitlesData(
                        topTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false)),
                        rightTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false)),
                        leftTitles: AxisTitles(
                            axisNameWidget:
                                const Text('N', style: TextStyle(fontSize: 9)),
                            sideTitles: SideTitles(
                                showTitles: true,
                                reservedSize: 35,
                                interval: 300,
                                getTitlesWidget: (v, _) => Text(
                                    v.toStringAsFixed(0),
                                    style: const TextStyle(fontSize: 9)))),
                        bottomTitles: AxisTitles(
                            axisNameWidget: const Text('Thời gian video (giây)',
                                style: TextStyle(fontSize: 9)),
                            sideTitles: SideTitles(
                                showTitles: true,
                                interval: 2,
                                reservedSize: 22,
                                getTitlesWidget: (v, _) => Text(
                                    v.toStringAsFixed(0),
                                    style: const TextStyle(fontSize: 9))))),
                    gridData: const FlGridData(
                        show: true,
                        horizontalInterval: 300,
                        verticalInterval: 2),
                    borderData: FlBorderData(show: false),
                    lineTouchData: const LineTouchData(enabled: true),
                  ),
                  duration: Duration.zero)),
        ]);
      });
}
