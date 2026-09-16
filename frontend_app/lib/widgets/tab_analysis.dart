import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart' hide Text;

import '../l10n/app_language.dart';
import '../l10n/localized_text.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../demo/demo_presentation_profile.dart';
import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'analysis_section_switcher.dart';
import 'app_alert.dart';
import 'fsr_force_phase_analysis.dart';

import 'fsr_region_analysis.dart';
import 'fsr_replay_analysis.dart';

import 'gait_cycle_analysis.dart';
import 'metrics_grid.dart';
import 'pose_replay_overlay.dart';
import 'video_stream.dart';

enum _AnalysisCameraView { compact, full, hidden }

enum _AnalysisAction {
  cameraCompact,
  cameraFull,
  reanalyze,
  toggleDemo,
  openDemoInScan,
}

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
    required this.createdAt,
    required this.isReference,
    required this.scanType,
    required this.analysisRevision,
    required this.algorithmVersion,
    required this.captureKind,
    required this.poseReplayAvailable,
  });

  final String scanId;
  final String label;
  final double start;
  final double end;
  final String frontalUrl;
  final String sagittalUrl;
  final String createdAt;
  final bool isReference;
  final String scanType;
  final int analysisRevision;
  final String algorithmVersion;
  final String captureKind;
  final bool poseReplayAvailable;

  bool get isFullRecording => scanType == 'full_recording';

  String get dateLabel {
    final parsed = DateTime.tryParse(createdAt)?.toLocal();
    if (parsed == null) return '';
    String two(int value) => value.toString().padLeft(2, '0');
    return '${two(parsed.day)}/${two(parsed.month)}/${parsed.year}';
  }

  factory _ClipInfo.fromJson(Map<String, dynamic> json) => _ClipInfo(
        scanId: json['scanId']?.toString() ?? '',
        label:
            json['label']?.toString() ?? '\u0110o\u1ea1n ph\u00e2n t\u00edch',
        start: (json['startOffsetSec'] as num?)?.toDouble() ?? 0,
        end: (json['endOffsetSec'] as num?)?.toDouble() ?? 0,
        frontalUrl: json['frontalVideoUrl']?.toString() ?? '',
        sagittalUrl: json['sagittalVideoUrl']?.toString() ?? '',
        createdAt: json['createdAt']?.toString() ?? '',
        isReference: json['isReference'] == true,
        scanType: json['scanType']?.toString() ?? 'segment',
        analysisRevision: (json['analysisRevision'] as num?)?.toInt() ?? 0,
        algorithmVersion: json['algorithmVersion']?.toString() ?? '',
        captureKind: json['captureKind']?.toString() ?? 'legacy_annotated',
        poseReplayAvailable: json['poseReplayAvailable'] == true,
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
    required this.isReference,
    required this.referenceStatus,
    required this.fsrAvailable,
    required this.captureKind,
    required this.analysisRevision,
  });

  final String id;
  final String sessionId;
  final String sessionCreatedAt;
  final String startedAt;
  final double duration;
  final String status;
  final bool isReference;
  final String referenceStatus;
  final bool fsrAvailable;
  final String captureKind;
  final int analysisRevision;

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
      isReference: json['isReference'] == true,
      referenceStatus: json['referenceStatus']?.toString() ?? 'none',
      fsrAvailable:
          json['available'] is Map && (json['available'] as Map)['fsr'] == true,
      captureKind: json['captureKind']?.toString() ?? 'legacy_annotated',
      analysisRevision: (json['analysisRevision'] as num?)?.toInt() ?? 0,
    );
  }
}

class _MenuAction extends StatelessWidget {
  const _MenuAction({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 17, color: AppColors.textSecondary),
        const SizedBox(width: 10),
        Text(label),
      ],
    );
  }
}

class TabAnalysis extends StatefulWidget {
  const TabAnalysis({super.key});

  @override
  State<TabAnalysis> createState() => _TabAnalysisState();
}

class _TabAnalysisState extends State<TabAnalysis> {
  static const String _demoArchiveId = 'rec-44479af3887d';
  static const String _demoSessionId = 's-6c4a45bfdc';
  static const String _demoScanId = 'clip-333d9448';
  static const String _demoFsrScanId = 'clip-fd7a8f16';

  List<_ClipInfo> _clips = [];
  List<_RecordingInfo> _recordings = [];
  _ClipInfo? _demoClip;
  String? _selectedId;
  String? _deletingArchiveId;
  String? _reanalyzingScanId;
  String? _loadedSessionId;
  int? _loadedScanCount;
  bool _loading = false;
  String? _error;
  Timer? _playTimer;
  double _position = 0;
  bool _playing = false;
  double _playbackStreamStart = 0;
  int _playbackGeneration = 0;
  int _analysisGeneration = 0;
  bool _useDemoVideos = false;
  bool _libraryCollapsed = false;
  _AnalysisPanel _analysisPanel = _AnalysisPanel.cameraCycles;
  _AnalysisCameraView _cameraView = _AnalysisCameraView.compact;
  _AnalysisCameraView _cameraViewBeforePresentation =
      _AnalysisCameraView.compact;
  late final SyncedVideoController _demoVideoController;

  bool get _cameraVisible => _cameraView != _AnalysisCameraView.hidden;
  bool get _cameraCompact => _cameraView == _AnalysisCameraView.compact;

  AnalysisSection get _analysisSection => switch (_analysisPanel) {
        _AnalysisPanel.cameraCycles => AnalysisSection.jointAngles,
        _AnalysisPanel.fsrRegions ||
        _AnalysisPanel.fsrPhases ||
        _AnalysisPanel.fsrReplay =>
          AnalysisSection.fsrForce,
        _AnalysisPanel.gaitMetrics => AnalysisSection.balance,
      };

  double _previewPosition(_ClipInfo clip) {
    final duration = clip.end - clip.start;
    if (!duration.isFinite || duration <= 0) return clip.start;
    // Full recordings usually contain setup/turning time at both ends.  A
    // late-middle preview is much more likely to show the measured walk than
    // an empty first/last frame, while the timeline remains fully seekable.
    return clip.start + duration * 0.74;
  }

  @override
  void initState() {
    super.initState();
    _demoVideoController = SyncedVideoController();
    _demoVideoController.setPlaybackRate(0.8);
  }

  @override
  void dispose() {
    _playTimer?.cancel();
    _demoVideoController.dispose();
    super.dispose();
  }

  Future<_ClipInfo?> _fetchDemoClip() async {
    try {
      final responses = await Future.wait([
        http.get(
          Uri.parse(
            'http://localhost:8000/sessions/$_demoSessionId/analysis-clips',
          ),
        ),
        http.get(
          Uri.parse(
            'http://localhost:8000/sessions/$_demoSessionId/recordings',
          ),
        ),
      ]).timeout(const Duration(seconds: 4));
      if (responses.any((response) => response.statusCode != 200)) return null;

      final decodedClips = jsonDecode(responses[0].body);
      final decodedRecordings = jsonDecode(responses[1].body);
      if (decodedClips is! List || decodedRecordings is! List) return null;
      final expectedArchive = decodedRecordings
          .whereType<Map<String, dynamic>>()
          .where(
            (item) =>
                item['archiveId']?.toString() == _demoArchiveId &&
                item['sessionId']?.toString() == _demoSessionId,
          )
          .firstOrNull;
      if (expectedArchive == null) return null;

      final clip = decodedClips
          .whereType<Map<String, dynamic>>()
          .map(_ClipInfo.fromJson)
          .where((clip) => clip.scanId == _demoScanId)
          .firstOrNull;
      if (clip == null || !clip.poseReplayAvailable) return null;
      final sameFrontalSource = clip.frontalUrl.split('?').first ==
          expectedArchive['frontalVideoUrl']?.toString().split('?').first;
      final sameSagittalSource = clip.sagittalUrl.split('?').first ==
          expectedArchive['sagittalVideoUrl']?.toString().split('?').first;
      return sameFrontalSource && sameSagittalSource ? clip : null;
    } catch (_) {
      return null;
    }
  }

  Future<void> _load(String sessionId) async {
    if (_loading) return;
    final patientId = context.read<SessionProvider>().activePatient?.id ?? '';
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final demoClipFuture = _fetchDemoClip();
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
      final demoClip = await demoClipFuture;
      if (!mounted) return;
      setState(() {
        _clips = clips;
        _recordings = recordings;
        _demoClip = demoClip;
        if (_useDemoVideos && demoClip == null) {
          _useDemoVideos = false;
        }
        _selectedId = clips.any((clip) => clip.scanId == _selectedId)
            ? _selectedId
            : (clips.isEmpty ? null : clips.first.scanId);
        _loadedSessionId = sessionId;
        _loadedScanCount =
            context.read<SessionProvider>().activeSession?.scans.length;
        final selected = _useDemoVideos
            ? demoClip
            : clips.where((clip) => clip.scanId == _selectedId).firstOrNull;
        if (selected != null) {
          _position = _previewPosition(selected);
          _playbackStreamStart = _position;
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

  Future<void> _reanalyzeClip(
    GaitSession session,
    _ClipInfo clip,
  ) async {
    if (_reanalyzingScanId != null) return;
    final isRaw = clip.captureKind == 'raw_v1';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Phân tích lại bằng thuật toán hiện tại?'),
        content: Text(
          isRaw
              ? 'Video raw, ADC FSR và timeline gốc sẽ được giữ nguyên. '
                  'Hệ thống tạo revision mới cho skeleton, nhận bước chân, '
                  'Newton/PeakFore/FSI và toàn bộ biểu đồ.'
              : 'Đây là bản ghi cũ đã đóng skeleton lên video. Hệ thống vẫn '
                  'có thể phân tích lại ở chế độ best-effort, nhưng không thể '
                  'gỡ hoàn toàn khung xương cũ khỏi ảnh.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('HỦY'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.replay_outlined, size: 18),
            label: const Text('PHÂN TÍCH LẠI'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    _playTimer?.cancel();
    setState(() {
      _reanalyzingScanId = clip.scanId;
      _playing = false;
    });
    try {
      final response = await http
          .post(
            Uri.parse(
              'http://127.0.0.1:8000/scans/${clip.scanId}/reanalyze-video'
              '?force=true',
            ),
          )
          .timeout(const Duration(minutes: 5));
      if (response.statusCode != 200) {
        String detail = 'Backend trả mã ${response.statusCode}';
        try {
          final body = jsonDecode(response.body);
          if (body is Map) detail = body['detail']?.toString() ?? detail;
        } catch (_) {}
        throw Exception(detail);
      }
      final result = jsonDecode(response.body);
      final revision =
          result is Map ? (result['analysisRevision'] as num?)?.toInt() : null;
      if (!mounted) return;
      await context.read<SessionProvider>().fetchPatients();
      if (!mounted) return;
      _loadedScanCount = null;
      await _load(session.id);
      if (!mounted) return;
      setState(() {
        _selectedId = clip.scanId;
        _position = _previewPosition(clip);
        _playbackStreamStart = _position;
        _playbackGeneration++;
        _analysisGeneration++;
      });
      AppAlert.show(
        context,
        'Đã tạo revision ${revision ?? 'mới'} từ cùng bản quay gốc. '
        'Skeleton và các biểu đồ đã được nạp lại.',
        tone: AppAlertTone.success,
      );
    } catch (error) {
      if (!mounted) return;
      AppAlert.show(
        context,
        'Không phân tích lại được: $error',
        tone: AppAlertTone.error,
      );
    } finally {
      if (mounted) setState(() => _reanalyzingScanId = null);
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
    final playbackClip = _useDemoVideos ? _demoClip : selectedClip;
    final playbackSessionId = _useDemoVideos ? _demoSessionId : session.id;
    final analysisContent = _useDemoVideos
        ? (_demoClip == null
            ? const Center(
                child: Text(
                  'Không nạp được video mẫu đã khóa nguồn.',
                  style: TextStyle(color: AppColors.textSecondary),
                ),
              )
            : _demoAnalysisPanelContent())
        : selectedScan == null
            ? _emptyState()
            : _analysisPanelContent(
                selectedScan,
                session,
                patient,
              );

    return Row(
      children: [
        Expanded(
          child: Column(
            children: [
              if (_cameraView == _AnalysisCameraView.hidden)
                _captureChartBar(provider, selectedClip)
              else
                _titleBar(provider, selectedClip),
              if (_cameraVisible && playbackClip != null) _analysisNavigation(),
              if (_cameraVisible && playbackClip != null)
                _videoPair(
                  playbackSessionId,
                  playbackClip,
                  isDemo: _useDemoVideos,
                ),
              if (_cameraVisible && playbackClip != null)
                _playbackControls(playbackClip),
              Expanded(
                child: _cameraView == _AnalysisCameraView.hidden
                    ? ColoredBox(
                        color: AppColors.panel,
                        child: analysisContent,
                      )
                    : analysisContent,
              ),
            ],
          ),
        ),
        if (_cameraView != _AnalysisCameraView.hidden) _clipList(session),
      ],
    );
  }

  Widget _demoAnalysisPanelContent() {
    return switch (_analysisPanel) {
      _AnalysisPanel.cameraCycles => GaitCycleAnalysis(
          key: ValueKey(
            'camera-$_demoScanId-${_demoClip!.analysisRevision}',
          ),
          scanId: _demoScanId,
          presentationProfile: true,
        ),
      _AnalysisPanel.gaitMetrics => _demoMetricsPanel(),
      _AnalysisPanel.fsrRegions => FsrRegionAnalysis(
          key: ValueKey('fsr-regions-$_demoFsrScanId-$_analysisGeneration'),
          scanId: _demoFsrScanId,
          presentationProfile: true,
        ),
      _AnalysisPanel.fsrPhases => FsrForcePhaseAnalysis(
          key: ValueKey('fsr-phases-$_demoFsrScanId-$_analysisGeneration'),
          scanId: _demoFsrScanId,
          sourceLabel: 'Dữ liệu chuẩn',
          presentationProfile: true,
        ),
      _AnalysisPanel.fsrReplay => FsrReplayAnalysis(
          key: ValueKey('fsr-replay-$_demoFsrScanId-$_analysisGeneration'),
          scanId: _demoFsrScanId,
          presentationProfile: true,
          position: _position,
        ),
    };
  }

  Widget _demoMetricsPanel() {
    return Column(
      children: [
        Container(
          width: double.infinity,
          margin: const EdgeInsets.fromLTRB(12, 9, 12, 0),
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
          decoration: BoxDecoration(
            color: AppColors.warning.withValues(alpha: 0.08),
            border: Border.all(
              color: AppColors.warning.withValues(alpha: 0.45),
            ),
            borderRadius: BorderRadius.circular(8),
          ),
          child: const Row(
            children: [
              Icon(
                Icons.assistant_direction_outlined,
                size: 16,
                color: AppColors.warning,
              ),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'NHẬN ĐỊNH THAM KHẢO · Hai chân lệch nhẹ khoảng 2–4%. '
                  'Khuyến nghị tinh chỉnh nhỏ, sau đó quét xác minh.',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: MetricsGrid(
            key: const ValueKey('demo-mild-left-prosthetic-metrics'),
            scan: DemoPresentationProfile.scan,
            baseline: DemoPresentationProfile.baseline,
            patient: DemoPresentationProfile.patient,
          ),
        ),
      ],
    );
  }

  String get _analysisPanelLabel => switch (_analysisPanel) {
        _AnalysisPanel.cameraCycles => 'GÓC KHỚP · CHU KỲ',
        _AnalysisPanel.gaitMetrics => 'THĂNG BẰNG · CHỈ SỐ',
        _AnalysisPanel.fsrRegions => 'LỰC FSR · 3 VÙNG',
        _AnalysisPanel.fsrPhases => 'LỰC FSR · TỔNG HỢP',
        _AnalysisPanel.fsrReplay => 'LỰC FSR · THEO THỜI ĐIỂM',
      };

  Widget _analysisPanelContent(
    ScanResult scan,
    GaitSession session,
    Patient patient,
  ) {
    final fsrScanId = _useDemoVideos ? _demoFsrScanId : scan.id;
    return switch (_analysisPanel) {
      _AnalysisPanel.cameraCycles => GaitCycleAnalysis(
          key: ValueKey('camera-${scan.id}-$_analysisGeneration'),
          scanId: scan.id,
        ),
      _AnalysisPanel.gaitMetrics => MetricsGrid(
          key: ValueKey('metrics-${scan.id}-$_analysisGeneration'),
          scan: scan,
          baseline: session.baseline,
          patient: patient,
        ),
      _AnalysisPanel.fsrRegions => FsrRegionAnalysis(
          key: ValueKey('fsr-regions-$fsrScanId-$_analysisGeneration'),
          scanId: fsrScanId,
          presentationProfile: _useDemoVideos,
        ),
      _AnalysisPanel.fsrPhases => FsrForcePhaseAnalysis(
          key: ValueKey('fsr-phases-$fsrScanId-$_analysisGeneration'),
          scanId: fsrScanId,
          presentationProfile: _useDemoVideos,
          sourceLabel: _useDemoVideos ? 'FSR mẫu đã lưu' : null,
        ),
      _AnalysisPanel.fsrReplay => FsrReplayAnalysis(
          key: ValueKey('fsr-replay-$fsrScanId-$_analysisGeneration'),
          scanId: fsrScanId,
          presentationProfile: _useDemoVideos,
          position: _position,
        ),
    };
  }

  Widget _analysisPanelMenu({bool enabled = true}) {
    return PopupMenuButton<_AnalysisPanel>(
      tooltip: context.tr('Chọn nội dung phân tích'),
      enabled: enabled,
      initialValue: _analysisPanel,
      onSelected: (panel) => setState(() => _analysisPanel = panel),
      itemBuilder: (context) => [
        _analysisMenuHeader('GÓC KHỚP'),
        _analysisMenuItem(
          _AnalysisPanel.cameraCycles,
          'Chu kỳ khớp · Mean ± SD',
        ),
        const PopupMenuDivider(),
        _analysisMenuHeader('LỰC FSR'),
        _analysisMenuItem(
          _AnalysisPanel.fsrPhases,
          'Tổng hợp · FSI & 3 pha',
        ),
        _analysisMenuItem(
          _AnalysisPanel.fsrRegions,
          'Theo 3 vùng · Mean ± SD',
        ),
        _analysisMenuItem(
          _AnalysisPanel.fsrReplay,
          'Theo thời điểm video',
        ),
        const PopupMenuDivider(),
        _analysisMenuHeader('THĂNG BẰNG'),
        _analysisMenuItem(
          _AnalysisPanel.gaitMetrics,
          'Chỉ số & đối xứng',
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

  PopupMenuItem<_AnalysisPanel> _analysisMenuHeader(String label) {
    return PopupMenuItem<_AnalysisPanel>(
      enabled: false,
      height: 28,
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 9,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.45,
          color: AppColors.textSecondary,
        ),
      ),
    );
  }

  CheckedPopupMenuItem<_AnalysisPanel> _analysisMenuItem(
    _AnalysisPanel panel,
    String label,
  ) {
    return CheckedPopupMenuItem<_AnalysisPanel>(
      value: panel,
      checked: _analysisPanel == panel,
      child: Text(label),
    );
  }

  void _selectAnalysisSection(AnalysisSection section) {
    setState(() {
      _analysisPanel = switch (section) {
        AnalysisSection.jointAngles => _AnalysisPanel.cameraCycles,
        AnalysisSection.fsrForce => _analysisSection == AnalysisSection.fsrForce
            ? _analysisPanel
            : _AnalysisPanel.fsrPhases,
        AnalysisSection.balance => _AnalysisPanel.gaitMetrics,
      };
    });
  }

  Widget _analysisNavigation() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: const BoxDecoration(
        color: AppColors.panel,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final switcher = AnalysisSectionSwitcher(
            selected: _analysisSection,
            onChanged: _selectAnalysisSection,
          );
          final sectionDetail = _analysisSectionDetail();

          if (constraints.maxWidth >= 760) {
            return Row(
              children: [
                SizedBox(width: 380, child: switcher),
                const SizedBox(width: 16),
                const SizedBox(
                  height: 26,
                  child: VerticalDivider(width: 1),
                ),
                const SizedBox(width: 16),
                Expanded(child: sectionDetail),
              ],
            );
          }
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              switcher,
              const SizedBox(height: 7),
              sectionDetail,
            ],
          );
        },
      ),
    );
  }

  Widget _analysisSectionDetail() {
    return switch (_analysisSection) {
      AnalysisSection.jointAngles => _sectionHint(
          Icons.multiline_chart_outlined,
          'Gối · hông · thân · Mean ± SD',
        ),
      AnalysisSection.balance => _sectionHint(
          Icons.monitor_heart_outlined,
          'Nhịp đi · đối xứng · xương chậu',
        ),
      AnalysisSection.fsrForce => Wrap(
          alignment: WrapAlignment.end,
          spacing: 6,
          runSpacing: 5,
          children: [
            _analysisPanelTab(
              _AnalysisPanel.fsrPhases,
              'Tổng hợp',
              Icons.analytics_outlined,
            ),
            _analysisPanelTab(
              _AnalysisPanel.fsrRegions,
              '3 vùng',
              Icons.grid_view_outlined,
            ),
            _analysisPanelTab(
              _AnalysisPanel.fsrReplay,
              'Theo thời điểm',
              Icons.play_circle_outline,
            ),
          ],
        ),
    };
  }

  Widget _sectionHint(IconData icon, String text) {
    return Align(
      alignment: Alignment.centerRight,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: AppColors.textSecondary),
          const SizedBox(width: 7),
          Flexible(
            child: Text(
              text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w600,
                color: AppColors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _analysisPanelTab(
    _AnalysisPanel panel,
    String label,
    IconData icon,
  ) {
    final selected = _analysisPanel == panel;
    return OutlinedButton.icon(
      onPressed: () => setState(() => _analysisPanel = panel),
      icon: Icon(icon, size: 14),
      label: Text(label),
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 31),
        padding: const EdgeInsets.symmetric(horizontal: 10),
        visualDensity: VisualDensity.compact,
        foregroundColor: selected ? AppColors.accent : AppColors.textSecondary,
        backgroundColor: selected
            ? AppColors.accent.withValues(alpha: 0.08)
            : AppColors.panel,
        side: BorderSide(
          color: selected
              ? AppColors.accent.withValues(alpha: 0.55)
              : AppColors.border,
        ),
        textStyle: TextStyle(
          fontSize: 10,
          fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
        ),
      ),
    );
  }

  Widget _captureChartBar(SessionProvider provider, _ClipInfo? clip) {
    final activeClip = _useDemoVideos ? _demoClip : clip;
    final clipLabel = _useDemoVideos
        ? 'Mẫu tham chiếu'
        : (clip?.label ?? 'Chưa chọn bản phân tích');
    final clipMeta = [
      if ((provider.activePatient?.name.trim() ?? '').isNotEmpty)
        'Hồ sơ: ${provider.activePatient!.name.trim()}',
      if (activeClip != null && activeClip.dateLabel.isNotEmpty)
        activeClip.dateLabel,
      if (activeClip != null)
        '${activeClip.start.toStringAsFixed(1)}–${activeClip.end.toStringAsFixed(1)} s',
    ].join(' · ');

    return Container(
      height: 42,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      decoration: const BoxDecoration(
        color: AppColors.panel,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final showModeTitle = constraints.maxWidth >= 850;
          return Row(
            children: [
              const Icon(
                Icons.present_to_all_outlined,
                size: 18,
                color: AppColors.accent,
              ),
              if (showModeTitle) ...[
                const SizedBox(width: 8),
                const Text(
                  'TRÌNH BÀY BÁO CÁO',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.3,
                  ),
                ),
                const SizedBox(width: 10),
                const SizedBox(
                  height: 20,
                  child: VerticalDivider(width: 1),
                ),
                const SizedBox(width: 10),
              ] else
                const SizedBox(width: 6),
              Expanded(
                child: Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: clipLabel,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      if (clipMeta.isNotEmpty)
                        TextSpan(
                          text: '  ·  $clipMeta',
                          style: const TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 10,
                            color: AppColors.textSecondary,
                          ),
                        ),
                    ],
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              _analysisPanelMenu(),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _exitPresentation,
                icon: const Icon(Icons.close_fullscreen_outlined, size: 16),
                label: const Text('THOÁT TRÌNH BÀY'),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(0, 32),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  visualDensity: VisualDensity.compact,
                  textStyle: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _titleBar(SessionProvider provider, _ClipInfo? clip) {
    final activeClip = _useDemoVideos ? _demoClip : clip;
    final clipLabel = _useDemoVideos
        ? 'Mẫu tham chiếu'
        : (clip?.label ?? 'Chưa chọn bản phân tích');
    final clipMeta = activeClip == null
        ? ''
        : '${activeClip.start.toStringAsFixed(1)}–'
            '${activeClip.end.toStringAsFixed(1)} s'
            '${activeClip.analysisRevision > 0 ? ' · REV ${activeClip.analysisRevision}' : ''}';

    return Container(
      height: 50,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: const BoxDecoration(
        color: AppColors.panel,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final showTitle = constraints.maxWidth >= 760;
          final showPresentationLabel = constraints.maxWidth >= 620;
          return Row(
            children: [
              IconButton(
                onPressed: () => provider.setTabIndex(2),
                icon: const Icon(Icons.arrow_back, size: 20),
                tooltip: context.tr('Về màn Scan'),
                visualDensity: VisualDensity.compact,
              ),
              if (showTitle) ...[
                const SizedBox(width: 3),
                const Text(
                  'PHÂN TÍCH DÁNG ĐI',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.2,
                  ),
                ),
                const SizedBox(width: 12),
                const SizedBox(
                  height: 20,
                  child: VerticalDivider(width: 1),
                ),
                const SizedBox(width: 12),
              ],
              Expanded(
                child: Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: clipLabel,
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      if (clipMeta.isNotEmpty)
                        TextSpan(
                          text: '  ·  $clipMeta',
                          style: const TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 10,
                            color: AppColors.textSecondary,
                          ),
                        ),
                    ],
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (_reanalyzingScanId != null) ...[
                const SizedBox(width: 8),
                const SizedBox.square(
                  dimension: 24,
                  child: Padding(
                    padding: EdgeInsets.all(4),
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
              ],
              const SizedBox(width: 8),
              if (constraints.maxWidth >= 720)
                OutlinedButton.icon(
                  onPressed: (_useDemoVideos || _demoClip != null)
                      ? () => _toggleDemoVideos(clip)
                      : null,
                  icon: Icon(
                    _useDemoVideos
                        ? Icons.analytics_outlined
                        : Icons.movie_outlined,
                    size: 15,
                  ),
                  label: Text(
                    _useDemoVideos ? 'BẢN PHÂN TÍCH' : 'VIDEO MẪU',
                  ),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(0, 32),
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    visualDensity: VisualDensity.compact,
                    foregroundColor: _useDemoVideos
                        ? AppColors.accentGreen
                        : AppColors.accent,
                    textStyle: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                )
              else
                IconButton(
                  onPressed: (_useDemoVideos || _demoClip != null)
                      ? () => _toggleDemoVideos(clip)
                      : null,
                  icon: Icon(
                    _useDemoVideos
                        ? Icons.analytics_outlined
                        : Icons.movie_outlined,
                    size: 18,
                  ),
                  tooltip: context.tr(
                    _useDemoVideos ? 'Trở lại bản phân tích' : 'Video mẫu',
                  ),
                  visualDensity: VisualDensity.compact,
                ),
              const SizedBox(width: 4),
              if (showPresentationLabel)
                OutlinedButton.icon(
                  onPressed: activeClip == null ? null : _enterPresentation,
                  icon: const Icon(Icons.present_to_all_outlined, size: 15),
                  label: const Text('TRÌNH BÀY'),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(0, 32),
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    visualDensity: VisualDensity.compact,
                    textStyle: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                )
              else
                IconButton(
                  onPressed: activeClip == null ? null : _enterPresentation,
                  icon: const Icon(Icons.present_to_all_outlined, size: 18),
                  tooltip: context.tr('Trình bày báo cáo'),
                  visualDensity: VisualDensity.compact,
                ),
              const SizedBox(width: 4),
              _analysisActionsMenu(provider, clip),
            ],
          );
        },
      ),
    );
  }

  Widget _analysisActionsMenu(
    SessionProvider provider,
    _ClipInfo? clip,
  ) {
    return PopupMenuButton<_AnalysisAction>(
      tooltip: context.tr('Tác vụ khác'),
      onSelected: (action) => _handleAnalysisAction(action, provider, clip),
      itemBuilder: (context) => [
        _analysisActionHeader('CAMERA'),
        CheckedPopupMenuItem<_AnalysisAction>(
          value: _AnalysisAction.cameraCompact,
          checked: _cameraView == _AnalysisCameraView.compact,
          child: const Text('Thu gọn'),
        ),
        CheckedPopupMenuItem<_AnalysisAction>(
          value: _AnalysisAction.cameraFull,
          checked: _cameraView == _AnalysisCameraView.full,
          child: const Text('Đầy đủ'),
        ),
        const PopupMenuDivider(),
        _analysisActionHeader('DỮ LIỆU & VIDEO'),
        if (clip != null && !_useDemoVideos)
          PopupMenuItem<_AnalysisAction>(
            value: _AnalysisAction.reanalyze,
            enabled: _reanalyzingScanId == null,
            child: const _MenuAction(
              icon: Icons.replay_outlined,
              label: 'Phân tích lại',
            ),
          ),
        PopupMenuItem<_AnalysisAction>(
          value: _AnalysisAction.toggleDemo,
          enabled: _useDemoVideos || _demoClip != null,
          child: _MenuAction(
            icon: _useDemoVideos
                ? Icons.analytics_outlined
                : Icons.movie_outlined,
            label: _useDemoVideos
                ? 'Trở lại bản phân tích'
                : 'Xem video mẫu · 0,8×',
          ),
        ),
        PopupMenuItem<_AnalysisAction>(
          value: _AnalysisAction.openDemoInScan,
          enabled: _demoClip != null,
          child: const _MenuAction(
            icon: Icons.open_in_new,
            label: 'Mở video mẫu ở Scan',
          ),
        ),
      ],
      icon: const Icon(Icons.more_horiz),
    );
  }

  PopupMenuItem<_AnalysisAction> _analysisActionHeader(String label) {
    return PopupMenuItem<_AnalysisAction>(
      enabled: false,
      height: 28,
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 9,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.45,
          color: AppColors.textSecondary,
        ),
      ),
    );
  }

  void _handleAnalysisAction(
    _AnalysisAction action,
    SessionProvider provider,
    _ClipInfo? clip,
  ) {
    switch (action) {
      case _AnalysisAction.cameraCompact:
        setState(() => _cameraView = _AnalysisCameraView.compact);
        break;
      case _AnalysisAction.cameraFull:
        setState(() => _cameraView = _AnalysisCameraView.full);
        break;
      case _AnalysisAction.reanalyze:
        final session = provider.activeSession;
        if (clip != null && session != null) {
          unawaited(_reanalyzeClip(session, clip));
        }
        break;
      case _AnalysisAction.toggleDemo:
        _toggleDemoVideos(clip);
        break;
      case _AnalysisAction.openDemoInScan:
        provider.openReferenceReplayInScan();
        break;
    }
  }

  void _toggleDemoVideos(_ClipInfo? selectedClip) {
    _playTimer?.cancel();
    final showDemo = !_useDemoVideos;
    if (showDemo && _demoClip == null) {
      AppAlert.show(
        context,
        'Không nạp được archive $_demoArchiveId. '
        'Hãy kiểm tra backend rồi thử lại.',
        tone: AppAlertTone.error,
      );
      return;
    }
    final targetClip = showDemo ? _demoClip : selectedClip;
    setState(() {
      _useDemoVideos = showDemo;
      if (showDemo) _analysisPanel = _AnalysisPanel.gaitMetrics;
      if (targetClip != null) {
        _position = _previewPosition(targetClip);
        _playbackStreamStart = _position;
        _playbackGeneration++;
      }
      _playing = false;
    });
    if (showDemo) {
      _demoVideoController.setPlaybackRate(0.8);
      _togglePlayback(targetClip!);
    } else {
      _demoVideoController.pause();
    }
  }

  void _enterPresentation() {
    _playTimer?.cancel();
    _demoVideoController.pause();
    setState(() {
      if (_cameraView != _AnalysisCameraView.hidden) {
        _cameraViewBeforePresentation = _cameraView;
      }
      _cameraView = _AnalysisCameraView.hidden;
      _libraryCollapsed = true;
      _playing = false;
    });
  }

  void _exitPresentation() {
    setState(() {
      _cameraView = _cameraViewBeforePresentation;
    });
  }

  void _selectClip(_ClipInfo clip) {
    _playTimer?.cancel();
    _demoVideoController.pause();
    setState(() {
      _selectedId = clip.scanId;
      _useDemoVideos = false;
      _position = _previewPosition(clip);
      _playbackStreamStart = _position;
      _playbackGeneration++;
      _playing = false;
    });
  }

  void _togglePlayback(_ClipInfo clip) {
    final isDemo = _useDemoVideos && clip.scanId == _demoScanId;
    if (_playing) {
      _playTimer?.cancel();
      if (isDemo) _demoVideoController.pause();
      setState(() => _playing = false);
      return;
    }
    if (_position >= clip.end) _position = clip.start;
    if (isDemo) {
      _demoVideoController.setPlaybackRate(0.8);
      _demoVideoController.play();
    }
    setState(() {
      _playbackStreamStart = _position;
      _playbackGeneration++;
      _playing = true;
    });
    final tick = Duration(milliseconds: isDemo ? 100 : 200);
    final delta = isDemo
        ? tick.inMilliseconds / 1000 * _demoVideoController.playbackRate
        : tick.inMilliseconds / 1000;
    _playTimer = Timer.periodic(tick, (timer) {
      if (!mounted || _position + delta >= clip.end) {
        timer.cancel();
        if (isDemo) _demoVideoController.pause();
        if (mounted) {
          setState(() {
            _position = _previewPosition(clip);
            _playbackStreamStart = _position;
            _playbackGeneration++;
            _playing = false;
          });
        }
        return;
      }
      setState(() => _position += delta);
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
            tooltip: context.tr(_playing ? 'Pause' : 'Play'),
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
                if (_useDemoVideos) _demoVideoController.pause();
                setState(() {
                  _position = next;
                  _playbackStreamStart = next;
                  _playbackGeneration++;
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

  Widget _videoPair(
    String sessionId,
    _ClipInfo clip, {
    bool isDemo = false,
  }) {
    final expectedPrefix = '/session-video/$sessionId/';
    final frontalUrl =
        clip.frontalUrl.contains(expectedPrefix) ? clip.frontalUrl : '';
    final sagittalUrl =
        clip.sagittalUrl.contains(expectedPrefix) ? clip.sagittalUrl : '';
    return SizedBox(
      height: _cameraCompact ? 135 : 220,
      child: Row(
        children: [
          Expanded(
            child: _recordedVideo(
              isDemo
                  ? 'VIDEO M\u1eaaU \u00b7 CH\u00cdNH DI\u1ec6N'
                  : 'CAM 1 \u00b7 CH\u00cdNH DI\u1ec6N',
              frontalUrl,
              clip,
              'frontal',
              isDemo: isDemo,
            ),
          ),
          Expanded(
            child: _recordedVideo(
              isDemo
                  ? 'VIDEO M\u1eaaU \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC'
                  : 'CAM 2 \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC',
              sagittalUrl,
              clip,
              'sagittal',
              isDemo: isDemo,
            ),
          ),
        ],
      ),
    );
  }

  Widget _recordedVideo(
    String label,
    String relativeUrl,
    _ClipInfo clip,
    String view, {
    bool isDemo = false,
  }) {
    final videoPath = relativeUrl.split('?').first;
    final framePath = videoPath.replaceFirst(
      '/session-video/',
      '/session-video-frame/',
    );
    final frameUrl =
        'http://localhost:8000$framePath?t=${_position.toStringAsFixed(2)}';
    final streamUrl = 'http://localhost:8000$videoPath'
        '?start=${_playbackStreamStart.toStringAsFixed(3)}'
        '&end=${clip.end.toStringAsFixed(3)}'
        '&loop=false&v=$_playbackGeneration';
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
                : _playing && !isDemo
                    ? createVideoStreamWidget(streamUrl)
                    : Image.network(
                        frameUrl,
                        fit: BoxFit.contain,
                        gaplessPlayback: true,
                        errorBuilder: (_, __, ___) => const Center(
                          child: Text(
                            'Không giải mã được video đã lưu',
                            style: TextStyle(
                              fontSize: 10,
                              color: AppColors.textSecondary,
                            ),
                          ),
                        ),
                      ),
          ),
          if (clip.poseReplayAvailable)
            Positioned.fill(
              child: PoseReplayOverlay(
                key: ValueKey(
                  '${clip.scanId}-$view-${clip.analysisRevision}-'
                  '$_analysisGeneration',
                ),
                scanId: clip.scanId,
                view: view,
                position: _position,
                analysisRevision: clip.analysisRevision,
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
          if (isDemo)
            const Positioned(
              right: 8,
              top: 8,
              child: DecoratedBox(
                decoration: BoxDecoration(color: Color(0xD9256D85)),
                child: Padding(
                  padding: EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  child: Text(
                    '$_demoArchiveId · 0,8×',
                    style: TextStyle(color: Colors.white, fontSize: 10),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _openRecordingSession(_RecordingInfo recording) async {
    if (recording.status != 'complete' || recording.duration <= 0) {
      AppAlert.show(
        context,
        'Bộ video này bị gián đoạn trước khi hoàn tất nên không thể phát ổn định. '
        'Hãy xóa bộ này và ghi lại, sau đó bấm DỪNG GHI trước khi tắt backend.',
        tone: AppAlertTone.error,
      );
      return;
    }
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
      padding: _libraryCollapsed
          ? const EdgeInsets.all(4)
          : const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: _libraryCollapsed
          ? Column(
              children: [
                IconButton(
                  onPressed: () => setState(() => _libraryCollapsed = false),
                  icon: const Icon(Icons.chevron_left),
                  tooltip: context.tr('Mở thư viện phiên ghi'),
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
              tooltip: context.tr('N\u1ea1p l\u1ea1i danh s\u00e1ch'),
            ),
            IconButton(
              onPressed: () => setState(() => _libraryCollapsed = true),
              icon: const Icon(Icons.chevron_right, size: 20),
              tooltip:
                  context.tr('Thu g\u1ecdn th\u01b0 vi\u1ec7n phi\u00ean ghi'),
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
            constraints: BoxConstraints(
              maxHeight: (MediaQuery.sizeOf(context).height * 0.28)
                  .clamp(140.0, 185.0),
            ),
            child: ListView.separated(
              shrinkWrap: true,
              itemCount: _recordings.length,
              separatorBuilder: (_, __) => const SizedBox(height: 4),
              itemBuilder: (_, index) {
                final recording = _recordings[index];
                final deleting = _deletingArchiveId == recording.id;
                final belongsToActiveSession =
                    recording.sessionId == session.id;
                return Material(
                  color: belongsToActiveSession
                      ? AppColors.accent.withValues(alpha: 0.07)
                      : AppColors.panel,
                  shape: RoundedRectangleBorder(
                    side: BorderSide(
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
                      '${recording.isReference ? ' · MẪU${recording.referenceStatus == 'draft' ? ' · chờ duyệt' : ''}' : ''}'
                      '${recording.status == 'interrupted' ? ' \u00b7 gi\u00e1n \u0111o\u1ea1n' : ''}'
                      '${recording.fsrAvailable ? ' \u00b7 FSR \u0111\u00e3 l\u01b0u' : ' \u00b7 thi\u1ebfu FSR'}',
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
                            tooltip:
                                context.tr('X\u00f3a tr\u1ecdn b\u1ed9 video'),
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
          'B\u1ea2N PH\u00c2N T\u00cdCH \u0110\u00c3 L\u01afU',
          style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        const Text(
          'G\u1ed3m b\u1ea3n ghi \u0111\u1ea7y \u0111\u1ee7 v\u00e0 c\u00e1c \u0111o\u1ea1n c\u1eaft theo m\u1ed1c.',
          style: TextStyle(fontSize: 10, color: AppColors.textSecondary),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: _clips.isEmpty && !_loading
              ? const Center(
                  child: Text(
                    'Ch\u01b0a c\u00f3 b\u1ea3n ph\u00e2n t\u00edch n\u00e0o.\nH\u00e3y ghi h\u00ecnh ho\u1eb7c \u0111\u1eb7t m\u1ed1c \u0111\u1ec3 t\u1ea1o \u0111o\u1ea1n c\u1eaft.',
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
                      leading: Icon(
                        clip.isFullRecording
                            ? Icons.video_library_outlined
                            : Icons.content_cut,
                        size: 18,
                        color: AppColors.accent,
                      ),
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
                        '${clip.isFullRecording ? '\u0110\u1ea6Y \u0110\u1ee6 \u00b7 ' : '\u0110O\u1ea0N C\u1eaeT \u00b7 '}'
                        '${clip.start.toStringAsFixed(1)}\u2013${clip.end.toStringAsFixed(1)} s'
                        ' \u00b7 ${(clip.end - clip.start).toStringAsFixed(1)} s'
                        '${clip.dateLabel.isEmpty ? '' : ' · ${clip.dateLabel}'}'
                        '${clip.isReference ? ' · MẪU' : ''}',
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
