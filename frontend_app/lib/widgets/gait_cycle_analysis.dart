import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../theme/app_theme.dart';

class GaitCycleAnalysis extends StatefulWidget {
  const GaitCycleAnalysis({
    super.key,
    this.scanId,
    this.assetPath,
    this.healthySideOverride,
  }) : assert(scanId != null || assetPath != null);

  final String? scanId;
  final String? assetPath;
  final String? healthySideOverride;

  @override
  State<GaitCycleAnalysis> createState() => _GaitCycleAnalysisState();
}

class _GaitCycleAnalysisState extends State<GaitCycleAnalysis> {
  Map<String, dynamic>? _data;
  int _windowSize = 7;
  int _activeMetric = 0;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant GaitCycleAnalysis oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.scanId != widget.scanId ||
        oldWidget.assetPath != widget.assetPath ||
        oldWidget.healthySideOverride != widget.healthySideOverride) {
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      late final Map<String, dynamic> decoded;
      if (widget.assetPath != null) {
        final source = await rootBundle.loadString(widget.assetPath!);
        decoded = _windowedAssetData(
          jsonDecode(source) as Map<String, dynamic>,
        );
      } else {
        final response = await http.get(Uri.parse(
          'http://127.0.0.1:8000/scans/${widget.scanId}/gait-analysis?window=$_windowSize',
        ));
        if (response.statusCode != 200) {
          throw Exception('Backend trả mã ${response.statusCode}');
        }
        decoded = jsonDecode(response.body) as Map<String, dynamic>;
      }
      if (mounted) setState(() => _data = decoded);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Map<String, dynamic> _windowedAssetData(Map<String, dynamic> raw) {
    final source = raw['cycles'];
    final allCycles = source is List
        ? source.whereType<Map>().map(Map<String, dynamic>.from).toList()
        : <Map<String, dynamic>>[];
    final start = max(0, allCycles.length - _windowSize);
    final cycles = allCycles.sublist(start);
    const metricNames = ['knee', 'hip', 'trunk'];
    final metrics = <String, dynamic>{};

    for (final metric in metricNames) {
      final sides = <String, dynamic>{};
      for (final side in const ['left', 'right']) {
        final curves = <List<double>>[];
        for (final cycle in cycles) {
          final sideData = cycle[side];
          final curveMap = sideData is Map ? sideData['curves'] : null;
          final values = curveMap is Map ? curveMap[metric] : null;
          if (values is List) {
            curves.add(
              values.whereType<num>().map((value) => value.toDouble()).toList(),
            );
          }
        }
        final pointCount =
            curves.isEmpty ? 0 : curves.map((item) => item.length).reduce(min);
        final mean = List<double>.generate(pointCount, (index) {
          return curves.fold<double>(
                0,
                (sum, curve) => sum + curve[index],
              ) /
              curves.length;
        });
        final sd = List<double>.generate(pointCount, (index) {
          if (curves.length < 2) return 0;
          final variance = curves.fold<double>(
                0,
                (sum, curve) => sum + pow(curve[index] - mean[index], 2),
              ) /
              (curves.length - 1);
          return sqrt(variance);
        });
        sides[side] = {
          'mean': mean,
          'sd': sd,
          'cycles': curves.length,
        };
      }
      metrics[metric] = sides;
    }

    final result = Map<String, dynamic>.from(raw)
      ..['cycles'] = cycles
      ..['cycleCount'] = cycles.length
      ..['windowSize'] = _windowSize
      ..['metrics'] = metrics;
    final healthy = widget.healthySideOverride?.toLowerCase();
    if (healthy == 'left' || healthy == 'right') {
      result['healthySide'] = healthy;
      result['prostheticSide'] = healthy == 'left' ? 'right' : 'left';
    }
    return result;
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Text(_error!, style: const TextStyle(color: AppColors.critical)),
      );
    }
    final metrics = _data?['metrics'];
    if (metrics is! Map || metrics.isEmpty) {
      return const Center(
        child: Text(
          'Clip này chưa đủ chu kỳ camera hợp lệ.\n'
          'Hãy ghi ít nhất 2 chu kỳ; nên dùng 5 hoặc 7 chu kỳ để tính Mean ± SD ổn định.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.textSecondary),
        ),
      );
    }
    final healthySide = _data?['healthySide']?.toString().toLowerCase();
    String sideLabel(String side) {
      final name = side == 'left' ? 'Chân trái' : 'Chân phải';
      return '$name · ${side == healthySide ? 'lành' : 'giả'}';
    }

    const items = [
      ('knee', 'GÓC GỐI 2D - PHÂN TÍCH'),
      ('hip', 'GÓC HÔNG 2D - PHÂN TÍCH'),
      ('trunk', 'GÓC NGHIÊNG THÂN TRƯỚC–SAU - PHÂN TÍCH'),
    ];
    final count = (_data?['cycleCount'] as num?)?.toInt() ?? 0;
    final rejectedFrames =
        (_data?['rejectedSampleCount'] as num?)?.toInt() ?? 0;
    return Column(
      children: [
        Container(
          margin: const EdgeInsets.fromLTRB(12, 10, 12, 0),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: AppColors.panel,
            border: Border.all(color: AppColors.border),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              const Icon(Icons.directions_walk,
                  size: 15, color: AppColors.accent),
              const SizedBox(width: 7),
              Text(
                'Mean ± SD · $count cặp chu kỳ hợp lệ',
                style:
                    const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
              ),
              const Spacer(),
              if (rejectedFrames > 0) ...[
                const Icon(Icons.visibility_off_outlined,
                    size: 13, color: AppColors.warning),
                const SizedBox(width: 4),
                Text(
                  'Đã loại $rejectedFrames frame visibility < 0,80',
                  style: const TextStyle(
                    fontSize: 9,
                    color: AppColors.warning,
                  ),
                ),
                const SizedBox(width: 10),
              ],
              const Text('Cửa sổ phân tích',
                  style:
                      TextStyle(fontSize: 9, color: AppColors.textSecondary)),
              const SizedBox(width: 6),
              DropdownButtonHideUnderline(
                child: DropdownButton<int>(
                  value: _windowSize,
                  isDense: true,
                  items: const [5, 7]
                      .map((value) => DropdownMenuItem(
                            value: value,
                            child: Text('$value cặp',
                                style: const TextStyle(fontSize: 10)),
                          ))
                      .toList(),
                  onChanged: (value) {
                    if (value == null || value == _windowSize) return;
                    setState(() => _windowSize = value);
                    _load();
                  },
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('BIỂU ĐỒ CHU KỲ',
                    style:
                        TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                const SizedBox(height: 5),
                Wrap(
                  spacing: 7,
                  children: List.generate(items.length, (index) {
                    final item = items[index];
                    return ChoiceChip(
                      selected: index == _activeMetric,
                      label: Text(item.$2.split(' - ').first,
                          style: const TextStyle(fontSize: 9)),
                      visualDensity: VisualDensity.compact,
                      onSelected: (_) => setState(() => _activeMetric = index),
                    );
                  }),
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: _GaitChartCard(
                    title: items[_activeMetric].$2,
                    metric: metrics[items[_activeMetric].$1],
                    leftLabel: items[_activeMetric].$1 == 'trunk'
                        ? 'Theo chu kỳ chân trái'
                        : sideLabel('left'),
                    rightLabel: items[_activeMetric].$1 == 'trunk'
                        ? 'Theo chu kỳ chân phải'
                        : sideLabel('right'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _Series {
  const _Series(this.mean, this.sd, this.cycles);

  final List<double> mean;
  final List<double> sd;
  final int cycles;

  factory _Series.from(dynamic value) {
    if (value is! Map) return const _Series([], [], 0);
    List<double> numbers(dynamic source) => source is List
        ? source.whereType<num>().map((item) => item.toDouble()).toList()
        : const [];
    return _Series(
      numbers(value['mean']),
      numbers(value['sd']),
      (value['cycles'] as num?)?.toInt() ?? 0,
    );
  }
}

class _GaitChartCard extends StatelessWidget {
  const _GaitChartCard({
    required this.title,
    required this.metric,
    required this.leftLabel,
    required this.rightLabel,
  });

  final String title;
  final dynamic metric;
  final String leftLabel;
  final String rightLabel;

  @override
  Widget build(BuildContext context) {
    final left = _Series.from(metric is Map ? metric['left'] : null);
    final right = _Series.from(metric is Map ? metric['right'] : null);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 14, 8),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style:
                  const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
          const SizedBox(height: 3),
          Text(
            'Mean ± SD · ${max(left.cycles, right.cycles)} cặp · 0–100% chu kỳ camera',
            style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: _MeanSdChart(
              left: left,
              right: right,
              yLabel: title.contains('GỐI')
                  ? 'Góc gập khớp gối 2D (°)'
                  : title.contains('HÔNG')
                      ? 'Góc gập khớp hông 2D (°)'
                      : 'Góc nghiêng thân trước–sau (°)',
            ),
          ),
          const SizedBox(height: 5),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _Legend(color: AppColors.leftLeg, label: leftLabel),
              const SizedBox(width: 16),
              _Legend(
                  color: AppColors.rightLeg, label: rightLabel, dashed: true),
            ],
          ),
        ],
      ),
    );
  }
}

class _MeanSdChart extends StatelessWidget {
  const _MeanSdChart({
    required this.left,
    required this.right,
    required this.yLabel,
  });

  final _Series left;
  final _Series right;
  final String yLabel;

  List<FlSpot> spots(List<double> mean, [List<double>? sd, int sign = 0]) =>
      List.generate(mean.length, (index) {
        final spread = sd != null && index < sd.length ? sd[index] : 0.0;
        return FlSpot(index.toDouble(), mean[index] + sign * spread);
      });

  LineChartBarData line(List<double> values, Color color,
          {bool dashed = false}) =>
      LineChartBarData(
        spots: spots(values),
        color: color,
        barWidth: 2.2,
        isCurved: true,
        curveSmoothness: 0.2,
        dashArray: dashed ? const [7, 5] : null,
        dotData: const FlDotData(show: false),
      );

  LineChartBarData bound(_Series series, int sign) => LineChartBarData(
        spots: spots(series.mean, series.sd, sign),
        color: Colors.transparent,
        barWidth: 0,
        dotData: const FlDotData(show: false),
      );

  @override
  Widget build(BuildContext context) {
    if (left.mean.isEmpty && right.mean.isEmpty) {
      return const Center(child: Text('Không đủ chu kỳ trong clip'));
    }
    final bars = [
      bound(left, -1),
      bound(left, 1),
      bound(right, -1),
      bound(right, 1),
      line(left.mean, AppColors.leftLeg),
      line(right.mean, AppColors.rightLeg, dashed: true),
    ];
    return LineChart(
      LineChartData(
        minX: 0,
        maxX: 100,
        lineBarsData: bars,
        betweenBarsData: [
          BetweenBarsData(
              fromIndex: 0,
              toIndex: 1,
              color: AppColors.leftLeg.withValues(alpha: 0.14)),
          BetweenBarsData(
              fromIndex: 2,
              toIndex: 3,
              color: AppColors.rightLeg.withValues(alpha: 0.12)),
        ],
        gridData: FlGridData(
          show: true,
          getDrawingHorizontalLine: (_) => const FlLine(
            color: AppColors.border,
            strokeWidth: 0.7,
            dashArray: [4, 4],
          ),
          getDrawingVerticalLine: (_) => const FlLine(
            color: AppColors.border,
            strokeWidth: 0.7,
            dashArray: [4, 4],
          ),
        ),
        borderData: FlBorderData(
            show: true, border: Border.all(color: AppColors.border)),
        titlesData: FlTitlesData(
          topTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            axisNameWidget: const Text('% chu kỳ camera chuẩn hóa',
                style: TextStyle(fontSize: 8)),
            sideTitles: SideTitles(
              showTitles: true,
              interval: 20,
              reservedSize: 22,
              getTitlesWidget: (value, _) => Text(value.toInt().toString(),
                  style: const TextStyle(fontSize: 8)),
            ),
          ),
          leftTitles: AxisTitles(
            axisNameWidget: Text(yLabel, style: const TextStyle(fontSize: 8)),
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 38,
              getTitlesWidget: (value, _) => Text(value.toStringAsFixed(0),
                  style: const TextStyle(fontSize: 8)),
            ),
          ),
        ),
      ),
      duration: const Duration(milliseconds: 180),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend(
      {required this.color, required this.label, this.dashed = false});

  final Color color;
  final String label;
  final bool dashed;

  @override
  Widget build(BuildContext context) => Row(
        children: [
          SizedBox(
            width: 20,
            child: Row(
              children: List.generate(
                dashed ? 3 : 1,
                (_) => Expanded(
                  child: Container(
                    height: 2,
                    margin: EdgeInsets.symmetric(horizontal: dashed ? 1 : 0),
                    color: color,
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(width: 5),
          Text(label,
              style:
                  const TextStyle(fontSize: 9, color: AppColors.textSecondary)),
        ],
      );
}
