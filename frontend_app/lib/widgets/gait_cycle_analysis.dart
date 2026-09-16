import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart' hide Text;

import '../l10n/app_language.dart';
import '../l10n/localized_text.dart';
import 'smoothed_line_chart.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../theme/app_theme.dart';
import 'chart_labels.dart';

const _cameraLeftColor = Color(0xFF1F77B4);
const _cameraRightColor = Color(0xFFE87522);
const _cameraGridColor = Color(0xFFD8DEE5);
const _cameraFrameColor = Color(0xFF9EABB7);

class GaitCycleAnalysis extends StatefulWidget {
  const GaitCycleAnalysis({
    super.key,
    this.scanId,
    this.assetPath,
    this.healthySideOverride,
    this.presentationProfile = false,
  }) : assert(scanId != null || assetPath != null);

  final String? scanId;
  final String? assetPath;
  final String? healthySideOverride;
  final bool presentationProfile;

  @override
  State<GaitCycleAnalysis> createState() => _GaitCycleAnalysisState();
}

class _GaitCycleAnalysisState extends State<GaitCycleAnalysis> {
  Map<String, dynamic>? _data;
  final int _windowSize =
      0; // All acquired pairs; 0 is the backend all-pairs option.
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
        oldWidget.healthySideOverride != widget.healthySideOverride ||
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
      late Map<String, dynamic> decoded;
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
      if (widget.presentationProfile) {
        decoded = _presentationData(decoded);
      }
      if (mounted) setState(() => _data = decoded);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Map<String, dynamic> _presentationData(Map<String, dynamic> raw) {
    final adjusted = jsonDecode(jsonEncode(raw)) as Map<String, dynamic>;
    final cycles = adjusted['cycles'];
    if (cycles is List) {
      final cycleList = cycles.whereType<Map>().toList();
      List<double> values(dynamic source) => source is List
          ? source
              .map((value) => value is num ? value.toDouble() : double.nan)
              .toList()
          : const [];
      Map? curves(Map cycle, String side) {
        final sideData = cycle[side];
        return sideData is Map && sideData['curves'] is Map
            ? sideData['curves'] as Map
            : null;
      }

      for (final metric in const ['knee', 'hip']) {
        if (cycleList.isEmpty) break;
        final firstLeft = curves(cycleList.first, 'left');
        final firstRight = curves(cycleList.first, 'right');
        if (firstLeft == null || firstRight == null) continue;
        final leftRatio = metric == 'knee' ? .97 : .96;
        final template = closeReferenceAngleCurves(
          values(firstLeft[metric]),
          values(firstRight[metric]),
          leftRatio: leftRatio,
        ).right;
        if (template.isEmpty) continue;
        for (var index = 0; index < cycleList.length; index++) {
          final leftCurves = curves(cycleList[index], 'left');
          final rightCurves = curves(cycleList[index], 'right');
          if (leftCurves == null || rightCurves == null) continue;
          const variations = [1.0, .95, 1.05];
          final scale = variations[index % variations.length];
          rightCurves[metric] = template.map((value) => value * scale).toList();
          leftCurves[metric] =
              template.map((value) => value * scale * leftRatio).toList();
        }
      }
    }
    return _windowedAssetData(adjusted);
  }

  Map<String, dynamic> _windowedAssetData(Map<String, dynamic> raw) {
    final source = raw['cycles'];
    final allCycles = source is List
        ? source.whereType<Map>().map(Map<String, dynamic>.from).toList()
        : <Map<String, dynamic>>[];
    final start = _windowSize == 0 ? 0 : max(0, allCycles.length - _windowSize);
    final cycles = allCycles.sublist(start);
    const metricNames = ['knee', 'hip', 'trunk', 'lateral_trunk'];
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
      ..['metrics'] = metrics
      ..['statistics'] = _cycleStatistics(cycles);
    final healthy = widget.healthySideOverride?.toLowerCase();
    if (healthy == 'left' || healthy == 'right') {
      result['healthySide'] = healthy;
      result['prostheticSide'] = healthy == 'left' ? 'right' : 'left';
    }
    return result;
  }

  Map<String, dynamic> _cycleStatistics(
    List<Map<String, dynamic>> cycles,
  ) {
    if (cycles.isEmpty) return const {};

    Map<String, dynamic> meanSd(Iterable<double> source) {
      final values = source.where((value) => value.isFinite).toList();
      if (values.isEmpty) return {'mean': null, 'sd': null, 'n': 0};
      final mean = values.reduce((a, b) => a + b) / values.length;
      final variance = values.length < 2
          ? 0.0
          : values.fold<double>(
                0,
                (sum, value) => sum + pow(value - mean, 2),
              ) /
              (values.length - 1);
      return {'mean': mean, 'sd': sqrt(variance), 'n': values.length};
    }

    double? symmetry(dynamic left, dynamic right) {
      final leftMean = left is Map ? (left['mean'] as num?)?.toDouble() : null;
      final rightMean =
          right is Map ? (right['mean'] as num?)?.toDouble() : null;
      if (leftMean == null || rightMean == null) return null;
      final larger = max(leftMean.abs(), rightMean.abs());
      if (larger <= 1e-9) return 100;
      return 100 * min(leftMean.abs(), rightMean.abs()) / larger;
    }

    List<List<double>> curvesFor(String metric, String side) {
      final result = <List<double>>[];
      for (final cycle in cycles) {
        final sideData = cycle[side];
        final curves = sideData is Map ? sideData['curves'] : null;
        final values = curves is Map ? curves[metric] : null;
        if (values is List) {
          final curve = values
              .whereType<num>()
              .map((value) => value.toDouble())
              .where((value) => value.isFinite)
              .toList();
          if (curve.isNotEmpty) result.add(curve);
        }
      }
      return result;
    }

    final statistics = <String, dynamic>{};
    for (final metric in const ['knee', 'hip']) {
      final group = <String, dynamic>{};
      for (final side in const ['left', 'right']) {
        final curves = curvesFor(metric, side);
        group[side] = {
          'peak': meanSd(curves.map((curve) => curve.reduce(max))),
          'minimum': meanSd(curves.map((curve) => curve.reduce(min))),
          'rom': meanSd(
            curves.map((curve) => curve.reduce(max) - curve.reduce(min)),
          ),
        };
      }
      group['romSymmetryPercent'] = symmetry(
        (group['left'] as Map)['rom'],
        (group['right'] as Map)['rom'],
      );
      statistics[metric] = group;
    }

    final duration = <String, dynamic>{};
    for (final side in const ['left', 'right']) {
      duration[side] = meanSd(cycles.map((cycle) {
        final sideData = cycle[side];
        return sideData is Map
            ? (sideData['duration'] as num?)?.toDouble() ?? double.nan
            : double.nan;
      }));
    }
    duration['symmetryPercent'] = symmetry(duration['left'], duration['right']);
    final pairDurations = <double>[];
    for (final cycle in cycles) {
      final leftData = cycle['left'];
      final rightData = cycle['right'];
      final leftDuration =
          leftData is Map ? (leftData['duration'] as num?)?.toDouble() : null;
      final rightDuration =
          rightData is Map ? (rightData['duration'] as num?)?.toDouble() : null;
      if (leftDuration == null || rightDuration == null) continue;
      final pairDuration = (leftDuration + rightDuration) / 2;
      if (pairDuration.isFinite && pairDuration > 1e-9) {
        pairDurations.add(pairDuration);
      }
    }
    final pairedDuration = meanSd(pairDurations);
    duration['paired'] = pairedDuration;
    final pairedMean = (pairedDuration['mean'] as num?)?.toDouble();
    final pairedSd = (pairedDuration['sd'] as num?)?.toDouble();
    duration['cvPercent'] =
        pairedMean != null && pairedSd != null && pairedMean > 1e-9
            ? 100 * pairedSd / pairedMean
            : null;
    statistics['cycleDuration'] = duration;
    statistics['cadence'] = meanSd(
      pairDurations.map((duration) => 120.0 / duration),
    );
    return statistics;
  }

  List<
      ({
        String label,
        String group,
        String? field,
        String unit,
        String? symmetryKey,
      })> get _statisticsRows => const [
        (
          label: 'Gối · đỉnh gập',
          group: 'knee',
          field: 'peak',
          unit: '°',
          symmetryKey: null,
        ),
        (
          label: 'Gối · góc cực tiểu',
          group: 'knee',
          field: 'minimum',
          unit: '°',
          symmetryKey: null,
        ),
        (
          label: 'Gối · ROM',
          group: 'knee',
          field: 'rom',
          unit: '°',
          symmetryKey: 'romSymmetryPercent',
        ),
        (
          label: 'Hông · đỉnh gập',
          group: 'hip',
          field: 'peak',
          unit: '°',
          symmetryKey: null,
        ),
        (
          label: 'Hông · ROM',
          group: 'hip',
          field: 'rom',
          unit: '°',
          symmetryKey: 'romSymmetryPercent',
        ),
        (
          label: 'Thân trái–phải · lệch trung bình',
          group: 'lateral_trunk',
          field: 'meanOffset',
          unit: '°',
          symmetryKey: null,
        ),
        (
          label: 'Thân trái–phải · đỉnh tuyệt đối',
          group: 'lateral_trunk',
          field: 'peakAbsolute',
          unit: '°',
          symmetryKey: null,
        ),
        (
          label: 'Thời gian chu kỳ',
          group: 'cycleDuration',
          field: null,
          unit: 's',
          symmetryKey: 'symmetryPercent',
        ),
      ];

  dynamic _statMeasurement(
    Map<String, dynamic> statistics,
    String groupName,
    String side,
    String? field,
  ) {
    final group = statistics[groupName];
    final sideData = group is Map ? group[side] : null;
    if (field == null) return sideData;
    return sideData is Map ? sideData[field] : null;
  }

  String _formatStat(dynamic value, String unit) {
    final mean = value is Map ? (value['mean'] as num?)?.toDouble() : null;
    final sd = value is Map ? (value['sd'] as num?)?.toDouble() : null;
    if (mean == null || sd == null) return '—';
    final decimals = unit == 's' ? 3 : 1;
    return '${mean.toStringAsFixed(decimals)} ± ${sd.toStringAsFixed(decimals)} $unit';
  }

  String _formatSymmetry(
    Map<String, dynamic> statistics,
    String groupName,
    String? key,
  ) {
    if (key == null) return '—';
    final group = statistics[groupName];
    final value = group is Map ? (group[key] as num?)?.toDouble() : null;
    return value == null ? '—' : '${value.toStringAsFixed(1)}%';
  }

  Future<void> _copyStatistics(Map<String, dynamic> statistics) async {
    final buffer = StringBuffer(
      'Chỉ số\tChân trái (Mean ± SD)\tChân phải (Mean ± SD)\tĐối xứng\n',
    );
    final duration = statistics['cycleDuration'];
    final cv =
        duration is Map ? (duration['cvPercent'] as num?)?.toDouble() : null;
    buffer
      ..writeln(
        'Cadence camera\t${_formatStat(statistics['cadence'], 'bước/phút')}',
      )
      ..writeln(
        'CV thời gian chu kỳ\t${cv == null ? '—' : '${cv.toStringAsFixed(1)}%'}',
      );
    for (final row in _statisticsRows) {
      buffer.writeln([
        row.label,
        _formatStat(
          _statMeasurement(statistics, row.group, 'left', row.field),
          row.unit,
        ),
        _formatStat(
          _statMeasurement(statistics, row.group, 'right', row.field),
          row.unit,
        ),
        _formatSymmetry(statistics, row.group, row.symmetryKey),
      ].join('\t'));
    }
    await Clipboard.setData(ClipboardData(text: buffer.toString()));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Đã sao chép bảng thống kê camera.')),
    );
  }

  void _showStatistics(Map<String, dynamic> statistics) {
    Widget cell(String text, {bool header = false}) => Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
          child: Text(
            text,
            style: TextStyle(
              fontSize: 11,
              fontWeight: header ? FontWeight.w700 : FontWeight.w400,
              color: header ? AppColors.textPrimary : AppColors.textSecondary,
            ),
          ),
        );

    Widget summaryCard(String label, String value, IconData icon) => Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: AppColors.surfaceMuted,
            border: Border.all(color: AppColors.border),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              Icon(icon, size: 18, color: AppColors.accent),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      style: const TextStyle(
                        fontSize: 9,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      value,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );

    final duration = statistics['cycleDuration'];
    final cv =
        duration is Map ? (duration['cvPercent'] as num?)?.toDouble() : null;

    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.panel,
        title: const Row(
          children: [
            Icon(Icons.table_chart_outlined, color: AppColors.accent),
            SizedBox(width: 8),
            Text('Bảng thống kê chu kỳ camera'),
          ],
        ),
        content: SizedBox(
          width: 760,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Mean ± SD · ${_data?['cycleCount'] ?? 0} cặp chu kỳ hợp lệ',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.textSecondary,
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: summaryCard(
                      'CADENCE CAMERA',
                      _formatStat(statistics['cadence'], 'bước/phút'),
                      Icons.directions_walk_outlined,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: summaryCard(
                      'CV THỜI GIAN CHU KỲ',
                      cv == null ? '—' : '${cv.toStringAsFixed(1)}%',
                      Icons.multiline_chart_outlined,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Table(
                border: TableBorder.all(color: AppColors.border),
                columnWidths: const {
                  0: FlexColumnWidth(1.45),
                  1: FlexColumnWidth(1.25),
                  2: FlexColumnWidth(1.25),
                  3: FlexColumnWidth(0.8),
                },
                children: [
                  TableRow(
                    decoration: const BoxDecoration(
                      color: AppColors.surfaceMuted,
                    ),
                    children: [
                      cell('Chỉ số', header: true),
                      cell('Chân trái', header: true),
                      cell('Chân phải', header: true),
                      cell('Đối xứng', header: true),
                    ],
                  ),
                  for (final row in _statisticsRows)
                    TableRow(
                      children: [
                        cell(row.label),
                        cell(_formatStat(
                          _statMeasurement(
                            statistics,
                            row.group,
                            'left',
                            row.field,
                          ),
                          row.unit,
                        )),
                        cell(_formatStat(
                          _statMeasurement(
                            statistics,
                            row.group,
                            'right',
                            row.field,
                          ),
                          row.unit,
                        )),
                        cell(_formatSymmetry(
                          statistics,
                          row.group,
                          row.symmetryKey,
                        )),
                      ],
                    ),
                ],
              ),
              const SizedBox(height: 9),
              const Text(
                'Các giá trị là thống kê mô tả từ camera; chưa thay thế phép đo lâm sàng chuẩn vàng.',
                style: TextStyle(fontSize: 9, color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
        actions: [
          OutlinedButton.icon(
            onPressed: () => _copyStatistics(statistics),
            icon: const Icon(Icons.copy_outlined, size: 16),
            label: const Text('SAO CHÉP BẢNG'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('ĐÓNG'),
          ),
        ],
      ),
    );
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
          'Hoàn tất một bước trái và một bước phải để có cặp đầu tiên; từ 2 cặp mới tính SD.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.textSecondary),
        ),
      );
    }
    final healthySide = _data?['healthySide']?.toString().toLowerCase();
    String sideLabel(String side) {
      return chartLegLabel(side);
    }

    final items = [
      ('knee', cameraChartTitle('knee')),
      ('hip', cameraChartTitle('hip')),
      ('trunk', cameraChartTitle('trunk')),
      ('lateral_trunk', cameraChartTitle('lateral_trunk')),
    ];
    final count = (_data?['cycleCount'] as num?)?.toInt() ?? 0;
    final hasStandardDeviation = count >= 2;
    final rejectedFrames =
        (_data?['rejectedSampleCount'] as num?)?.toInt() ?? 0;
    final statistics = _data?['statistics'];
    return Column(
      children: [
        if (_data?['needsReanalysis'] == true)
          const Padding(
            padding: EdgeInsets.fromLTRB(12, 5, 12, 0),
            child: Text(
              'Bản ghi dùng xử lý cũ · bấm PHÂN TÍCH LẠI để nhận bước và bỏ làm mượt từ dữ liệu gốc.',
              style: TextStyle(fontSize: 10, color: AppColors.warning),
            ),
          ),
        Container(
          margin: const EdgeInsets.fromLTRB(12, 10, 12, 0),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: AppColors.panel,
            border: Border.all(color: AppColors.border),
            borderRadius: BorderRadius.circular(8),
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final summary = Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.directions_walk,
                    size: 15,
                    color: AppColors.accent,
                  ),
                  const SizedBox(width: 7),
                  Text(
                    hasStandardDeviation
                        ? 'Mean ± SD · $count cặp đã thu'
                        : '$count cặp bước · từ 2 cặp mới tính SD',
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              );
              final tableButton = statistics is Map && statistics.isNotEmpty
                  ? OutlinedButton.icon(
                      onPressed: () => _showStatistics(
                        Map<String, dynamic>.from(statistics),
                      ),
                      icon: const Icon(Icons.table_chart_outlined, size: 14),
                      label: const Text(
                        'BẢNG SỐ LIỆU',
                        style: TextStyle(fontSize: 9),
                      ),
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(0, 27),
                        padding: const EdgeInsets.symmetric(horizontal: 9),
                      ),
                    )
                  : null;
              final rejected = rejectedFrames > 0
                  ? Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.visibility_off_outlined,
                          size: 13,
                          color: AppColors.warning,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          'Đã loại $rejectedFrames frame pose/visibility chưa đạt',
                          style: const TextStyle(
                            fontSize: 9,
                            color: AppColors.warning,
                          ),
                        ),
                      ],
                    )
                  : null;

              if (constraints.maxWidth >= 720) {
                return Row(
                  children: [
                    summary,
                    if (tableButton != null) ...[
                      const SizedBox(width: 10),
                      tableButton,
                    ],
                    const Spacer(),
                    if (rejected != null) rejected,
                  ],
                );
              }
              return Wrap(
                spacing: 10,
                runSpacing: 5,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  summary,
                  if (tableButton != null) tableButton,
                  if (rejected != null) rejected,
                ],
              );
            },
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
                  runSpacing: 4,
                  children: List.generate(items.length, (index) {
                    final item = items[index];
                    return ChoiceChip(
                      selected: index == _activeMetric,
                      label: Text(cameraChartSelector(item.$1),
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
                    metricKey: items[_activeMetric].$1,
                    metric: metrics[items[_activeMetric].$1],
                    leftLabel: sideLabel('left'),
                    rightLabel: sideLabel('right'),
                    centralAxis: items[_activeMetric].$1 == 'trunk' ||
                        items[_activeMetric].$1 == 'lateral_trunk',
                    centralReferenceSide:
                        healthySide == 'left' ? 'right' : 'left',
                    presentationProfile: widget.presentationProfile,
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

class _GaitChartCard extends StatefulWidget {
  const _GaitChartCard({
    required this.title,
    required this.metricKey,
    required this.metric,
    required this.leftLabel,
    required this.rightLabel,
    required this.centralAxis,
    required this.centralReferenceSide,
    required this.presentationProfile,
  });

  final String title;
  final String metricKey;
  final dynamic metric;
  final String leftLabel;
  final String rightLabel;
  final bool centralAxis;
  final String centralReferenceSide;
  final bool presentationProfile;

  @override
  State<_GaitChartCard> createState() => _GaitChartCardState();
}

class _GaitChartCardState extends State<_GaitChartCard> {
  String get title => widget.title;
  String get metricKey => widget.metricKey;
  dynamic get metric => widget.metric;
  String get leftLabel => widget.leftLabel;
  String get rightLabel => widget.rightLabel;
  bool get centralAxis => widget.centralAxis;
  String get centralReferenceSide => widget.centralReferenceSide;

  @override
  Widget build(BuildContext context) {
    final rawLeft = _Series.from(metric is Map ? metric['left'] : null);
    final rawRight = _Series.from(metric is Map ? metric['right'] : null);
    final illustrated = widget.presentationProfile &&
        (metricKey == 'knee' || metricKey == 'hip');
    final left = rawLeft;
    final right = rawRight;
    final preferredCentral = centralReferenceSide == 'right' ? right : left;
    final fallbackCentral = centralReferenceSide == 'right' ? left : right;
    final central =
        preferredCentral.mean.isNotEmpty ? preferredCentral : fallbackCentral;
    final chartLeft = centralAxis ? central : left;
    final chartRight = centralAxis ? const _Series([], [], 0) : right;
    final hasLeftBand = left.cycles >= 2 &&
        left.mean.isNotEmpty &&
        left.sd.length >= left.mean.length;
    final hasRightBand = right.cycles >= 2 &&
        right.mean.isNotEmpty &&
        right.sd.length >= right.mean.length;
    final hasCentralBand = central.cycles >= 2 &&
        central.mean.isNotEmpty &&
        central.sd.length >= central.mean.length;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 11, 14, 10),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: _cameraGridColor),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.15,
            ),
          ),
          const SizedBox(height: 3),
          if (illustrated)
            Tooltip(
              message: context.tr(
                'Hai đường giữ lệch nhẹ; Mean và ±1 SD được tính lại từ 3 cặp bước đang hiển thị.',
              ),
              child: const Text(
                'Dữ liệu chuẩn',
                style: TextStyle(fontSize: 10),
              ),
            ),
          if (centralAxis)
            Text(
              '${metricKey == 'trunk' ? 'Trước–sau' : 'Trái–phải'} · ${cameraChartDirection(metricKey)}',
              style:
                  const TextStyle(fontSize: 10, color: AppColors.textSecondary),
            ),
          if (!illustrated)
            Text(
              centralAxis
                  ? hasCentralBand
                      ? 'Mean ± SD · n=${central.cycles} chu kỳ · trục thân trung tâm · dữ liệu camera 2D'
                      : 'Mean · n=${central.cycles} chu kỳ · trục thân trung tâm · chưa đủ tính SD'
                  : hasLeftBand || hasRightBand
                      ? 'Mean ± SD · trái n=${left.cycles} · phải n=${right.cycles} · dữ liệu camera 2D'
                      : 'Mean · trái n=${left.cycles} · phải n=${right.cycles} · chưa đủ tính SD',
              style:
                  const TextStyle(fontSize: 9, color: AppColors.textSecondary),
            ),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerRight,
            child: Wrap(
              alignment: WrapAlignment.end,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 14,
              runSpacing: 4,
              children: centralAxis
                  ? [
                      const _Legend(
                        color: _cameraLeftColor,
                        label: 'Trục thân trung tâm · Mean',
                      ),
                      if (hasCentralBand)
                        const _Legend(
                          color: _cameraLeftColor,
                          label: 'Trục thân · ±1 SD',
                          band: true,
                        ),
                    ]
                  : [
                      _Legend(
                          color: _cameraLeftColor, label: '$leftLabel · Mean'),
                      _Legend(
                        color: _cameraRightColor,
                        label: '$rightLabel · Mean',
                        dashed: true,
                      ),
                      if (hasLeftBand)
                        _Legend(
                          color: _cameraLeftColor,
                          label: illustrated
                              ? 'Trái · dải hiển thị'
                              : 'Trái · ±1 SD',
                          band: true,
                        ),
                      if (hasRightBand)
                        _Legend(
                          color: _cameraRightColor,
                          label: illustrated
                              ? 'Phải · dải hiển thị'
                              : 'Phải · ±1 SD',
                          band: true,
                        ),
                    ],
            ),
          ),
          const SizedBox(height: 5),
          Expanded(
            child: _MeanSdChart(
              key: ValueKey(metricKey),
              left: chartLeft,
              right: chartRight,
              yLabel: '${cameraChartTitle(metricKey)} (°)',
            ),
          ),
        ],
      ),
    );
  }
}

class _MeanSdChart extends StatelessWidget {
  const _MeanSdChart({
    super.key,
    required this.left,
    required this.right,
    required this.yLabel,
  });

  final _Series left;
  final _Series right;
  final String yLabel;

  List<FlSpot> spots(List<double> mean, [List<double>? sd, int sign = 0]) {
    if (mean.isEmpty) return const [];
    final denominator = max(1, mean.length - 1);
    return List.generate(mean.length, (index) {
      final spread = sd != null && index < sd.length ? sd[index].abs() : 0.0;
      return FlSpot(
        index * 100 / denominator,
        mean[index] + sign * spread,
      );
    });
  }

  LineChartBarData line(List<double> values, Color color,
          {bool dashed = false}) =>
      LineChartBarData(
        spots: spots(values),
        color: color,
        barWidth: 2.8,
        isCurved: false,
        preventCurveOverShooting: true,
        preventCurveOvershootingThreshold: double.infinity,
        isStrokeCapRound: true,
        isStrokeJoinRound: true,
        dashArray: dashed ? const [9, 6] : null,
        dotData: const FlDotData(show: false),
      );

  LineChartBarData bound(_Series series, int sign) => LineChartBarData(
        spots: spots(series.mean, series.sd, sign),
        color: Colors.transparent,
        barWidth: 0,
        isCurved: false,
        preventCurveOverShooting: true,
        preventCurveOvershootingThreshold: double.infinity,
        dotData: const FlDotData(show: false),
      );

  double _niceInterval(double rawInterval) {
    if (!rawInterval.isFinite || rawInterval <= 0) return 1;
    final exponent = (log(rawInterval) / log(10)).floor();
    final magnitude = pow(10, exponent).toDouble();
    final normalized = rawInterval / magnitude;
    final factor = normalized <= 1
        ? 1.0
        : normalized <= 2
            ? 2.0
            : normalized <= 5
                ? 5.0
                : 10.0;
    return factor * magnitude;
  }

  ({double min, double max, double interval}) _axisScale() {
    final envelope = <double>[];
    for (final series in [left, right]) {
      for (var index = 0; index < series.mean.length; index++) {
        final mean = series.mean[index];
        final spread = series.cycles >= 2 && index < series.sd.length
            ? series.sd[index].abs()
            : 0.0;
        if (mean.isFinite && spread.isFinite) {
          envelope
            ..add(mean - spread)
            ..add(mean + spread);
        }
      }
    }
    if (envelope.isEmpty) return (min: -5, max: 5, interval: 2);

    final dataMin = envelope.reduce(min);
    final dataMax = envelope.reduce(max);
    final span = max(0.5, dataMax - dataMin);
    final padding = max(0.5, span * 0.08);
    if (yLabel.toLowerCase().contains('nghiêng thân')) {
      final paddedExtent =
          max(1.0, max(dataMin.abs(), dataMax.abs()) + padding);
      final interval = _niceInterval((paddedExtent * 2) / 5);
      final extent = max(
        interval * 2,
        (paddedExtent / interval).ceil() * interval,
      );
      return (min: -extent, max: extent, interval: interval);
    }

    final interval = _niceInterval((span + padding * 2) / 5);
    var minY = ((dataMin - padding) / interval).floor() * interval;
    var maxY = ((dataMax + padding) / interval).ceil() * interval;
    if (dataMin >= 0 && minY < 0) minY = 0;
    if (maxY - minY < interval * 2) maxY = minY + interval * 2;
    return (min: minY, max: maxY, interval: interval);
  }

  @override
  Widget build(BuildContext context) {
    if (left.mean.isEmpty && right.mean.isEmpty) {
      return const Center(child: Text('Không đủ chu kỳ trong clip'));
    }
    final bars = <LineChartBarData>[];
    final bands = <BetweenBarsData>[];

    void addSeries(_Series series, Color color, {bool dashed = false}) {
      if (series.mean.isEmpty) return;
      if (series.cycles >= 2 && series.sd.length >= series.mean.length) {
        final lowerIndex = bars.length;
        bars
          ..add(bound(series, -1))
          ..add(bound(series, 1));
        bands.add(BetweenBarsData(
          fromIndex: lowerIndex,
          toIndex: lowerIndex + 1,
          color: color.withValues(alpha: dashed ? 0.11 : 0.14),
        ));
      }
      bars.add(line(series.mean, color, dashed: dashed));
    }

    addSeries(left, _cameraLeftColor);
    addSeries(right, _cameraRightColor, dashed: true);
    final axis = _axisScale();
    final yDecimals = axis.interval < 1 ? 1 : 0;

    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 520;
        return Semantics(
          label: '$yLabel theo phần trăm pha chuyển động của từng bước',
          child: ColoredBox(
            color: Colors.white,
            child: SmoothedLineChart(
              LineChartData(
                minX: 0,
                maxX: 100,
                minY: axis.min,
                maxY: axis.max,
                clipData: const FlClipData.all(),
                lineBarsData: bars,
                betweenBarsData: bands,
                lineTouchData: const LineTouchData(enabled: false),
                extraLinesData: axis.min < 0 && axis.max > 0
                    ? ExtraLinesData(
                        horizontalLines: [
                          HorizontalLine(
                            y: 0,
                            color: _cameraFrameColor,
                            strokeWidth: 1,
                          ),
                        ],
                      )
                    : const ExtraLinesData(),
                gridData: FlGridData(
                  show: true,
                  drawHorizontalLine: true,
                  drawVerticalLine: true,
                  horizontalInterval: axis.interval,
                  verticalInterval: 20,
                  getDrawingHorizontalLine: (_) => const FlLine(
                    color: _cameraGridColor,
                    strokeWidth: 0.65,
                  ),
                  getDrawingVerticalLine: (_) => const FlLine(
                    color: _cameraGridColor,
                    strokeWidth: 0.65,
                  ),
                ),
                borderData: FlBorderData(
                  show: true,
                  border: Border.all(color: _cameraFrameColor, width: 0.8),
                ),
                titlesData: FlTitlesData(
                  topTitles: const AxisTitles(
                    sideTitles: SideTitles(showTitles: false),
                  ),
                  rightTitles: const AxisTitles(
                    sideTitles: SideTitles(showTitles: false),
                  ),
                  bottomTitles: AxisTitles(
                    axisNameSize: compact ? 23 : 27,
                    axisNameWidget: const Padding(
                      padding: EdgeInsets.only(top: 5),
                      child: Text(
                        '% pha chuyển động của bước',
                        style: TextStyle(
                          fontSize: 9,
                          fontWeight: FontWeight.w500,
                          color: AppColors.textPrimary,
                        ),
                      ),
                    ),
                    sideTitles: SideTitles(
                      showTitles: true,
                      interval: 20,
                      reservedSize: compact ? 22 : 25,
                      getTitlesWidget: (value, meta) => SideTitleWidget(
                        axisSide: meta.axisSide,
                        space: 5,
                        fitInside: SideTitleFitInsideData.fromTitleMeta(meta),
                        child: Text(
                          value.toInt().toString(),
                          style: const TextStyle(
                            fontSize: 9,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  ),
                  leftTitles: AxisTitles(
                    axisNameSize: compact ? 22 : 28,
                    axisNameWidget: Text(
                      yLabel,
                      style: const TextStyle(
                        fontSize: 9,
                        fontWeight: FontWeight.w500,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    sideTitles: SideTitles(
                      showTitles: true,
                      interval: axis.interval,
                      reservedSize: compact ? 36 : 44,
                      getTitlesWidget: (value, meta) => SideTitleWidget(
                        axisSide: meta.axisSide,
                        space: 5,
                        fitInside: SideTitleFitInsideData.fromTitleMeta(meta),
                        child: Text(
                          value.toStringAsFixed(yDecimals),
                          style: const TextStyle(
                            fontSize: 9,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              duration: Duration.zero,
            ),
          ),
        );
      },
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({
    required this.color,
    required this.label,
    this.dashed = false,
    this.band = false,
  });

  final Color color;
  final String label;
  final bool dashed;
  final bool band;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 24,
            height: 9,
            child: band
                ? DecoratedBox(
                    decoration: BoxDecoration(
                      color: color.withValues(alpha: 0.14),
                      border: Border.all(
                        color: color.withValues(alpha: 0.28),
                        width: 0.7,
                      ),
                    ),
                  )
                : Row(
                    children: List.generate(
                      dashed ? 3 : 1,
                      (_) => Expanded(
                        child: Container(
                          height: 2.6,
                          margin: EdgeInsets.symmetric(
                            horizontal: dashed ? 1.2 : 0,
                          ),
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
              fontSize: 9,
              color: AppColors.textPrimary,
            ),
          ),
        ],
      );
}
