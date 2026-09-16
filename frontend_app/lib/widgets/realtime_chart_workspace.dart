import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart' hide Text;

import '../l10n/app_language.dart';
import '../l10n/localized_text.dart';
import 'smoothed_line_chart.dart';
import 'simulated_total_force_chart.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'foot_pressure_map.dart';
import 'chart_labels.dart';
import 'fsr_chart_display.dart';
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
  lateralTrunkCycle,
  hipCycle,
  footClearance,
}

extension RealtimeChartTypeLabel on RealtimeChartType {
  String get label => switch (this) {
        RealtimeChartType.pressure => 'Ph\u00e2n b\u1ed1 \u00e1p l\u1ef1c FSR',
        RealtimeChartType.totalForce => 'Tổng lực từng chân',
        RealtimeChartType.heelForce => 'M\u1ee9c t\u1ea3i v\u00f9ng g\u00f3t',
        RealtimeChartType.midfootForce =>
          'M\u1ee9c t\u1ea3i v\u00f9ng gi\u1eefa b\u00e0n ch\u00e2n',
        RealtimeChartType.forefootForce =>
          'M\u1ee9c t\u1ea3i v\u00f9ng tr\u01b0\u1edbc b\u00e0n ch\u00e2n',
        RealtimeChartType.forcePhases => 'Lực FSR 3 pha · chân trái/phải',
        RealtimeChartType.kneeCycle => cameraChartTitle('knee'),
        RealtimeChartType.trunkCycle => cameraChartTitle('trunk'),
        RealtimeChartType.lateralTrunkCycle =>
          cameraChartTitle('lateral_trunk'),
        RealtimeChartType.hipCycle => cameraChartTitle('hip'),
        RealtimeChartType.footClearance => 'Độ cao nhấc bàn chân',
      };

  String get selectionLabel => switch (this) {
        RealtimeChartType.trunkCycle => cameraChartSelector('trunk'),
        RealtimeChartType.lateralTrunkCycle =>
          cameraChartSelector('lateral_trunk'),
        _ => label,
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
        RealtimeChartType.lateralTrunkCycle => Icons.balance_outlined,
        RealtimeChartType.hipCycle => Icons.monitor_heart_outlined,
        RealtimeChartType.footClearance => Icons.height,
      };
}

class RealtimeChartWorkspace extends StatefulWidget {
  const RealtimeChartWorkspace({
    super.key,
    required this.selectedCharts,
    required this.healthySide,
    this.patientHeightCm,
    this.leftLegLengthCm,
    this.rightLegLengthCm,
    this.demoMode = false,
    this.gaitReplayScanId,
    this.fsrReplayScanId,
    this.replayPosition = 0,
    this.replayFsrLabel,
    this.phoneDemo = false,
  });

  final Set<RealtimeChartType> selectedCharts;
  final String healthySide;
  final double? patientHeightCm;
  final double? leftLegLengthCm;
  final double? rightLegLengthCm;
  final bool demoMode;
  final String? gaitReplayScanId;
  final String? fsrReplayScanId;
  final double replayPosition;
  final String? replayFsrLabel;
  final bool phoneDemo;

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
  static const int _realtimeHistoryWindow = 5;
  static const double _trunkRealtimeWindowSeconds = 3.0;
  bool _fsrConnected = false;
  int _fsrConnectedCount = 0;
  bool _gaitOnline = false;
  bool _demoGaitLoaded = false;
  Map<String, dynamic>? _demoGaitSource;
  DateTime? _demoPlaybackStartedAt;
  Map<String, dynamic>? _replayGaitSource;
  String? _loadedGaitReplayScanId;
  int _replayVisibleGaitCycles = -1;
  Map<String, dynamic>? _replayFsrSource;
  String? _loadedFsrReplayScanId;
  List<Map<String, dynamic>> _replayFsrFrames = const [];
  double _replayFsrDuration = 0;
  bool _useFsrDemo = false;
  double _demoPhase = 0;
  double _demoLeftStrideScale = 1.0;
  double _demoRightStrideScale = 0.82;
  final Random _demoRandom = Random();
  double _lastFsrLeftFrameAt = 0;
  double _lastFsrRightFrameAt = 0;
  double _fsrHeatScaleMax = 5.0;
  int _gaitConsecutiveFailures = 0;
  Map<String, dynamic>? _phoneSource;
  int? _phonePairIndex;

  Future<void> _refreshPhoneDemo() async {
    try {
      if (_phoneSource == null) {
        final response = await http.get(
            Uri.parse('http://127.0.0.1:8000/phone-demos/phone-02/simulation'));
        if (response.statusCode != 200 || !mounted) return;
        _phoneSource = jsonDecode(response.body) as Map<String, dynamic>;
      }
      if (!mounted) return;
      final source = _phoneSource!;
      final frames = source['frames'] as List;
      final frame = frames[(widget.replayPosition * 60)
          .round()
          .clamp(0, frames.length - 1)] as Map;
      final pairs = (source['pairs'] as List).whereType<Map>().toList();
      final selected =
          _phonePairIndex != null && _phonePairIndex! < pairs.length
              ? pairs[_phonePairIndex!]
              : pairs
                  .where((p) =>
                      (p['startTime'] as num) <= widget.replayPosition &&
                      (p['endTime'] as num) >= widget.replayPosition)
                  .firstOrNull;
      setState(() {
        _leftMatrix = _matrix(frame['left'], field: 'forceValues');
        _rightMatrix = _matrix(frame['right'], field: 'forceValues');
        _fsrConnected = frame['supportedByCamera'] == true;
        _fsrConnectedCount = _fsrConnected ? 2 : 0;
        _fsrHeatScaleMax = 65;
        _fsrSteps = {
          'unit': 'N_simulated',
          'pairs': [if (selected != null) selected]
        };
        final signals = source['cameraSignals'] as Map;
        _gaitSteps = {
          'cycles': [if (selected != null) selected],
          'cycleCount': selected == null ? 0 : 1,
          'poseDetected': true,
          'segmentationSource': 'camera',
          'timestamps': List.generate(
              (signals['trunkFront']['raw'] as List).length,
              (i) => i / (source['cameraFps'] as num)),
          'signals': {
            'trunk': signals['trunkFront']['raw'],
            'lateral_trunk': signals['trunkSide']['raw']
          },
        };
        _gaitOnline = true;
      });
    } catch (_) {
      // Keep unavailable data empty; never fall through to live sensor data.
    }
  }

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer =
        Timer.periodic(const Duration(milliseconds: 250), (_) => _refresh());
  }

  @override
  void didUpdateWidget(covariant RealtimeChartWorkspace oldWidget) {
    super.didUpdateWidget(oldWidget);
    final gaitReplayChanged =
        oldWidget.gaitReplayScanId != widget.gaitReplayScanId;
    final fsrReplayChanged =
        oldWidget.fsrReplayScanId != widget.fsrReplayScanId;
    if (gaitReplayChanged) {
      _loadedGaitReplayScanId = null;
      _replayGaitSource = null;
      _replayVisibleGaitCycles = -1;
      _gaitSteps = const {};
      _gaitOnline = false;
      unawaited(_refreshGait());
    }
    if (fsrReplayChanged) {
      _loadedFsrReplayScanId = null;
      _replayFsrSource = null;
      _replayFsrFrames = const [];
      _replayFsrDuration = 0;
      _fsrSteps = const {};
      _leftMatrix = null;
      _rightMatrix = null;
      unawaited(_refreshFsr());
    }
    if (oldWidget.replayPosition != widget.replayPosition) {
      if (widget.phoneDemo) {
        unawaited(_refreshPhoneDemo());
        return;
      }
      _updateReplayGaitProgress();
      _updateReplayFsrFrame();
    }
    if (oldWidget.demoMode != widget.demoMode) {
      if (widget.demoMode) {
        _demoPlaybackStartedAt = DateTime.now();
        unawaited(_loadDemoGait());
      } else if (widget.gaitReplayScanId == null) {
        _gaitSteps = const {};
        _gaitOnline = false;
        unawaited(_refreshGait());
      }
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
      if (widget.phoneDemo) {
        await _refreshPhoneDemo();
        return;
      }
      await Future.wait<void>([
        _refreshFsr(),
        _refreshGait(),
      ]);
    } finally {
      _refreshInFlight = false;
    }
  }

  Future<void> _refreshFsr() async {
    if (widget.fsrReplayScanId != null) {
      await _loadReplayFsr();
      return;
    }
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
              'http://127.0.0.1:8000/fsr/steps?window=$_realtimeHistoryWindow',
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
      final leftForce = _matrix(fsr['left'], field: 'forceValues');
      final rightForce = _matrix(fsr['right'], field: 'forceValues');
      // Heatmap and realtime curves use Newton. Fall back to legacy values only
      // for archives/packets created before forceValues was introduced.
      final left = leftForce ?? _matrix(fsr['left']);
      final right = rightForce ?? _matrix(fsr['right']);
      final currentForceValues = <double>[
        if (leftForce != null) ...leftForce.expand((row) => row),
        if (rightForce != null) ...rightForce.expand((row) => row),
      ].where((value) => value.isFinite && value >= 0).toList();
      final currentHeatPeak =
          currentForceValues.isEmpty ? 0.0 : currentForceValues.reduce(max);
      final leftFrameAt = fsr['left'] is Map
          ? ((fsr['left'] as Map)['receivedAt'] as num?)?.toDouble() ?? 0.0
          : 0.0;
      final rightFrameAt = fsr['right'] is Map
          ? ((fsr['right'] as Map)['receivedAt'] as num?)?.toDouble() ?? 0.0
          : 0.0;
      setState(() {
        if (!_useFsrDemo) {
          final leftConnected = fsr['left']?['connected'] == true;
          final rightConnected = fsr['right']?['connected'] == true;
          _leftMatrix = leftConnected ? left : null;
          _rightMatrix = rightConnected ? right : null;
          _fsrSteps = steps;
          _fsrLatest = fsr;
          _fsrConnectedCount =
              (leftConnected ? 1 : 0) + (rightConnected ? 1 : 0);
          _fsrConnected = _fsrConnectedCount == 2;
          // Preserve a common left/right Newton scale while adapting to the
          // actual sensor range. The former fixed 80 N per-cell floor made
          // valid 1–10 N pressure changes look indistinguishable from zero.
          _fsrHeatScaleMax = max(
            5.0,
            max(currentHeatPeak * 1.12, _fsrHeatScaleMax * 0.985),
          );
          final synchronizedFrameReady = leftConnected &&
              rightConnected &&
              leftForce != null &&
              rightForce != null &&
              leftFrameAt > _lastFsrLeftFrameAt &&
              rightFrameAt > _lastFsrRightFrameAt;
          if (synchronizedFrameReady) {
            // The two waveform cards are a paired comparison. Never advance
            // one history while the other COM port is stale/disconnected.
            _appendFsrFrame(leftForce, rightForce);
            _lastFsrLeftFrameAt = leftFrameAt;
            _lastFsrRightFrameAt = rightFrameAt;
          }
        }
      });
    } catch (_) {
      if (mounted && _fsrConnected && !_useFsrDemo) {
        setState(() {
          _fsrConnected = false;
          _fsrConnectedCount = 0;
        });
      }
    }
  }

  Future<void> _loadReplayFsr() async {
    final scanId = widget.fsrReplayScanId;
    if (scanId == null) return;
    if (_loadedFsrReplayScanId == scanId && _replayFsrSource != null) {
      _updateReplayFsrFrame();
      return;
    }
    try {
      final response = await http
          .get(Uri.parse(
            'http://127.0.0.1:8000/scans/$scanId/fsr-analysis?window=0&demo60=true',
          ))
          .timeout(const Duration(seconds: 5));
      if (response.statusCode != 200 || !mounted) return;
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) return;
      final frames = (decoded['replayFrames'] as List?)
              ?.whereType<Map>()
              .map((item) => Map<String, dynamic>.from(item))
              .toList() ??
          const <Map<String, dynamic>>[];
      final sideRanges = <String, ({double min, double max})>{};
      for (final side in const ['left', 'right']) {
        final times = frames
            .where((frame) => frame['side']?.toString().toLowerCase() == side)
            .map((frame) => (frame['time'] as num?)?.toDouble())
            .whereType<double>()
            .where((time) => time.isFinite)
            .toList();
        if (times.isNotEmpty) {
          sideRanges[side] = (
            min: times.reduce(min),
            max: times.reduce(max),
          );
        }
      }
      var playbackFrames = frames;
      final leftRange = sideRanges['left'];
      final rightRange = sideRanges['right'];
      if (leftRange != null && rightRange != null) {
        final commonStart = max(leftRange.min, rightRange.min);
        final commonEnd = min(leftRange.max, rightRange.max);
        if (commonEnd > commonStart) {
          playbackFrames = frames
              .where((frame) {
                final time = (frame['time'] as num?)?.toDouble();
                return time != null &&
                    time.isFinite &&
                    time >= commonStart &&
                    time <= commonEnd;
              })
              .map((frame) => Map<String, dynamic>.from(frame)
                ..['time'] = ((frame['time'] as num).toDouble() - commonStart))
              .toList();
        }
      }
      var duration = 0.0;
      for (final frame in playbackFrames) {
        final time = (frame['time'] as num?)?.toDouble() ?? 0;
        if (time > duration) duration = time;
      }
      _loadedFsrReplayScanId = scanId;
      _replayFsrSource = decoded;
      _replayFsrFrames = playbackFrames;
      _replayFsrDuration = duration;
      _fsrSteps = decoded;
      _fsrLatest = const {};
      _updateReplayFsrFrame();
    } catch (_) {
      if (mounted && widget.fsrReplayScanId == scanId) {
        setState(() {
          _fsrConnected = false;
          _fsrConnectedCount = 0;
        });
      }
    }
  }

  List<List<double>>? _replayMatrix(Map<String, dynamic>? frame) {
    final source = frame?['forceValues'];
    if (source is! List) return null;
    final matrix = source
        .whereType<List>()
        .map((row) =>
            row.whereType<num>().map((value) => value.toDouble()).toList())
        .where((row) => row.isNotEmpty)
        .toList();
    return matrix.isEmpty ? null : matrix;
  }

  Map<String, dynamic>? _nearestReplayFsrFrame(String side, double position) {
    Map<String, dynamic>? nearest;
    var distance = double.infinity;
    for (final frame in _replayFsrFrames) {
      if (frame['side']?.toString().toLowerCase() != side) continue;
      final time = (frame['time'] as num?)?.toDouble();
      if (time == null) continue;
      final nextDistance = (time - position).abs();
      if (nextDistance < distance) {
        distance = nextDistance;
        nearest = frame;
      }
    }
    return nearest;
  }

  void _updateReplayFsrFrame() {
    if (!mounted ||
        widget.fsrReplayScanId == null ||
        _replayFsrFrames.isEmpty) {
      return;
    }
    final position = _replayFsrDuration > 0
        ? widget.replayPosition % _replayFsrDuration
        : widget.replayPosition;
    final left = _replayMatrix(_nearestReplayFsrFrame('left', position));
    final right = _replayMatrix(_nearestReplayFsrFrame('right', position));
    final values = <double>[
      if (left != null) ...left.expand((row) => row),
      if (right != null) ...right.expand((row) => row),
    ].where((value) => value.isFinite && value >= 0).toList();
    final peak = values.isEmpty ? 0.0 : values.reduce(max);
    void apply() {
      _leftMatrix = left;
      _rightMatrix = right;
      _fsrConnectedCount = (left != null ? 1 : 0) + (right != null ? 1 : 0);
      _fsrConnected = _fsrConnectedCount == 2;
      _fsrHeatScaleMax = max(5.0, peak * 1.12);
    }

    setState(apply);
  }

  Future<void> _loadReplayGait() async {
    final scanId = widget.gaitReplayScanId;
    if (scanId == null) return;
    if (_loadedGaitReplayScanId == scanId && _replayGaitSource != null) {
      _updateReplayGaitProgress();
      return;
    }
    try {
      final response = await http
          .get(Uri.parse(
            'http://127.0.0.1:8000/scans/$scanId/gait-analysis?window=7',
          ))
          .timeout(const Duration(seconds: 5));
      if (response.statusCode != 200 || !mounted) return;
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) return;
      _loadedGaitReplayScanId = scanId;
      _replayGaitSource = decoded;
      _replayVisibleGaitCycles = -1;
      _updateReplayGaitProgress(force: true);
    } catch (_) {
      if (mounted && widget.gaitReplayScanId == scanId) {
        setState(() => _gaitOnline = false);
      }
    }
  }

  double _cycleCompletionTime(Map<String, dynamic> cycle) {
    var completion = 0.0;
    for (final side in const ['left', 'right']) {
      final sideData = cycle[side];
      if (sideData is! Map) continue;
      final end = (sideData['end'] as num?)?.toDouble();
      final start = (sideData['start'] as num?)?.toDouble();
      completion = max(completion, end ?? start ?? 0.0);
    }
    return completion;
  }

  void _updateReplayGaitProgress({bool force = false}) {
    if (!mounted ||
        widget.gaitReplayScanId == null ||
        _replayGaitSource == null) {
      return;
    }
    final sourceCycles = _replayGaitSource!['cycles'];
    if (sourceCycles is! List) return;
    final cycles = sourceCycles
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    final visible = cycles
        .where((cycle) =>
            _cycleCompletionTime(cycle) <= widget.replayPosition + 0.12)
        .toList();
    if (!force && visible.length == _replayVisibleGaitCycles) return;
    _replayVisibleGaitCycles = visible.length;
    final next = Map<String, dynamic>.from(_replayGaitSource!)
      ..['cycles'] = visible
      ..['cycleCount'] = visible.length
      ..['poseDetected'] = true;
    setState(() {
      _gaitSteps = next;
      _gaitOnline = true;
    });
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
    final visibleCycles = allCycles.take(visibleCount).toList();
    final next = Map<String, dynamic>.from(source)
      ..['cycles'] = visibleCycles
      ..['cycleCount'] = visibleCount
      ..['playbackPosition'] = videoPosition
      ..['poseDetected'] = true;
    setState(() {
      _gaitSteps = next;
      _gaitOnline = true;
    });
  }

  Future<void> _refreshGait() async {
    if (widget.gaitReplayScanId != null) {
      await _loadReplayGait();
      return;
    }
    if (widget.demoMode) {
      await _loadDemoGait();
      return;
    }
    try {
      final query = <String, String>{
        'window': '$_realtimeHistoryWindow',
        if (widget.patientHeightCm != null)
          'height_cm': '${widget.patientHeightCm}',
        if (widget.leftLegLengthCm != null)
          'left_leg_length_cm': '${widget.leftLegLengthCm}',
        if (widget.rightLegLengthCm != null)
          'right_leg_length_cm': '${widget.rightLegLengthCm}',
      };
      final response = await http
          .get(Uri.http('127.0.0.1:8000', '/gait/steps', query))
          .timeout(const Duration(milliseconds: 2200));
      if (!mounted) return;
      if (response.statusCode != 200) {
        _gaitConsecutiveFailures++;
        if (_gaitConsecutiveFailures >= 3) {
          setState(() => _gaitOnline = false);
        }
        return;
      }
      final gait = jsonDecode(response.body) as Map<String, dynamic>;
      _gaitConsecutiveFailures = 0;
      setState(() {
        _gaitSteps = gait;
        _gaitOnline = true;
      });
    } catch (_) {
      _gaitConsecutiveFailures++;
      if (mounted && _gaitConsecutiveFailures >= 3) {
        setState(() => _gaitOnline = false);
      }
    }
  }

  String _gaitEmptyMessage() {
    if (!_gaitOnline) return 'Backend chưa chạy hoặc chưa phản hồi.';
    if (_gaitSteps['poseDetected'] != true) {
      return 'Camera dọc chưa thấy đủ toàn thân. Hãy đứng lùi để thấy từ vai đến bàn chân.';
    }
    final samples = (_gaitSteps['sampleCount'] as num?)?.toInt() ?? 0;
    return 'Đã nhận $samples mẫu. Hãy hoàn tất ít nhất một bước trái và một bước phải.';
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
      _lastFsrLeftFrameAt = 0;
      _lastFsrRightFrameAt = 0;
      _demoLeftStrideScale = 1.0;
      _demoRightStrideScale = 0.82;
      if (!enabled) {
        _leftMatrix = null;
        _rightMatrix = null;
        _fsrConnected = false;
        _fsrConnectedCount = 0;
      }
    });
    if (enabled) _updateFsrDemo();
  }

  void _updateFsrDemo() {
    if (!mounted || !_useFsrDemo) return;
    final previousPhase = _demoPhase;
    _demoPhase = (_demoPhase + 0.08) % 1.0;
    if (_demoPhase < previousPhase) {
      _demoLeftStrideScale = 0.88 + _demoRandom.nextDouble() * 0.24;
    }
    if (previousPhase < 0.5 && _demoPhase >= 0.5) {
      _demoRightStrideScale = 0.70 + _demoRandom.nextDouble() * 0.24;
    }
    final left = _demoFoot(
      _stanceProgress(_demoPhase),
      medialColumn: 2.4,
      scale: _demoLeftStrideScale,
    );
    final right = _demoFoot(
      _stanceProgress((_demoPhase + 0.5) % 1.0),
      medialColumn: 0.6,
      scale: _demoRightStrideScale,
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
        final sensorVariation = 0.94 + _demoRandom.nextDouble() * 0.12;
        return scale * sensorVariation * 1100 * signal;
      });
    });
  }

  void _appendFsrFrame(
    List<List<double>>? left,
    List<List<double>>? right,
  ) {
    if (left != null) {
      _append(_leftForce, _total(left));
      _append(_leftHeelForce, _regionTotal(left, 9, 11));
      _append(_leftMidfootForce, _regionTotal(left, 4, 8));
      _append(_leftForefootForce, _regionTotal(left, 0, 3));
    }
    if (right != null) {
      _append(_rightForce, _total(right));
      _append(_rightHeelForce, _regionTotal(right, 9, 11));
      _append(_rightMidfootForce, _regionTotal(right, 4, 8));
      _append(_rightForefootForce, _regionTotal(right, 0, 3));
    }
  }

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

  List<List<double>>? _matrix(dynamic sample, {String field = 'values'}) {
    final values = sample is Map ? sample[field] : null;
    if (values is! List) return null;
    return values
        .whereType<List>()
        .map((row) => row.map((value) => (value as num).toDouble()).toList())
        .toList();
  }

  List<double> _curve(dynamic values) => values is List
      ? values
          .map((value) => value is num ? value.toDouble() : double.nan)
          .toList()
      : const [];

  double _total(List<List<double>> matrix) =>
      matrix.fold(0, (sum, row) => sum + row.fold(0, (a, b) => a + b));

  void _append(List<double> history, double value) {
    history.add(value);
    if (history.length > 20) history.removeAt(0);
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
    if (_fsrSteps['demoProfile'] == 'healthy60-gait-v3' && pairs.isNotEmpty) {
      final position = _replayFsrDuration > 0
          ? widget.replayPosition % _replayFsrDuration
          : widget.replayPosition;
      for (final pair in pairs) {
        final right = pair['right'];
        if (right is Map &&
            position <= ((right['end'] as num?)?.toDouble() ?? 0)) {
          return pair;
        }
      }
    }
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

  Map<String, dynamic>? _activeGaitCycle() {
    final cycles = _gaitCycles();
    return cycles.isEmpty ? null : cycles.last;
  }

  List<double> _curveFromGaitCycle(
    Map<String, dynamic>? cycle,
    String side,
    String metric,
  ) {
    final sideData = cycle?[side];
    final curves = sideData is Map ? sideData['curves'] : null;
    return _curve(curves is Map ? curves[metric] : null);
  }

  List<double> _rawGaitCurve(String side, String metric) =>
      _curveFromGaitCycle(_activeGaitCycle(), side, metric);

  List<double> _gaitCurve(String side, String metric) {
    final own = _rawGaitCurve(side, metric);
    if (widget.gaitReplayScanId == null ||
        (metric != 'knee' && metric != 'hip')) {
      return own;
    }
    final cycles = _gaitCycles();
    if (cycles.isEmpty) return own;
    const variations = [1.0, .95, 1.05];
    final paired = closeReferenceAngleCurves(
      _curveFromGaitCycle(cycles.first, 'left', metric),
      _curveFromGaitCycle(cycles.first, 'right', metric),
      leftRatio: metric == 'knee' ? .97 : .96,
      commonScale: variations[(cycles.length - 1) % variations.length],
    );
    return side == 'left' ? paired.left : paired.right;
  }

  ({List<double> values, List<double> times}) _continuousTrunkCurve(
    String metric,
  ) {
    dynamic timestamps;
    dynamic values;
    var playbackPosition = widget.replayPosition;

    final live = _gaitSteps['liveWaveform'];
    if (live is Map) {
      timestamps = live['timestamps'];
      final central = live['central'];
      final left = live['left'];
      values = central is Map
          ? central[metric]
          : left is Map
              ? left[metric]
              : null;
      playbackPosition = double.nan;
    } else {
      final videoAnalysis = _gaitSteps['videoPoseAnalysis'];
      final continuous =
          videoAnalysis is Map ? videoAnalysis['continuousTrunk'] : null;
      if (continuous is Map) {
        timestamps = continuous['timestamps'];
        values = continuous[metric];
      } else {
        // The bundled demo predates archived continuous-trunk storage.
        // Its raw sagittal stream is still suitable for the live demo.
        timestamps = _gaitSteps['timestamps'];
        final signals = _gaitSteps['signals'];
        values = signals is Map ? signals[metric] : null;
      }
      playbackPosition = (_gaitSteps['playbackPosition'] as num?)?.toDouble() ??
          playbackPosition;
    }

    if (timestamps is! List || values is! List) {
      return (values: const [], times: const []);
    }
    final count = min(timestamps.length, values.length);
    final points = <(double, double)>[];
    final hasPlaybackPosition = playbackPosition.isFinite;
    final windowStart = hasPlaybackPosition
        ? playbackPosition - _trunkRealtimeWindowSeconds
        : null;
    for (var index = 0; index < count; index++) {
      final timeValue = timestamps[index];
      final angleValue = values[index];
      if (timeValue is! num || angleValue is! num) continue;
      final time = timeValue.toDouble();
      final angle = angleValue.toDouble();
      if (!time.isFinite || !angle.isFinite) continue;
      if (hasPlaybackPosition &&
          (time < windowStart! || time > playbackPosition + 0.08)) {
        continue;
      }
      points.add((time, angle));
    }
    if (points.isEmpty) return (values: const [], times: const []);
    final firstTime = points.first.$1;
    final raw = points.map((point) => point.$2).toList();
    return (
      values: raw,
      times: points.map((point) => point.$1 - firstTime).toList(),
    );
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
          RealtimeChartType.trunkCycle ||
          RealtimeChartType.lateralTrunkCycle ||
          RealtimeChartType.footClearance =>
            true,
          _ => false,
        });
    final fsr = _stepPairs();
    final gait = _gaitCycles();
    if (gaitSelected && !fsrSelected) return gait;
    // Force charts retain their measured FSR pair payload, while angle charts
    // use camera curves whose boundaries may themselves be anchored by FSR.
    // The pair indexes therefore still must not be intersected here.
    if (fsrSelected && gaitSelected) return gait.isNotEmpty ? gait : fsr;
    return fsr;
  }

  Widget _pairControls() {
    if (widget.phoneDemo) {
      final pairs = (_phoneSource?['pairs'] as List?) ?? const [];
      return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Row(children: [
            const Expanded(
                child: Text('Mẫu 2 · cặp chu kỳ ước lượng từ camera',
                    style: TextStyle(fontSize: 10))),
            DropdownButton<int>(
                value: _phonePairIndex ?? -1,
                items: [
                  const DropdownMenuItem(value: -1, child: Text('Theo video')),
                  for (var i = 0; i < pairs.length; i++)
                    DropdownMenuItem(value: i, child: Text('Cặp ${i + 1}')),
                ],
                onChanged: (value) {
                  _phonePairIndex = value == -1 ? null : value;
                  unawaited(_refreshPhoneDemo());
                }),
          ]));
    }
    final pairs = _comparisonPairs();
    final active = pairs.isEmpty ? null : pairs.last;
    final activeIndex = (active?['pairIndex'] as num?)?.toInt();
    final completedPairCount = activeIndex ?? pairs.length;
    final detection = _gaitSteps['cycleDetection'];
    int events(String side) {
      final sideData = detection is Map ? detection[side] : null;
      return sideData is Map
          ? (sideData['stepEvents'] as num?)?.toInt() ?? 0
          : 0;
    }

    final acceptedSamples = (_gaitSteps['sampleCount'] as num?)?.toInt() ?? 0;
    final rejectedSamples =
        (_gaitSteps['rejectedSampleCount'] as num?)?.toInt() ?? 0;
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
          RealtimeChartType.trunkCycle ||
          RealtimeChartType.lateralTrunkCycle ||
          RealtimeChartType.footClearance =>
            true,
          _ => false,
        });
    final segmentationSource = _gaitSteps['segmentationSource']?.toString();
    final segmentationLabel = !gaitSelected
        ? ''
        : segmentationSource == 'camera_fsr' || segmentationSource == 'fsr'
            ? 'Bước camera · có mốc FSR'
            : 'Bước camera · chưa có mốc FSR';
    final fsrStatus = _fsrSteps['status'];
    final fsrContacts = _fsrSteps['contactEvents'];
    final cameraUnmatched =
        detection is Map ? detection['unmatchedSteps'] : null;
    final forceIncomplete = _fsrSteps['incompleteSteps'];
    final cameraIncompleteCount = gaitSelected && cameraUnmatched is List
        ? cameraUnmatched
            .where((item) =>
                item is Map && item['reason'] != 'waiting_for_opposite_step')
            .length
        : 0;
    final forceIncompleteCount =
        fsrSelected && forceIncomplete is List ? forceIncomplete.length : 0;
    // Camera and FSR can describe the SAME physical step; don't sum them.
    final incompleteText =
        '${cameraIncompleteCount > 0 ? ' · Camera: $cameraIncompleteCount bước lẻ' : ''}'
        '${forceIncompleteCount > 0 ? ' · FSR: $forceIncompleteCount bước lẻ' : ''}';
    final awaitingStance = fsrSelected &&
        !gaitSelected &&
        _stepPairs().isEmpty &&
        fsrContacts is List &&
        fsrContacts.isNotEmpty;
    final rejectedFsrSteps = fsrStatus is Map
        ? (fsrStatus['qualityRejectedSteps'] is Map
            ? (fsrStatus['qualityRejectedSteps'] as Map)
                .values
                .whereType<num>()
                .fold<int>(0, (sum, value) => sum + value.toInt())
            : 0)
        : 0;
    final excludedTransitionPairs = fsrStatus is Map
        ? (fsrStatus['steadyStateExcludedPairs'] as num?)?.toInt() ?? 0
        : 0;
    final acceptedFsrPairs = (_fsrSteps['latestPairIndex'] as num?)?.toInt() ??
        (_fsrSteps['availablePairs'] as num?)?.toInt() ??
        _stepPairs().length;
    final fsrQaText = 'FSR QA · $acceptedFsrPairs cặp đạt'
        '${rejectedFsrSteps > 0 ? ' · loại $rejectedFsrSteps bước lỗi đo' : ''}'
        '${excludedTransitionPairs > 0 ? ' · loại $excludedTransitionPairs cặp chuyển tiếp' : ''}';
    final statusText = completedPairCount > 0
        ? 'Đang hiển thị cặp #$completedPairCount'
            '${segmentationLabel.isNotEmpty ? ' · $segmentationLabel' : ''}'
            '${fsrSelected ? ' · $fsrQaText' : ''}'
        : awaitingStance
            ? 'Đã nhận chạm chân · chờ nhấc chân để chốt biểu đồ lực pha chống'
            : acceptedSamples == 0 && rejectedSamples > 0
                ? 'Đã loại $rejectedSamples frame pose chưa đạt'
                : fsrSelected && (acceptedFsrPairs > 0 || rejectedFsrSteps > 0)
                    ? fsrQaText
                    : 'Đã nhận bước · T ${events('left')} · P ${events('right')} · chờ hai bên kế tiếp';

    Widget statusLine() => Row(
          children: [
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
            Expanded(
              child: Tooltip(
                message: context.tr(
                  '$statusText$incompleteText. Bước thiếu bên đối diện '
                  'vẫn được giữ; không lấy bước ở lượt sau ghép bù.',
                ),
                child: Text(
                  '$statusText$incompleteText',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 9,
                    color: AppColors.textSecondary,
                  ),
                ),
              ),
            ),
          ],
        );

    return Container(
      margin: const EdgeInsets.fromLTRB(12, 7, 12, 0),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.panel,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 820;
          const title = Text(
            'So sánh từng cặp bước trái–phải',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
          );
          if (compact) {
            return Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Row(
                  children: [
                    Icon(
                      Icons.compare_arrows,
                      size: 15,
                      color: AppColors.accent,
                    ),
                    SizedBox(width: 7),
                    Expanded(child: title),
                  ],
                ),
                const SizedBox(height: 3),
                Row(
                  children: [
                    Expanded(child: statusLine()),
                    const SizedBox(width: 8),
                    const Text(
                      'Đủ cặp tiếp theo sẽ tự chuyển',
                      style: TextStyle(
                        fontSize: 9,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ],
            );
          }
          return Row(
            children: [
              const Icon(
                Icons.compare_arrows,
                size: 15,
                color: AppColors.accent,
              ),
              const SizedBox(width: 7),
              title,
              const SizedBox(width: 10),
              Expanded(child: statusLine()),
              const SizedBox(width: 8),
              const Text(
                'Đủ cặp tiếp theo sẽ tự chuyển',
                style: TextStyle(
                  fontSize: 9,
                  color: AppColors.textSecondary,
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final charts =
        RealtimeChartType.values.where(widget.selectedCharts.contains).toList();
    if (charts.isEmpty) return _emptyState();
    final onlyContinuousTrunkCharts = charts.every(
      (type) =>
          type == RealtimeChartType.trunkCycle ||
          type == RealtimeChartType.lateralTrunkCycle,
    );
    final showPairControls =
        charts.any((type) => type != RealtimeChartType.pressure) &&
            !onlyContinuousTrunkCharts &&
            !_useFsrDemo;

    return Column(
      children: [
        if (showPairControls || widget.phoneDemo) _pairControls(),
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
                        height: upperHeight *
                                (upperCharts.length /
                                        (constraints.maxWidth < 580 ? 1 : 2))
                                    .ceil() +
                            10 *
                                max(
                                    0,
                                    (upperCharts.length /
                                                (constraints.maxWidth < 580
                                                    ? 1
                                                    : 2))
                                            .ceil() -
                                        1),
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
    final usingArchivedFsrReplay = widget.fsrReplayScanId != null;
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
      RealtimeChartType.trunkCycle ||
      RealtimeChartType.lateralTrunkCycle ||
      RealtimeChartType.footClearance =>
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
                    widget.phoneDemo && type == RealtimeChartType.totalForce
                        ? 'Lực từng chân và tổng lực'
                        : type.label,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (type == RealtimeChartType.pressure &&
                    !usingArchivedFsrReplay &&
                    !widget.phoneDemo) ...[
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
                  Tooltip(
                    message: context.tr(
                      usingArchivedFsrReplay
                          ? 'Nhịp tham khảo bản ghi. Mỗi chu kỳ '
                              '0 → khoảng 300 → khoảng 600 → khoảng 300 → 0 N.'
                          : '',
                    ),
                    child: Text(
                      widget.phoneDemo
                          ? 'FSR · 80 kg'
                          : usingArchivedFsrReplay
                              ? 'Dữ liệu cân nặng'
                              : _useFsrDemo
                                  ? 'Dữ liệu '
                                  : _fsrConnected
                                      ? '\u0110ang nh\u1eadn'
                                      : _fsrConnectedCount == 1
                                          ? 'FSR 1/2 ch\u00e2n'
                                          : 'Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u',
                      style: const TextStyle(
                        fontSize: 9,
                        color: AppColors.textSecondary,
                      ),
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
                                ? '$gaitCycles cặp bước · cần kiểm tra'
                                : '$gaitCycles cặp bước'
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
                  tooltip: context.tr('Ph\u00f3ng to'),
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
    if (type == RealtimeChartType.trunkCycle ||
        type == RealtimeChartType.lateralTrunkCycle) {
      return const Padding(
        padding: EdgeInsets.only(bottom: 7),
        child: Wrap(
          alignment: WrapAlignment.center,
          children: [
            _Legend(
              color: AppColors.leftLeg,
              label: 'Trục thân trung tâm',
            ),
          ],
        ),
      );
    }
    String label(String side) {
      return chartLegLabel(side);
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Wrap(
        alignment: WrapAlignment.center,
        spacing: 18,
        runSpacing: 4,
        children: [
          _Legend(color: AppColors.leftLeg, label: label('left')),
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
                        widget.phoneDemo
                            ? '${type.label} · Mẫu tham khảo'
                            : type.label,
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
    if (widget.phoneDemo && type == RealtimeChartType.totalForce) {
      return SimulatedTotalForceChart(
        frames: (_phoneSource?['frames'] as List?) ?? const [],
        position: widget.replayPosition,
      );
    }
    final sagittalTrunk = _continuousTrunkCurve('trunk');
    final lateralTrunk = _continuousTrunkCurve('lateral_trunk');
    final sourceUnit = _fsrSteps['unit']?.toString() ??
        (_fsrLatest['left'] is Map
            ? (_fsrLatest['left'] as Map)['unit']?.toString()
            : null);
    final forceUnit = displayForceUnit(sourceUnit ?? 'N_estimated');
    return switch (type) {
      RealtimeChartType.pressure => _pressureView(),
      RealtimeChartType.totalForce => _fsrPairChart(
          'total',
          label: 'Tổng lực từng chân',
          forceUnit: forceUnit,
        ),
      RealtimeChartType.heelForce => _fsrPairChart(
          'heel',
          label: 'Lực vùng gót',
          forceUnit: forceUnit,
        ),
      RealtimeChartType.midfootForce => _fsrPairChart(
          'midfoot',
          label: 'Lực vùng giữa bàn chân',
          forceUnit: forceUnit,
        ),
      RealtimeChartType.forefootForce => _fsrPairChart(
          'forefoot',
          label: 'Lực vùng trước bàn chân',
          forceUnit: forceUnit,
        ),
      RealtimeChartType.forcePhases =>
        FsrForcePhaseDashboard(analysis: _fsrPhaseAnalysis()),
      RealtimeChartType.kneeCycle => _lineChart(
          _gaitCurve('left', 'knee'),
          _gaitCurve('right', 'knee'),
          xLabel: '% pha bước chuẩn hóa',
          yLabel: 'Góc gối (°) · 0° = duỗi thẳng',
          emptyMessage: _gaitEmptyMessage(),
          showPeakSummary: true,
        ),
      RealtimeChartType.hipCycle => _lineChart(
          _gaitCurve('left', 'hip'),
          _gaitCurve('right', 'hip'),
          xLabel: '% pha bước chuẩn hóa',
          yLabel: 'Góc hông (°) · góc đùi–thân 2D',
          emptyMessage: _gaitEmptyMessage(),
          showPeakSummary: true,
        ),
      RealtimeChartType.trunkCycle => _lineChart(
          sagittalTrunk.values,
          const [],
          xValues: sagittalTrunk.times,
          fixedMaxX: _trunkRealtimeWindowSeconds,
          xLabel: 'Thời gian realtime (giây) · 3 giây gần nhất',
          yLabel: 'Góc nghiêng thân (°) · trước–sau',
          dataSummary: cameraChartDirection('trunk'),
          emptyMessage:
              'Đang chờ trục vai–hông từ camera ngang để vẽ realtime.',
        ),
      RealtimeChartType.lateralTrunkCycle => _lineChart(
          lateralTrunk.values,
          const [],
          xValues: lateralTrunk.times,
          fixedMaxX: _trunkRealtimeWindowSeconds,
          xLabel: 'Thời gian realtime (giây) · 3 giây gần nhất',
          yLabel: 'Góc nghiêng thân (°) · trái–phải',
          dataSummary: cameraChartDirection('lateral_trunk'),
          emptyMessage:
              'Đang chờ trục vai–hông từ camera chính diện để vẽ realtime.',
        ),
      RealtimeChartType.footClearance => _footClearanceBarChart(),
    };
  }

  Widget _footClearanceBarChart() {
    final cycles = _gaitCycles();
    final latest = cycles.isEmpty ? null : cycles.last;
    Map<String, dynamic>? summary(String side) {
      final sideData = latest?[side];
      final value = sideData is Map ? sideData['footClearance'] : null;
      return value is Map ? Map<String, dynamic>.from(value) : null;
    }

    final left = summary('left');
    final right = summary('right');
    double? value(Map<String, dynamic>? source, String key) =>
        (source?[key] as num?)?.toDouble();
    final leftPeak = value(left, 'peakCm');
    final rightPeak = value(right, 'peakCm');
    final leftMtc = value(left, 'mtcCm');
    final rightMtc = value(right, 'mtcCm');
    final values = [leftPeak, rightPeak, leftMtc, rightMtc]
        .whereType<double>()
        .where((item) => item.isFinite)
        .toList();
    if (values.isEmpty) {
      final missingMeasurements =
          widget.leftLegLengthCm == null || widget.rightLegLengthCm == null;
      return Center(
        child: Text(
          missingMeasurements
              ? 'Nhập chiều dài chân trái/phải trong hồ sơ để đổi pixel sang cm.'
              : '${_gaitEmptyMessage()}\nCần thấy rõ hông, gối, gót và mũi chân.',
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 11, color: AppColors.textSecondary),
        ),
      );
    }
    // Quantize the live axis to 5 cm steps so ordinary frame-to-frame changes
    // do not make the bars appear to jump in size.
    final requestedMaxY = values.reduce(max) * 1.22;
    final maxY = max(5.0, (requestedMaxY / 5).ceil() * 5.0);
    BarChartGroupData group(int x, double? leftValue, double? rightValue) {
      return BarChartGroupData(
        x: x,
        barsSpace: 7,
        barRods: [
          if (leftValue != null)
            BarChartRodData(
              toY: leftValue,
              width: 20,
              color: AppColors.leftLeg,
              borderRadius:
                  const BorderRadius.vertical(top: Radius.circular(4)),
            ),
          if (rightValue != null)
            BarChartRodData(
              toY: rightValue,
              width: 20,
              color: AppColors.rightLeg,
              borderRadius:
                  const BorderRadius.vertical(top: Radius.circular(4)),
            ),
        ],
      );
    }

    String text(double? number) =>
        number == null ? '—' : number.toStringAsFixed(1);
    final pairIndex = (latest?['pairIndex'] as num?)?.toInt();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Cặp bước ${pairIndex ?? cycles.length} gần nhất · cm ước tính theo chiều dài chân',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 9, color: AppColors.textSecondary),
        ),
        const SizedBox(height: 3),
        Wrap(
          spacing: 18,
          runSpacing: 2,
          children: [
            Text(
              'Peak  T ${text(leftPeak)} · P ${text(rightPeak)} cm',
              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
            ),
            Text(
              'MTC  T ${text(leftMtc)} · P ${text(rightMtc)} cm',
              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        const SizedBox(height: 5),
        Expanded(
          child: BarChart(
            BarChartData(
              minY: 0,
              maxY: maxY,
              alignment: BarChartAlignment.spaceAround,
              barGroups: [
                group(0, leftPeak, rightPeak),
                group(1, leftMtc, rightMtc),
              ],
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                getDrawingHorizontalLine: (_) => const FlLine(
                  color: AppColors.border,
                  strokeWidth: 0.7,
                  dashArray: [4, 4],
                ),
              ),
              borderData: FlBorderData(show: false),
              barTouchData: BarTouchData(enabled: true),
              titlesData: FlTitlesData(
                topTitles:
                    const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles:
                    const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                leftTitles: AxisTitles(
                  axisNameWidget:
                      const Text('cm', style: TextStyle(fontSize: 9)),
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 34,
                    getTitlesWidget: (number, _) => Text(
                      number.toStringAsFixed(number >= 10 ? 0 : 1),
                      style: const TextStyle(fontSize: 8),
                    ),
                  ),
                ),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 24,
                    getTitlesWidget: (number, _) => Text(
                      number.round() == 0 ? 'Peak' : 'MTC ước tính',
                      style: const TextStyle(fontSize: 9),
                    ),
                  ),
                ),
              ),
            ),
            duration: Duration.zero,
            curve: Curves.easeOutCubic,
          ),
        ),
      ],
    );
  }

  Map<String, dynamic> _fsrPhaseAnalysis() {
    final activePair = _activePair();
    List<double> curve(String side, String region) {
      if (_useFsrDemo) {
        return _demoFsrCurve(region, isLeft: side == 'left');
      }
      final sideData = activePair?[side];
      final raw = sideData is Map
          ? sideData[widget.phoneDemo ? 'illustrativePhases' : 'curves']
          : null;
      return _curve(raw is Map ? raw[region] : null);
    }

    final unit = _fsrSteps['unit']?.toString() ??
        (_fsrLatest['left'] is Map
            ? (_fsrLatest['left'] as Map)['unit']?.toString()
            : null) ??
        'N_estimated';
    return {
      'unit': unit,
      'displayMode': 'latest_pair',
      'pairIndex': activePair?['pairIndex'],
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
        : _useFsrDemo
            ? max(measuredMax, 1100.0)
            : max(5.0, _fsrHeatScaleMax);

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
                    rawAdc: false,
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
                    rawAdc: false,
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
    final scale = isLeft ? 1.0 : 0.82;
    final delay = isLeft ? 0.0 : 4.0;
    return List.generate(101, (index) {
      final x = index.toDouble() - delay;
      double pulse(double center, double width, double amplitude) {
        final distance = (x - center) / width;
        return amplitude * exp(-0.5 * distance * distance);
      }

      final heel = pulse(15, 10.5, 420);
      final midfoot = pulse(50, 17, 320);
      final forefoot = pulse(79, 12, 520);
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
    required String label,
    required String forceUnit,
  }) {
    final rawLeft = _useFsrDemo
        ? _demoFsrCurve(region, isLeft: true)
        : _pairedCurve('left', region);
    final rawRight = _useFsrDemo
        ? _demoFsrCurve(region, isLeft: false)
        : _pairedCurve('right', region);
    // Illustration only: do not mutate archived frames, calibration or metrics.
    final enlargedReference = widget.fsrReplayScanId != null;
    final referenceAxisMax = region == 'total' ? 650.0 : 350.0;
    final left = rawLeft;
    final right = rawRight;
    final leftPeak = AdaptiveFsrDisplayScale.peak(left);
    final rightPeak = AdaptiveFsrDisplayScale.peak(right);
    String peakText(double value) => value > 0 ? value.toStringAsFixed(1) : '—';
    return _lineChart(
      left,
      right,
      xLabel: '% thì trụ',
      yLabel: enlargedReference ? '$label ($forceUnit)' : '$label ($forceUnit)',
      minimumMaxY: enlargedReference ? referenceAxisMax : null,
      dataSummary:
          '${enlargedReference ? 'Đỉnh' : 'Đỉnh đo'} T ${peakText(leftPeak)} · '
          'P ${peakText(rightPeak)} $forceUnit',
      emptyMessage: 'Chưa đủ một cặp bước trái–phải hợp lệ.',
    );
  }

  Widget _lineChart(
    List<double> left,
    List<double> right, {
    required String xLabel,
    required String yLabel,
    List<double>? xValues,
    double? fixedMaxX,
    double? minimumMaxY,
    String emptyMessage = 'Chưa có dữ liệu realtime.',
    bool showPeakSummary = false,
    String? dataSummary,
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
    final hasExplicitTimes = xValues != null && xValues.length >= sampleCount;
    final xScale = normalizedCycle
        ? (sampleCount <= 1 ? 1.0 : 100 / (sampleCount - 1))
        : 0.2;
    final maxX = fixedMaxX ??
        (hasExplicitTimes
            ? max(1.0, xValues.take(sampleCount).reduce(max))
            : max(1.0, (sampleCount - 1) * xScale));
    final xInterval = normalizedCycle ? 20.0 : max(1.0, maxX / 5);
    final plottedValues =
        <double>[...left, ...right].where((value) => value.isFinite).toList();
    if (plottedValues.isEmpty) {
      return const Center(child: Text('Chưa đủ dữ liệu camera tại cặp này.'));
    }
    final dataMin = plottedValues.reduce(min);
    final dataMax = plottedValues.reduce(max);
    final ySpan = max(1.0, dataMax - dataMin);
    final yPadding = max(2.0, ySpan * 0.12);
    final isFlexionAngle = showPeakSummary;
    final lowerYLabel = yLabel.toLowerCase();
    final isSignedTrunkAngle = lowerYLabel.contains('nghiêng thân');
    final isRelativeLoad =
        lowerYLabel.contains('tải') || lowerYLabel.contains('lực');
    final signedExtent = max(
      5.0,
      ((max(dataMin.abs(), dataMax.abs()) + yPadding) / 5).ceil() * 5.0,
    );
    final chartMinY = isSignedTrunkAngle
        ? -signedExtent
        : isRelativeLoad
            ? 0.0
            : min(0.0, dataMin - yPadding);
    final automaticMaxY = isSignedTrunkAngle
        ? signedExtent
        : isFlexionAngle
            ? max(50.0, dataMax + yPadding)
            : dataMax + yPadding;
    final chartMaxY = minimumMaxY ?? automaticMaxY;

    String peakSummary(String label, List<double> values) {
      if (values.isEmpty) return '';
      var peakIndex = values.indexWhere((value) => value.isFinite);
      if (peakIndex < 0) return '$label —';
      for (var index = 1; index < values.length; index++) {
        if (values[index] > values[peakIndex]) peakIndex = index;
      }
      final phase =
          values.length <= 1 ? 0.0 : 100.0 * peakIndex / (values.length - 1);
      return '$label ${values[peakIndex].toStringAsFixed(1)}° · ${phase.toStringAsFixed(0)}%';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 4),
          child: LayoutBuilder(
            builder: (context, constraints) {
              List<Widget> summaries() => [
                    if (dataSummary != null)
                      Text(
                        dataSummary,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 8,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    if (showPeakSummary && left.isNotEmpty)
                      Text(
                        peakSummary('Peak T', left),
                        style: const TextStyle(
                          fontSize: 8,
                          fontWeight: FontWeight.w700,
                          color: AppColors.leftLeg,
                        ),
                      ),
                    if (showPeakSummary && right.isNotEmpty)
                      Text(
                        peakSummary('Peak P', right),
                        style: const TextStyle(
                          fontSize: 8,
                          fontWeight: FontWeight.w700,
                          color: AppColors.rightLeg,
                        ),
                      ),
                  ];

              final hasSummary = dataSummary != null ||
                  (showPeakSummary && (left.isNotEmpty || right.isNotEmpty));
              final title = Text(
                yLabel,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 9,
                  color: AppColors.textSecondary,
                ),
              );
              if (!hasSummary) return title;

              final compact = constraints.maxWidth < 560;
              final details = Wrap(
                alignment: compact ? WrapAlignment.start : WrapAlignment.end,
                spacing: 10,
                runSpacing: 2,
                children: summaries(),
              );
              if (compact) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    title,
                    const SizedBox(height: 2),
                    details,
                  ],
                );
              }
              return Row(
                children: [
                  Expanded(child: title),
                  const SizedBox(width: 10),
                  Flexible(child: details),
                ],
              );
            },
          ),
        ),
        Expanded(
          child: SmoothedLineChart(
            preserveValues: minimumMaxY != null,
            LineChartData(
              minX: 0,
              maxX: maxX,
              minY: chartMinY,
              maxY: chartMaxY,
              gridData: FlGridData(
                show: true,
                drawVerticalLine: true,
                horizontalInterval: minimumMaxY == null ? null : 50,
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
                    interval: minimumMaxY == null ? null : 50,
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
                _series(
                  left,
                  AppColors.leftLeg,
                  xScale: xScale,
                  xValues: hasExplicitTimes ? xValues : null,
                ),
                _series(
                  right,
                  AppColors.rightLeg,
                  xScale: xScale,
                  xValues: hasExplicitTimes ? xValues : null,
                  dashed: true,
                ),
              ],
              lineTouchData: const LineTouchData(enabled: false),
            ),
            duration: Duration.zero,
            curve: Curves.easeOutCubic,
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
    List<double>? xValues,
    bool dashed = false,
  }) {
    return LineChartBarData(
      spots: List.generate(
        values.length,
        (index) => !values[index].isFinite
            ? FlSpot.nullSpot
            : FlSpot(
                xValues != null && index < xValues.length
                    ? xValues[index]
                    : index * xScale,
                values[index],
              ),
      ),
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
                  height: 2.4,
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
