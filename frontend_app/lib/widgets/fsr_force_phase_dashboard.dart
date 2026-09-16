import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';
import 'smoothed_line_chart.dart';

import '../theme/app_theme.dart';
import 'chart_labels.dart';

const _reportGrid = Color(0xFFD8DEE5);
const _reportFrame = Color(0xFF9EA8B3);

/// Hiển thị lực FSR theo ba pha: chạm gót, pha đứng và đẩy mũi chân.
class FsrForcePhaseDashboard extends StatelessWidget {
  const FsrForcePhaseDashboard({
    super.key,
    required this.analysis,
    this.liveMode = false,
  });

  final Map<String, dynamic> analysis;
  final bool liveMode;

  @override
  Widget build(BuildContext context) {
    final regions = analysis['regions'] is Map
        ? Map<String, dynamic>.from(analysis['regions'] as Map)
        : const <String, dynamic>{};
    final latestPair = analysis['displayMode'] == 'latest_pair';
    final pairCount = (analysis['pairCount'] as num?)?.toInt() ?? 0;
    final excludedPairCount =
        (analysis['qualityExcludedPairCount'] as num?)?.toInt() ?? 0;
    final steadyStateExcludedPairCount =
        (analysis['steadyStateExcludedPairCount'] as num?)?.toInt() ?? 0;
    final acquisitionQuality = analysis['acquisitionQuality'];
    final rejectedBySide = acquisitionQuality is Map
        ? acquisitionQuality['qualityRejectedSteps'] ??
            acquisitionQuality['rejectedSteps']
        : null;
    final rejectedStepCount = rejectedBySide is Map
        ? rejectedBySide.values
            .whereType<num>()
            .fold<int>(0, (sum, value) => sum + value.toInt())
        : 0;
    final unit = analysis['unit']?.toString() ?? 'N_estimated';
    final forceSummary = analysis['forceSummary'] is Map
        ? Map<String, dynamic>.from(analysis['forceSummary'] as Map)
        : const <String, dynamic>{};
    final showQualitySummary = !liveMode &&
        !latestPair &&
        analysis['qualityPolicy']?.toString().isNotEmpty == true;
    final charts = _PhaseChartsLayout(
      regions: regions,
      unit: unit,
      healthySide: analysis['healthySide']?.toString().toLowerCase(),
      liveMode: liveMode,
      latestPair: latestPair,
    );
    final content = <Widget>[
      if (analysis['needsReanalysis'] == true)
        const Padding(
          padding: EdgeInsets.only(bottom: 5),
          child: Text(
            'Bản ghi dùng xử lý cũ · PHÂN TÍCH LẠI để lấy mọi cặp từ dữ liệu gốc.',
            style: TextStyle(fontSize: 10, color: AppColors.warning),
          ),
        ),
      if (showQualitySummary) ...[
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.panel,
            border: Border.all(color: AppColors.border),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              const Icon(
                Icons.verified_outlined,
                size: 15,
                color: AppColors.accentGreen,
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  'QA dữ liệu · $pairCount cặp đạt · '
                  '${[
                    if (excludedPairCount > 0)
                      '$excludedPairCount cặp lỗi đo bị loại',
                    if (rejectedStepCount > 0)
                      '$rejectedStepCount bước lỗi đo bị loại',
                    if (steadyStateExcludedPairCount > 0)
                      '$steadyStateExcludedPairCount cặp chuyển tiếp bị loại',
                    if (excludedPairCount == 0 &&
                        rejectedStepCount == 0 &&
                        steadyStateExcludedPairCount == 0)
                      'không phát hiện lỗi đo',
                  ].join(' · ')}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
      ],
      if (!liveMode &&
          forceSummary['rows'] is List &&
          (forceSummary['rows'] as List).isNotEmpty) ...[
        _ForceComparisonTable(
          summary: forceSummary,
          healthySide: analysis['healthySide']?.toString().toLowerCase(),
          sourceLabel: analysis['displaySourceLabel']?.toString(),
        ),
        const SizedBox(height: 8),
      ],
      Expanded(child: charts),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final body = Column(children: content);
        if (!liveMode && constraints.maxHeight < 560) {
          return SingleChildScrollView(
            child: SizedBox(
              height: 600,
              child: body,
            ),
          );
        }
        return body;
      },
    );
  }
}

class _ForceComparisonTable extends StatelessWidget {
  const _ForceComparisonTable({
    required this.summary,
    required this.healthySide,
    this.sourceLabel,
  });

  final Map<String, dynamic> summary;
  final String? healthySide;
  final String? sourceLabel;

  List<Map<String, dynamic>> get _rows => (summary['rows'] as List? ?? const [])
      .whereType<Map>()
      .map((row) => Map<String, dynamic>.from(row))
      .toList(growable: false);

  String _sideHeader(String side) {
    return chartLegLabel(side);
  }

  String _displayUnit(String unit) => displayForceUnit(unit);

  String _meanSd(dynamic source) {
    if (source is! Map) return '—';
    final mean = (source['mean'] as num?)?.toDouble();
    final sd = (source['sd'] as num?)?.toDouble();
    final n = (source['n'] as num?)?.toInt() ?? 0;
    if (mean == null || !mean.isFinite || n == 0) return '—';
    final spread = sd != null && sd.isFinite ? sd : 0.0;
    return '${mean.toStringAsFixed(1)} ± ${spread.toStringAsFixed(1)}';
  }

  Widget _cell(
    String text, {
    int flex = 2,
    Alignment alignment = Alignment.center,
    FontWeight weight = FontWeight.w500,
    Color? color,
  }) {
    return Expanded(
      flex: flex,
      child: Align(
        alignment: alignment,
        child: Text(
          text,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 9.5,
            fontWeight: weight,
            color: color ?? AppColors.textPrimary,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final pairCount = (summary['pairCount'] as num?)?.toInt() ?? 0;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 7),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              const Icon(
                Icons.balance_outlined,
                size: 15,
                color: AppColors.accent,
              ),
              const SizedBox(width: 7),
              const Text(
                'BẢNG SO SÁNH LỰC FSR TRÁI–PHẢI',
                style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700),
              ),
              const Spacer(),
              Text(
                '${sourceLabel == null ? '' : '$sourceLabel · '}'
                'Mean ± SD · $pairCount cặp bước · FSI 100% = cân bằng',
                style: const TextStyle(
                  fontSize: 9,
                  color: AppColors.textSecondary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Container(
            height: 24,
            padding: const EdgeInsets.symmetric(horizontal: 7),
            decoration: BoxDecoration(
              color: AppColors.background,
              borderRadius: BorderRadius.circular(5),
            ),
            child: Row(
              children: [
                _cell(
                  'CHỈ SỐ',
                  flex: 4,
                  alignment: Alignment.centerLeft,
                  weight: FontWeight.w700,
                ),
                _cell(_sideHeader('left'), weight: FontWeight.w700),
                _cell(_sideHeader('right'), weight: FontWeight.w700),
                _cell('FSI', flex: 1, weight: FontWeight.w700),
                _cell('CHÊNH', flex: 1, weight: FontWeight.w700),
              ],
            ),
          ),
          for (var index = 0; index < _rows.length; index++) ...[
            SizedBox(
              height: 25,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 7),
                child: Row(
                  children: [
                    _cell(
                      '${_rows[index]['label']} '
                      '(${_displayUnit(_rows[index]['unit']?.toString() ?? 'N')})',
                      flex: 4,
                      alignment: Alignment.centerLeft,
                      weight: FontWeight.w600,
                    ),
                    _cell(_meanSd(_rows[index]['left'])),
                    _cell(_meanSd(_rows[index]['right'])),
                    _cell(
                      (_rows[index]['fsi'] as num?)?.toDouble().isFinite == true
                          ? '${(_rows[index]['fsi'] as num).toDouble().toStringAsFixed(1)}%'
                          : '—',
                      flex: 1,
                      weight: FontWeight.w700,
                      color: AppColors.accent,
                    ),
                    _cell(
                      (_rows[index]['asymmetry'] as num?)
                                  ?.toDouble()
                                  .isFinite ==
                              true
                          ? '${(_rows[index]['asymmetry'] as num).toDouble().toStringAsFixed(1)}%'
                          : '—',
                      flex: 1,
                    ),
                  ],
                ),
              ),
            ),
            if (index < _rows.length - 1)
              const Divider(height: 1, color: AppColors.border),
          ],
        ],
      ),
    );
  }
}

class _PhaseChartsLayout extends StatelessWidget {
  const _PhaseChartsLayout({
    required this.regions,
    required this.unit,
    required this.healthySide,
    required this.liveMode,
    required this.latestPair,
  });

  final Map<String, dynamic> regions;
  final String unit;
  final String? healthySide;
  final bool liveMode;
  final bool latestPair;

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

  List<double> _spread(String side, String region) {
    final regionData = regions[region];
    final sideData = regionData is Map ? regionData[side] : null;
    final spread = sideData is Map ? sideData['sd'] : null;
    if (spread is! List) return const <double>[];
    return spread
        .whereType<num>()
        .map((value) => value.toDouble().abs())
        .toList(growable: false);
  }

  String _sideLabel(String side) {
    return chartLegLabel(side);
  }

  double _rawFootPeak(String side) {
    final values = <double>[
      for (final region in const ['heel', 'midfoot', 'forefoot'])
        ..._curve(side, region),
    ].where((value) => value.isFinite && value >= 0).toList();
    return values.isEmpty ? 0 : values.reduce(max);
  }

  double get _sharedMaxY {
    final values = <double>[];
    for (final side in const ['left', 'right']) {
      for (final region in const ['heel', 'midfoot', 'forefoot']) {
        final mean = _curve(side, region);
        final sd = _spread(side, region);
        for (var index = 0; index < mean.length; index++) {
          final upper = mean[index] + (index < sd.length ? sd[index] : 0);
          if (upper.isFinite && upper >= 0) values.add(upper);
        }
      }
    }
    final peak = values.isEmpty ? 0.0 : values.reduce(max);
    if (!peak.isFinite || peak <= 0) return 10;
    if (unit == 'N_demo60') {
      return 350.0;
    }
    return max(10.0, (peak * 1.10 / 10).ceil() * 10.0);
  }

  _FootPhaseChartCard _card(String side) => _FootPhaseChartCard(
        title: _sideLabel(side),
        heel: _curve(side, 'heel'),
        heelSd: _spread(side, 'heel'),
        midfoot: _curve(side, 'midfoot'),
        midfootSd: _spread(side, 'midfoot'),
        forefoot: _curve(side, 'forefoot'),
        forefootSd: _spread(side, 'forefoot'),
        unit: unit,
        liveMode: liveMode,
        latestPair: latestPair,
        maxY: _sharedMaxY,
        rawPeak: _rawFootPeak(side),
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
    required this.heelSd,
    required this.midfoot,
    required this.midfootSd,
    required this.forefoot,
    required this.forefootSd,
    required this.unit,
    required this.liveMode,
    required this.latestPair,
    required this.maxY,
    required this.rawPeak,
  });

  final String title;
  final List<double> heel;
  final List<double> heelSd;
  final List<double> midfoot;
  final List<double> midfootSd;
  final List<double> forefoot;
  final List<double> forefootSd;
  final String unit;
  final bool liveMode;
  final bool latestPair;
  final double maxY;
  final double rawPeak;

  static const _heelColor = Color(0xFF2563EB);
  static const _midfootColor = Color(0xFF0F9D8A);
  static const _forefootColor = Color(0xFFE07A2D);

  @override
  Widget build(BuildContext context) {
    final hasData =
        heel.isNotEmpty || midfoot.isNotEmpty || forefoot.isNotEmpty;
    final hasSd = [heelSd, midfootSd, forefootSd]
        .expand((values) => values)
        .any((value) => value.isFinite && value > 0);
    final summaryLabel = liveMode
        ? 'Khoảng 1–2 nhịp gần nhất'
        : latestPair
            ? 'Cặp bước gần nhất'
            : hasSd
                ? 'Mean ± SD theo cặp bước'
                : 'Mean theo cặp bước';
    return Container(
      padding: const EdgeInsets.fromLTRB(15, 12, 15, 10),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border, width: 0.8),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.15,
              ),
            ),
          ),
          const SizedBox(height: 4),
          Center(
            child: Text(
              '$summaryLabel'
              '${rawPeak > 0 ? ' · đỉnh Mean ${rawPeak.toStringAsFixed(1)} ${displayForceUnit(unit)}' : ''}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 10,
                color: AppColors.textSecondary,
              ),
            ),
          ),
          const SizedBox(height: 7),
          Align(
            alignment: Alignment.centerRight,
            child: Wrap(
              spacing: 12,
              runSpacing: 4,
              alignment: WrapAlignment.end,
              children: [
                const _PhaseLegend(color: _heelColor, label: 'Gót'),
                const _PhaseLegend(color: _midfootColor, label: 'Giữa'),
                const _PhaseLegend(color: _forefootColor, label: 'Trước'),
                if (hasSd) const _PhaseBandLegend(),
              ],
            ),
          ),
          const SizedBox(height: 7),
          Expanded(
            child: hasData
                ? _ThreePhaseLineChart(
                    heel: heel,
                    heelSd: heelSd,
                    midfoot: midfoot,
                    midfootSd: midfootSd,
                    forefoot: forefoot,
                    forefootSd: forefootSd,
                    heelColor: _heelColor,
                    midfootColor: _midfootColor,
                    forefootColor: _forefootColor,
                    liveMode: liveMode,
                    maxY: maxY,
                    unit: unit,
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
        ],
      ),
    );
  }
}

class _ThreePhaseLineChart extends StatelessWidget {
  const _ThreePhaseLineChart({
    required this.heel,
    required this.heelSd,
    required this.midfoot,
    required this.midfootSd,
    required this.forefoot,
    required this.forefootSd,
    required this.heelColor,
    required this.midfootColor,
    required this.forefootColor,
    required this.liveMode,
    required this.maxY,
    required this.unit,
  });

  final List<double> heel;
  final List<double> heelSd;
  final List<double> midfoot;
  final List<double> midfootSd;
  final List<double> forefoot;
  final List<double> forefootSd;
  final Color heelColor;
  final Color midfootColor;
  final Color forefootColor;
  final bool liveMode;
  final double maxY;
  final String unit;

  double get _maxX {
    final count = max(heel.length, max(midfoot.length, forefoot.length));
    if (!liveMode) return 100;
    return max(1.0, (count - 1) * 0.2);
  }

  List<FlSpot> _spots(List<double> values) {
    if (values.length == 1) return [FlSpot(0, values.first)];
    return List.generate(
      values.length,
      (index) => FlSpot(
        liveMode ? index * 0.2 : index * 100 / (values.length - 1),
        values[index],
      ),
    );
  }

  LineChartBarData _line(List<double> values, Color color) => LineChartBarData(
        spots: _spots(values),
        color: color,
        barWidth: 2.8,
        isCurved: false,
        preventCurveOverShooting: true,
        isStrokeCapRound: true,
        isStrokeJoinRound: true,
        dotData: const FlDotData(show: false),
      );

  LineChartBarData _bound(
    List<double> mean,
    List<double> sd,
    int sign,
    Color color,
  ) =>
      LineChartBarData(
        spots: List.generate(mean.length, (index) {
          final spread = index < sd.length ? sd[index].abs() : 0.0;
          return FlSpot(
            liveMode ? index * 0.2 : index * 100 / (mean.length - 1),
            max(0.0, mean[index] + sign * spread),
          );
        }),
        color: color.withValues(alpha: 0.68),
        barWidth: 1.0,
        isCurved: false,
        preventCurveOverShooting: true,
        dotData: const FlDotData(show: false),
      );

  @override
  Widget build(BuildContext context) {
    final bars = <LineChartBarData>[];
    final bands = <BetweenBarsData>[];
    void addBand(List<double> mean, List<double> sd, Color color) {
      if (mean.length < 2 ||
          sd.length < mean.length ||
          !sd.any((value) => value.isFinite && value > 0)) {
        return;
      }
      final lower = bars.length;
      bars
        ..add(_bound(mean, sd, -1, color))
        ..add(_bound(mean, sd, 1, color));
      bands.add(BetweenBarsData(
        fromIndex: lower,
        toIndex: lower + 1,
        color: color.withValues(alpha: 0.52),
      ));
    }

    addBand(heel, heelSd, heelColor);
    addBand(midfoot, midfootSd, midfootColor);
    addBand(forefoot, forefootSd, forefootColor);
    if (heel.isNotEmpty) bars.add(_line(heel, heelColor));
    if (midfoot.isNotEmpty) bars.add(_line(midfoot, midfootColor));
    if (forefoot.isNotEmpty) bars.add(_line(forefoot, forefootColor));
    return SmoothedLineChart(
      preserveValues: unit == 'N_demo60',
      LineChartData(
        minX: 0,
        maxX: _maxX,
        minY: 0,
        maxY: maxY,
        lineBarsData: bars,
        betweenBarsData: bands,
        gridData: FlGridData(
          show: true,
          drawVerticalLine: true,
          horizontalInterval: max(1.0, maxY / 5),
          verticalInterval: liveMode ? max(1.0, _maxX / 4) : 20,
          getDrawingHorizontalLine: (_) => const FlLine(
            color: _reportGrid,
            strokeWidth: 0.65,
          ),
          getDrawingVerticalLine: (_) => const FlLine(
            color: _reportGrid,
            strokeWidth: 0.65,
          ),
        ),
        borderData: FlBorderData(
          show: true,
          border: Border.all(color: _reportFrame, width: 0.8),
        ),
        titlesData: FlTitlesData(
          topTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            axisNameWidget: Text(
              liveMode ? 'Thời gian trực tiếp (s)' : 'Pha chống đỡ (%)',
              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w500),
            ),
            sideTitles: SideTitles(
              showTitles: true,
              interval: liveMode ? max(1.0, _maxX / 4) : 25,
              reservedSize: 29,
              getTitlesWidget: (value, _) => Text(
                liveMode ? value.toStringAsFixed(1) : value.toInt().toString(),
                style: const TextStyle(
                  fontSize: 10,
                  color: AppColors.textSecondary,
                ),
              ),
            ),
          ),
          leftTitles: AxisTitles(
            axisNameWidget: Text(
              'Lực (${displayForceUnit(unit)})',
              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w500),
            ),
            sideTitles: SideTitles(
              showTitles: true,
              interval: max(1.0, maxY / 5),
              reservedSize: 54,
              getTitlesWidget: (value, _) => Text(
                value.toStringAsFixed(0),
                style: const TextStyle(
                  fontSize: 10,
                  color: AppColors.textSecondary,
                ),
              ),
            ),
          ),
        ),
        lineTouchData: const LineTouchData(enabled: false),
      ),
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
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
        Container(width: 16, height: 2.5, color: color),
        const SizedBox(width: 5),
        Text(
          label,
          style: const TextStyle(
            fontSize: 10,
            color: AppColors.textPrimary,
          ),
        ),
      ],
    );
  }
}

class _PhaseBandLegend extends StatelessWidget {
  const _PhaseBandLegend();

  @override
  Widget build(BuildContext context) {
    return const Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(
            color: Color(0x703B82F6),
            border: Border.fromBorderSide(
              BorderSide(color: Color(0xB02563EB), width: 0.8),
            ),
          ),
          child: SizedBox(width: 14, height: 8),
        ),
        SizedBox(width: 5),
        Text(
          '+-SD',
          style: TextStyle(fontSize: 10, color: AppColors.textPrimary),
        ),
      ],
    );
  }
}
