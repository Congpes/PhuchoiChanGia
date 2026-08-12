import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../theme/app_theme.dart';

class FsrRegionAnalysis extends StatefulWidget {
  const FsrRegionAnalysis({super.key, required this.scanId});

  final String scanId;

  @override
  State<FsrRegionAnalysis> createState() => _FsrRegionAnalysisState();
}

class _FsrRegionAnalysisState extends State<FsrRegionAnalysis> {
  Map<String, dynamic>? _data;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant FsrRegionAnalysis oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.scanId != widget.scanId) _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await http.get(
        Uri.parse(
          'http://127.0.0.1:8000/scans/${widget.scanId}/fsr-analysis',
        ),
      );
      if (response.statusCode != 200) {
        throw Exception('Backend tr\u1ea3 m\u00e3 ${response.statusCode}');
      }
      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      if (mounted) setState(() => _data = decoded);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Text(
          _error!,
          style: const TextStyle(color: AppColors.critical),
        ),
      );
    }
    final regions = _data?['regions'];
    if (regions is! Map || regions.isEmpty) {
      return const Center(
        child: Text(
          'Clip n\u00e0y ch\u01b0a c\u00f3 d\u1eef li\u1ec7u FSR.\n'
          'H\u00e3y ghi m\u1ed9t phi\u00ean m\u1edbi sau khi k\u1ebft n\u1ed1i t\u1ea5m FSR.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.textSecondary),
        ),
      );
    }

    final items = const [
      ('heel', 'L\u1ef0C V\u00d9NG G\u00d3T - PH\u00c2N T\u00cdCH'),
      (
        'midfoot',
        'L\u1ef0C V\u00d9NG GI\u1eeeA B\u00c0N CH\u00c2N - PH\u00c2N T\u00cdCH'
      ),
      (
        'forefoot',
        'L\u1ef0C V\u00d9NG TR\u01af\u1edaC B\u00c0N CH\u00c2N - PH\u00c2N T\u00cdCH'
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 940 ? 2 : 1;
        return GridView.builder(
          padding: const EdgeInsets.all(12),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
            mainAxisExtent: 300,
          ),
          itemCount: items.length,
          itemBuilder: (_, index) {
            final item = items[index];
            return _RegionChartCard(
              title: item.$2,
              region: regions[item.$1],
              unit: _data?['unit']?.toString() ?? 'raw_adc',
            );
          },
        );
      },
    );
  }
}

class _RegionSeries {
  const _RegionSeries(this.mean, this.sd, this.steps);

  final List<double> mean;
  final List<double> sd;
  final int steps;

  factory _RegionSeries.from(dynamic value) {
    if (value is! Map) return const _RegionSeries([], [], 0);
    List<double> numbers(dynamic source) => source is List
        ? source.whereType<num>().map((item) => item.toDouble()).toList()
        : const [];
    return _RegionSeries(
      numbers(value['mean']),
      numbers(value['sd']),
      (value['steps'] as num?)?.toInt() ?? 0,
    );
  }
}

class _RegionChartCard extends StatelessWidget {
  const _RegionChartCard({
    required this.title,
    required this.region,
    required this.unit,
  });

  final String title;
  final dynamic region;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final left = _RegionSeries.from(region is Map ? region['left'] : null);
    final right = _RegionSeries.from(region is Map ? region['right'] : null);
    final hasData = left.mean.isNotEmpty || right.mean.isNotEmpty;
    return Container(
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
      ),
      padding: const EdgeInsets.fromLTRB(12, 10, 14, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 3),
          Text(
            'Mean \u00b1 SD \u00b7 0\u2013100% pha ch\u1ed1ng \u0111\u1ee1'
            ' \u00b7 ${max(left.steps, right.steps)} b\u01b0\u1edbc',
            style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: hasData
                ? _RegionLineChart(left: left, right: right, unit: unit)
                : const Center(
                    child: Text(
                      'Kh\u00f4ng \u0111\u1ee7 m\u1eabu FSR trong clip',
                      style: TextStyle(
                        fontSize: 10,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ),
          ),
          const SizedBox(height: 5),
          const Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _ChartLegend(
                  color: AppColors.leftLeg, label: 'Ch\u00e2n tr\u00e1i'),
              SizedBox(width: 16),
              _ChartLegend(
                color: AppColors.rightLeg,
                label: 'Ch\u00e2n ph\u1ea3i',
                dashed: true,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RegionLineChart extends StatelessWidget {
  const _RegionLineChart({
    required this.left,
    required this.right,
    required this.unit,
  });

  final _RegionSeries left;
  final _RegionSeries right;
  final String unit;

  List<FlSpot> _spots(List<double> values,
      [List<double>? spread, bool upper = true]) {
    return List.generate(values.length, (index) {
      final delta = spread != null && index < spread.length ? spread[index] : 0;
      final value =
          upper ? values[index] + delta : max(0.0, values[index] - delta);
      return FlSpot(index.toDouble(), value);
    });
  }

  LineChartBarData _bound(List<double> mean, List<double> sd, bool upper) {
    return LineChartBarData(
      spots: _spots(mean, sd, upper),
      color: Colors.transparent,
      barWidth: 0,
      dotData: const FlDotData(show: false),
    );
  }

  LineChartBarData _mean(List<double> values, Color color,
      {bool dashed = false}) {
    return LineChartBarData(
      spots: _spots(values),
      color: color,
      barWidth: 2.2,
      isCurved: true,
      curveSmoothness: 0.22,
      dashArray: dashed ? const [7, 5] : null,
      dotData: const FlDotData(show: false),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bars = <LineChartBarData>[
      _bound(left.mean, left.sd, false),
      _bound(left.mean, left.sd, true),
      _bound(right.mean, right.sd, false),
      _bound(right.mean, right.sd, true),
      _mean(left.mean, AppColors.leftLeg),
      _mean(right.mean, AppColors.rightLeg, dashed: true),
    ];
    return LineChart(
      LineChartData(
        minX: 0,
        maxX: 100,
        minY: 0,
        lineBarsData: bars,
        betweenBarsData: [
          BetweenBarsData(
            fromIndex: 0,
            toIndex: 1,
            color: AppColors.leftLeg.withValues(alpha: 0.14),
          ),
          BetweenBarsData(
            fromIndex: 2,
            toIndex: 3,
            color: AppColors.rightLeg.withValues(alpha: 0.12),
          ),
        ],
        gridData: FlGridData(
          show: true,
          drawVerticalLine: true,
          horizontalInterval: null,
          getDrawingHorizontalLine: (_) =>
              const FlLine(color: AppColors.border, strokeWidth: 0.7),
          getDrawingVerticalLine: (_) =>
              const FlLine(color: AppColors.border, strokeWidth: 0.7),
        ),
        borderData: FlBorderData(
          show: true,
          border: Border.all(color: AppColors.border),
        ),
        titlesData: FlTitlesData(
          topTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            axisNameWidget: const Text(
              '% pha ch\u1ed1ng \u0111\u1ee1',
              style: TextStyle(fontSize: 8),
            ),
            sideTitles: SideTitles(
              showTitles: true,
              interval: 25,
              reservedSize: 22,
              getTitlesWidget: (value, _) => Text(
                value.toInt().toString(),
                style: const TextStyle(fontSize: 8),
              ),
            ),
          ),
          leftTitles: AxisTitles(
            axisNameWidget: Text(unit, style: const TextStyle(fontSize: 8)),
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 42,
              getTitlesWidget: (value, _) => Text(
                value.toStringAsFixed(0),
                style: const TextStyle(fontSize: 8),
              ),
            ),
          ),
        ),
        lineTouchData: const LineTouchData(enabled: true),
      ),
      duration: const Duration(milliseconds: 180),
    );
  }
}

class _ChartLegend extends StatelessWidget {
  const _ChartLegend(
      {required this.color, required this.label, this.dashed = false});

  final Color color;
  final String label;
  final bool dashed;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: 22,
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
        Text(label, style: const TextStyle(fontSize: 9)),
      ],
    );
  }
}
