import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'foot_pressure_map.dart';
import 'fsr_force_phase_dashboard.dart';
import '../theme/app_theme.dart';

enum RealtimeChartType {
  pressure,
  totalForce,
  heelForce,
  midfootForce,
  forefootForce,
  forcePhases,
  kneeCycle,
  trunkCycle,
  hipCycle,
}

extension RealtimeChartTypeLabel on RealtimeChartType {
  String get label => switch (this) {
        RealtimeChartType.pressure => 'Ph\u00e2n b\u1ed1 \u00e1p l\u1ef1c FSR',
        RealtimeChartType.totalForce =>
          'T\u1ed5ng m\u1ee9c t\u1ea3i hai ch\u00e2n',
        RealtimeChartType.heelForce => 'M\u1ee9c t\u1ea3i v\u00f9ng g\u00f3t',
        RealtimeChartType.midfootForce =>
          'M\u1ee9c t\u1ea3i v\u00f9ng gi\u1eefa b\u00e0n ch\u00e2n',
        RealtimeChartType.forefootForce =>
          'M\u1ee9c t\u1ea3i v\u00f9ng tr\u01b0\u1edbc b\u00e0n ch\u00e2n',
        RealtimeChartType.forcePhases => 'Lực FSR 3 pha · chân trái/phải',
        RealtimeChartType.kneeCycle => 'Góc gập gối 2D',
        RealtimeChartType.trunkCycle =>
          'G\u00f3c nghi\u00eang th\u00e2n tr\u01b0\u1edbc\u2013sau',
        RealtimeChartType.hipCycle => 'Góc gập hông 2D',
      };

  IconData get icon => switch (this) {
        RealtimeChartType.pressure => Icons.grid_view_outlined,
        RealtimeChartType.totalForce => Icons.show_chart,
        RealtimeChartType.heelForce => Icons.vertical_align_bottom,
        RealtimeChartType.midfootForce => Icons.swap_vert,
        RealtimeChartType.forefootForce => Icons.vertical_align_top,
        RealtimeChartType.forcePhases => Icons.monitor_heart_outlined,
        RealtimeChartType.kneeCycle => Icons.directions_walk,
        RealtimeChartType.trunkCycle => Icons.accessibility_new,
        RealtimeChartType.hipCycle => Icons.monitor_heart_outlined,
      };
}

class RealtimeChartWorkspace extends StatefulWidget {
  const RealtimeChartWorkspace({
    super.key,
    required this.selectedCharts,
    required this.healthySide,
    this.demoMode = false,
  });

  final Set<RealtimeChartType> selectedCharts;
  final String healthySide;
  final bool demoMode;

  @override
  State<RealtimeChartWorkspace> createState() => _RealtimeChartWorkspaceState();
}

class _RealtimeChartWorkspaceState extends State<RealtimeChartWorkspace> {
  Timer? _timer;
  bool _refreshInFlight = false;
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
  Map<String, dynamic> _fsrSteps = const {};
  Map<String, dynamic> _fsrLatest = const {};
  Map<String, dynamic> _gaitSteps = const {};
  int _windowSize = 5;
  bool _fsrConnected = false;
  bool _gaitOnline = false;
  bool _demoGaitLoaded = false;
  Map<String, dynamic>? _demoGaitSource;
  DateTime? _demoPlaybackStartedAt;
  int _demoVisiblePairCount = -1;
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
  void didUpdateWidget(covariant RealtimeChartWorkspace oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.demoMode == widget.demoMode) return;
    if (widget.demoMode) {
      _demoPlaybackStartedAt = DateTime.now();
      _demoVisiblePairCount = -1;
      _loadDemoGait();
    } else {
      setState(() {
        _gaitSteps = const {};
        _gaitOnline = false;
      });
      _refreshGait();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_refreshInFlight) return;
    _refreshInFlight = true;
    try {
      await Future.wait<void>([
        _refreshFsr(),
        _refreshGait(),
      ]);
    } finally {
      _refreshInFlight = false;
    }
  }

  Future<void> _refreshFsr() async {
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
            .get(Uri.parse(
              'http://127.0.0.1:8000/fsr/steps?window=$_windowSize',
            ))
            .timeout(const Duration(milliseconds: 900)),
      ]);
      if (!mounted) return;
      final fsr = responses[0].statusCode == 200
          ? jsonDecode(responses[0].body) as Map<String, dynamic>
          : <String, dynamic>{};

      final steps = responses[1].statusCode == 200
          ? jsonDecode(responses[1].body) as Map<String, dynamic>
          : <String, dynamic>{};
      final left = _matrix(fsr['left']);
      final right = _matrix(fsr['right']);
      setState(() {
        if (!_useFsrDemo) {
          final leftConnected = fsr['left']?['connected'] == true;
          final rightConnected = fsr['right']?['connected'] == true;
          _leftMatrix = leftConnected ? left : null;
          _rightMatrix = rightConnected ? right : null;
          _fsrSteps = steps;
          _fsrLatest = fsr;
          _fsrConnected = leftConnected || rightConnected;
          if (left != null || right != null) {
            final empty = List.generate(12, (_) => List.filled(4, 4000.0));
            _appendFsrFrame(
              _adcLoadMatrix(left ?? empty),
              _adcLoadMatrix(right ?? empty),
            );
          }
        }
      });
    } catch (_) {
      if (mounted && _fsrConnected && !_useFsrDemo) {
        setState(() => _fsrConnected = false);
      }
    }
  }

  Future<void> _loadDemoGait() async {
    if (_demoGaitLoaded) {
      _updateDemoGaitProgress();
      return;
    }
    try {
      final source =
          await rootBundle.loadString('assets/demo/demo_gait_data.json');
      final gait = jsonDecode(source) as Map<String, dynamic>;
      if (!mounted || !widget.demoMode) return;
      _demoGaitSource = gait;
      _demoPlaybackStartedAt ??= DateTime.now();
      _demoGaitLoaded = true;
      _updateDemoGaitProgress();
    } catch (_) {
      if (mounted && widget.demoMode) {
        setState(() => _gaitOnline = false);
      }
    }
  }

  void _updateDemoGaitProgress() {
    final source = _demoGaitSource;
    final startedAt = _demoPlaybackStartedAt;
    if (!mounted || !widget.demoMode || source == null || startedAt == null) {
      return;
    }
    final allCycles = source['cycles'];
    if (allCycles is! List || allCycles.isEmpty) return;
    final duration = (source['duration'] as num?)?.toDouble() ?? 10.4667;
    if (duration <= 0) return;
    final elapsed =
        DateTime.now().difference(startedAt).inMilliseconds / 1000.0;
    final videoPosition = elapsed % duration;
    final visibleCount = min(allCycles.length,
        (videoPosition / duration * (allCycles.length + 1)).floor());
    if (visibleCount == _demoVisiblePairCount) return;
    final visibleCycles = allCycles.take(visibleCount).toList();
    final next = Map<String, dynamic>.from(source)
      ..['cycles'] = visibleCycles
      ..['cycleCount'] = visibleCount
      ..['poseDetected'] = true;
    setState(() {
      _gaitSteps = next;
      _gaitOnline = true;
      _demoVisiblePairCount = visibleCount;
    });
  }

  Future<void> _refreshGait() async {
    if (widget.demoMode) {
      await _loadDemoGait();
      return;
    }
    try {
      final response = await http
          .get(Uri.parse(
            'http://127.0.0.1:8000/gait/steps?window=$_windowSize',
          ))
          .timeout(const Duration(milliseconds: 900));
      if (!mounted) return;
      if (response.statusCode != 200) {
        setState(() => _gaitOnline = false);
        return;
      }
      final gait = jsonDecode(response.body) as Map<String, dynamic>;
      setState(() {
        _gaitSteps = gait;
        _gaitOnline = true;
      });
    } catch (_) {
      if (mounted) setState(() => _gaitOnline = false);
    }
  }

  String _gaitEmptyMessage() {
    if (!_gaitOnline) return 'Backend chưa chạy hoặc chưa phản hồi.';
    if (_gaitSteps['poseDetected'] != true) {
      return 'Camera dọc chưa thấy đủ toàn thân. Hãy đứng lùi để thấy từ vai đến bàn chân.';
    }
    final samples = (_gaitSteps['sampleCount'] as num?)?.toInt() ?? 0;
    return 'Đã nhận $samples mẫu. Hãy đi liên tục ít nhất 2 chu kỳ.';
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
        final heel = hotspot(row, column, 10.0, 1.5, 1.4, 1.15);
        final midfoot = hotspot(row, column, 5.3, medialColumn, 2.1, 0.95);
        final forefoot = hotspot(row, column, 2.3, 1.5, 1.8, 1.5);
        final bigToe = hotspot(row, column, 0.2, medialColumn, 0.9, 0.72);
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
    _append(_leftHeelForce, _regionTotal(left, 9, 11));
    _append(_rightHeelForce, _regionTotal(right, 9, 11));
    _append(_leftMidfootForce, _regionTotal(left, 4, 8));
    _append(_rightMidfootForce, _regionTotal(right, 4, 8));
    _append(_leftForefootForce, _regionTotal(left, 0, 3));
    _append(_rightForefootForce, _regionTotal(right, 0, 3));
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

  List<Map<String, dynamic>> _stepPairs() {
    final source = _fsrSteps['pairs'];
    if (source is! List) return const [];
    return source
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Map<String, dynamic>? _activePair() {
    final pairs = _stepPairs();
    return pairs.isEmpty ? null : pairs.last;
  }

  List<double> _pairedCurve(String side, String region) {
    final pair = _activePair();
    final sideData = pair?[side];
    final curves = sideData is Map ? sideData['curves'] : null;
    return _curve(curves is Map ? curves[region] : null);
  }

  List<Map<String, dynamic>> _gaitCycles() {
    final source = _gaitSteps['cycles'];
    if (source is! List) return const [];
    return source
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  List<Map<String, dynamic>> _comparisonPairs() {
    final fsrSelected = widget.selectedCharts.any((type) => switch (type) {
          RealtimeChartType.totalForce ||
          RealtimeChartType.heelForce ||
          RealtimeChartType.midfootForce ||
          RealtimeChartType.forefootForce ||
          RealtimeChartType.forcePhases =>
            true,
          _ => false,
        });
    final gaitSelected = widget.selectedCharts.any((type) => switch (type) {
          RealtimeChartType.kneeCycle ||
          RealtimeChartType.hipCycle ||
          RealtimeChartType.trunkCycle =>
            true,
          _ => false,
        });
    final fsr = _stepPairs();
    final gait = _gaitCycles();
    if (gaitSelected && !fsrSelected) return gait;
    // The camera and hand-pressed FSR streams are intentionally independent;
    // their pair indexes must not be intersected.
    if (fsrSelected && gaitSelected) return gait.isNotEmpty ? gait : fsr;
    return fsr;
  }

  Map<String, dynamic>? _activeGaitCycle() {
    final cycles = _gaitCycles();
    return cycles.isEmpty ? null : cycles.last;
  }

  List<double> _gaitCurve(String side, String metric) {
    final cycle = _activeGaitCycle();
    final sideData = cycle?[side];
    final curves = sideData is Map ? sideData['curves'] : null;
    return _curve(curves is Map ? curves[metric] : null);
  }

  Widget _pairControls() {
    final pairs = _comparisonPairs();
    final active = pairs.isEmpty ? null : pairs.last;
    final activeIndex = (active?['pairIndex'] as num?)?.toInt();
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 7, 12, 0),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          const Icon(Icons.compare_arrows, size: 15, color: AppColors.accent),
          const SizedBox(width: 7),
          const Text('Theo dõi cặp bước trực tiếp',
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.w600)),
          const SizedBox(width: 8),
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(
              color: pairs.isEmpty
                  ? AppColors.textSecondary
                  : AppColors.accentGreen,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 5),
          Text(
            pairs.isEmpty
                ? 'Chờ cặp bước đầu tiên'
                : 'Mới nhất: cặp #$activeIndex',
            style: const TextStyle(
              fontSize: 9,
              color: AppColors.textSecondary,
            ),
          ),
          const Spacer(),
          const Text('Giữ gần nhất',
              style: TextStyle(fontSize: 9, color: AppColors.textSecondary)),
          const SizedBox(width: 5),
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
                _refresh();
              },
            ),
          ),
          const SizedBox(width: 8),
          Text(
            pairs.isEmpty
                ? '0 cặp'
                : '${pairs.length}/$_windowSize cặp trong bộ nhớ',
            style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final charts =
        RealtimeChartType.values.where(widget.selectedCharts.contains).toList();
    if (charts.isEmpty) return _emptyState();
    final showPairControls =
        charts.any((type) => type != RealtimeChartType.pressure) &&
            !_useFsrDemo;

    return Column(
      children: [
        if (showPairControls) _pairControls(),
        Expanded(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final showForcePhases =
                  charts.contains(RealtimeChartType.forcePhases);
              if (showForcePhases) {
                final upperCharts = charts
                    .where((type) => type != RealtimeChartType.forcePhases)
                    .toList();
                final upperHeight = upperCharts.isEmpty
                    ? 0.0
                    : max(220.0, constraints.maxHeight * 0.48);
                final phaseHeight = upperCharts.isEmpty
                    ? max(400.0, constraints.maxHeight - 16)
                    : max(440.0, constraints.maxHeight * 0.90);
                return ListView(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 14),
                  children: [
                    if (upperCharts.isNotEmpty) ...[
                      SizedBox(
                        height: upperHeight,
                        child: upperCharts.length == 1
                            ? _chartCard(upperCharts.single)
                            : GridView.builder(
                                physics: const NeverScrollableScrollPhysics(),
                                gridDelegate:
                                    SliverGridDelegateWithFixedCrossAxisCount(
                                  crossAxisCount:
                                      constraints.maxWidth < 580 ? 1 : 2,
                                  crossAxisSpacing: 10,
                                  mainAxisSpacing: 10,
                                  mainAxisExtent: upperHeight,
                                ),
                                itemCount: upperCharts.length,
                                itemBuilder: (_, index) =>
                                    _chartCard(upperCharts[index]),
                              ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    SizedBox(
                      height: phaseHeight,
                      width: double.infinity,
                      child: _chartCard(RealtimeChartType.forcePhases),
                    ),
                  ],
                );
              }

              final columns =
                  charts.length == 1 || constraints.maxWidth < 580 ? 1 : 2;
              final rowsVisible = columns == 1
                  ? min(charts.length, 2)
                  : (charts.length <= 2 ? 1 : 2);
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
          ),
        ),
      ],
    );
  }

  Widget _emptyState() {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
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
      RealtimeChartType.forefootForce ||
      RealtimeChartType.forcePhases =>
        true,
      _ => false,
    };
    final isGait = switch (type) {
      RealtimeChartType.kneeCycle ||
      RealtimeChartType.hipCycle ||
      RealtimeChartType.trunkCycle =>
        true,
      _ => false,
    };
    final gaitCycles = (_gaitSteps['cycleCount'] as num?)?.toInt() ?? 0;
    final gaitPoseDetected = _gaitSteps['poseDetected'] == true;
    final gaitQuality = _gaitSteps['poseQuality'];
    final gaitUnreliable =
        gaitQuality is Map && gaitQuality['status'] == 'unreliable';

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
                if (isGait) ...[
                  Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: !_gaitOnline
                          ? AppColors.critical
                          : gaitUnreliable
                              ? AppColors.warning
                              : gaitCycles > 0
                                  ? AppColors.accentGreen
                                  : gaitPoseDetected
                                      ? AppColors.warning
                                      : AppColors.baseline,
                    ),
                  ),
                  const SizedBox(width: 5),
                  Text(
                    !_gaitOnline
                        ? 'Backend chưa kết nối'
                        : gaitCycles > 0
                            ? gaitUnreliable
                                ? '$gaitCycles chu kỳ · cần kiểm tra'
                                : '$gaitCycles chu kỳ'
                            : gaitPoseDetected
                                ? 'Đang thu chuyển động'
                                : 'Chưa thấy toàn thân',
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
    if (type == RealtimeChartType.pressure ||
        type == RealtimeChartType.forcePhases) {
      return const SizedBox(height: 6);
    }
    final healthy = (_fsrSteps['healthySide']?.toString() ?? widget.healthySide)
        .toLowerCase();
    String label(String side) {
      final name = side == 'left' ? 'Chân trái' : 'Chân phải';
      if (type == RealtimeChartType.trunkCycle) {
        return 'Theo chu kỳ $name';
      }
      if (healthy != 'left' && healthy != 'right') return name;
      return '$name · ${side == healthy ? 'lành' : 'giả'}';
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _Legend(color: AppColors.leftLeg, label: label('left')),
          const SizedBox(width: 18),
          _Legend(
            color: AppColors.rightLeg,
            label: label('right'),
            dashed: true,
          ),
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
      RealtimeChartType.totalForce => _fsrPairChart(
          'total',
          demoLeft: _leftForce,
          demoRight: _rightForce,
          yLabel: 'Tổng mức tải tương đối',
        ),
      RealtimeChartType.heelForce => _fsrPairChart(
          'heel',
          demoLeft: _leftHeelForce,
          demoRight: _rightHeelForce,
          yLabel: 'Mức tải vùng gót tương đối',
        ),
      RealtimeChartType.midfootForce => _fsrPairChart(
          'midfoot',
          demoLeft: _leftMidfootForce,
          demoRight: _rightMidfootForce,
          yLabel: 'Mức tải vùng giữa bàn chân tương đối',
        ),
      RealtimeChartType.forefootForce => _fsrPairChart(
          'forefoot',
          demoLeft: _leftForefootForce,
          demoRight: _rightForefootForce,
          yLabel: 'Mức tải vùng trước bàn chân tương đối',
        ),
      RealtimeChartType.forcePhases =>
        FsrForcePhaseDashboard(analysis: _fsrPhaseAnalysis()),
      RealtimeChartType.kneeCycle => _lineChart(
          _gaitCurve('left', 'knee'),
          _gaitCurve('right', 'knee'),
          xLabel: '% chu kỳ camera chuẩn hóa',
          yLabel: 'Góc gập khớp gối 2D (°)',
          emptyMessage: _gaitEmptyMessage(),
        ),
      RealtimeChartType.hipCycle => _lineChart(
          _gaitCurve('left', 'hip'),
          _gaitCurve('right', 'hip'),
          xLabel: '% chu kỳ camera chuẩn hóa',
          yLabel: 'Góc gập khớp hông 2D (°)',
          emptyMessage: _gaitEmptyMessage(),
        ),
      RealtimeChartType.trunkCycle => _lineChart(
          _gaitCurve('left', 'trunk'),
          _gaitCurve('right', 'trunk'),
          xLabel: '% chu kỳ camera chuẩn hóa',
          yLabel: 'Góc nghiêng thân trước–sau (°)',
          emptyMessage: _gaitEmptyMessage(),
        ),
    };
  }

  Map<String, dynamic> _fsrPhaseAnalysis() {
    List<double> curve(String side, String region) {
      if (_useFsrDemo) {
        return _demoFsrCurve(region, isLeft: side == 'left');
      }
      return _pairedCurve(side, region);
    }

    final unit = _fsrSteps['unit']?.toString() ??
        (_fsrLatest['left'] is Map
            ? (_fsrLatest['left'] as Map)['unit']?.toString()
            : null) ??
        'N_estimated';
    return {
      'unit': unit,
      'healthySide': _fsrSteps['healthySide']?.toString() ?? widget.healthySide,
      'regions': {
        for (final region in const ['heel', 'midfoot', 'forefoot'])
          region: {
            'left': {'mean': curve('left', region)},
            'right': {'mean': curve('right', region)},
          },
      },
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
          (constraints.maxWidth - 10) / 0.86,
        );
        final footWidth = footHeight * 0.43;
        return Center(
          child: SizedBox(
            width: footWidth * 2 + 10,
            height: footHeight,
            child: Row(
              children: [
                SizedBox(
                  width: footWidth,
                  height: footHeight,
                  child: FootPressureMap(
                    matrix: _leftMatrix,
                    isLeft: true,
                    scaleMax: sharedMax,
                    rawAdc: !_useFsrDemo,
                  ),
                ),
                const SizedBox(width: 10),
                SizedBox(
                  width: footWidth,
                  height: footHeight,
                  child: FootPressureMap(
                    matrix: _rightMatrix,
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

  List<double> _demoFsrCurve(String region, {required bool isLeft}) {
    final scale = isLeft ? 1.0 : 0.78;
    final delay = isLeft ? 0.0 : 4.0;
    return List.generate(101, (index) {
      final x = index.toDouble() - delay;
      double pulse(double center, double width, double amplitude) {
        final distance = (x - center) / width;
        return amplitude * exp(-0.5 * distance * distance);
      }

      final heel = pulse(15, 10.5, 11500);
      final midfoot = pulse(50, 17, 10500);
      final forefoot = pulse(79, 12, 12500);
      final value = switch (region) {
        'heel' => heel,
        'midfoot' => midfoot,
        'forefoot' => forefoot,
        _ => heel + midfoot + forefoot,
      };
      final envelope =
          x <= 0 || x >= 100 ? 0.0 : pow(sin(pi * x / 100), 0.7).toDouble();
      return value * envelope * scale;
    });
  }

  Widget _fsrPairChart(
    String region, {
    required List<double> demoLeft,
    required List<double> demoRight,
    required String yLabel,
  }) {
    if (_useFsrDemo) {
      return _lineChart(
        _demoFsrCurve(region, isLeft: true),
        _demoFsrCurve(region, isLeft: false),
        xLabel: '% pha chống đỡ',
        yLabel: yLabel,
      );
    }
    return _lineChart(
      _pairedCurve('left', region),
      _pairedCurve('right', region),
      xLabel: '% pha chống đỡ',
      yLabel: yLabel,
      emptyMessage: 'Chưa đủ một cặp bước trái–phải hợp lệ.',
    );
  }

  Widget _lineChart(
    List<double> left,
    List<double> right, {
    required String xLabel,
    required String yLabel,
    String emptyMessage = 'Chưa có dữ liệu realtime.',
  }) {
    if (left.isEmpty && right.isEmpty) {
      return Center(
        child: Text(
          emptyMessage,
          style: const TextStyle(
            fontSize: 11,
            color: AppColors.textSecondary,
          ),
        ),
      );
    }

    final sampleCount = max(left.length, right.length);
    final normalizedCycle = xLabel.startsWith('%');
    final xScale = normalizedCycle
        ? (sampleCount <= 1 ? 1.0 : 100 / (sampleCount - 1))
        : 0.2;
    final maxX = max(1.0, (sampleCount - 1) * xScale);
    final xInterval = normalizedCycle ? 20.0 : max(1.0, maxX / 5);
    final plottedValues =
        <double>[...left, ...right].where((value) => value.isFinite).toList();
    final dataMin = plottedValues.reduce(min);
    final dataMax = plottedValues.reduce(max);
    final ySpan = max(1.0, dataMax - dataMin);
    final yPadding = max(2.0, ySpan * 0.12);
    final isFlexionAngle = yLabel.contains('Góc gập');
    final isRelativeLoad = yLabel.contains('tải');
    final chartMinY =
        isFlexionAngle || isRelativeLoad ? 0.0 : min(0.0, dataMin - yPadding);
    final chartMaxY =
        isFlexionAngle ? max(50.0, dataMax + yPadding) : dataMax + yPadding;

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
              minY: chartMinY,
              maxY: chartMaxY,
              gridData: FlGridData(
                show: true,
                drawVerticalLine: true,
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
                _series(left, AppColors.leftLeg, xScale: xScale),
                _series(
                  right,
                  AppColors.rightLeg,
                  xScale: xScale,
                  dashed: true,
                ),
              ],
              lineTouchData: const LineTouchData(enabled: false),
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
      isCurved: false,
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
