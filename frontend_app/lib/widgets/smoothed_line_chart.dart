import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';

import '../l10n/app_language.dart';

/// Shared presentation setting. Does not mutate measurements or derived metrics.
final reportSmoothing = ValueNotifier<bool>(true);

List<FlSpot> smoothReportSpots(List<FlSpot> source) {
  final result = List<FlSpot>.of(source);
  var start = 0;
  while (start < source.length) {
    if (!source[start].x.isFinite || !source[start].y.isFinite) {
      start++;
      continue;
    }
    var end = start + 1;
    while (end < source.length &&
        source[end].x.isFinite &&
        source[end].y.isFinite &&
        source[end].x > source[end - 1].x) {
      end++;
    }
    if (end - start >= 5) {
      final values = source.sublist(start, end).map((p) => p.y).toList();
      double sample(List<double> data, int i) =>
          data[i.clamp(0, data.length - 1)];
      final median = List<double>.generate(values.length, (i) {
        final window =
            List<double>.generate(5, (j) => sample(values, i + j - 2))..sort();
        return window[2];
      });
      for (var i = 0; i < values.length; i++) {
        var sum = 0.0;
        for (var j = -2; j <= 2; j++) {
          sum += sample(median, i + j);
        }
        result[start + i] = FlSpot(source[start + i].x, sum / 5);
      }
    }
    start = end;
  }
  return result;
}

class ReportSmoothingSwitch extends StatelessWidget {
  const ReportSmoothingSwitch({super.key});
  @override
  Widget build(BuildContext context) => ValueListenableBuilder<bool>(
        valueListenable: reportSmoothing,
        builder: (context, enabled, _) => Tooltip(
            message: context.tr(
              'Làm mượt đường biểu đồ camera và FSR ở mọi tab. Không đổi dữ liệu lưu, peak hoặc bảng chỉ số. Tắt để bỏ lọc hiển thị; không tắt tiền xử lý cảm biến.',
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Switch(
                  value: enabled,
                  onChanged: (value) => reportSmoothing.value = value),
            ])),
      );
}

class SmoothedLineChart extends StatelessWidget {
  const SmoothedLineChart(this.data,
      {super.key,
      this.duration = Duration.zero,
      this.curve = Curves.linear,
      this.preserveValues = false});
  final LineChartData data;
  final Duration duration;
  final Curve curve;

  /// Analytic demo curves already are smooth; retain their values for exact
  /// agreement with regional sums, heatmaps and summary statistics.
  final bool preserveValues;
  @override
  Widget build(BuildContext context) => ValueListenableBuilder<bool>(
        valueListenable: reportSmoothing,
        builder: (context, enabled, _) => LineChart(
          enabled
              ? data.copyWith(
                  lineBarsData: data.lineBarsData
                      .map((bar) => bar.copyWith(
                          spots: preserveValues
                              ? bar.spots
                              : smoothReportSpots(bar.spots),
                          isCurved: true,
                          curveSmoothness: 0.15,
                          preventCurveOverShooting: true,
                          preventCurveOvershootingThreshold: 0,
                          isStrokeCapRound: true))
                      .toList())
              : data,
          duration: duration,
          curve: curve,
        ),
      );
}
