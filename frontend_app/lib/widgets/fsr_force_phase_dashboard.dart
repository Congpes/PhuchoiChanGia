import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Hiển thị lực FSR theo ba pha: chạm gót, pha đứng và đẩy mũi chân.
class FsrForcePhaseDashboard extends StatelessWidget {
  const FsrForcePhaseDashboard({super.key, required this.analysis});

  final Map<String, dynamic> analysis;

  @override
  Widget build(BuildContext context) {
    final regions = analysis['regions'] is Map
        ? Map<String, dynamic>.from(analysis['regions'] as Map)
        : const <String, dynamic>{};
    return _PhaseChartsLayout(
      regions: regions,
      unit: analysis['unit']?.toString() ?? 'N_estimated',
      healthySide: analysis['healthySide']?.toString().toLowerCase(),
    );
  }
}

class _PhaseChartsLayout extends StatelessWidget {
  const _PhaseChartsLayout({
    required this.regions,
    required this.unit,
    required this.healthySide,
  });

  final Map<String, dynamic> regions;
  final String unit;
  final String? healthySide;

  List<double> _curve(String side, String region) {
    final regionData = regions[region];
    final sideData = regionData is Map ? regionData[side] : null;
    final curve = sideData is Map ? sideData['mean'] : null;
    if (curve is! List) return const <double>[];
    return curve
        .whereType<num>()
        .map((value) => value.toDouble())
        .toList(growable: false);
  }

  String _sideLabel(String side) {
    final sideName = side == 'left' ? 'TRÁI' : 'PHẢI';
    if (healthySide != 'left' && healthySide != 'right') {
      return 'CHÂN $sideName';
    }
    return 'CHÂN $sideName · ${healthySide == side ? 'LÀNH' : 'GIẢ'}';
  }

  _FootPhaseChartCard _card(String side) => _FootPhaseChartCard(
        title: _sideLabel(side),
        heel: _curve(side, 'heel'),
        midfoot: _curve(side, 'midfoot'),
        forefoot: _curve(side, 'forefoot'),
        unit: unit,
      );

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        // Khi bảng realtime hẹp, xếp hai chân theo cột để biểu đồ rộng hơn
        // thay vì nén cả trục và chú giải vào cùng một hàng.
        final stacked = constraints.maxWidth < 520;
        if (stacked) {
          return Column(
            children: [
              Expanded(child: _card('left')),
              const SizedBox(height: 8),
              Expanded(child: _card('right')),
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: _card('left')),
            const SizedBox(width: 10),
            Expanded(child: _card('right')),
          ],
        );
      },
    );
  }
}

class _FootPhaseChartCard extends StatelessWidget {
  const _FootPhaseChartCard({
    required this.title,
    required this.heel,
    required this.midfoot,
    required this.forefoot,
    required this.unit,
  });

  final String title;
  final List<double> heel;
  final List<double> midfoot;
  final List<double> forefoot;
  final String unit;

  static const _heelColor = Color(0xFF2563EB);
  static const _midfootColor = Color(0xFF0F9D8A);
  static const _forefootColor = Color(0xFFE07A2D);

  @override
  Widget build(BuildContext context) {
    final hasData =
        heel.isNotEmpty || midfoot.isNotEmpty || forefoot.isNotEmpty;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 2),
          const Text(
            'Lực theo thời gian · 0–100% pha chống đỡ',
            style: TextStyle(fontSize: 9, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 6),
          Expanded(
            child: hasData
                ? _ThreePhaseLineChart(
                    heel: heel,
                    midfoot: midfoot,
                    forefoot: forefoot,
                    unit: unit,
                    heelColor: _heelColor,
                    midfootColor: _midfootColor,
                    forefootColor: _forefootColor,
                  )
                : const Center(
                    child: Text(
                      'Chưa đủ dữ liệu bước FSR',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 11,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ),
          ),
          const SizedBox(height: 6),
          const Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              _PhaseLegend(color: _heelColor, label: 'Gót · chạm đất'),
              _PhaseLegend(color: _midfootColor, label: 'Giữa · pha đứng'),
              _PhaseLegend(color: _forefootColor, label: 'Mũi · đẩy lên'),
            ],
          ),
        ],
      ),
    );
  }
}

class _ThreePhaseLineChart extends StatelessWidget {
  const _ThreePhaseLineChart({
    required this.heel,
    required this.midfoot,
    required this.forefoot,
    required this.unit,
    required this.heelColor,
    required this.midfootColor,
    required this.forefootColor,
  });

  final List<double> heel;
  final List<double> midfoot;
  final List<double> forefoot;
  final String unit;
  final Color heelColor;
  final Color midfootColor;
  final Color forefootColor;

  List<FlSpot> _spots(List<double> values) {
    if (values.length == 1) return [FlSpot(0, values.first)];
    return List.generate(
      values.length,
      (index) => FlSpot(index * 100 / (values.length - 1), values[index]),
    );
  }

  LineChartBarData _line(List<double> values, Color color) => LineChartBarData(
        spots: _spots(values),
        color: color,
        barWidth: 2.5,
        isCurved: true,
        curveSmoothness: 0.2,
        dotData: const FlDotData(show: false),
      );

  @override
  Widget build(BuildContext context) {
    final values = <double>[...heel, ...midfoot, ...forefoot]
        .where((value) => value.isFinite)
        .toList();
    final maxY = values.isEmpty ? 1.0 : max(1.0, values.reduce(max) * 1.15);
    final forceLabel = unit == 'N' ? 'N' : 'N (ước tính)';
    return LineChart(
      LineChartData(
        minX: 0,
        maxX: 100,
        minY: 0,
        maxY: maxY,
        lineBarsData: [
          _line(heel, heelColor),
          _line(midfoot, midfootColor),
          _line(forefoot, forefootColor),
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
              '% pha chống đỡ',
              style: TextStyle(fontSize: 9),
            ),
            sideTitles: SideTitles(
              showTitles: true,
              interval: 25,
              reservedSize: 25,
              getTitlesWidget: (value, _) => Text(
                value.toInt().toString(),
                style: const TextStyle(fontSize: 9),
              ),
            ),
          ),
          leftTitles: AxisTitles(
            axisNameWidget:
                Text(forceLabel, style: const TextStyle(fontSize: 9)),
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 48,
              getTitlesWidget: (value, _) => Text(
                value.toStringAsFixed(0),
                style: const TextStyle(fontSize: 9),
              ),
            ),
          ),
        ),
        lineTouchData: const LineTouchData(enabled: false),
      ),
      duration: const Duration(milliseconds: 180),
    );
  }
}

class _PhaseLegend extends StatelessWidget {
  const _PhaseLegend({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 14, height: 2.5, color: color),
        const SizedBox(width: 5),
        Text(label, style: const TextStyle(fontSize: 9)),
      ],
    );
  }
}
