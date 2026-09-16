import 'dart:convert';
import '../demo/phone_demo_timeline.dart';
import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';
import 'smoothed_line_chart.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:http/http.dart' as http;

/// Offline measured angles, never mixed with live/reference FSR.
class PhoneDemoCharts extends StatefulWidget {
  const PhoneDemoCharts({super.key});
  @override
  State<PhoneDemoCharts> createState() => _PhoneDemoChartsState();
}

class _PhoneDemoChartsState extends State<PhoneDemoCharts> {
  Map<String, dynamic>? _signals;
  String? _error;
  double _fps = 30;
  double _duration = 8;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final response = await http
          .get(Uri.parse('http://127.0.0.1:8000/phone-demos/phone-02'));
      if (response.statusCode != 200) {
        throw Exception('HTTP ${response.statusCode}');
      }
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final signals = data['cameraPreview']['signals'] as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _signals = signals;
          _fps = (data['cameraPreview']['fps'] as num).toDouble();
          _duration = (data['durationSec'] as num).toDouble();
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Chưa tải được dữ liệu góc của Mẫu 2.');
      }
    }
  }

  List<LineChartBarData> _lines(String key, Color color) {
    final values = _signals![key]['raw'] as List;
    final result = <LineChartBarData>[];
    var run = <FlSpot>[];
    void finish() {
      if (run.isNotEmpty) {
        result.add(LineChartBarData(
            spots: run,
            color: color,
            barWidth: 2.5,
            isStrokeCapRound: true,
            isCurved: false,
            dotData: FlDotData(show: run.length == 1)));
      }
      run = <FlSpot>[];
    }

    for (var i = 0; i < values.length; i++) {
      final value = values[i];
      if (value is num && value.isFinite) {
        run.add(FlSpot(i / _fps, value.toDouble()));
      } else {
        finish();
      }
    }
    finish();
    return result;
  }

  Widget _chart(String title, String first, [String? second]) => Card(
      child: Padding(
          padding: const EdgeInsets.all(16),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
            Text(
                second == null
                    ? 'Góc (°) · thời gian (s)'
                    : 'Xanh: chân trái · Cam: chân phải · Góc (°)',
                style: TextStyle(
                    fontSize: 11,
                    color: Theme.of(context).colorScheme.onSurfaceVariant)),
            const SizedBox(height: 10),
            SizedBox(
                height: 170,
                child: ValueListenableBuilder<double>(
                    valueListenable: phoneDemoPosition,
                    builder: (context, position, _) => SmoothedLineChart(
                        LineChartData(
                          minX: 0,
                          maxX: _duration,
                          extraLinesData: ExtraLinesData(verticalLines: [
                            VerticalLine(
                                x: position.clamp(0, _duration),
                                color: Colors.teal,
                                strokeWidth: 1.5,
                                dashArray: [4, 4]),
                          ]),
                          lineBarsData: [
                            ..._lines(first, Colors.blue),
                            if (second != null) ..._lines(second, Colors.orange)
                          ],
                          titlesData: const FlTitlesData(
                              topTitles: AxisTitles(
                                  sideTitles: SideTitles(showTitles: false)),
                              rightTitles: AxisTitles(
                                  sideTitles: SideTitles(showTitles: false)),
                              bottomTitles: AxisTitles(
                                  sideTitles: SideTitles(
                                      showTitles: true,
                                      interval: 2,
                                      reservedSize: 24)),
                              leftTitles: AxisTitles(
                                  sideTitles: SideTitles(
                                      showTitles: true, reservedSize: 36))),
                          borderData: FlBorderData(show: false),
                          gridData: const FlGridData(show: true),
                        ),
                        duration: Duration.zero))),
          ])));

  @override
  Widget build(BuildContext context) {
    if (_error != null) return Center(child: Text(_error!));
    if (_signals == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(padding: const EdgeInsets.all(8), children: [
      const Padding(
          padding: EdgeInsets.all(12),
          child: Text('Mẫu 2 · CAMERA + FSR · con trỏ theo video.')),
      _chart('Góc gối', 'leftKnee', 'rightKnee'),
      _chart('Góc hông', 'leftHip', 'rightHip'),
      _chart('Nghiêng trước–sau · dương: trước', 'trunkFront'),
      _chart('Góc nghiêng thân · dương: phải', 'trunkSide'),
      const Padding(
          padding: EdgeInsets.all(12),
          child: Text(
              'Dữ liệu FSR minh họa · chưa hiệu chuẩn. Góc camera giữ nguyên nguồn; chưa xác nhận đồng bộ hai góc quay.',
              style: TextStyle(fontSize: 11))),
    ]);
  }
}
