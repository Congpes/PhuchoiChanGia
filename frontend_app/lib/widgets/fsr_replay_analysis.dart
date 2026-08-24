import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../theme/app_theme.dart';
import 'foot_pressure_map.dart';

class FsrReplayAnalysis extends StatefulWidget {
  const FsrReplayAnalysis({
    super.key,
    required this.scanId,
    required this.position,
  });

  final String scanId;
  final double position;

  @override
  State<FsrReplayAnalysis> createState() => _FsrReplayAnalysisState();
}

class _FsrReplayAnalysisState extends State<FsrReplayAnalysis> {
  List<_ReplayFrame> _frames = const [];
  String _unit = 'N_estimated';
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant FsrReplayAnalysis oldWidget) {
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
            'http://127.0.0.1:8000/scans/${widget.scanId}/fsr-analysis?window=7'),
      );
      if (response.statusCode != 200) {
        throw Exception('Backend trả mã ${response.statusCode}');
      }
      final data = jsonDecode(response.body);
      if (data is! Map<String, dynamic>) {
        throw Exception('Dữ liệu FSR không đúng định dạng');
      }
      final frames = (data['replayFrames'] as List?)
              ?.map(_ReplayFrame.fromJson)
              .whereType<_ReplayFrame>()
              .toList() ??
          const <_ReplayFrame>[];
      if (mounted) {
        setState(() {
          _frames = frames;
          _unit = data['unit']?.toString() ?? 'N_estimated';
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  _ReplayFrame? _frameAt(String side) {
    final candidates = _frames.where((frame) => frame.side == side).toList();
    if (candidates.isEmpty) return null;
    candidates.sort((a, b) => (a.time - widget.position)
        .abs()
        .compareTo((b.time - widget.position).abs()));
    return candidates.first;
  }

  List<_ReplayFrame> _window(String side) {
    const duration = 4.0;
    final start = max(0.0, widget.position - duration);
    return _frames
        .where((frame) =>
            frame.side == side &&
            frame.time >= start &&
            frame.time <= widget.position + 0.08)
        .toList()
      ..sort((a, b) => a.time.compareTo(b.time));
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Text(
          _error!,
          style: const TextStyle(color: AppColors.critical),
          textAlign: TextAlign.center,
        ),
      );
    }
    if (_frames.isEmpty) return const _ReplayEmptyState();

    final left = _frameAt('left');
    final right = _frameAt('right');
    final sharedMax = max(
      1.0,
      <double>[
        ...left?.forceValues.expand((row) => row) ?? const [],
        ...right?.forceValues.expand((row) => row) ?? const []
      ].fold(0.0, max),
    );
    final forceUnit = _unit == 'N' ? 'N' : 'N (ước tính)';
    final leftWindow = _window('left');
    final rightWindow = _window('right');

    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 16),
      children: [
        _ReplayHeader(position: widget.position, unit: forceUnit),
        const SizedBox(height: 10),
        _InstantForceSummary(left: left, right: right, unit: forceUnit),
        const SizedBox(height: 10),
        _PressureReplayCard(
          left: left,
          right: right,
          scaleMax: sharedMax,
          unit: forceUnit,
        ),
        const SizedBox(height: 12),
        const Text(
          'TOÀN BỘ THÔNG SỐ LỰC TỨC THỜI',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
        ),
        const Text(
          'Mỗi biểu đồ là dữ liệu thô theo thời gian video, không phải Mean ± SD hay chu kỳ đã gộp.',
          style: TextStyle(fontSize: 9, color: AppColors.textSecondary),
        ),
        const SizedBox(height: 6),
        LayoutBuilder(
          builder: (context, constraints) {
            final charts = [
              _ReplayMetricChart(
                title: 'TỔNG LỰC HAI CHÂN',
                metric: 'total',
                leftFrames: leftWindow,
                rightFrames: rightWindow,
                position: widget.position,
                unit: forceUnit,
              ),
              _ReplayMetricChart(
                title: 'LỰC VÙNG GÓT',
                metric: 'heel',
                leftFrames: leftWindow,
                rightFrames: rightWindow,
                position: widget.position,
                unit: forceUnit,
              ),
              _ReplayMetricChart(
                title: 'LỰC VÙNG GIỮA BÀN CHÂN',
                metric: 'midfoot',
                leftFrames: leftWindow,
                rightFrames: rightWindow,
                position: widget.position,
                unit: forceUnit,
              ),
              _ReplayMetricChart(
                title: 'LỰC VÙNG TRƯỚC BÀN CHÂN',
                metric: 'forefoot',
                leftFrames: leftWindow,
                rightFrames: rightWindow,
                position: widget.position,
                unit: forceUnit,
              ),
            ];
            if (constraints.maxWidth < 760) {
              return Column(
                children: [
                  for (var index = 0; index < charts.length; index++) ...[
                    SizedBox(height: 230, child: charts[index]),
                    if (index < charts.length - 1) const SizedBox(height: 10),
                  ],
                ],
              );
            }
            return Column(
              children: [
                for (var row = 0; row < 2; row++) ...[
                  SizedBox(
                    height: 230,
                    child: Row(
                      children: [
                        Expanded(child: charts[row * 2]),
                        const SizedBox(width: 10),
                        Expanded(child: charts[row * 2 + 1]),
                      ],
                    ),
                  ),
                  if (row == 0) const SizedBox(height: 10),
                ],
              ],
            );
          },
        ),
      ],
    );
  }
}

class _ReplayFrame {
  const _ReplayFrame({
    required this.time,
    required this.side,
    required this.regions,
    required this.forceValues,
  });

  final double time;
  final String side;
  final Map<String, double> regions;
  final List<List<double>> forceValues;

  static _ReplayFrame? fromJson(dynamic value) {
    if (value is! Map) return null;
    final time = value['time'];
    final side = value['side']?.toString().toLowerCase();
    if (time is! num || (side != 'left' && side != 'right')) return null;
    final sourceRegions = value['regions'];
    final regions = <String, double>{
      for (final name in const ['heel', 'midfoot', 'forefoot', 'total'])
        name: sourceRegions is Map && sourceRegions[name] is num
            ? (sourceRegions[name] as num).toDouble()
            : 0.0,
    };
    final matrix = value['forceValues'];
    final forceValues = matrix is List
        ? matrix
            .whereType<List>()
            .map((row) =>
                row.whereType<num>().map((item) => item.toDouble()).toList())
            .toList()
        : const <List<double>>[];
    return _ReplayFrame(
      time: time.toDouble(),
      side: side!,
      regions: regions,
      forceValues: forceValues,
    );
  }
}

class _ReplayHeader extends StatelessWidget {
  const _ReplayHeader({required this.position, required this.unit});

  final double position;
  final String unit;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          const Icon(Icons.replay_outlined, size: 17, color: AppColors.accent),
          const SizedBox(width: 7),
          const Expanded(
            child: Text(
              'REPLAY FSR · DỮ LIỆU TỪNG THỜI ĐIỂM',
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
            ),
          ),
          Text(
            't = ${position.toStringAsFixed(1)} s · $unit',
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 10,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _InstantForceSummary extends StatelessWidget {
  const _InstantForceSummary({
    required this.left,
    required this.right,
    required this.unit,
  });

  final _ReplayFrame? left;
  final _ReplayFrame? right;
  final String unit;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final cards = [
          _InstantFootCard(
            title: 'CHÂN TRÁI',
            frame: left,
            unit: unit,
            color: AppColors.leftLeg,
          ),
          _InstantFootCard(
            title: 'CHÂN PHẢI',
            frame: right,
            unit: unit,
            color: AppColors.rightLeg,
          ),
        ];
        if (constraints.maxWidth < 620) {
          return Column(
            children: [
              cards.first,
              const SizedBox(height: 8),
              cards.last,
            ],
          );
        }
        return Row(
          children: [
            Expanded(child: cards.first),
            const SizedBox(width: 10),
            Expanded(child: cards.last),
          ],
        );
      },
    );
  }
}

class _InstantFootCard extends StatelessWidget {
  const _InstantFootCard({
    required this.title,
    required this.frame,
    required this.unit,
    required this.color,
  });

  final String title;
  final _ReplayFrame? frame;
  final String unit;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final total = frame?.regions['total'] ?? 0.0;
    final contact = frame != null && total > 0.01;
    return Container(
      padding: const EdgeInsets.fromLTRB(11, 8, 11, 9),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(9),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(width: 3, height: 14, color: color),
              const SizedBox(width: 6),
              Text(title,
                  style: const TextStyle(
                      fontSize: 10, fontWeight: FontWeight.w700)),
              const Spacer(),
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  color: contact ? AppColors.accentGreen : AppColors.baseline,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 5),
              Text(
                frame == null
                    ? 'Không có dữ liệu'
                    : contact
                        ? 'Đang chạm'
                        : 'Không tải',
                style: const TextStyle(
                    fontSize: 9, color: AppColors.textSecondary),
              ),
            ],
          ),
          const SizedBox(height: 7),
          Row(
            children: [
              for (final metric in const [
                ('total', 'Tổng'),
                ('heel', 'Gót'),
                ('midfoot', 'Giữa'),
                ('forefoot', 'Trước'),
              ])
                Expanded(
                  child: _InstantValue(
                    label: metric.$2,
                    value: frame?.regions[metric.$1],
                    unit: unit,
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _InstantValue extends StatelessWidget {
  const _InstantValue({
    required this.label,
    required this.value,
    required this.unit,
  });

  final String label;
  final double? value;
  final String unit;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style:
                const TextStyle(fontSize: 8, color: AppColors.textSecondary)),
        const SizedBox(height: 1),
        Text(
          value == null ? '—' : '${value!.toStringAsFixed(1)} $unit',
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
        ),
      ],
    );
  }
}

class _PressureReplayCard extends StatelessWidget {
  const _PressureReplayCard({
    required this.left,
    required this.right,
    required this.scaleMax,
    required this.unit,
  });

  final _ReplayFrame? left;
  final _ReplayFrame? right;
  final double scaleMax;
  final String unit;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 265,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('BẢN ĐỒ ÁP LỰC TỨC THỜI',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
          const SizedBox(height: 2),
          Text(
            'Khung FSR gần nhất theo thanh phát video · $unit',
            style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 5),
          Expanded(
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Expanded(
                  child: _ReplayFoot(
                    title: 'TRÁI',
                    frame: left,
                    isLeft: true,
                    scaleMax: scaleMax,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: _ReplayFoot(
                    title: 'PHẢI',
                    frame: right,
                    isLeft: false,
                    scaleMax: scaleMax,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ReplayFoot extends StatelessWidget {
  const _ReplayFoot({
    required this.title,
    required this.frame,
    required this.isLeft,
    required this.scaleMax,
  });

  final String title;
  final _ReplayFrame? frame;
  final bool isLeft;
  final double scaleMax;

  @override
  Widget build(BuildContext context) {
    final hasMatrix = frame != null && frame!.forceValues.isNotEmpty;
    return Column(
      children: [
        Text('CHÂN $title',
            style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
        const SizedBox(height: 3),
        Expanded(
          child: hasMatrix
              ? FootPressureMap(
                  matrix: frame!.forceValues,
                  isLeft: isLeft,
                  scaleMax: scaleMax,
                  rawAdc: false,
                )
              : const Center(
                  child: Text(
                    'Không có khung FSR',
                    textAlign: TextAlign.center,
                    style:
                        TextStyle(fontSize: 9, color: AppColors.textSecondary),
                  ),
                ),
        ),
      ],
    );
  }
}

class _ReplayMetricChart extends StatelessWidget {
  const _ReplayMetricChart({
    required this.title,
    required this.metric,
    required this.leftFrames,
    required this.rightFrames,
    required this.position,
    required this.unit,
  });

  final String title;
  final String metric;
  final List<_ReplayFrame> leftFrames;
  final List<_ReplayFrame> rightFrames;
  final double position;
  final String unit;

  List<FlSpot> _spots(List<_ReplayFrame> frames, double start) => frames
      .map((frame) => FlSpot(frame.time - start, frame.regions[metric] ?? 0.0))
      .toList();

  LineChartBarData _line(List<_ReplayFrame> frames, Color color, double start,
          {bool dashed = false}) =>
      LineChartBarData(
        spots: _spots(frames, start),
        color: color,
        barWidth: 2.2,
        isCurved: false,
        dashArray: dashed ? const [7, 5] : null,
        dotData: const FlDotData(show: false),
      );

  @override
  Widget build(BuildContext context) {
    final allFrames = [...leftFrames, ...rightFrames];
    final start = allFrames.isEmpty
        ? max(0.0, position - 4.0)
        : allFrames.map((frame) => frame.time).reduce(min);
    final values = [
      for (final frame in allFrames) frame.regions[metric] ?? 0.0,
    ].where((value) => value.isFinite).toList();
    final maxY = values.isEmpty ? 1.0 : max(1.0, values.reduce(max) * 1.16);
    return Container(
      padding: const EdgeInsets.fromLTRB(11, 9, 12, 8),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style:
                  const TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
          const SizedBox(height: 2),
          const Text('4 giây gần thời điểm đang xem',
              style: TextStyle(fontSize: 9, color: AppColors.textSecondary)),
          const SizedBox(height: 5),
          Expanded(
            child: allFrames.isEmpty
                ? const Center(
                    child: Text('Chưa có mẫu FSR ở thời điểm này',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                            fontSize: 10, color: AppColors.textSecondary)),
                  )
                : LineChart(
                    LineChartData(
                      minX: 0,
                      maxX: max(0.2, position - start),
                      minY: 0,
                      maxY: maxY,
                      lineBarsData: [
                        _line(leftFrames, AppColors.leftLeg, start),
                        _line(
                          rightFrames,
                          AppColors.rightLeg,
                          start,
                          dashed: true,
                        ),
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
                        topTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false)),
                        rightTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false)),
                        bottomTitles: AxisTitles(
                          axisNameWidget: const Text('t (s)',
                              style: TextStyle(fontSize: 8)),
                          sideTitles: SideTitles(
                            showTitles: true,
                            interval: 1,
                            reservedSize: 22,
                            getTitlesWidget: (value, _) => Text(
                              value.toStringAsFixed(1),
                              style: const TextStyle(fontSize: 8),
                            ),
                          ),
                        ),
                        leftTitles: AxisTitles(
                          axisNameWidget:
                              Text(unit, style: const TextStyle(fontSize: 8)),
                          sideTitles: SideTitles(
                            showTitles: true,
                            reservedSize: 40,
                            getTitlesWidget: (value, _) => Text(
                              value.toStringAsFixed(0),
                              style: const TextStyle(fontSize: 8),
                            ),
                          ),
                        ),
                      ),
                      lineTouchData: const LineTouchData(enabled: false),
                    ),
                    duration: const Duration(milliseconds: 150),
                  ),
          ),
          const SizedBox(height: 5),
          const Wrap(
            spacing: 10,
            children: [
              _ReplayLegend(color: AppColors.leftLeg, label: 'Chân trái'),
              _ReplayLegend(
                color: AppColors.rightLeg,
                label: 'Chân phải',
                dashed: true,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ReplayLegend extends StatelessWidget {
  const _ReplayLegend({
    required this.color,
    required this.label,
    this.dashed = false,
  });

  final Color color;
  final String label;
  final bool dashed;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: 16,
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
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 8)),
      ],
    );
  }
}

class _ReplayEmptyState extends StatelessWidget {
  const _ReplayEmptyState();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.sensors_off_outlined,
                size: 34, color: AppColors.baseline),
            SizedBox(height: 10),
            Text(
              'Clip này chưa có dữ liệu FSR phát lại theo thời điểm.\n'
              'Hãy ghi clip mới khi hai tấm FSR đã kết nối.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
            ),
          ],
        ),
      ),
    );
  }
}
