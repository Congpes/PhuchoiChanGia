import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../models/analysis_segment.dart';
import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'realtime_chart_workspace.dart';
import 'recording_timeline.dart';
import 'video_stream.dart';

class TabScan extends StatefulWidget {
  const TabScan({super.key});

  @override
  State<TabScan> createState() => _TabScanState();
}

class _TabScanState extends State<TabScan> {
  bool _sidebarOpen = false;
  bool _chartsExpanded = true;
  bool? _camera0Connected;
  bool? _camera1Connected;
  bool? _camera1PoseDetected;
  bool _camerasSwapped = false;
  bool _swappingCameras = false;
  Timer? _cameraTimer;
  double? _pendingStart;
  final List<AnalysisSegment> _segments = [];
  String? _loadedSegmentSessionId;
  bool _loadingSegments = false;
  final Set<RealtimeChartType> _selectedCharts = {};

  @override
  void initState() {
    super.initState();
    _pollCameraStatus();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      context.read<SessionProvider>().syncRecordingStatus();
    });
    _cameraTimer = Timer.periodic(
      const Duration(seconds: 2),
      (_) => _pollCameraStatus(),
    );
  }

  @override
  void dispose() {
    _cameraTimer?.cancel();
    super.dispose();
  }

  Future<void> _pollCameraStatus() async {
    try {
      final response = await http
          .get(Uri.parse('http://127.0.0.1:8000/camera-status'))
          .timeout(const Duration(milliseconds: 900));
      if (response.statusCode != 200 || !mounted) return;
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      setState(() {
        _camera0Connected = body['camera0']?['connected'] == true;
        _camera1Connected = body['camera1']?['connected'] == true;
        _camera1PoseDetected = body['camera1']?['poseDetected'] == true;
        _camerasSwapped = body['swapped'] == true;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _camera0Connected = false;
          _camera1Connected = false;
          _camera1PoseDetected = false;
        });
      }
    }
  }

  Future<void> _loadSegments(String sessionId, {bool force = false}) async {
    if (_loadingSegments || (!force && _loadedSegmentSessionId == sessionId)) {
      return;
    }
    _loadingSegments = true;
    try {
      final response = await http
          .get(Uri.parse(
              'http://127.0.0.1:8000/sessions/$sessionId/analysis-clips'))
          .timeout(const Duration(seconds: 3));
      if (response.statusCode != 200) return;
      final decoded = jsonDecode(response.body) as List;
      final segments = decoded.whereType<Map<String, dynamic>>().map((item) {
        return AnalysisSegment(
          start: (item['startOffsetSec'] as num?)?.toDouble() ?? 0,
          end: (item['endOffsetSec'] as num?)?.toDouble() ?? 0,
          label: item['label']?.toString() ?? 'Đoạn phân tích',
        );
      }).toList();
      if (!mounted) return;
      setState(() {
        _segments
          ..clear()
          ..addAll(segments);
        _loadedSegmentSessionId = sessionId;
      });
    } catch (_) {
      // Keep the last visible list during a brief backend interruption.
    } finally {
      _loadingSegments = false;
    }
  }

  void _message(String text, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(text),
        backgroundColor: error ? AppColors.critical : AppColors.accent,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _swapCameras(GaitSession session) async {
    if (session.isRecording || _swappingCameras) return;
    setState(() => _swappingCameras = true);
    try {
      final response = await http
          .post(Uri.parse('http://127.0.0.1:8000/camera/swap'))
          .timeout(const Duration(seconds: 3));
      if (response.statusCode != 200) {
        _message('Không thể đảo camera: ${response.body}', error: true);
        return;
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (mounted) {
        setState(() => _camerasSwapped = body['swapped'] == true);
      }
      await _pollCameraStatus();
      _message(
        _camerasSwapped
            ? 'Đã đổi: camera vật lý 2 là chính diện, camera vật lý 1 là mặt phẳng dọc.'
            : 'Đã trả camera về cấu hình ban đầu.',
      );
    } catch (_) {
      _message('Backend chưa phản hồi nên chưa thể đảo camera.', error: true);
    } finally {
      if (mounted) setState(() => _swappingCameras = false);
    }
  }

  String _clock(double seconds) {
    final total = seconds.floor();
    final hours = (total ~/ 3600).toString().padLeft(2, '0');
    final minutes = ((total % 3600) ~/ 60).toString().padLeft(2, '0');
    final secs = (total % 60).toString().padLeft(2, '0');
    return '$hours:$minutes:$secs';
  }

  Future<void> _startRecording(SessionProvider provider) async {
    final error = await provider.startContinuousRecording();
    if (error != null) {
      _message(error, error: true);
      return;
    }
    setState(() {
      _pendingStart = null;
      _segments.clear();
    });
  }

  Future<void> _stopRecording(SessionProvider provider) async {
    final hadPendingMarker = _pendingStart != null;
    final error = await provider.stopContinuousRecording();
    if (error != null) {
      _message(error, error: true);
      return;
    }
    setState(() => _pendingStart = null);
    _message(
      hadPendingMarker
          ? 'Phi\u00ean ghi \u0111\u00e3 d\u1eebng. M\u1ed1c \u0111\u1ea7u cu\u1ed1i c\u00f9ng ch\u01b0a c\u00f3 m\u1ed1c cu\u1ed1i n\u00ean kh\u00f4ng \u0111\u01b0\u1ee3c l\u01b0u.'
          : '\u0110\u00e3 d\u1eebng v\u00e0 l\u01b0u video g\u1ed1c c\u1ee7a phi\u00ean \u0111o.',
    );
  }

  Future<void> _toggleMarker(
    SessionProvider provider,
    GaitSession session,
  ) async {
    final now = session.recordingElapsedSec;
    if (_pendingStart == null) {
      await provider.addMarker(
        session.id,
        offset: now,
        note: 'M\u1ed1c \u0111\u1ea7u \u0111o\u1ea1n ${_segments.length + 1}',
      );
      setState(() => _pendingStart = now);
      _message(
        '\u0110\u00e3 \u0111\u1eb7t m\u1ed1c \u0111\u1ea7u t\u1ea1i ${now.toStringAsFixed(1)} gi\u00e2y.',
      );
      return;
    }

    final start = _pendingStart!;
    if (now - start < 0.5) {
      _message(
        '\u0110o\u1ea1n ph\u00e2n t\u00edch ph\u1ea3i d\u00e0i \u00edt nh\u1ea5t 0,5 gi\u00e2y.',
        error: true,
      );
      return;
    }

    final label = '\u0110o\u1ea1n ph\u00e2n t\u00edch ${_segments.length + 1}';
    final error = await provider.createVirtualSegment(start, now, label);
    if (error != null) {
      _message(error, error: true);
      return;
    }
    await provider.addMarker(
      session.id,
      offset: now,
      note: 'M\u1ed1c cu\u1ed1i $label',
    );
    await _loadSegments(session.id, force: true);
    if (mounted) setState(() => _pendingStart = null);
    _message(
      '\u0110\u00e3 l\u01b0u $label '
      '(${start.toStringAsFixed(1)}\u2013${now.toStringAsFixed(1)} gi\u00e2y).',
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;
    final session = provider.activeSession;

    if (patient == null || session == null) {
      return _empty(provider);
    }

    if (_loadedSegmentSessionId != session.id && !_loadingSegments) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadSegments(session.id);
      });
    }

    return ColoredBox(
      color: AppColors.background,
      child: Column(
        children: [
          _statusBar(provider, session),
          Expanded(
            child: Stack(
              children: [
                Positioned.fill(
                  child: Column(
                    children: [
                      _workspaceToolbar(session),
                      Expanded(
                        child: _analysisWorkspace(
                          patient: patient,
                          session: session,
                        ),
                      ),
                      RecordingTimeline(
                        duration: session.recordingElapsedSec,
                        segments: _segments,
                        pendingStart: _pendingStart,
                      ),
                    ],
                  ),
                ),
                if (_sidebarOpen)
                  Positioned.fill(
                    child: GestureDetector(
                      onTap: () => setState(() => _sidebarOpen = false),
                      child: Container(
                        color: AppColors.textPrimary.withValues(alpha: 0.08),
                      ),
                    ),
                  ),
                _sidebar(patient, session),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _empty(SessionProvider provider) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.person_search_outlined,
            size: 48,
            color: AppColors.textSecondary,
          ),
          const SizedBox(height: 12),
          const Text(
            'Ch\u01b0a ch\u1ecdn b\u1ec7nh nh\u00e2n ho\u1eb7c phi\u00ean \u0111o',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: () => provider.setTabIndex(0),
            child: const Text('V\u1ec0 H\u1ed2 S\u01a0 B\u1ec6NH NH\u00c2N'),
          ),
        ],
      ),
    );
  }

  Widget _statusBar(
    SessionProvider provider,
    GaitSession session,
  ) {
    final recording = session.isRecording;
    return Container(
      height: 52,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(
        color: AppColors.panel,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        children: [
          Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: recording ? AppColors.critical : AppColors.baseline,
            ),
          ),
          const SizedBox(width: 9),
          Text(
            recording
                ? '\u0110ang ghi'
                : 'Phi\u00ean ghi \u0111\u00e3 d\u1eebng',
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
          if (recording) ...[
            const SizedBox(width: 12),
            Text(
              _clock(session.recordingElapsedSec),
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppColors.critical,
              ),
            ),
          ],
          const Spacer(),
          if (recording) ...[
            OutlinedButton.icon(
              onPressed: provider.isLoading
                  ? null
                  : () => _toggleMarker(provider, session),
              icon: Icon(
                _pendingStart == null ? Icons.flag_outlined : Icons.flag,
                size: 16,
              ),
              label: Text(
                _pendingStart == null
                    ? '\u0110\u1eb6T M\u1ed0C \u0110\u1ea6U'
                    : 'M\u1ed0C CU\u1ed0I & L\u01afU',
              ),
              style: OutlinedButton.styleFrom(
                foregroundColor: _pendingStart == null
                    ? AppColors.warning
                    : AppColors.accentGreen,
                side: BorderSide(
                  color: _pendingStart == null
                      ? AppColors.warning
                      : AppColors.accentGreen,
                ),
                padding: const EdgeInsets.symmetric(
                  horizontal: 13,
                  vertical: 11,
                ),
              ),
            ),
            const SizedBox(width: 9),
            FilledButton.icon(
              onPressed: () => _stopRecording(provider),
              icon: const Icon(Icons.stop, size: 16),
              label: const Text('D\u1eeaNG GHI'),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.critical,
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 11,
                ),
              ),
            ),
          ] else ...[
            if (_segments.isNotEmpty || session.scans.isNotEmpty) ...[
              TextButton.icon(
                onPressed: () => provider.setTabIndex(3),
                icon: const Icon(Icons.analytics_outlined, size: 16),
                label: const Text('XEM PH\u00c2N T\u00cdCH'),
              ),
              const SizedBox(width: 8),
            ],
            FilledButton.icon(
              onPressed:
                  provider.isLoading ? null : () => _startRecording(provider),
              icon: const Icon(Icons.fiber_manual_record, size: 15),
              label: const Text('B\u1eaeT \u0110\u1ea6U GHI'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 11,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _workspaceToolbar(GaitSession session) {
    return SizedBox(
      height: 34,
      child: Row(
        children: [
          IconButton(
            onPressed: () => setState(() => _sidebarOpen = !_sidebarOpen),
            icon: const Icon(Icons.menu, size: 20),
            tooltip: 'M\u1edf menu',
            visualDensity: VisualDensity.compact,
          ),
          const Text(
            'SCAN / GAIT ANALYSIS',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              color: AppColors.textSecondary,
              letterSpacing: 0.5,
            ),
          ),
          const Spacer(),
          OutlinedButton.icon(
            onPressed: session.isRecording || _swappingCameras
                ? null
                : () => _swapCameras(session),
            icon: _swappingCameras
                ? const SizedBox(
                    width: 13,
                    height: 13,
                    child: CircularProgressIndicator(strokeWidth: 1.7),
                  )
                : const Icon(Icons.swap_horiz, size: 16),
            label: Text(_camerasSwapped ? 'TRẢ LẠI CAM' : 'ĐẢO CAM 1 ↔ 2'),
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(0, 28),
              padding: const EdgeInsets.symmetric(horizontal: 10),
              textStyle: const TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 12),
          if (_selectedCharts.isNotEmpty)
            Text(
              '${_selectedCharts.length} bi\u1ec3u \u0111\u1ed3 \u0111ang hi\u1ec3n th\u1ecb',
              style: const TextStyle(
                fontSize: 9,
                color: AppColors.textSecondary,
              ),
            ),
          const SizedBox(width: 12),
        ],
      ),
    );
  }

  Widget _analysisWorkspace({
    required Patient patient,
    required GaitSession session,
  }) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (_selectedCharts.isEmpty) {
          return _cameraWorkspace(session);
        }

        final availableWidth = max(0.0, constraints.maxWidth - 24);
        final preferredChartWidth = availableWidth * 0.46;
        final chartWidth = availableWidth < 1220
            ? preferredChartWidth
            : preferredChartWidth.clamp(560.0, 860.0).toDouble();
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: _cameraWorkspace(
                session,
                padding: const EdgeInsets.fromLTRB(12, 0, 5, 7),
              ),
            ),
            SizedBox(
              width: chartWidth,
              child: _chartWorkspace(
                patient,
                margin: const EdgeInsets.fromLTRB(5, 0, 12, 7),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _cameraWorkspace(
    GaitSession session, {
    EdgeInsetsGeometry padding = const EdgeInsets.fromLTRB(12, 0, 12, 7),
  }) {
    return Padding(
      padding: padding,
      child: Row(
        children: [
          Expanded(
            child: _cameraCard(
              title: 'CAM 1 \u00b7 CH\u00cdNH DI\u1ec6N',
              url: 'http://127.0.0.1:8000/video_feed_0',
              connected: _camera0Connected,
              session: session,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _cameraCard(
              title: 'CAM 2 \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC',
              url: 'http://127.0.0.1:8000/video_feed_1',
              connected: _camera1Connected,
              poseDetected: _camera1PoseDetected,
              session: session,
            ),
          ),
        ],
      ),
    );
  }

  Widget _cameraCard({
    required String title,
    required String url,
    required bool? connected,
    bool? poseDetected,
    required GaitSession session,
  }) {
    final poseMissing = connected == true && poseDetected == false;
    final stateText = connected == null
        ? '\u0110ang k\u1ebft n\u1ed1i'
        : connected
            ? poseMissing
                ? 'Ch\u01b0a th\u1ea5y to\u00e0n th\u00e2n'
                : '\u0110ang ho\u1ea1t \u0111\u1ed9ng'
            : 'M\u1ea5t t\u00edn hi\u1ec7u';
    final stateColor = connected == null
        ? AppColors.warning
        : connected
            ? poseMissing
                ? AppColors.warning
                : AppColors.accentGreen
            : AppColors.critical;

    return Container(
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: connected == true
                ? createVideoStreamWidget(url)
                : ColoredBox(
                    color: AppColors.surfaceMuted,
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            connected == null
                                ? Icons.sync
                                : Icons.videocam_off_outlined,
                            size: 30,
                            color: AppColors.baseline,
                          ),
                          const SizedBox(height: 7),
                          Text(
                            stateText,
                            style: const TextStyle(
                              fontSize: 11,
                              color: AppColors.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
          ),
          Positioned(
            left: 9,
            top: 9,
            child: Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 8,
                vertical: 4,
              ),
              decoration: BoxDecoration(
                color: AppColors.panel.withValues(alpha: 0.92),
                borderRadius: BorderRadius.circular(5),
              ),
              child: Text(
                title,
                style: const TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
          Positioned(
            right: 9,
            top: 9,
            child: Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 7,
                vertical: 4,
              ),
              decoration: BoxDecoration(
                color: AppColors.panel.withValues(alpha: 0.92),
                borderRadius: BorderRadius.circular(5),
              ),
              child: Row(
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: stateColor,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 5),
                  Text(
                    session.isRecording && connected == true
                        ? 'REC'
                        : stateText,
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w600,
                      color: session.isRecording && connected == true
                          ? AppColors.critical
                          : stateColor,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _chartWorkspace(
    Patient patient, {
    EdgeInsetsGeometry margin = const EdgeInsets.fromLTRB(12, 0, 12, 7),
  }) {
    return Container(
      margin: margin,
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(10),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          Container(
            height: 30,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: const Row(
              children: [
                Icon(
                  Icons.monitor_heart_outlined,
                  size: 15,
                  color: AppColors.accent,
                ),
                SizedBox(width: 7),
                Text(
                  'BI\u1ec2U \u0110\u1ed2 REALTIME',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.4,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: RealtimeChartWorkspace(
              selectedCharts: _selectedCharts,
              healthySide: patient.healthyLeg.name,
            ),
          ),
        ],
      ),
    );
  }

  Widget _sidebar(Patient patient, GaitSession session) {
    return AnimatedPositioned(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
      left: _sidebarOpen ? 0 : -286,
      top: 0,
      bottom: 0,
      width: 286,
      child: Material(
        color: AppColors.panel,
        elevation: 8,
        child: SafeArea(
          top: false,
          child: Column(
            children: [
              SizedBox(
                height: 48,
                child: Row(
                  children: [
                    IconButton(
                      onPressed: () => setState(() => _sidebarOpen = false),
                      icon: const Icon(Icons.menu_open),
                      tooltip: '\u0110\u00f3ng menu',
                    ),
                    const Text(
                      'WORKSPACE',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.6,
                      ),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1, color: AppColors.border),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  children: [
                    _menuItem(
                      Icons.radar,
                      'Scan / Phi\u00ean \u0111o',
                      active: true,
                    ),
                    _menuItem(
                      Icons.videocam_outlined,
                      'Camera',
                      trailing: Text(
                        _camera0Connected == true && _camera1Connected == true
                            ? '2/2'
                            : '0\u20132/2',
                        style: const TextStyle(
                          fontSize: 10,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ),
                    Theme(
                      data: Theme.of(context).copyWith(
                        dividerColor: Colors.transparent,
                      ),
                      child: ExpansionTile(
                        initiallyExpanded: _chartsExpanded,
                        onExpansionChanged: (value) =>
                            setState(() => _chartsExpanded = value),
                        leading: const Icon(
                          Icons.insert_chart_outlined,
                          size: 19,
                        ),
                        title: const Text(
                          'Bi\u1ec3u \u0111\u1ed3',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        children: [
                          for (final chart in RealtimeChartType.values)
                            CheckboxListTile(
                              dense: true,
                              visualDensity: VisualDensity.compact,
                              contentPadding:
                                  const EdgeInsets.only(left: 28, right: 12),
                              controlAffinity: ListTileControlAffinity.leading,
                              value: _selectedCharts.contains(chart),
                              title: Text(
                                chart.label,
                                style: const TextStyle(fontSize: 11),
                              ),
                              onChanged: (checked) {
                                setState(() {
                                  if (checked == true) {
                                    _selectedCharts.add(chart);
                                  } else {
                                    _selectedCharts.remove(chart);
                                  }
                                });
                              },
                            ),
                          if (_selectedCharts.isNotEmpty)
                            Align(
                              alignment: Alignment.centerRight,
                              child: TextButton(
                                onPressed: () =>
                                    setState(_selectedCharts.clear),
                                child: const Text(
                                  'B\u1ece CH\u1eccN',
                                  style: TextStyle(fontSize: 10),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                    ExpansionTile(
                      leading: const Icon(
                        Icons.info_outline,
                        size: 19,
                      ),
                      title: const Text(
                        'Th\u00f4ng tin phi\u00ean',
                        style: TextStyle(fontSize: 12),
                      ),
                      childrenPadding: const EdgeInsets.fromLTRB(54, 0, 14, 10),
                      expandedCrossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'ID: ${session.id}',
                          style: const TextStyle(
                            fontSize: 10,
                            color: AppColors.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'B\u1ec7nh nh\u00e2n: ${patient.name}',
                          style: const TextStyle(
                            fontSize: 10,
                            color: AppColors.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Th\u1eddi l\u01b0\u1ee3ng: ${_clock(session.recordingElapsedSec)}',
                          style: const TextStyle(
                            fontSize: 10,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                    _menuItem(
                      Icons.settings_outlined,
                      'C\u00e0i \u0111\u1eb7t',
                      onTap: () => _message(
                        'C\u00e0i \u0111\u1eb7t camera v\u00e0 thi\u1ebft b\u1ecb s\u1ebd \u0111\u01b0\u1ee3c b\u1ed5 sung t\u1ea1i \u0111\u00e2y.',
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _menuItem(
    IconData icon,
    String label, {
    bool active = false,
    Widget? trailing,
    VoidCallback? onTap,
  }) {
    return ListTile(
      dense: true,
      leading: Icon(
        icon,
        size: 19,
        color: active ? AppColors.accent : AppColors.textSecondary,
      ),
      title: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          fontWeight: active ? FontWeight.w600 : FontWeight.w400,
          color: active ? AppColors.accent : AppColors.textPrimary,
        ),
      ),
      trailing: trailing,
      selected: active,
      selectedTileColor: AppColors.accent.withValues(alpha: 0.08),
      onTap: onTap,
    );
  }
}
