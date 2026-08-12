import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'foot_pressure_map.dart';
import '../theme/app_theme.dart';

enum RealtimeChartType {
  pressure,
  totalForce,
  heelForce,
  midfootForce,
  forefootForce,
  kneeCycle,
  ankleCycle,
  hipCycle,
}

extension RealtimeChartTypeLabel on RealtimeChartType {
  String get label => switch (this) {
        RealtimeChartType.pressure => 'Ph\u00e2n b\u1ed1 \u00e1p l\u1ef1c FSR',
        RealtimeChartType.totalForce => 'T\u1ed5ng l\u1ef1c hai ch\u00e2n',
        RealtimeChartType.heelForce => 'L\u1ef1c v\u00f9ng g\u00f3t',
        RealtimeChartType.midfootForce =>
          'L\u1ef1c v\u00f9ng gi\u1eefa b\u00e0n ch\u00e2n',
        RealtimeChartType.forefootForce =>
          'L\u1ef1c v\u00f9ng tr\u01b0\u1edbc b\u00e0n ch\u00e2n',
        RealtimeChartType.kneeCycle =>
          'Chu k\u1ef3 b\u01b0\u1edbc \u2013 g\u1ed1i',
        RealtimeChartType.ankleCycle => 'G\u00f3c c\u1ed5 ch\u00e2n',
        RealtimeChartType.hipCycle => 'G\u00f3c h\u00f4ng',
      };

  IconData get icon => switch (this) {
        RealtimeChartType.pressure => Icons.grid_view_outlined,
        RealtimeChartType.totalForce => Icons.show_chart,
        RealtimeChartType.heelForce => Icons.vertical_align_bottom,
        RealtimeChartType.midfootForce => Icons.swap_vert,
        RealtimeChartType.forefootForce => Icons.vertical_align_top,
        RealtimeChartType.kneeCycle => Icons.directions_walk,
        RealtimeChartType.ankleCycle => Icons.multiline_chart,
        RealtimeChartType.hipCycle => Icons.monitor_heart_outlined,
      };
}

class RealtimeChartWorkspace extends StatefulWidget {
  const RealtimeChartWorkspace({
    super.key,
    required this.selectedCharts,
  });

  final Set<RealtimeChartType> selectedCharts;

  @override
  State<RealtimeChartWorkspace> createState() => _RealtimeChartWorkspaceState();
}

class _RealtimeChartWorkspaceState extends State<RealtimeChartWorkspace> {
  Timer? _timer;
  List<List<double>>? _leftMatrix;
  List<List<double>>? _rightMatrix;
  final List<double> _leftForce = [];
  final List<double> _rightForce = [];
  final List<double> _leftHeelForce = [];
  final List<double> _rightHeelForce = [];
  final List<double> _leftMidfootForce = [];
  final List<double> _rightMidfootForce = [];
  final List<double> _leftForefootForce = [];
  final List<double> _rightForefootForce = [];
  Map<String, List<double>> _angles = const {};
  bool _fsrConnected = false;
  bool _useFsrDemo = false;
  double _demoPhase = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer =
        Timer.periodic(const Duration(milliseconds: 200), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_useFsrDemo) {
      _updateFsrDemo();
      return;
    }
    try {
      final responses = await Future.wait([
        http
            .get(Uri.parse('http://127.0.0.1:8000/fsr/latest'))
            .timeout(const Duration(milliseconds: 900)),
        http
            .get(Uri.parse('http://127.0.0.1:8000/get_angles'))
            .timeout(const Duration(milliseconds: 900)),
      ]);
      if (!mounted) return;
      final fsr = responses[0].statusCode == 200
          ? jsonDecode(responses[0].body) as Map<String, dynamic>
          : <String, dynamic>{};
      final angles = responses[1].statusCode == 200
          ? jsonDecode(responses[1].body) as Map<String, dynamic>
          : <String, dynamic>{};
      final left = _matrix(fsr['left']);
      final right = _matrix(fsr['right']);
      setState(() {
        if (!_useFsrDemo) {
          _leftMatrix = left ?? _leftMatrix;
          _rightMatrix = right ?? _rightMatrix;
          _fsrConnected = fsr['left']?['connected'] == true ||
              fsr['right']?['connected'] == true;
          if (left != null || right != null) {
            final empty = List.generate(12, (_) => List.filled(4, 4000.0));
            _appendFsrFrame(
              _adcLoadMatrix(left ?? empty),
              _adcLoadMatrix(right ?? empty),
            );
          }
        }
        _angles = {
          for (final key in const [
            'left_knee',
            'right_knee',
            'left_ankle',
            'right_ankle',
            'left_hip',
            'right_hip',
          ])
            key: _curve(angles[key]),
        };
      });
    } catch (_) {
      if (mounted && _fsrConnected && !_useFsrDemo) {
        setState(() => _fsrConnected = false);
      }
    }
  }

  void _toggleFsrDemo(bool enabled) {
    setState(() {
      _useFsrDemo = enabled;
      _demoPhase = 0;
      _leftForce.clear();
      _rightForce.clear();
      _leftHeelForce.clear();
      _rightHeelForce.clear();
      _leftMidfootForce.clear();
      _rightMidfootForce.clear();
      _leftForefootForce.clear();
      _rightForefootForce.clear();
      if (!enabled) {
        _leftMatrix = null;
        _rightMatrix = null;
        _fsrConnected = false;
      }
    });
    if (enabled) _updateFsrDemo();
  }

  void _updateFsrDemo() {
    if (!mounted || !_useFsrDemo) return;
    _demoPhase = (_demoPhase + 0.16) % 1.0;
    final left = _demoFoot(
      _stanceProgress(_demoPhase),
      medialColumn: 2.4,
      scale: 1.0,
    );
    final right = _demoFoot(
      _stanceProgress((_demoPhase + 0.5) % 1.0),
      medialColumn: 0.6,
      scale: 0.78,
    );
    setState(() {
      _leftMatrix = left;
      _rightMatrix = right;
      _appendFsrFrame(left, right);
    });
  }

  double? _stanceProgress(double cycle) {
    const stanceRatio = 0.62;
    return cycle < stanceRatio ? cycle / stanceRatio : null;
  }

  double _pulse(double progress, double center, double width) {
    final distance = (progress - center) / width;
    return exp(-(distance * distance));
  }

  List<List<double>> _demoFoot(
    double? progress, {
    required double medialColumn,
    required double scale,
  }) {
    if (progress == null) {
      return List.generate(12, (_) => List.filled(4, 0.0));
    }

    double hotspot(int row, int column, double centerRow, double centerColumn,
        double rowSpread, double columnSpread) {
      final dr = (row - centerRow) / rowSpread;
      final dc = (column - centerColumn) / columnSpread;
      return exp(-(dr * dr + dc * dc));
    }

    final heelWeight = _pulse(progress, 0.12, 0.18);
    final midWeight = _pulse(progress, 0.46, 0.28);
    final foreWeight = _pulse(progress, 0.73, 0.22);
    final toeWeight = _pulse(progress, 0.90, 0.13);
    return List.generate(12, (row) {
      return List.generate(4, (column) {
        final heel = hotspot(row, column, 1.0, 1.5, 1.4, 1.15);
        final midfoot = hotspot(row, column, 5.3, medialColumn, 2.1, 0.95);
        final forefoot = hotspot(row, column, 8.7, 1.5, 1.8, 1.5);
        final bigToe = hotspot(row, column, 10.8, medialColumn, 0.9, 0.72);
        final signal = heelWeight * heel +
            0.58 * midWeight * midfoot +
            1.05 * foreWeight * forefoot +
            0.82 * toeWeight * bigToe;
        return scale * 1100 * signal;
      });
    });
  }

  void _appendFsrFrame(
    List<List<double>> left,
    List<List<double>> right,
  ) {
    _append(_leftForce, _total(left));
    _append(_rightForce, _total(right));
    _append(_leftHeelForce, _regionTotal(left, 0, 2));
    _append(_rightHeelForce, _regionTotal(right, 0, 2));
    _append(_leftMidfootForce, _regionTotal(left, 3, 7));
    _append(_rightMidfootForce, _regionTotal(right, 3, 7));
    _append(_leftForefootForce, _regionTotal(left, 8, 11));
    _append(_rightForefootForce, _regionTotal(right, 8, 11));
  }

  List<List<double>> _adcLoadMatrix(List<List<double>> matrix) => matrix
      .map((row) => row.map((value) => max(0.0, 4000.0 - value)).toList())
      .toList();

  double _regionTotal(
    List<List<double>> matrix,
    int firstRow,
    int lastRow,
  ) {
    var total = 0.0;
    for (var row = firstRow; row <= lastRow && row < matrix.length; row++) {
      total += matrix[row].fold(0.0, (sum, value) => sum + value);
    }
    return total;
  }

  List<List<double>>? _matrix(dynamic sample) {
    final values = sample is Map ? sample['values'] : null;
    if (values is! List) return null;
    return values
        .whereType<List>()
        .map((row) => row.map((value) => (value as num).toDouble()).toList())
        .toList();
  }

  List<double> _curve(dynamic values) => values is List
      ? values.map((value) => (value as num).toDouble()).toList()
      : const [];

  double _total(List<List<double>> matrix) =>
      matrix.fold(0, (sum, row) => sum + row.fold(0, (a, b) => a + b));

  void _append(List<double> history, double value) {
    history.add(value);
    if (history.length > 100) history.removeAt(0);
  }

  @override
  Widget build(BuildContext context) {
    final charts =
        RealtimeChartType.values.where(widget.selectedCharts.contains).toList();
    if (charts.isEmpty) return _emptyState();

    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = charts.length == 1 ? 1 : 2;
        final rowsVisible = charts.length <= 2 ? 1 : 2;
        final availableHeight =
            constraints.maxHeight - ((rowsVisible - 1) * 10);
        final extent = max(150.0, availableHeight / rowsVisible);
        return GridView.builder(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            mainAxisExtent: extent,
          ),
          itemCount: charts.length,
          itemBuilder: (_, index) => _chartCard(charts[index]),
        );
      },
    );
  }

  Widget _emptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: const [
          Icon(
            Icons.insert_chart_outlined,
            size: 34,
            color: AppColors.baseline,
          ),
          SizedBox(height: 10),
          Text(
            'Ch\u1ecdn bi\u1ec3u \u0111\u1ed3 t\u1eeb menu b\u00ean tr\u00e1i \u0111\u1ec3 hi\u1ec3n th\u1ecb v\u00e0 so s\u00e1nh d\u1eef li\u1ec7u.',
            style: TextStyle(
              fontSize: 12,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _chartCard(RealtimeChartType type) {
    final isFsr = switch (type) {
      RealtimeChartType.pressure ||
      RealtimeChartType.totalForce ||
      RealtimeChartType.heelForce ||
      RealtimeChartType.midfootForce ||
      RealtimeChartType.forefootForce =>
        true,
      _ => false,
    };
    return Container(
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 6, 6),
            child: Row(
              children: [
                Icon(type.icon, size: 16, color: AppColors.accent),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    type.label,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (type == RealtimeChartType.pressure) ...[
                  const Text(
                    'D\u1eef li\u1ec7u m\u1eabu',
                    style: TextStyle(
                      fontSize: 9,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(width: 5),
                  SizedBox(
                    width: 34,
                    height: 22,
                    child: FittedBox(
                      fit: BoxFit.contain,
                      child: Switch(
                        value: _useFsrDemo,
                        onChanged: _toggleFsrDemo,
                      ),
                    ),
                  ),
                  const SizedBox(width: 9),
                ],
                if (isFsr) ...[
                  Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: _useFsrDemo
                          ? AppColors.warning
                          : _fsrConnected
                              ? AppColors.accentGreen
                              : AppColors.baseline,
                    ),
                  ),
                  const SizedBox(width: 5),
                  Text(
                    _useFsrDemo
                        ? 'M\u1eabu mô ph\u1ecfng'
                        : _fsrConnected
                            ? '\u0110ang nh\u1eadn'
                            : 'Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u',
                    style: const TextStyle(
                      fontSize: 9,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
                IconButton(
                  onPressed: () => _showExpanded(type),
                  icon: const Icon(Icons.open_in_full, size: 15),
                  tooltip: 'Ph\u00f3ng to',
                  visualDensity: VisualDensity.compact,
                ),
              ],
            ),
          ),
          const Divider(height: 1, color: AppColors.border),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(10, 8, 12, 8),
              child: _chartBody(type),
            ),
          ),
          _legend(type),
        ],
      ),
    );
  }

  Widget _legend(RealtimeChartType type) {
    if (type == RealtimeChartType.pressure) {
      return const SizedBox(height: 6);
    }
    return const Padding(
      padding: EdgeInsets.only(bottom: 7),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _Legend(color: Color(0xFF175FC4), label: 'Ch\u00e2n tr\u00e1i'),
          SizedBox(width: 18),
          _Legend(
              color: Color(0xFFD64545),
              label: 'Ch\u00e2n ph\u1ea3i',
              dashed: true),
        ],
      ),
    );
  }

  void _showExpanded(RealtimeChartType type) {
    showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        child: SizedBox(
          width: 920,
          height: 580,
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              children: [
                Row(
                  children: [
                    Icon(type.icon, color: AppColors.accent),
                    const SizedBox(width: 9),
                    Expanded(
                      child: Text(
                        type.label,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                const Divider(color: AppColors.border),
                Expanded(child: _chartBody(type)),
                _legend(type),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _chartBody(RealtimeChartType type) {
    return switch (type) {
      RealtimeChartType.pressure => _pressureView(),
      RealtimeChartType.totalForce => _lineChart(
          _leftForce,
          _rightForce,
          xLabel: 'Th\u1eddi gian (s)',
          yLabel: 'T\u1ed5ng l\u1ef1c (raw ADC)',
        ),
      RealtimeChartType.heelForce => _lineChart(
          _leftHeelForce,
          _rightHeelForce,
          xLabel: 'Th\u1eddi gian (s)',
          yLabel: 'L\u1ef1c g\u00f3t (raw ADC)',
        ),
      RealtimeChartType.midfootForce => _lineChart(
          _leftMidfootForce,
          _rightMidfootForce,
          xLabel: 'Th\u1eddi gian (s)',
          yLabel: 'L\u1ef1c gi\u1eefa b\u00e0n ch\u00e2n (raw ADC)',
        ),
      RealtimeChartType.forefootForce => _lineChart(
          _leftForefootForce,
          _rightForefootForce,
          xLabel: 'Th\u1eddi gian (s)',
          yLabel: 'L\u1ef1c tr\u01b0\u1edbc b\u00e0n ch\u00e2n (raw ADC)',
        ),
      RealtimeChartType.kneeCycle => _lineChart(
          _angles['left_knee'] ?? const [],
          _angles['right_knee'] ?? const [],
          xLabel: '% chu k\u1ef3 b\u01b0\u1edbc',
          yLabel: 'G\u00f3c g\u1ed1i (\u00b0)',
        ),
      RealtimeChartType.ankleCycle => _lineChart(
          _angles['left_ankle'] ?? const [],
          _angles['right_ankle'] ?? const [],
          xLabel: '% chu k\u1ef3 b\u01b0\u1edbc',
          yLabel: 'G\u00f3c c\u1ed5 ch\u00e2n (\u00b0)',
        ),
      RealtimeChartType.hipCycle => _lineChart(
          _angles['left_hip'] ?? const [],
          _angles['right_hip'] ?? const [],
          xLabel: '% chu k\u1ef3 b\u01b0\u1edbc',
          yLabel: 'G\u00f3c h\u00f4ng (\u00b0)',
        ),
    };
  }

  Widget _pressureView() {
    final values = <double>[
      if (_leftMatrix != null) ..._leftMatrix!.expand((row) => row),
      if (_rightMatrix != null) ..._rightMatrix!.expand((row) => row),
    ].where((value) => value > 0).toList();
    final measuredMax = values.isEmpty ? 0.0 : values.reduce(max);
    final sharedMax = measuredMax <= 0
        ? 0.0
        : max(measuredMax, _useFsrDemo ? 1100.0 : 4500.0);

    return LayoutBuilder(
      builder: (context, constraints) {
        final footHeight = min(
          constraints.maxHeight,
          (constraints.maxWidth - 6) / 0.96,
        );
        final footWidth = footHeight * 0.48;
        return Center(
          child: SizedBox(
            width: footWidth * 2 + 6,
            height: footHeight,
            child: Row(
              children: [
                SizedBox(
                  width: footWidth,
                  height: footHeight,
                  child: FootPressureMap(
                    matrix: _rightMatrix,
                    isLeft: true,
                    scaleMax: sharedMax,
                    rawAdc: !_useFsrDemo,
                  ),
                ),
                const SizedBox(width: 6),
                SizedBox(
                  width: footWidth,
                  height: footHeight,
                  child: FootPressureMap(
                    matrix: _leftMatrix,
                    isLeft: false,
                    scaleMax: sharedMax,
                    rawAdc: !_useFsrDemo,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _lineChart(
    List<double> left,
    List<double> right, {
    required String xLabel,
    required String yLabel,
  }) {
    if (left.isEmpty && right.isEmpty) {
      return const Center(
        child: Text(
          'Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u realtime.',
          style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
        ),
      );
    }

    final sampleCount = max(left.length, right.length);
    final normalizedCycle = xLabel.startsWith('%');
    final xScale = normalizedCycle
        ? (sampleCount <= 1 ? 1.0 : 100 / (sampleCount - 1))
        : 0.2;
    final maxX = max(1.0, (sampleCount - 1) * xScale);
    final xInterval = normalizedCycle ? 25.0 : max(1.0, maxX / 5);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 4),
          child: Text(
            yLabel,
            style: const TextStyle(
              fontSize: 9,
              color: AppColors.textSecondary,
            ),
          ),
        ),
        Expanded(
          child: LineChart(
            LineChartData(
              minX: 0,
              maxX: maxX,
              minY: 0,
              gridData: FlGridData(
                show: true,
                drawVerticalLine: true,
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
                topTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false),
                ),
                rightTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false),
                ),
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 46,
                    getTitlesWidget: (value, _) => Text(
                      _formatAxisValue(value),
                      style: const TextStyle(fontSize: 8),
                    ),
                  ),
                ),
                bottomTitles: AxisTitles(
                  axisNameWidget: Text(
                    xLabel,
                    style: const TextStyle(fontSize: 9),
                  ),
                  sideTitles: SideTitles(
                    showTitles: true,
                    interval: xInterval,
                    reservedSize: 25,
                    getTitlesWidget: (value, _) => Text(
                      normalizedCycle
                          ? value.toStringAsFixed(0)
                          : value.toStringAsFixed(1),
                      style: const TextStyle(fontSize: 8),
                    ),
                  ),
                ),
              ),
              lineBarsData: [
                _series(left, const Color(0xFF175FC4), xScale: xScale),
                _series(
                  right,
                  const Color(0xFFD64545),
                  xScale: xScale,
                  dashed: true,
                ),
              ],
            ),
            duration: const Duration(milliseconds: 160),
          ),
        ),
      ],
    );
  }

  String _formatAxisValue(double value) {
    final magnitude = value.abs();
    if (magnitude >= 1000000) {
      return '${(value / 1000000).toStringAsFixed(1)}M';
    }
    if (magnitude >= 1000) {
      return '${(value / 1000).toStringAsFixed(magnitude >= 10000 ? 0 : 1)}K';
    }
    return value.toStringAsFixed(0);
  }

  LineChartBarData _series(
    List<double> values,
    Color color, {
    required double xScale,
    bool dashed = false,
  }) {
    return LineChartBarData(
      spots: List.generate(
        values.length,
        (index) => FlSpot(index * xScale, values[index]),
      ),
      color: color,
      barWidth: 2.2,
      isCurved: true,
      curveSmoothness: 0.18,
      dashArray: dashed ? const [7, 5] : null,
      dotData: const FlDotData(show: false),
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
  Widget build(BuildContext context) {
    return Row(
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
        Text(
          label,
          style: const TextStyle(
            fontSize: 9,
            color: AppColors.textSecondary,
          ),
        ),
      ],
    );
  }
}
