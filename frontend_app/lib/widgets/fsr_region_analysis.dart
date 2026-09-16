import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';
import 'smoothed_line_chart.dart';
import 'package:http/http.dart' as http;

import '../theme/app_theme.dart';
import 'chart_labels.dart';

const _reportRightLine = Color(0xFFE07A2D);
const _reportGrid = Color(0xFFD8DEE5);
const _reportFrame = Color(0xFF9EA8B3);

class FsrRegionAnalysis extends StatefulWidget {
  const FsrRegionAnalysis({
    super.key,
    required this.scanId,
    this.presentationProfile = false,
  });

  final String scanId;
  final bool presentationProfile;

  @override
  State<FsrRegionAnalysis> createState() => _FsrRegionAnalysisState();
}

class _FsrRegionAnalysisState extends State<FsrRegionAnalysis> {
  Map<String, dynamic>? _data;
  final int _windowSize = 0;
  int _activeRegion = 0;
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
    if (oldWidget.scanId != widget.scanId ||
        oldWidget.presentationProfile != widget.presentationProfile) {
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await http.get(
        Uri.parse(
          'http://127.0.0.1:8000/scans/${widget.scanId}/fsr-analysis?window=$_windowSize&demo60=${widget.presentationProfile}',
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

    const items = [
      ('heel', 'Lực gót'),
      ('midfoot', 'Lực giữa bàn chân'),
      ('forefoot', 'Lực trước bàn chân'),
    ];
    String sideLabel(String side) {
      return chartLegLabel(side);
    }

    final pairCount = (_data?['pairCount'] as num?)?.toInt() ?? 0;
    final qualityExcludedPairCount =
        (_data?['qualityExcludedPairCount'] as num?)?.toInt() ?? 0;
    final steadyStateExcludedPairCount =
        (_data?['steadyStateExcludedPairCount'] as num?)?.toInt() ?? 0;
    final acquisitionQuality = _data?['acquisitionQuality'];
    final rejectedBySide = acquisitionQuality is Map
        ? acquisitionQuality['qualityRejectedSteps'] ??
            acquisitionQuality['rejectedSteps']
        : null;
    final qualityRejectedStepCount = rejectedBySide is Map
        ? rejectedBySide.values
            .whereType<num>()
            .fold<int>(0, (sum, value) => sum + value.toInt())
        : 0;
    final hasStandardDeviation = pairCount >= 2;
    final qualitySuffix = [
      if (qualityExcludedPairCount > 0)
        'loại $qualityExcludedPairCount cặp lỗi đo',
      if (qualityRejectedStepCount > 0)
        'loại $qualityRejectedStepCount bước lỗi đo',
      if (steadyStateExcludedPairCount > 0)
        'loại $steadyStateExcludedPairCount cặp chuyển tiếp',
    ];
    final qualitySummary =
        qualitySuffix.isEmpty ? '' : ' · ${qualitySuffix.join(' · ')}';
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
              const Icon(Icons.analytics_outlined,
                  size: 15, color: AppColors.accent),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  widget.presentationProfile
                      ? 'Dữ liệu minh họa · 60 kg · hai chân lành · Mean ± SD'
                      : hasStandardDeviation
                          ? 'Mean ± SD · $pairCount cặp đạt QA$qualitySummary'
                          : '$pairCount cặp đạt QA · cần ít nhất 2 cặp để tính SD'
                              '$qualitySummary',
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
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('VÙNG BÀN CHÂN',
                    style:
                        TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                const SizedBox(height: 5),
                Wrap(
                  spacing: 7,
                  runSpacing: 5,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: List.generate(items.length, (index) {
                    const labels = ['GÓT', 'GIỮA BÀN CHÂN', 'TRƯỚC BÀN CHÂN'];
                    return ChoiceChip(
                      selected: index == _activeRegion,
                      label: Text(
                        labels[index],
                        style: const TextStyle(fontSize: 9),
                      ),
                      visualDensity: VisualDensity.compact,
                      onSelected: (_) => setState(() => _activeRegion = index),
                    );
                  }),
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: _RegionChartCard(
                    title: items[_activeRegion].$2,
                    region: regions[items[_activeRegion].$1],
                    unit: _data?['unit']?.toString() ?? 'relative_load',
                    leftLabel: sideLabel('left'),
                    rightLabel: sideLabel('right'),
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

  double get peak {
    final values = mean.where((value) => value.isFinite && value >= 0).toList();
    return values.isEmpty ? 0 : values.reduce(max);
  }
}

class _RegionChartCard extends StatelessWidget {
  const _RegionChartCard({
    required this.title,
    required this.region,
    required this.unit,
    required this.leftLabel,
    required this.rightLabel,
  });

  final String title;
  final dynamic region;
  final String unit;
  final String leftLabel;
  final String rightLabel;

  @override
  Widget build(BuildContext context) {
    final left = _RegionSeries.from(region is Map ? region['left'] : null);
    final right = _RegionSeries.from(region is Map ? region['right'] : null);
    final strongerPeak = max(left.peak, right.peak);
    final hasBothSides = left.peak > 0 && right.peak > 0;
    final rawSymmetry = !hasBothSides || strongerPeak <= 0
        ? 0.0
        : 100 * min(left.peak, right.peak) / strongerPeak;
    final pairCount = left.steps > 0 && right.steps > 0
        ? min(left.steps, right.steps)
        : max(left.steps, right.steps);
    final hasSd = left.steps >= 2 || right.steps >= 2;
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
          Center(
            child: Text(
              title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
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
              '${hasSd ? 'Mean ± SD' : 'Mean'} · n=$pairCount cặp song phương · '
              '${hasBothSides ? 'đối xứng đỉnh ${rawSymmetry.toStringAsFixed(1)}% · ' : ''}'
              'đỉnh T ${left.peak.toStringAsFixed(1)} / '
              'P ${right.peak.toStringAsFixed(1)} '
              '${displayForceUnit(unit)}',
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
              spacing: 14,
              runSpacing: 4,
              alignment: WrapAlignment.end,
              children: [
                _ChartLegend(
                  color: AppColors.leftLeg,
                  label: '$leftLabel · Mean',
                ),
                _ChartLegend(
                  color: _reportRightLine,
                  label: '$rightLabel · Mean',
                  dashed: true,
                ),
                if (hasSd) const _BandLegend(),
              ],
            ),
          ),
          const SizedBox(height: 7),
          Expanded(
            child: hasData
                ? _RegionLineChart(
                    left: left,
                    right: right,
                    unit: unit,
                  )
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

  LineChartBarData _bound(
    List<double> mean,
    List<double> sd,
    bool upper,
    Color color,
  ) {
    return LineChartBarData(
      spots: _spots(mean, sd, upper),
      color: color.withValues(alpha: 0.68),
      barWidth: 1.0,
      isCurved: false,
      preventCurveOverShooting: true,
      dotData: const FlDotData(show: false),
    );
  }

  LineChartBarData _mean(List<double> values, Color color,
      {bool dashed = false}) {
    return LineChartBarData(
      spots: _spots(values),
      color: color,
      barWidth: 2.4,
      isCurved: false,
      preventCurveOverShooting: true,
      isStrokeCapRound: true,
      isStrokeJoinRound: true,
      dashArray: dashed ? const [8, 5] : null,
      dotData: const FlDotData(show: false),
    );
  }

  @override
  Widget build(BuildContext context) {
    final envelope = <double>[
      for (final series in [left, right])
        for (var index = 0; index < series.mean.length; index++)
          series.mean[index] +
              (series.steps >= 2 && index < series.sd.length
                  ? series.sd[index].abs()
                  : 0),
    ].where((value) => value.isFinite && value >= 0).toList();
    final peak = envelope.isEmpty ? 0.0 : envelope.reduce(max);
    final maxY = unit == 'N_demo60'
        ? 350.0
        : max(10.0, (peak * 1.08 / 10).ceil() * 10.0);
    final bars = <LineChartBarData>[];
    final bands = <BetweenBarsData>[];
    void addSeries(
      _RegionSeries series,
      Color color, {
      bool dashed = false,
    }) {
      if (series.mean.isEmpty) return;
      if (series.steps >= 2 && series.sd.length >= series.mean.length) {
        final lowerIndex = bars.length;
        bars
          ..add(_bound(series.mean, series.sd, false, color))
          ..add(_bound(series.mean, series.sd, true, color));
        bands.add(BetweenBarsData(
          fromIndex: lowerIndex,
          toIndex: lowerIndex + 1,
          color: color.withValues(alpha: 0.52),
        ));
      }
      bars.add(_mean(series.mean, color, dashed: dashed));
    }

    addSeries(left, AppColors.leftLeg);
    addSeries(right, _reportRightLine, dashed: true);
    return SmoothedLineChart(
      preserveValues: unit == 'N_demo60',
      LineChartData(
        minX: 0,
        maxX: 100,
        minY: 0,
        maxY: maxY,
        lineBarsData: bars,
        betweenBarsData: bands,
        gridData: FlGridData(
          show: true,
          drawVerticalLine: true,
          horizontalInterval: max(1.0, maxY / 5),
          verticalInterval: 20,
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
            axisNameWidget: const Text(
              'Pha chống đỡ (%)',
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.w500),
            ),
            sideTitles: SideTitles(
              showTitles: true,
              interval: 20,
              reservedSize: 29,
              getTitlesWidget: (value, _) => Text(
                value.toInt().toString(),
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
      duration: Duration.zero,
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

class _BandLegend extends StatelessWidget {
  const _BandLegend();

  @override
  Widget build(BuildContext context) {
    return const Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(color: Color(0x1F175CD3)),
          child: SizedBox(width: 14, height: 8),
        ),
        SizedBox(width: 5),
        Text(
          'Dải mờ · ±1 SD',
          style: TextStyle(fontSize: 10, color: AppColors.textPrimary),
        ),
      ],
    );
  }
}
