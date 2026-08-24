import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'app_alert.dart';
import 'fsr_force_phase_analysis.dart';

import 'fsr_region_analysis.dart';
import 'fsr_replay_analysis.dart';

import 'gait_cycle_analysis.dart';
import 'metrics_grid.dart';
import 'synced_video_controls.dart';
import 'video_stream.dart';

enum _AnalysisCameraView { compact, full, hidden }

enum _AnalysisPanel {
  cameraCycles,
  gaitMetrics,
  fsrRegions,
  fsrPhases,
  fsrReplay,
}

class _ClipInfo {
  const _ClipInfo({
    required this.scanId,
    required this.label,
    required this.start,
    required this.end,
    required this.frontalUrl,
    required this.sagittalUrl,
  });

  final String scanId;
  final String label;
  final double start;
  final double end;
  final String frontalUrl;
  final String sagittalUrl;

  factory _ClipInfo.fromJson(Map<String, dynamic> json) => _ClipInfo(
        scanId: json['scanId']?.toString() ?? '',
        label:
            json['label']?.toString() ?? '\u0110o\u1ea1n ph\u00e2n t\u00edch',
        start: (json['startOffsetSec'] as num?)?.toDouble() ?? 0,
        end: (json['endOffsetSec'] as num?)?.toDouble() ?? 0,
        frontalUrl: json['frontalVideoUrl']?.toString() ?? '',
        sagittalUrl: json['sagittalVideoUrl']?.toString() ?? '',
      );
}

class _RecordingInfo {
  const _RecordingInfo({
    required this.id,
    required this.sessionId,
    required this.sessionCreatedAt,
    required this.startedAt,
    required this.duration,
    required this.status,
  });

  final String id;
  final String sessionId;
  final String sessionCreatedAt;
  final String startedAt;
  final double duration;
  final String status;

  String get shortId => id.length <= 10 ? id : id.substring(id.length - 8);
  String get shortSessionId => sessionId.length <= 8
      ? sessionId
      : sessionId.substring(sessionId.length - 6);

  String get sessionDate {
    final parsed = DateTime.tryParse(sessionCreatedAt)?.toLocal();
    if (parsed == null) return '';
    String two(int value) => value.toString().padLeft(2, '0');
    return '${two(parsed.day)}/${two(parsed.month)}/${parsed.year}';
  }

  factory _RecordingInfo.fromJson(Map<String, dynamic> json) {
    return _RecordingInfo(
      id: json['archiveId']?.toString() ?? '',
      sessionId: json['sessionId']?.toString() ?? '',
      sessionCreatedAt: json['sessionCreatedAt']?.toString() ?? '',
      startedAt: json['startedAt']?.toString() ?? '',
      duration: (json['durationSec'] as num?)?.toDouble() ?? 0,
      status: json['status']?.toString() ?? 'complete',
    );
  }
}

class TabAnalysis extends StatefulWidget {
  const TabAnalysis({super.key});

  @override
  State<TabAnalysis> createState() => _TabAnalysisState();
}

class _TabAnalysisState extends State<TabAnalysis> {
  List<_ClipInfo> _clips = [];
  List<_RecordingInfo> _recordings = [];
  String? _selectedId;
  String? _deletingArchiveId;
  String? _loadedSessionId;
  int? _loadedScanCount;
  bool _loading = false;
  String? _error;
  Timer? _playTimer;
  double _position = 0;
  bool _playing = false;
  bool _useDemoVideos = false;
  bool _libraryCollapsed = false;
  _AnalysisPanel _analysisPanel = _AnalysisPanel.cameraCycles;
  _AnalysisCameraView _cameraView = _AnalysisCameraView.compact;
  late final SyncedVideoController _demoVideoController;

  bool get _cameraVisible => _cameraView != _AnalysisCameraView.hidden;
  bool get _cameraCompact => _cameraView == _AnalysisCameraView.compact;

  String get _cameraViewLabel => switch (_cameraView) {
        _AnalysisCameraView.compact => 'CAM THU GỌN',
        _AnalysisCameraView.full => 'CAM ĐẦY ĐỦ',
        _AnalysisCameraView.hidden => 'CHỈ SỐ LIỆU',
      };

  @override
  void initState() {
    super.initState();
    _demoVideoController = SyncedVideoController();
  }

  @override
  void dispose() {
    _playTimer?.cancel();
    _demoVideoController.dispose();
    super.dispose();
  }

  Future<void> _load(String sessionId) async {
    if (_loading) return;
    final patientId = context.read<SessionProvider>().activePatient?.id ?? '';
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final responses = await Future.wait([
        http.get(
          Uri.parse(
            'http://localhost:8000/sessions/$sessionId/analysis-clips',
          ),
        ),
        http.get(
          Uri.parse(
            patientId.isEmpty
                ? 'http://localhost:8000/sessions/$sessionId/recordings'
                : 'http://localhost:8000/patients/$patientId/recordings',
          ),
        ),
      ]).timeout(const Duration(seconds: 4));
      if (responses.any((response) => response.statusCode != 200)) {
        throw Exception(
          'Backend kh\u00f4ng tr\u1ea3 \u0111\u01b0\u1ee3c th\u01b0 vi\u1ec7n video.',
        );
      }
      final decodedClips = jsonDecode(responses[0].body) as List;
      final decodedRecordings = jsonDecode(responses[1].body) as List;
      final clips = decodedClips
          .whereType<Map<String, dynamic>>()
          .map(_ClipInfo.fromJson)
          .toList();
      final recordings = decodedRecordings
          .whereType<Map<String, dynamic>>()
          .map(_RecordingInfo.fromJson)
          .where((item) => item.id.isNotEmpty)
          .toList();
      if (!mounted) return;
      setState(() {
        _clips = clips;
        _recordings = recordings;
        _selectedId = clips.any((clip) => clip.scanId == _selectedId)
            ? _selectedId
            : (clips.isEmpty ? null : clips.first.scanId);
        _loadedSessionId = sessionId;
        _loadedScanCount =
            context.read<SessionProvider>().activeSession?.scans.length;
        if (clips.isNotEmpty) {
          _position =
              clips.firstWhere((clip) => clip.scanId == _selectedId).start;
        }
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _deleteRecording(
    GaitSession session,
    _RecordingInfo recording,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('X\u00f3a b\u1ed9 video \u0111\u00e3 ghi?'),
        content: Text(
          'B\u1ed9 ${recording.shortId} g\u1ed3m hai video camera. '
          'C\u00e1c \u0111o\u1ea1n ph\u00e2n t\u00edch v\u00e0 bi\u1ec3u \u0111\u1ed3 \u0111\u00e3 c\u1eaft t\u1eeb b\u1ed9 n\u00e0y '
          'c\u0169ng s\u1ebd b\u1ecb x\u00f3a. Thao t\u00e1c n\u00e0y kh\u00f4ng th\u1ec3 ho\u00e0n t\u00e1c.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('H\u1ee6Y'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.delete_outline, size: 18),
            label: const Text('X\u00d3A B\u1ed8 VIDEO'),
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.critical,
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    _playTimer?.cancel();
    setState(() {
      _deletingArchiveId = recording.id;
      _playing = false;
    });
    try {
      final response = await http
          .delete(
            Uri.parse(
              'http://localhost:8000/sessions/${recording.sessionId}/recordings/${recording.id}',
            ),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) {
        String detail = 'Backend tr\u1ea3 m\u00e3 ${response.statusCode}';
        try {
          final body = jsonDecode(response.body) as Map<String, dynamic>;
          detail = body['detail']?.toString() ?? detail;
        } catch (_) {}
        throw Exception(detail);
      }
      if (!mounted) return;
      await context.read<SessionProvider>().fetchPatients();
      if (!mounted) return;
      _loadedScanCount = null;
      await _load(session.id);
      if (!mounted) return;
      AppAlert.show(
        context,
        'Đã xóa bộ video và dữ liệu liên quan.',
        tone: AppAlertTone.success,
      );
    } catch (error) {
      if (!mounted) return;
      AppAlert.show(
        context,
        'Không xóa được bộ video: $error',
        tone: AppAlertTone.error,
      );
    } finally {
      if (mounted) setState(() => _deletingArchiveId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;
    final session = provider.activeSession;
    if (patient == null || session == null) {
      return const Center(
          child: Text(
              'Ch\u01b0a ch\u1ecdn b\u1ec7nh nh\u00e2n ho\u1eb7c phi\u00ean \u0111o.'));
    }
    if ((_loadedSessionId != session.id ||
            _loadedScanCount != session.scans.length) &&
        !_loading) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _load(session.id));
    }

    final selectedClip =
        _clips.where((clip) => clip.scanId == _selectedId).firstOrNull;
    final allScans = <ScanResult>[
      if (session.baseline != null) session.baseline!,
      ...session.scans,
    ];
    final selectedScan =
        allScans.where((scan) => scan.id == selectedClip?.scanId).firstOrNull;

    return Row(
      children: [
        Expanded(
          child: Column(
            children: [
              _titleBar(provider, selectedClip),
              if (_cameraVisible && _useDemoVideos)
                _demoVideoPair()
              else if (_cameraVisible && selectedClip != null)
                _videoPair(session.id, selectedClip),
              if (!_useDemoVideos && selectedClip != null)
                _playbackControls(selectedClip),
              Expanded(
                child: _useDemoVideos
                    ? GaitCycleAnalysis(
                        assetPath: 'assets/demo/demo_gait_data.json',
                        healthySideOverride: patient.healthyLeg.name,
                      )
                    : selectedScan == null
                        ? _emptyState()
                        : _analysisPanelContent(
                            selectedScan,
                            session,
                            patient,
                          ),
              ),
            ],
          ),
        ),
        _clipList(session),
      ],
    );
  }

  String get _analysisPanelLabel => switch (_analysisPanel) {
        _AnalysisPanel.cameraCycles => 'CHU KỲ CAMERA',
        _AnalysisPanel.gaitMetrics => 'CHỈ SỐ DÁNG ĐI',
        _AnalysisPanel.fsrRegions => 'FSR · 3 VÙNG',
        _AnalysisPanel.fsrPhases => 'LỰC FSR · 3 PHA',
        _AnalysisPanel.fsrReplay => 'REPLAY FSR',
      };

  Widget _analysisPanelContent(
    ScanResult scan,
    GaitSession session,
    Patient patient,
  ) {
    return switch (_analysisPanel) {
      _AnalysisPanel.cameraCycles => GaitCycleAnalysis(scanId: scan.id),
      _AnalysisPanel.gaitMetrics => MetricsGrid(
          scan: scan,
          baseline: session.baseline,
          patient: patient,
        ),
      _AnalysisPanel.fsrRegions => FsrRegionAnalysis(scanId: scan.id),
      _AnalysisPanel.fsrPhases => FsrForcePhaseAnalysis(scanId: scan.id),
      _AnalysisPanel.fsrReplay => FsrReplayAnalysis(
          scanId: scan.id,
          position: _position,
        ),
    };
  }

  Widget _analysisPanelMenu() {
    const options = [
      (_AnalysisPanel.cameraCycles, 'Chu kỳ camera · Mean ± SD'),
      (_AnalysisPanel.gaitMetrics, 'Chỉ số dáng đi'),
      (_AnalysisPanel.fsrReplay, 'Replay FSR · dữ liệu tức thời'),
      (_AnalysisPanel.fsrRegions, 'FSR · Mean ± SD 3 vùng'),
      (_AnalysisPanel.fsrPhases, 'Lực FSR · 3 pha'),
    ];
    return PopupMenuButton<_AnalysisPanel>(
      tooltip: 'Chọn nội dung phân tích',
      initialValue: _analysisPanel,
      onSelected: (panel) => setState(() => _analysisPanel = panel),
      itemBuilder: (context) => options
          .map(
            (option) => CheckedPopupMenuItem<_AnalysisPanel>(
              value: option.$1,
              checked: _analysisPanel == option.$1,
              child: Text(option.$2),
            ),
          )
          .toList(),
      child: Container(
        height: 31,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(18),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.insights_outlined,
                size: 16, color: AppColors.accent),
            const SizedBox(width: 6),
            Text(
              _analysisPanelLabel,
              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
            ),
            const SizedBox(width: 2),
            const Icon(Icons.arrow_drop_down, size: 18),
          ],
        ),
      ),
    );
  }

  Widget _titleBar(SessionProvider provider, _ClipInfo? clip) {
    return Container(
      height: 50,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: const BoxDecoration(
        color: AppColors.panel,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        children: [
          IconButton(
            onPressed: () => provider.setTabIndex(2),
            icon: const Icon(Icons.arrow_back),
            tooltip: 'V\u1ec1 m\u00e0n Scan',
          ),
          const SizedBox(width: 6),
          const Text(
            'PH\u00c2N T\u00cdCH \u0110O\u1ea0N D\u00c1NG \u0110I',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
          ),
          if (clip != null && !_useDemoVideos) ...[
            const SizedBox(width: 12),
            Text(
              '${clip.start.toStringAsFixed(1)}\u2013${clip.end.toStringAsFixed(1)} s',
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                color: AppColors.accent,
              ),
            ),
          ],
          const Spacer(),
          if (clip != null && !_useDemoVideos) ...[
            _analysisPanelMenu(),
            const SizedBox(width: 8),
          ],
          PopupMenuButton<_AnalysisCameraView>(
            tooltip: 'Chọn cách hiển thị camera',
            initialValue: _cameraView,
            onSelected: (view) {
              setState(() {
                _cameraView = view;
                if (view == _AnalysisCameraView.hidden) {
                  _playTimer?.cancel();
                  _playing = false;
                  _demoVideoController.pause();
                }
              });
            },
            itemBuilder: (context) => [
              CheckedPopupMenuItem(
                value: _AnalysisCameraView.compact,
                checked: _cameraView == _AnalysisCameraView.compact,
                child: const Text('Camera thu gọn'),
              ),
              CheckedPopupMenuItem(
                value: _AnalysisCameraView.full,
                checked: _cameraView == _AnalysisCameraView.full,
                child: const Text('Camera đầy đủ'),
              ),
              CheckedPopupMenuItem(
                value: _AnalysisCameraView.hidden,
                checked: _cameraView == _AnalysisCameraView.hidden,
                child: const Text('Chỉ xem số liệu và biểu đồ'),
              ),
            ],
            child: Container(
              height: 31,
              padding: const EdgeInsets.symmetric(horizontal: 10),
              decoration: BoxDecoration(
                border: Border.all(color: AppColors.border),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    _cameraVisible
                        ? (_cameraCompact
                            ? Icons.video_camera_front_outlined
                            : Icons.videocam_outlined)
                        : Icons.analytics_outlined,
                    size: 16,
                    color: AppColors.accent,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    _cameraViewLabel,
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(width: 2),
                  const Icon(Icons.arrow_drop_down, size: 18),
                ],
              ),
            ),
          ),
          const SizedBox(width: 8),
          OutlinedButton.icon(
            onPressed: () {
              _playTimer?.cancel();
              final showDemo = !_useDemoVideos;
              setState(() {
                _useDemoVideos = showDemo;
                _playing = false;
              });
              if (showDemo) {
                _demoVideoController.play();
              } else {
                _demoVideoController.pause();
              }
            },
            icon: Icon(
              _useDemoVideos ? Icons.analytics_outlined : Icons.movie_outlined,
              size: 17,
            ),
            label: Text(
              _useDemoVideos
                  ? 'TR\u1ede L\u1ea0I PH\u00c2N T\u00cdCH'
                  : 'VIDEO M\u1eaaU 0,8\u00d7',
            ),
          ),
        ],
      ),
    );
  }

  void _selectClip(_ClipInfo clip) {
    _playTimer?.cancel();
    _demoVideoController.pause();
    setState(() {
      _selectedId = clip.scanId;
      _useDemoVideos = false;
      _position = clip.start;
      _playing = false;
    });
  }

  void _togglePlayback(_ClipInfo clip) {
    if (_playing) {
      _playTimer?.cancel();
      setState(() => _playing = false);
      return;
    }
    if (_position >= clip.end) _position = clip.start;
    setState(() => _playing = true);
    _playTimer = Timer.periodic(const Duration(milliseconds: 200), (timer) {
      if (!mounted || _position + 0.2 >= clip.end) {
        timer.cancel();
        if (mounted) {
          setState(() {
            _position = clip.end;
            _playing = false;
          });
        }
        return;
      }
      setState(() => _position += 0.2);
    });
  }

  Widget _playbackControls(_ClipInfo clip) {
    final value = _position.clamp(clip.start, clip.end);
    return Container(
      height: _cameraCompact ? 40 : 48,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      color: AppColors.sidebar,
      child: Row(
        children: [
          IconButton(
            onPressed: () => _togglePlayback(clip),
            icon: Icon(_playing ? Icons.pause : Icons.play_arrow),
            tooltip: _playing ? 'Pause' : 'Play',
          ),
          SizedBox(
            width: 62,
            child: Text(
              '${value.toStringAsFixed(1)} s',
              style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
            ),
          ),
          Expanded(
            child: Slider(
              min: clip.start,
              max: clip.end,
              value: value,
              onChanged: (next) {
                _playTimer?.cancel();
                setState(() {
                  _position = next;
                  _playing = false;
                });
              },
            ),
          ),
          Text(
            '${clip.end.toStringAsFixed(1)} s',
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 11,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _demoVideoPair() {
    return SizedBox(
      height: _cameraCompact ? 170 : 260,
      child: Column(
        children: [
          Expanded(
            child: Row(
              children: [
                Expanded(
                  child: _demoVideo(
                    'VIDEO M\u1eaaU \u00b7 CH\u00cdNH DI\u1ec6N',
                    'assets/assets/demo/demo_frontal_x08.mp4?v=mediapipe3',
                    'frontal',
                  ),
                ),
                Expanded(
                  child: _demoVideo(
                    'VIDEO M\u1eaaU \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC',
                    'assets/assets/demo/demo_sagittal_x08.mp4?v=mediapipe3',
                    'sagittal',
                  ),
                ),
              ],
            ),
          ),
          SyncedVideoControls(controller: _demoVideoController),
        ],
      ),
    );
  }

  Widget _demoVideo(String label, String assetUrl, String streamKey) {
    return Container(
      margin: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: createVideoFileWidget(
              assetUrl,
              controller: _demoVideoController,
              streamKey: streamKey,
            ),
          ),
          Positioned(
            left: 8,
            top: 8,
            child: Container(
              color: const Color(0xD9FFFFFF),
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
              child: Text(
                label,
                style:
                    const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
              ),
            ),
          ),
          const Positioned(
            right: 8,
            top: 8,
            child: DecoratedBox(
              decoration: BoxDecoration(color: Color(0xD9256D85)),
              child: Padding(
                padding: EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                child: Text(
                  '4 C?P ? 0,8?',
                  style: TextStyle(color: Colors.white, fontSize: 10),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _videoPair(String sessionId, _ClipInfo clip) {
    return SizedBox(
      height: _cameraCompact ? 135 : 220,
      child: Row(
        children: [
          Expanded(
            child: _recordedVideo(
              'CAM 1 \u00b7 CH\u00cdNH DI\u1ec6N',
              clip.frontalUrl,
            ),
          ),
          Expanded(
            child: _recordedVideo(
              'CAM 2 \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC',
              clip.sagittalUrl,
            ),
          ),
        ],
      ),
    );
  }

  Widget _recordedVideo(String label, String relativeUrl) {
    final framePath = relativeUrl.split('?').first.replaceFirst(
          '/session-video/',
          '/session-video-frame/',
        );
    final url =
        'http://localhost:8000$framePath?t=${_position.toStringAsFixed(2)}';
    return Container(
      margin: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: relativeUrl.isEmpty
                ? const Center(child: Text('Kh\u00f4ng c\u00f3 video'))
                : Image.network(
                    url,
                    key: ValueKey(url),
                    fit: BoxFit.contain,
                    gaplessPlayback: true,
                  ),
          ),
          Positioned(
            left: 8,
            top: 8,
            child: Container(
              color: const Color(0xD9FFFFFF),
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
              child: Text(
                label,
                style:
                    const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _openRecordingSession(_RecordingInfo recording) async {
    final provider = context.read<SessionProvider>();
    final patient = provider.activePatient;
    final owner = patient?.sessions
        .where((session) => session.id == recording.sessionId)
        .firstOrNull;
    if (owner == null) {
      AppAlert.show(
        context,
        'Không tìm thấy phiên gốc của bộ video này.',
        tone: AppAlertTone.error,
      );
      return;
    }
    _playTimer?.cancel();
    setState(() {
      _selectedId = null;
      _loadedSessionId = null;
      _loadedScanCount = null;
      _position = 0;
      _playing = false;
      _useDemoVideos = false;
      _analysisPanel = _AnalysisPanel.cameraCycles;
    });
    provider.selectSession(owner);
    await _load(owner.id);
  }

  Widget _clipList(GaitSession session) {
    return Container(
      width: _libraryCollapsed ? 48 : 290,
      color: AppColors.sidebar,
      padding: EdgeInsets.all(_libraryCollapsed ? 4 : 14),
      child: _libraryCollapsed
          ? Column(
              children: [
                IconButton(
                  onPressed: () => setState(() => _libraryCollapsed = false),
                  icon: const Icon(Icons.chevron_left),
                  tooltip: 'Mở thư viện phiên ghi',
                ),
                const SizedBox(height: 8),
                const Icon(
                  Icons.video_library_outlined,
                  size: 18,
                  color: AppColors.accent,
                ),
                const SizedBox(height: 8),
                const RotatedBox(
                  quarterTurns: 3,
                  child: Text(
                    'THƯ VIỆN PHIÊN GHI',
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            )
          : _expandedClipList(session),
    );
  }

  Widget _expandedClipList(GaitSession session) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Expanded(
              child: Text(
                'TH\u01af VI\u1ec6N PHI\u00caN GHI',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
              ),
            ),
            IconButton(
              onPressed: _loading ? null : () => _load(session.id),
              icon: const Icon(Icons.refresh, size: 18),
              tooltip: 'N\u1ea1p l\u1ea1i danh s\u00e1ch',
            ),
            IconButton(
              onPressed: () => setState(() => _libraryCollapsed = true),
              icon: const Icon(Icons.chevron_right, size: 20),
              tooltip: 'Thu g\u1ecdn th\u01b0 vi\u1ec7n phi\u00ean ghi',
            ),
          ],
        ),
        const Text(
          'T\u1ef1 \u0111\u1ed9ng l\u01b0u video c\u1ee7a t\u1ea5t c\u1ea3 phi\u00ean thu\u1ed9c b\u1ec7nh nh\u00e2n.',
          style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
        ),
        const SizedBox(height: 10),
        if (_loading) const LinearProgressIndicator(minHeight: 2),
        if (_error != null)
          Text(
            _error!,
            style: const TextStyle(fontSize: 11, color: AppColors.critical),
          ),
        const SizedBox(height: 8),
        Text(
          'B\u1ed8 VIDEO \u0110\u00c3 L\u01afU \u00b7 ${_recordings.length}',
          style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 5),
        if (_recordings.isEmpty && !_loading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text(
              'Ch\u01b0a c\u00f3 b\u1ed9 video n\u00e0o.',
              style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
            ),
          )
        else
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 185),
            child: ListView.separated(
              shrinkWrap: true,
              itemCount: _recordings.length,
              separatorBuilder: (_, __) => const SizedBox(height: 4),
              itemBuilder: (_, index) {
                final recording = _recordings[index];
                final deleting = _deletingArchiveId == recording.id;
                final belongsToActiveSession =
                    recording.sessionId == session.id;
                return DecoratedBox(
                  decoration: BoxDecoration(
                    color: belongsToActiveSession
                        ? AppColors.accent.withValues(alpha: 0.07)
                        : AppColors.panel,
                    border: Border.all(
                      color: belongsToActiveSession
                          ? AppColors.accent.withValues(alpha: 0.45)
                          : AppColors.border,
                    ),
                    borderRadius: BorderRadius.circular(7),
                  ),
                  child: ListTile(
                    dense: true,
                    contentPadding: const EdgeInsets.only(left: 9, right: 2),
                    leading: const Icon(
                      Icons.video_library_outlined,
                      size: 18,
                      color: AppColors.accent,
                    ),
                    title: Tooltip(
                      message: recording.id,
                      child: Text(
                        'B\u1ed9 ${recording.shortId}',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    subtitle: Text(
                      '${recording.duration.toStringAsFixed(1)} s'
                      ' · Phiên ${recording.shortSessionId}'
                      '${recording.sessionDate.isEmpty ? '' : ' · ${recording.sessionDate}'}'
                      '${recording.status == 'interrupted' ? ' \u00b7 gi\u00e1n \u0111o\u1ea1n' : ''}',
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 9,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    trailing: deleting
                        ? const SizedBox.square(
                            dimension: 28,
                            child: Padding(
                              padding: EdgeInsets.all(6),
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                          )
                        : IconButton(
                            onPressed: _deletingArchiveId == null
                                ? () => _deleteRecording(session, recording)
                                : null,
                            icon: const Icon(Icons.delete_outline, size: 17),
                            color: AppColors.critical,
                            tooltip: 'X\u00f3a tr\u1ecdn b\u1ed9 video',
                            visualDensity: VisualDensity.compact,
                          ),
                    onTap: deleting
                        ? null
                        : () => _openRecordingSession(recording),
                  ),
                );
              },
            ),
          ),
        const Divider(height: 22),
        const Text(
          '\u0110O\u1ea0N PH\u00c2N T\u00cdCH \u0110\u00c3 C\u1eaeT',
          style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        const Text(
          'Ch\u1ecdn m\u1ed9t \u0111o\u1ea1n \u0111\u1ec3 \u0111\u1ed3ng b\u1ed9 video v\u00e0 bi\u1ec3u \u0111\u1ed3.',
          style: TextStyle(fontSize: 10, color: AppColors.textSecondary),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: _clips.isEmpty && !_loading
              ? const Center(
                  child: Text(
                    'Ch\u01b0a c\u00f3 \u0111o\u1ea1n ph\u00e2n t\u00edch.\nV\u1ec1 tab Scan \u0111\u1ec3 \u0111\u1eb7t m\u1ed1c \u0111\u1ea7u v\u00e0 m\u1ed1c cu\u1ed1i.',
                    textAlign: TextAlign.center,
                    style:
                        TextStyle(fontSize: 12, color: AppColors.textSecondary),
                  ),
                )
              : ListView.separated(
                  itemCount: _clips.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (_, index) {
                    final clip = _clips[index];
                    final selected = clip.scanId == _selectedId;
                    return ListTile(
                      selected: selected,
                      selectedTileColor:
                          AppColors.accent.withValues(alpha: 0.09),
                      contentPadding: const EdgeInsets.symmetric(horizontal: 8),
                      title: Text(
                        clip.label,
                        style: const TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                      subtitle: Text(
                        '${clip.start.toStringAsFixed(1)}\u2013${clip.end.toStringAsFixed(1)} s'
                        ' \u00b7 ${(clip.end - clip.start).toStringAsFixed(1)} s',
                        style: const TextStyle(
                          fontFamily: 'monospace',
                          fontSize: 10,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      trailing: selected
                          ? const Icon(Icons.play_arrow,
                              color: AppColors.accent)
                          : null,
                      onTap: () => _selectClip(clip),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _emptyState() {
    return Center(
      child: Text(
        _loading
            ? '\u0110ang n\u1ea1p d\u1eef li\u1ec7u \u0111o\u1ea1n...'
            : 'Ch\u1ecdn m\u1ed9t \u0111o\u1ea1n \u1edf danh s\u00e1ch b\u00ean ph\u1ea3i \u0111\u1ec3 xem k\u1ebft qu\u1ea3.',
        style: const TextStyle(color: AppColors.textSecondary),
      ),
    );
  }
}
