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
import 'app_alert.dart';
import 'realtime_chart_workspace.dart';

import 'recording_timeline.dart';
import 'video_stream.dart';

class _SavedRecording {
  const _SavedRecording({
    required this.id,
    required this.startedAt,
    required this.duration,
    required this.frontalUrl,
    required this.sagittalUrl,
    required this.available,
  });

  final String id;
  final String startedAt;
  final double duration;
  final String frontalUrl;
  final String sagittalUrl;
  final bool available;

  String get shortId => id.length <= 10 ? id : id.substring(id.length - 8);

  factory _SavedRecording.fromJson(Map<String, dynamic> json) {
    return _SavedRecording(
      id: json['archiveId']?.toString() ?? '',
      startedAt: json['startedAt']?.toString() ?? '',
      duration: (json['durationSec'] as num?)?.toDouble() ?? 0,
      frontalUrl: json['frontalVideoUrl']?.toString() ?? '',
      sagittalUrl: json['sagittalVideoUrl']?.toString() ?? '',
      available: json['available']?['frontal'] == true &&
          json['available']?['sagittal'] == true,
    );
  }
}

class _CameraSetupSelection {
  const _CameraSetupSelection({
    required this.frontalIndex,
    required this.sagittalIndex,
    required this.singleCameraMode,
  });

  final int frontalIndex;
  final int sagittalIndex;
  final bool singleCameraMode;
}

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
  bool? _camera0PoseDetected;
  bool? _camera1PoseDetected;
  bool? _camerasSynchronized;
  double? _cameraSyncErrorMs;
  bool _singleCameraMode = false;
  bool _stereoCalibrationCompatible = false;
  bool _camerasSwapped = false;
  bool _swappingCameras = false;
  bool _cameraStatusLoaded = false;
  bool _cameraConfigured = false;
  bool _configuringCameras = false;
  bool _setupPromptShown = false;
  int? _frontalCameraIndex;
  int? _sagittalCameraIndex;

  bool _useDemoVideos = false;
  final List<_SavedRecording> _savedRecordings = [];
  String? _selectedRecordingId;
  String? _recordingsSessionId;
  bool _loadingRecordings = false;
  bool _scanWasActive = false;
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
        _camera0PoseDetected = body['camera0']?['poseDetected'] == true;
        _camera1PoseDetected = body['camera1']?['poseDetected'] == true;
        _camerasSwapped = body['swapped'] == true;
        final configuration = body['configuration'];
        _cameraConfigured =
            configuration is Map && configuration['configured'] == true;
        _frontalCameraIndex = configuration is Map
            ? (configuration['frontalIndex'] as num?)?.toInt()
            : null;
        _sagittalCameraIndex = configuration is Map
            ? (configuration['sagittalIndex'] as num?)?.toInt()
            : null;
        _singleCameraMode =
            configuration is Map && configuration['singleCameraMode'] == true;
        final synchronization = body['synchronization'];
        _camerasSynchronized = synchronization is Map
            ? synchronization['synchronized'] == true
            : null;
        _cameraSyncErrorMs = synchronization is Map
            ? (synchronization['lastErrorMs'] as num?)?.toDouble()
            : null;
        final stereoCalibration = body['stereoCalibration'];
        _stereoCalibrationCompatible =
            stereoCalibration is Map && stereoCalibration['compatible'] == true;
        _cameraStatusLoaded = true;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _camera0Connected = false;
          _camera1Connected = false;
          _camera0PoseDetected = false;
          _camera1PoseDetected = false;
          _camerasSynchronized = false;
          _cameraSyncErrorMs = null;
          _stereoCalibrationCompatible = false;
        });
      }
    }
  }

  Future<void> _showCameraSetupDialog() async {
    if (_configuringCameras) return;
    setState(() => _configuringCameras = true);
    try {
      final response = await http
          .get(Uri.parse('http://127.0.0.1:8000/camera/devices'))
          .timeout(const Duration(seconds: 5));
      if (response.statusCode != 200) {
        _message('Không thể dò camera: ${response.body}', error: true);
        return;
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final devices = (body['devices'] as List?)
              ?.whereType<Map<String, dynamic>>()
              .toList() ??
          const <Map<String, dynamic>>[];
      if (devices.isEmpty) {
        _message(
          body['message']?.toString() ??
              'Không tìm thấy camera. Kiểm tra cáp USB và đóng ứng dụng đang chiếm camera.',
          error: true,
        );
        return;
      }

      final availableIndexes =
          devices.map((device) => (device['index'] as num).toInt()).toList();
      if (!mounted) return;
      final selection = await showDialog<_CameraSetupSelection>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) {
          var frontalIndex = availableIndexes.contains(_frontalCameraIndex)
              ? _frontalCameraIndex!
              : (availableIndexes.length >= 3
                  ? availableIndexes[availableIndexes.length - 2]
                  : availableIndexes.first);
          var sagittalIndex = availableIndexes.contains(_sagittalCameraIndex)
              ? _sagittalCameraIndex!
              : (availableIndexes.length >= 3
                  ? availableIndexes.last
                  : availableIndexes.length > 1
                      ? availableIndexes[1]
                      : availableIndexes.first);
          var singleCameraMode = false;

          String labelFor(int index) {
            final device = devices.firstWhere(
                (item) => (item['index'] as num?)?.toInt() == index);
            final width = device['width']?.toString() ?? '?';
            final height = device['height']?.toString() ?? '?';
            return 'Camera $index · $width×$height';
          }

          Widget preview(String role, int index) {
            return Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(role,
                      style: const TextStyle(
                          fontSize: 10, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 5),
                  Container(
                    height: 120,
                    width: double.infinity,
                    color: AppColors.surfaceMuted,
                    child: Image.network(
                      'http://127.0.0.1:8000/camera/preview/$index?cache=${DateTime.now().millisecondsSinceEpoch}',
                      key: ValueKey('$role-$index'),
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => const Center(
                        child: Text('Không đọc được ảnh thử',
                            style: TextStyle(fontSize: 9)),
                      ),
                    ),
                  ),
                ],
              ),
            );
          }

          return StatefulBuilder(
            builder: (context, setDialogState) => AlertDialog(
              title: const Row(
                children: [
                  Icon(Icons.video_settings_outlined, size: 20),
                  SizedBox(width: 8),
                  Text('Thiết lập camera trước Scan'),
                ],
              ),
              content: SizedBox(
                width: 560,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Chọn vai trò theo ảnh thử, không dựa vào vị trí cắm USB. Camera mặt phẳng dọc cần thấy liên tục vai–hông–gối–cổ chân.',
                      style: TextStyle(
                          fontSize: 11, color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<int>(
                      key: ValueKey('frontal-$frontalIndex'),
                      initialValue: frontalIndex,
                      decoration: const InputDecoration(
                        labelText: 'Camera chính diện',
                        border: OutlineInputBorder(),
                        isDense: true,
                      ),
                      items: availableIndexes
                          .map((index) => DropdownMenuItem(
                                value: index,
                                child: Text(labelFor(index)),
                              ))
                          .toList(),
                      onChanged: (value) {
                        if (value != null) {
                          setDialogState(() => frontalIndex = value);
                        }
                      },
                    ),
                    const SizedBox(height: 10),
                    DropdownButtonFormField<int>(
                      key: ValueKey(
                        'sagittal-${singleCameraMode ? frontalIndex : sagittalIndex}',
                      ),
                      initialValue:
                          singleCameraMode ? frontalIndex : sagittalIndex,
                      decoration: const InputDecoration(
                        labelText: 'Camera mặt phẳng dọc',
                        border: OutlineInputBorder(),
                        isDense: true,
                      ),
                      items: availableIndexes
                          .map((index) => DropdownMenuItem(
                                value: index,
                                child: Text(labelFor(index)),
                              ))
                          .toList(),
                      onChanged: singleCameraMode
                          ? null
                          : (value) {
                              if (value != null) {
                                setDialogState(() => sagittalIndex = value);
                              }
                            },
                    ),
                    CheckboxListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      value: singleCameraMode,
                      title: const Text(
                          'Chỉ dùng một camera (đặt ở mặt phẳng dọc)',
                          style: TextStyle(fontSize: 11)),
                      onChanged: (value) => setDialogState(
                        () => singleCameraMode = value ?? false,
                      ),
                    ),
                    if (!singleCameraMode && frontalIndex == sagittalIndex)
                      const Padding(
                        padding: EdgeInsets.only(bottom: 8),
                        child: Text(
                            'Hai vai trò phải dùng hai camera khác nhau.',
                            style: TextStyle(
                                fontSize: 10, color: AppColors.critical)),
                      ),
                    Row(
                      children: [
                        preview('Ảnh thử · chính diện', frontalIndex),
                        const SizedBox(width: 10),
                        preview(
                          singleCameraMode
                              ? 'Ảnh thử · một camera'
                              : 'Ảnh thử · mặt phẳng dọc',
                          singleCameraMode ? frontalIndex : sagittalIndex,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('HỦY'),
                ),
                FilledButton.icon(
                  onPressed: !singleCameraMode && frontalIndex == sagittalIndex
                      ? null
                      : () => Navigator.of(dialogContext).pop(
                            _CameraSetupSelection(
                              frontalIndex: frontalIndex,
                              sagittalIndex: sagittalIndex,
                              singleCameraMode: singleCameraMode,
                            ),
                          ),
                  icon: const Icon(Icons.check, size: 16),
                  label: const Text('ÁP DỤNG & MỞ SCAN'),
                ),
              ],
            ),
          );
        },
      );
      if (selection == null) return;

      final apply = await http
          .post(
            Uri.parse('http://127.0.0.1:8000/camera/configure'),
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode({
              'frontalIndex': selection.frontalIndex,
              'sagittalIndex': selection.sagittalIndex,
              'singleCameraMode': selection.singleCameraMode,
            }),
          )
          .timeout(const Duration(seconds: 5));
      if (apply.statusCode != 200) {
        _message('Không thể áp dụng camera: ${apply.body}', error: true);
        return;
      }
      await Future<void>.delayed(const Duration(milliseconds: 600));
      await _pollCameraStatus();
      _message('Đã gán camera. Kiểm tra hai khung hình rồi bắt đầu ghi.');
    } catch (_) {
      _message('Backend chưa phản hồi khi thiết lập camera.', error: true);
    } finally {
      if (mounted) setState(() => _configuringCameras = false);
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

  _SavedRecording? get _selectedRecording {
    for (final item in _savedRecordings) {
      if (item.id == _selectedRecordingId) return item;
    }
    return null;
  }

  bool get _usingPlaybackSource => _useDemoVideos || _selectedRecording != null;

  Future<void> _loadRecordings(
    String sessionId, {
    bool force = false,
  }) async {
    if (_loadingRecordings || (!force && _recordingsSessionId == sessionId)) {
      return;
    }
    _loadingRecordings = true;
    try {
      final response = await http
          .get(Uri.parse(
            'http://127.0.0.1:8000/sessions/$sessionId/recordings',
          ))
          .timeout(const Duration(seconds: 3));
      if (response.statusCode != 200) return;
      final decoded = jsonDecode(response.body) as List;
      final recordings = decoded
          .whereType<Map<String, dynamic>>()
          .map(_SavedRecording.fromJson)
          .where((item) =>
              item.id.isNotEmpty &&
              item.available &&
              item.frontalUrl.isNotEmpty &&
              item.sagittalUrl.isNotEmpty)
          .toList();
      if (!mounted) return;
      setState(() {
        _savedRecordings
          ..clear()
          ..addAll(recordings);
        if (!_savedRecordings.any((item) => item.id == _selectedRecordingId)) {
          _selectedRecordingId = null;
        }
        _recordingsSessionId = sessionId;
      });
    } catch (_) {
      // Keep the last known list during a brief backend interruption.
    } finally {
      _loadingRecordings = false;
    }
  }

  void _message(String text, {bool error = false}) {
    if (!mounted) return;
    AppAlert.show(
      context,
      text,
      tone: error ? AppAlertTone.error : AppAlertTone.success,
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

  Future<void> _showStereoCalibrationDialog() async {
    Map<String, dynamic> status;
    try {
      final response = await http
          .get(Uri.parse(
            'http://127.0.0.1:8000/camera/calibration/status',
          ))
          .timeout(const Duration(seconds: 3));
      if (response.statusCode != 200) {
        _message('Không đọc được trạng thái hiệu chuẩn.', error: true);
        return;
      }
      status = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (error) {
      _message('Không kết nối được backend hiệu chuẩn: $error', error: true);
      return;
    }
    if (!mounted) return;

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        var workingStatus = Map<String, dynamic>.from(status);
        var busy = false;
        String? errorText;
        return StatefulBuilder(
          builder: (context, setDialogState) {
            Future<void> runAction(String action) async {
              setDialogState(() {
                busy = true;
                errorText = null;
              });
              try {
                final response = await http
                    .post(Uri.parse(
                      'http://127.0.0.1:8000/camera/calibration/$action',
                    ))
                    .timeout(const Duration(seconds: 30));
                final decoded = jsonDecode(response.body);
                if (response.statusCode != 200) {
                  final detail = decoded is Map ? decoded['detail'] : null;
                  throw Exception(detail ?? response.body);
                }
                if (!dialogContext.mounted) return;
                setDialogState(() {
                  workingStatus = {
                    ...workingStatus,
                    ...(decoded as Map).cast<String, dynamic>(),
                  };
                });
                if (action == 'solve') {
                  await _pollCameraStatus();
                }
              } catch (error) {
                if (!dialogContext.mounted) return;
                setDialogState(() {
                  errorText = error.toString().replaceFirst('Exception: ', '');
                });
              } finally {
                if (dialogContext.mounted) {
                  setDialogState(() => busy = false);
                }
              }
            }

            final sampleCount =
                (workingStatus['sampleCount'] as num?)?.toInt() ?? 0;
            final minimumSamples =
                (workingStatus['minimumSamples'] as num?)?.toInt() ?? 12;
            final ready = workingStatus['readyToSolve'] == true;
            final compatible = workingStatus['compatible'] == true;
            final calibration = workingStatus['calibration'];
            final stereoRms = calibration is Map
                ? (calibration['stereoRms'] as num?)?.toDouble()
                : null;
            return AlertDialog(
              title: const Row(
                children: [
                  Icon(Icons.view_in_ar_outlined, size: 21),
                  SizedBox(width: 8),
                  Text('Hiệu chuẩn hình học 2 camera'),
                ],
              ),
              content: SizedBox(
                width: 560,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '1. In bảng ChArUco trên A4 ngang ở Actual size 100% (ô vuông 30 mm; không co giãn).\n'
                        '2. Giữ bảng nghiêng khoảng 45° để cả hai camera cùng thấy.\n'
                        '3. Di chuyển bảng tới nhiều vị trí và góc khác nhau; mỗi vị trí bấm Chụp mẫu một lần.',
                        style: TextStyle(fontSize: 12, height: 1.5),
                      ),
                      const SizedBox(height: 10),
                      const SelectableText(
                        'Bảng in: http://127.0.0.1:8000/camera/calibration/board',
                        style: TextStyle(
                          fontSize: 11,
                          color: AppColors.accent,
                        ),
                      ),
                      const SizedBox(height: 14),
                      LinearProgressIndicator(
                        value: (sampleCount / minimumSamples).clamp(0.0, 1.0),
                        minHeight: 6,
                      ),
                      const SizedBox(height: 7),
                      Text(
                        'Đã chụp $sampleCount/$minimumSamples mẫu'
                        '${compatible ? ' · Calibration đang dùng được' : ''}'
                        '${stereoRms == null ? '' : ' · RMS ${stereoRms.toStringAsFixed(2)} px'}',
                        style: const TextStyle(fontSize: 11),
                      ),
                      if (errorText != null) ...[
                        const SizedBox(height: 10),
                        Text(
                          errorText!,
                          style: const TextStyle(
                            color: AppColors.critical,
                            fontSize: 11,
                          ),
                        ),
                      ],
                      const SizedBox(height: 14),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          OutlinedButton.icon(
                            onPressed: busy ? null : () => runAction('reset'),
                            icon: const Icon(Icons.restart_alt, size: 16),
                            label: const Text('Làm lại'),
                          ),
                          FilledButton.icon(
                            onPressed: busy ? null : () => runAction('capture'),
                            icon: const Icon(
                              Icons.add_a_photo_outlined,
                              size: 16,
                            ),
                            label: const Text('Chụp mẫu'),
                          ),
                          FilledButton.icon(
                            onPressed: busy || !ready
                                ? null
                                : () => runAction('solve'),
                            icon: busy
                                ? const SizedBox(
                                    width: 14,
                                    height: 14,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 1.7,
                                    ),
                                  )
                                : const Icon(
                                    Icons.calculate_outlined,
                                    size: 16,
                                  ),
                            label: const Text('Tính calibration'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: busy ? null : () => Navigator.of(context).pop(),
                  child: const Text('Đóng'),
                ),
              ],
            );
          },
        );
      },
    );
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
    final sessionId = provider.activeSession?.id;
    if (sessionId != null) {
      await _loadRecordings(sessionId, force: true);
    }
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
      _scanWasActive = false;
      return _empty(provider);
    }

    final scanIsActive = provider.activeTabIndex == 2;
    if (scanIsActive &&
        _cameraStatusLoaded &&
        !_cameraConfigured &&
        !_usingPlaybackSource &&
        !_setupPromptShown) {
      _setupPromptShown = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _showCameraSetupDialog();
      });
    }
    if (scanIsActive && !_scanWasActive) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadRecordings(session.id, force: true);
      });
    }
    _scanWasActive = scanIsActive;

    if (_loadedSegmentSessionId != session.id && !_loadingSegments) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadSegments(session.id);
      });
    }
    if (_recordingsSessionId != session.id && !_loadingRecordings) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadRecordings(session.id);
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
    final savedRecording = _selectedRecording;
    final demo = _usingPlaybackSource && !recording;
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
              color: recording
                  ? AppColors.critical
                  : demo
                      ? AppColors.accent
                      : AppColors.baseline,
            ),
          ),
          const SizedBox(width: 9),
          Text(
            recording
                ? '\u0110ang ghi'
                : savedRecording != null
                    ? 'Video \u0111\u00e3 l\u01b0u \u00b7 ${savedRecording.duration.toStringAsFixed(1)} s'
                    : demo
                        ? 'Video m\u1eabu \u00b7 4 c\u1eb7p \u00b7 0,8\u00d7'
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
              onPressed: (provider.isLoading || _usingPlaybackSource)
                  ? null
                  : _cameraConfigured
                      ? () => _startRecording(provider)
                      : _showCameraSetupDialog,
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
    final savedRecording = _selectedRecording;
    final sourceLabel = savedRecording != null
        ? 'VIDEO \u0110\u00c3 L\u01afU'
        : _useDemoVideos
            ? 'VIDEO M\u1eaaU 0,8\u00d7'
            : 'CAMERA TH\u1eacT';
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
          PopupMenuButton<String>(
            enabled: !session.isRecording,
            tooltip: 'Ch\u1ecdn ngu\u1ed3n video',
            onSelected: (value) {
              setState(() {
                _useDemoVideos = value == 'bundled';
                _selectedRecordingId =
                    value.startsWith('saved:') ? value.substring(6) : null;
              });
            },
            itemBuilder: (context) => [
              const PopupMenuItem(
                value: 'live',
                child: ListTile(
                  dense: true,
                  leading: Icon(Icons.videocam_outlined),
                  title: Text('Camera th\u1eadt'),
                ),
              ),
              const PopupMenuItem(
                value: 'bundled',
                child: ListTile(
                  dense: true,
                  leading: Icon(Icons.movie_outlined),
                  title: Text('Video m\u1eabu c\u00f3 s\u1eb5n'),
                ),
              ),
              for (final item in _savedRecordings)
                PopupMenuItem(
                  value: 'saved:${item.id}',
                  child: ListTile(
                    dense: true,
                    leading: const Icon(Icons.video_library_outlined),
                    title: Text('B\u1ed9 video ${item.shortId}'),
                    subtitle: Text(
                      '${item.duration.toStringAsFixed(1)} s \u00b7 ${item.startedAt}',
                    ),
                  ),
                ),
            ],
            child: IgnorePointer(
              child: OutlinedButton.icon(
                onPressed: session.isRecording ? null : () {},
                icon: Icon(
                  savedRecording != null
                      ? Icons.video_library_outlined
                      : _useDemoVideos
                          ? Icons.movie_outlined
                          : Icons.videocam_outlined,
                  size: 16,
                ),
                label: Text(sourceLabel),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(0, 28),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  textStyle: const TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          OutlinedButton.icon(
            onPressed:
                session.isRecording || _swappingCameras || _usingPlaybackSource
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
          if (!_usingPlaybackSource && !_singleCameraMode) ...[
            OutlinedButton.icon(
              onPressed: session.isRecording
                  ? null
                  : () => _showStereoCalibrationDialog(),
              icon: Icon(
                _stereoCalibrationCompatible
                    ? Icons.view_in_ar_outlined
                    : Icons.tune,
                size: 15,
              ),
              label: Text(
                _stereoCalibrationCompatible
                    ? 'STEREO 3D ĐÃ CHUẨN'
                    : 'HIỆU CHUẨN 3D',
              ),
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(0, 28),
                padding: const EdgeInsets.symmetric(horizontal: 9),
                foregroundColor:
                    _stereoCalibrationCompatible ? AppColors.accentGreen : null,
                textStyle: const TextStyle(
                  fontSize: 9,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            const SizedBox(width: 12),
          ],
          if (!_usingPlaybackSource && !_singleCameraMode) ...[
            _cameraSyncChip(),
            const SizedBox(width: 12),
          ],
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

  Widget _cameraSyncChip() {
    final synchronized = _camerasSynchronized == true;
    final bothPoses =
        _camera0PoseDetected == true && _camera1PoseDetected == true;
    final color = synchronized
        ? AppColors.accentGreen
        : bothPoses
            ? AppColors.warning
            : AppColors.textSecondary;
    final label = synchronized
        ? _cameraSyncErrorMs == null
            ? '2 CAM ĐÃ SYNC'
            : 'SYNC ${_cameraSyncErrorMs!.toStringAsFixed(0)} ms'
        : bothPoses
            ? 'ĐANG GHÉP KHUNG'
            : 'CHỜ POSE 2 CAM';
    return Tooltip(
      message: synchronized
          ? 'Hai camera đang được ghép theo thời điểm chụp; góc gập lấy từ camera dọc và nghiêng chậu lấy từ camera chính diện.'
          : 'Cần thấy đủ cơ thể ở cả hai camera để ghép dữ liệu.',
      child: Container(
        height: 28,
        padding: const EdgeInsets.symmetric(horizontal: 9),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(7),
          border: Border.all(color: color.withValues(alpha: 0.55)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.sync, size: 14, color: color),
            const SizedBox(width: 5),
            Text(
              label,
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w700,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _cameraWorkspace(
    GaitSession session, {
    EdgeInsetsGeometry padding = const EdgeInsets.fromLTRB(12, 0, 12, 7),
  }) {
    final savedRecording = _selectedRecording;
    return Padding(
      padding: padding,
      child: Row(
        children: [
          Expanded(
            child: _cameraCard(
              title: _useDemoVideos
                  ? 'VIDEO M\u1eaaU \u00b7 CH\u00cdNH DI\u1ec6N'
                  : savedRecording != null
                      ? 'VIDEO \u0110\u00c3 L\u01afU \u00b7 CH\u00cdNH DI\u1ec6N'
                      : 'CH\u00cdNH DI\u1ec6N · CAM ${_frontalCameraIndex ?? '—'}',
              url: _useDemoVideos
                  ? 'assets/assets/demo/demo_frontal_x08.mp4?v=mediapipe3'
                  : savedRecording != null
                      ? 'http://127.0.0.1:8000${savedRecording.frontalUrl}&loop=true'
                      : 'http://127.0.0.1:8000/video_feed_0',
              connected: _usingPlaybackSource ? true : _camera0Connected,
              poseDetected: _usingPlaybackSource ? true : _camera0PoseDetected,
              isVideoFile: _useDemoVideos,
              isSavedVideo: savedRecording != null,
              session: session,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _cameraCard(
              title: _useDemoVideos
                  ? 'VIDEO M\u1eaaU \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC'
                  : savedRecording != null
                      ? 'VIDEO \u0110\u00c3 L\u01afU \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC'
                      : 'M\u1eb6T PH\u1eb2NG D\u1eccC · CAM ${_sagittalCameraIndex ?? '—'}',
              url: _useDemoVideos
                  ? 'assets/assets/demo/demo_sagittal_x08.mp4?v=mediapipe3'
                  : savedRecording != null
                      ? 'http://127.0.0.1:8000${savedRecording.sagittalUrl}&loop=true'
                      : 'http://127.0.0.1:8000/video_feed_1',
              connected: _usingPlaybackSource ? true : _camera1Connected,
              poseDetected: _usingPlaybackSource ? true : _camera1PoseDetected,
              isVideoFile: _useDemoVideos,
              isSavedVideo: savedRecording != null,
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
    bool isVideoFile = false,
    bool isSavedVideo = false,
    required GaitSession session,
  }) {
    final poseMissing = !isVideoFile &&
        !isSavedVideo &&
        connected == true &&
        poseDetected == false;
    final stateText = isSavedVideo
        ? 'Video \u0111\u00e3 l\u01b0u'
        : isVideoFile
            ? 'Video m\u1eabu \u00b7 4 c\u1eb7p \u00b7 0,8\u00d7'
            : connected == null
                ? '\u0110ang k\u1ebft n\u1ed1i'
                : connected
                    ? poseMissing
                        ? 'Ch\u01b0a th\u1ea5y to\u00e0n th\u00e2n'
                        : '\u0110ang ho\u1ea1t \u0111\u1ed9ng'
                    : 'M\u1ea5t t\u00edn hi\u1ec7u';
    final stateColor = isVideoFile || isSavedVideo
        ? AppColors.accent
        : connected == null
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
            child: isVideoFile
                ? createVideoFileWidget(url)
                : isSavedVideo
                    ? createVideoStreamWidget(url)
                    : connected == true
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
              demoMode: _useDemoVideos,
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
