import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:ai_progait/widgets/smoothed_line_chart.dart';

void main() {
  tearDown(() => reportSmoothing.value = true);
  testWidgets('adjusted demo retains exact values with smoothing enabled',
      (tester) async {
    final raw =
        List.generate(5, (i) => FlSpot(i.toDouble(), i == 2 ? 390 : 300));
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SizedBox(
      height: 180,
      child: SmoothedLineChart(
        LineChartData(lineBarsData: [LineChartBarData(spots: raw)]),
        preserveValues: true,
      ),
    ))));
    final chart = tester.widget<LineChart>(find.byType(LineChart));
    expect(chart.data.lineBarsData.first.spots, raw);
  });
  test('median removes isolated spike, preserves raw and missing runs', () {
    final raw = [
      const FlSpot(0, 2),
      const FlSpot(1, 2),
      const FlSpot(2, 90),
      const FlSpot(3, 2),
      const FlSpot(4, 2),
      FlSpot.nullSpot,
      const FlSpot(6, 10)
    ];
    final result = smoothReportSpots(raw);
    expect(result.take(5).map((p) => p.y), everyElement(2));
    expect(result[5].isNull(), true);
    expect(result[6].y, 10);
    expect(raw[2].y, 90);
  });
  test('ordered mean and SD envelopes stay ordered', () {
    final mean =
        List.generate(21, (i) => FlSpot(i.toDouble(), i % 3 == 0 ? 20 : 5));
    final lower =
        smoothReportSpots(mean.map((p) => FlSpot(p.x, p.y - 3)).toList());
    final upper =
        smoothReportSpots(mean.map((p) => FlSpot(p.x, p.y + 7)).toList());
    final filtered = smoothReportSpots(mean);
    for (var i = 0; i < mean.length; i++) {
      expect(lower[i].y, lessThanOrEqualTo(filtered[i].y));
      expect(upper[i].y, greaterThanOrEqualTo(filtered[i].y));
    }
  });
  testWidgets('one switch updates all mounted charts and restores input',
      (tester) async {
    final raw = List.generate(5, (i) => FlSpot(i.toDouble(), i == 2 ? 90 : 2));
    final data = LineChartData(lineBarsData: [LineChartBarData(spots: raw)]);
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Column(children: [
      const ReportSmoothingSwitch(),
      SizedBox(height: 180, child: SmoothedLineChart(data)),
      SizedBox(height: 180, child: SmoothedLineChart(data)),
    ]))));
    expect(
        tester
            .widgetList<LineChart>(find.byType(LineChart))
            .map((c) => c.data.lineBarsData.first.spots[2].y),
        everyElement(2));
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(
        tester
            .widgetList<LineChart>(find.byType(LineChart))
            .map((c) => c.data.lineBarsData.first.spots[2].y),
        everyElement(90));
    expect(raw[2].y, 90);
  });
}
