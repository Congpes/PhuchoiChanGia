import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' hide Text;

import '../l10n/app_language.dart';
import '../l10n/localized_text.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'app_alert.dart';
import 'video_stream.dart';

class _CameraRoleSelection {
  const _CameraRoleSelection({
    required this.frontalIndex,
    required this.sagittalIndex,
    required this.singleCameraMode,
  });

  final int frontalIndex;
  final int sagittalIndex;
  final bool singleCameraMode;
}

class TabPrepareSession extends StatefulWidget {
  const TabPrepareSession({super.key});

  @override
  State<TabPrepareSession> createState() => _TabPrepareSessionState();
}

class _TabPrepareSessionState extends State<TabPrepareSession> {
  final _formKey = GlobalKey<FormState>();
  late TextEditingController _injuryController;
  late TextEditingController _goalsController;
  late TextEditingController _noteController;
  late TextEditingController _leftLegController;
  late TextEditingController _rightLegController;
  String? _loadedPatientId;
  String _selectedNoteType = 'history';
  bool _configuringCamera = false;
  bool _connectingFsr = false;
  bool _backendOnline = false;
  bool _fsrLeftConnected = false;
  bool _fsrRightConnected = false;
  double? _fsrLeftTotal;
  double? _fsrRightTotal;
  List<String> _fsrPorts = const [];
  List<String> _fsrConnectedPorts = const [];
  String _fsrError = '';
  bool _camera0Connected = false;
  bool _camera1Connected = false;
  bool _camera0PoseDetected = false;
  bool _camera1PoseDetected = false;
  double _camera0CaptureFps = 0;
  double _camera1CaptureFps = 0;
  double _camera0PoseFps = 0;
  double _camera1PoseFps = 0;
  double _camera0ReliablePoseFps = 0;
  double _camera1ReliablePoseFps = 0;
  double _camera0PoseDetectionRate = 0;
  double _camera1PoseDetectionRate = 0;
  double _camera0ReliablePoseRate = 0;
  double _camera1ReliablePoseRate = 0;
  bool _camera0ImageReady = false;
  bool _camera1ImageReady = false;
  List<String> _camera0ImageReasons = const [];
  List<String> _camera1ImageReasons = const [];
  bool _singleCameraMode = false;
  bool _cameraSyncReady = false;
  Timer? _cameraStatusTimer;

  static const _cameraDiscoveryTimeout = Duration(seconds: 30);
  static const _cameraConfigureTimeout = Duration(seconds: 15);

  @override
  void initState() {
    super.initState();
    _injuryController = TextEditingController();
    _goalsController = TextEditingController();
    _noteController = TextEditingController();
    _leftLegController = TextEditingController();
    _rightLegController = TextEditingController();
    unawaited(_refreshPreparationStatus());
    _cameraStatusTimer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => unawaited(_refreshPreparationStatus()),
    );
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final patient = context.watch<SessionProvider>().activePatient;
    if (patient != null && patient.id != _loadedPatientId) {
      _loadedPatientId = patient.id;
      _injuryController.text = patient.injuryHistory;
      _goalsController.text = patient.treatmentGoals;
      _leftLegController.text = patient.leftLegLengthCm?.toString() ?? '';
      _rightLegController.text = patient.rightLegLengthCm?.toString() ?? '';
    }
  }

  @override
  void dispose() {
    _cameraStatusTimer?.cancel();
    _injuryController.dispose();
    _goalsController.dispose();
    _noteController.dispose();
    _leftLegController.dispose();
    _rightLegController.dispose();
    super.dispose();
  }

  Future<void> _refreshPreparationStatus() async {
    await Future.wait<void>([
      _refreshCameraStatus(),
      _refreshFsrStatus(),
    ]);
  }

  Future<void> _refreshFsrStatus() async {
    var leftConnected = false;
    var rightConnected = false;
    double? leftTotal;
    double? rightTotal;
    var ports = <String>[];
    var connectedPorts = <String>[];
    var error = '';
    try {
      final response = await http
          .get(Uri.parse('http://127.0.0.1:8000/fsr/latest'))
          .timeout(const Duration(seconds: 2));
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final left = body['left'] as Map<String, dynamic>?;
        final right = body['right'] as Map<String, dynamic>?;
        final serial = body['serialStatus'] as Map<String, dynamic>?;
        leftConnected = left?['connected'] == true;
        rightConnected = right?['connected'] == true;
        leftTotal = (left?['total'] as num?)?.toDouble();
        rightTotal = (right?['total'] as num?)?.toDouble();
        ports = (serial?['ports'] as List?)?.map((item) => '$item').toList() ??
            const [];
        connectedPorts = (serial?['connectedPorts'] as List?)
                ?.map((item) => '$item')
                .toList() ??
            const [];
        error = serial?['lastError']?.toString() ?? '';
      }
    } catch (_) {
      // Camera status already reports whether the shared backend is online.
    }
    if (!mounted ||
        (_fsrLeftConnected == leftConnected &&
            _fsrRightConnected == rightConnected &&
            _fsrLeftTotal == leftTotal &&
            _fsrRightTotal == rightTotal &&
            listEquals(_fsrPorts, ports) &&
            listEquals(_fsrConnectedPorts, connectedPorts) &&
            _fsrError == error)) {
      return;
    }
    setState(() {
      _fsrLeftConnected = leftConnected;
      _fsrRightConnected = rightConnected;
      _fsrLeftTotal = leftTotal;
      _fsrRightTotal = rightTotal;
      _fsrPorts = ports;
      _fsrConnectedPorts = connectedPorts;
      _fsrError = error;
    });
  }

  Future<void> _connectFsr() async {
    if (_connectingFsr) return;
    setState(() => _connectingFsr = true);
    try {
      final response = await http
          .post(Uri.parse('http://127.0.0.1:8000/fsr/connect'))
          .timeout(const Duration(seconds: 5));
      if (response.statusCode != 200) {
        throw Exception('Không thể khởi động kết nối FSR: ${response.body}');
      }
      await Future<void>.delayed(const Duration(milliseconds: 900));
      await _refreshFsrStatus();
      if (!mounted) return;
      AppAlert.show(
        context,
        _fsrLeftConnected && _fsrRightConnected
            ? 'Đã nhận dữ liệu lực từ cả hai chân ngay trong AI-ProGait.'
            : 'Đã mở kết nối FSR. Hệ thống sẽ tự nhận khi hai tấm bắt đầu gửi dữ liệu.',
        tone: _fsrLeftConnected && _fsrRightConnected
            ? AppAlertTone.success
            : AppAlertTone.warning,
      );
    } on TimeoutException {
      if (!mounted) return;
      AppAlert.show(
        context,
        'Kết nối FSR quá thời gian. Hãy kiểm tra Bluetooth và bật nguồn hai tấm.',
        tone: AppAlertTone.error,
      );
    } catch (error) {
      if (!mounted) return;
      AppAlert.show(context, '$error', tone: AppAlertTone.error);
    } finally {
      if (mounted) setState(() => _connectingFsr = false);
    }
  }

  Future<void> _refreshCameraStatus() async {
    var backendOnline = false;
    var camera0Connected = false;
    var camera1Connected = false;
    var camera0PoseDetected = false;
    var camera1PoseDetected = false;
    var camera0CaptureFps = 0.0;
    var camera1CaptureFps = 0.0;
    var camera0PoseFps = 0.0;
    var camera1PoseFps = 0.0;
    var camera0ReliablePoseFps = 0.0;
    var camera1ReliablePoseFps = 0.0;
    var camera0PoseDetectionRate = 0.0;
    var camera1PoseDetectionRate = 0.0;
    var camera0ReliablePoseRate = 0.0;
    var camera1ReliablePoseRate = 0.0;
    var camera0ImageReady = false;
    var camera1ImageReady = false;
    var camera0ImageReasons = <String>[];
    var camera1ImageReasons = <String>[];
    var singleCameraMode = false;
    var cameraSyncReady = false;
    try {
      final response = await http
          .get(Uri.parse('http://127.0.0.1:8000/camera-status'))
          .timeout(const Duration(seconds: 2));
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final camera0 = body['camera0'] as Map<String, dynamic>?;
        final camera1 = body['camera1'] as Map<String, dynamic>?;
        final configuration = body['configuration'] as Map<String, dynamic>?;
        final synchronization =
            body['synchronization'] as Map<String, dynamic>?;
        backendOnline = body['backendOnline'] == true;
        camera0Connected = camera0?['connected'] == true;
        camera1Connected = camera1?['connected'] == true;
        camera0PoseDetected = camera0?['poseDetected'] == true;
        camera1PoseDetected = camera1?['poseDetected'] == true;
        camera0CaptureFps = (camera0?['captureFps'] as num?)?.toDouble() ?? 0;
        camera1CaptureFps = (camera1?['captureFps'] as num?)?.toDouble() ?? 0;
        camera0PoseFps = (camera0?['poseFps'] as num?)?.toDouble() ?? 0;
        camera1PoseFps = (camera1?['poseFps'] as num?)?.toDouble() ?? 0;
        camera0ReliablePoseFps =
            (camera0?['reliablePoseFps'] as num?)?.toDouble() ?? 0;
        camera1ReliablePoseFps =
            (camera1?['reliablePoseFps'] as num?)?.toDouble() ?? 0;
        camera0PoseDetectionRate =
            (camera0?['poseDetectionRate'] as num?)?.toDouble() ?? 0;
        camera1PoseDetectionRate =
            (camera1?['poseDetectionRate'] as num?)?.toDouble() ?? 0;
        camera0ReliablePoseRate =
            (camera0?['reliablePoseRate'] as num?)?.toDouble() ?? 0;
        camera1ReliablePoseRate =
            (camera1?['reliablePoseRate'] as num?)?.toDouble() ?? 0;
        final image0 = camera0?['imageQuality'] as Map<String, dynamic>?;
        final image1 = camera1?['imageQuality'] as Map<String, dynamic>?;
        camera0ImageReady = image0?['qualityReady'] == true;
        camera1ImageReady = image1?['qualityReady'] == true;
        camera0ImageReasons =
            (image0?['qualityReasons'] as List?)?.map((e) => '$e').toList() ??
                [];
        camera1ImageReasons =
            (image1?['qualityReasons'] as List?)?.map((e) => '$e').toList() ??
                [];
        singleCameraMode = configuration?['singleCameraMode'] == true;
        final paired =
            (synchronization?['recentPairedSamples'] as num?)?.toInt() ??
                (synchronization?['pairedSamples'] as num?)?.toInt() ??
                0;
        final fallback =
            (synchronization?['recentFallbackSamples'] as num?)?.toInt() ??
                (synchronization?['fallbackSamples'] as num?)?.toInt() ??
                0;
        final pairRatio = paired / (paired + fallback).clamp(1, 1 << 30);
        cameraSyncReady = singleCameraMode ||
            (synchronization?['synchronized'] == true &&
                paired >= 5 &&
                pairRatio >= 0.70);
      }
    } catch (_) {
      // The status banner below explains that the backend is unavailable.
    }
    if (!mounted) return;
    if (_backendOnline == backendOnline &&
        _camera0Connected == camera0Connected &&
        _camera1Connected == camera1Connected &&
        _camera0PoseDetected == camera0PoseDetected &&
        _camera1PoseDetected == camera1PoseDetected &&
        _camera0CaptureFps == camera0CaptureFps &&
        _camera1CaptureFps == camera1CaptureFps &&
        _camera0PoseFps == camera0PoseFps &&
        _camera1PoseFps == camera1PoseFps &&
        _camera0ReliablePoseFps == camera0ReliablePoseFps &&
        _camera1ReliablePoseFps == camera1ReliablePoseFps &&
        _camera0PoseDetectionRate == camera0PoseDetectionRate &&
        _camera1PoseDetectionRate == camera1PoseDetectionRate &&
        _camera0ReliablePoseRate == camera0ReliablePoseRate &&
        _camera1ReliablePoseRate == camera1ReliablePoseRate &&
        _camera0ImageReady == camera0ImageReady &&
        _camera1ImageReady == camera1ImageReady &&
        _cameraSyncReady == cameraSyncReady &&
        listEquals(_camera0ImageReasons, camera0ImageReasons) &&
        listEquals(_camera1ImageReasons, camera1ImageReasons) &&
        _singleCameraMode == singleCameraMode) {
      return;
    }
    setState(() {
      _backendOnline = backendOnline;
      _camera0Connected = camera0Connected;
      _camera1Connected = camera1Connected;
      _camera0PoseDetected = camera0PoseDetected;
      _camera1PoseDetected = camera1PoseDetected;
      _camera0CaptureFps = camera0CaptureFps;
      _camera1CaptureFps = camera1CaptureFps;
      _camera0PoseFps = camera0PoseFps;
      _camera1PoseFps = camera1PoseFps;
      _camera0ReliablePoseFps = camera0ReliablePoseFps;
      _camera1ReliablePoseFps = camera1ReliablePoseFps;
      _camera0PoseDetectionRate = camera0PoseDetectionRate;
      _camera1PoseDetectionRate = camera1PoseDetectionRate;
      _camera0ReliablePoseRate = camera0ReliablePoseRate;
      _camera1ReliablePoseRate = camera1ReliablePoseRate;
      _camera0ImageReady = camera0ImageReady;
      _camera1ImageReady = camera1ImageReady;
      _camera0ImageReasons = camera0ImageReasons;
      _camera1ImageReasons = camera1ImageReasons;
      _singleCameraMode = singleCameraMode;
      _cameraSyncReady = cameraSyncReady;
    });
  }

  bool get _camerasReady {
    if (!_backendOnline) return false;
    final camera0Ready = _camera0Connected &&
        _camera0PoseDetected &&
        _camera0CaptureFps >= 12 &&
        _camera0PoseFps >= 8 &&
        _camera0ReliablePoseFps >= 6 &&
        _camera0PoseDetectionRate >= 0.70 &&
        _camera0ReliablePoseRate >= 0.50 &&
        _camera0ImageReady;
    final camera1Ready = _camera1Connected &&
        _camera1PoseDetected &&
        _camera1CaptureFps >= 12 &&
        _camera1PoseFps >= 8 &&
        _camera1ReliablePoseFps >= 6 &&
        _camera1PoseDetectionRate >= 0.70 &&
        _camera1ReliablePoseRate >= 0.50 &&
        _camera1ImageReady;
    return _singleCameraMode
        ? camera1Ready
        : camera0Ready && camera1Ready && _cameraSyncReady;
  }

  bool get _cameraHardwareReady {
    if (!_backendOnline) return false;
    final camera0Ready =
        _camera0Connected && _camera0CaptureFps >= 12 && _camera0ImageReady;
    final camera1Ready =
        _camera1Connected && _camera1CaptureFps >= 12 && _camera1ImageReady;
    return _singleCameraMode ? camera1Ready : camera0Ready && camera1Ready;
  }

  String get _cameraReadinessText {
    if (!_backendOnline) return 'Backend chưa chạy.';
    final camera0Required = !_singleCameraMode;
    if ((camera0Required && !_camera0Connected) || !_camera1Connected) {
      return _singleCameraMode
          ? 'Chưa nhận camera mặt phẳng dọc. Bấm CÀI CAMERA để chọn thiết bị.'
          : 'Chưa nhận đủ hai camera. Bấm CÀI CAMERA để chọn chính diện và mặt phẳng dọc.';
    }
    final captureFps = _singleCameraMode
        ? _camera1CaptureFps
        : [_camera0CaptureFps, _camera1CaptureFps].reduce(
            (value, item) => value < item ? value : item,
          );
    final poseFps = _singleCameraMode
        ? _camera1PoseFps
        : [_camera0PoseFps, _camera1PoseFps].reduce(
            (value, item) => value < item ? value : item,
          );
    final reliablePoseFps = _singleCameraMode
        ? _camera1ReliablePoseFps
        : [_camera0ReliablePoseFps, _camera1ReliablePoseFps].reduce(
            (value, item) => value < item ? value : item,
          );
    final detectionRate = _singleCameraMode
        ? _camera1PoseDetectionRate
        : [_camera0PoseDetectionRate, _camera1PoseDetectionRate].reduce(
            (value, item) => value < item ? value : item,
          );
    final reliableRate = _singleCameraMode
        ? _camera1ReliablePoseRate
        : [_camera0ReliablePoseRate, _camera1ReliablePoseRate].reduce(
            (value, item) => value < item ? value : item,
          );
    final imageReady = _singleCameraMode
        ? _camera1ImageReady
        : _camera0ImageReady && _camera1ImageReady;
    if (!imageReady) {
      const labels = {
        'too_dark': 'hình quá tối hoặc nắp camera đang đóng',
        'overexposed': 'hình bị cháy sáng',
        'too_blurry': 'hình quá mờ/mất nét',
      };
      final reasons = {
        ..._camera0ImageReasons,
        ..._camera1ImageReasons,
      }.map((item) => labels[item] ?? item).join(', ');
      return 'Chất lượng hình chưa đạt${reasons.isEmpty ? '' : ': $reasons'}.';
    }
    if (captureFps < 12) {
      return 'Camera mới đạt ${captureFps.toStringAsFixed(1)} FPS (cần ≥ 12). '
          'Tăng ánh sáng và đóng Camera/Zoom/Meet.';
    }
    final requiredPoseDetected = _singleCameraMode
        ? _camera1PoseDetected
        : _camera0PoseDetected && _camera1PoseDetected;
    if (poseFps < 8 || !requiredPoseDetected) {
      return 'Chưa thấy ổn định toàn thân ở cả hai góc (pose ${poseFps.toStringAsFixed(1)} FPS, cần ≥ 8).';
    }
    if (detectionRate < 0.70) {
      return 'Nhận diện toàn thân mới đạt ${(detectionRate * 100).toStringAsFixed(0)}% '
          'frame (cần ≥ 70%).';
    }
    if (reliablePoseFps < 6 || reliableRate < 0.50) {
      return 'Pose có chất lượng mới đạt ${reliablePoseFps.toStringAsFixed(1)} FPS '
          'và ${(reliableRate * 100).toStringAsFixed(0)}% frame '
          '(cần ≥ 6 FPS, ≥ 50%). Hãy thấy trọn vai–hông–gối–cổ chân.';
    }
    if (!_singleCameraMode && !_cameraSyncReady) {
      return 'Hai camera chưa ghép frame đồng thời ổn định. Hãy đứng trong cả hai khung và chờ vài giây.';
    }
    return 'Sẵn sàng ghi · camera ${captureFps.toStringAsFixed(1)} FPS · '
        'pose ${poseFps.toStringAsFixed(1)} FPS.';
  }

  bool get _fsrReady => _fsrLeftConnected && _fsrRightConnected;

  String get _fsrReadinessText {
    String force(double? value) =>
        value == null ? '—' : value.toStringAsFixed(1);
    if (_fsrReady) {
      return 'FSR 2/2 · trái ${force(_fsrLeftTotal)} N · '
          'phải ${force(_fsrRightTotal)} N';
    }
    if (_fsrLeftConnected || _fsrRightConnected) {
      return 'FSR 1/2 · chưa nhận chân '
          '${_fsrLeftConnected ? 'phải' : 'trái'}';
    }
    if (_fsrConnectedPorts.isNotEmpty) {
      return 'Đã mở ${_fsrConnectedPorts.join(', ')} · đang chờ LL/RR';
    }
    if (_fsrError.isNotEmpty) {
      final portBusy = _fsrError.toLowerCase().contains('access is denied') ||
          _fsrError.toLowerCase().contains('permissionerror');
      return portBusy
          ? 'Cổng FSR đang bị ứng dụng khác giữ · hãy đóng bản FSR Transmitter cũ'
          : 'FSR chưa kết nối · $_fsrError';
    }
    return _fsrPorts.isEmpty
        ? 'Chưa thấy FSR · vẫn có thể quay chỉ với camera'
        : 'Đã tìm thấy ${_fsrPorts.join(', ')} · đang kết nối';
  }

  Future<void> _savePatientDetails(SessionProvider provider) async {
    final patient = provider.activePatient;
    if (patient == null) return;
    if (!_formKey.currentState!.validate()) return;
    await provider.updatePatientDetails(
      patient.id,
      patient.name,
      patient.age,
      patient.heightCm,
      patient.weightKg,
      double.tryParse(_leftLegController.text.trim()),
      double.tryParse(_rightLegController.text.trim()),
      patient.healthyLeg,
      patient.prostheticLeg,
      _injuryController.text,
      _goalsController.text,
    );
    if (!mounted) return;
    AppAlert.show(
      context,
      'Đã cập nhật số đo hiệu chuẩn và thông tin lâm sàng.',
      tone: AppAlertTone.success,
    );
  }

  Future<void> _addClinicalNote(SessionProvider provider) async {
    if (_noteController.text.trim().isEmpty) return;
    await provider.createClinicalNote(
      _selectedNoteType,
      _noteController.text.trim(),
    );
    if (!mounted) return;
    _noteController.clear();

    AppAlert.show(
      context,
      'Đã thêm ghi chú lâm sàng thành công.',
      tone: AppAlertTone.success,
    );
  }

  Future<void> _showCameraSetupDialog() async {
    if (_configuringCamera) return;
    setState(() => _configuringCamera = true);
    var operation = 'dò danh sách camera';
    try {
      final response = await http
          .get(Uri.parse('http://127.0.0.1:8000/camera/devices?refresh=true'))
          .timeout(_cameraDiscoveryTimeout);
      if (response.statusCode != 200) {
        throw Exception('Không thể dò camera: ${response.body}');
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final devices = (body['devices'] as List?)
              ?.whereType<Map<String, dynamic>>()
              .toList() ??
          const <Map<String, dynamic>>[];
      if (devices.isEmpty) {
        throw Exception(
          body['message']?.toString() ??
              'Không tìm thấy camera. Kiểm tra cáp USB và đóng ứng dụng đang chiếm camera.',
        );
      }
      final indexes =
          devices.map((device) => (device['index'] as num).toInt()).toList();
      final preferredPair = indexes.length >= 3
          ? indexes.sublist(indexes.length - 2)
          : List<int>.from(indexes);
      final configuration = body['configuration'] is Map
          ? Map<String, dynamic>.from(body['configuration'] as Map)
          : const <String, dynamic>{};
      int? configuredIndex(String key) {
        final value = configuration[key];
        final index = value is num ? value.toInt() : null;
        return index != null && indexes.contains(index) ? index : null;
      }

      if (!mounted) return;
      final selection = await showDialog<_CameraRoleSelection>(
        context: context,
        builder: (dialogContext) {
          final configuredFrontal = configuredIndex('frontalIndex');
          final configuredSagittal = configuredIndex('sagittalIndex');
          final configuredUsesPreferredPair = preferredPair.length >= 2 &&
              configuredFrontal != null &&
              configuredSagittal != null &&
              preferredPair.contains(configuredFrontal) &&
              preferredPair.contains(configuredSagittal);
          // On this workstation index 0 is the laptop webcam. Once both Brio
          // cameras are present, propose the two external slots even if a
          // previous one-Brio session had remembered laptop + Brio.
          var frontalIndex = indexes.length >= 3 && !configuredUsesPreferredPair
              ? preferredPair.first
              : configuredFrontal ?? preferredPair.first;
          var sagittalIndex =
              indexes.length >= 3 && !configuredUsesPreferredPair
                  ? preferredPair.last
                  : configuredSagittal ??
                      (preferredPair.length > 1
                          ? preferredPair.last
                          : preferredPair.first);
          var singleCameraMode = configuration['singleCameraMode'] == true;

          String labelFor(int index) {
            final device = devices.firstWhere(
              (item) => (item['index'] as num?)?.toInt() == index,
            );
            final width = device['width']?.toString() ?? '?';
            final height = device['height']?.toString() ?? '?';
            final fps = (device['probeFps'] as num?)?.toDouble() ?? 0;
            final imageQuality = device['imageQuality'] is Map
                ? Map<String, dynamic>.from(device['imageQuality'] as Map)
                : const <String, dynamic>{};
            final qualityReady = imageQuality['qualityReady'] != false;
            final reasons = (imageQuality['qualityReasons'] as List?)
                    ?.map((item) => item.toString())
                    .toSet() ??
                const <String>{};
            final qualityLabel = qualityReady
                ? 'hình OK'
                : reasons.contains('too_dark')
                    ? 'CẢNH BÁO: hình tối'
                    : reasons.contains('overexposed')
                        ? 'CẢNH BÁO: cháy sáng'
                        : 'CẢNH BÁO: hình mờ';
            return 'Camera $index · $width×$height · '
                '${fps.toStringAsFixed(1)} FPS · $qualityLabel';
          }

          return StatefulBuilder(
            builder: (context, setDialogState) => AlertDialog(
              title: const Row(
                children: [
                  Icon(Icons.video_settings_outlined, size: 20),
                  SizedBox(width: 8),
                  Text('Thiết lập camera'),
                ],
              ),
              content: SizedBox(
                width: 430,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      indexes.length >= 3
                          ? 'Đã đề xuất hai camera ngoài theo thứ tự Windows; webcam laptop chỉ dự phòng. Cổng có thể đổi nên hãy xác nhận lại bằng ảnh thử.'
                          : 'Chọn camera cho góc chính diện và mặt phẳng dọc. Có thể đổi ngay trong phiên; hai luồng hình sẽ tạm dừng vài giây khi áp dụng.',
                      style: const TextStyle(
                          fontSize: 11, color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: 14),
                    DropdownButtonFormField<int>(
                      key: ValueKey('prepare-frontal-$frontalIndex'),
                      initialValue: frontalIndex,
                      decoration: const InputDecoration(
                        labelText: 'Camera chính diện',
                        border: OutlineInputBorder(),
                        isDense: true,
                      ).localized(context),
                      items: indexes
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
                          'prepare-sagittal-${singleCameraMode ? frontalIndex : sagittalIndex}'),
                      initialValue:
                          singleCameraMode ? frontalIndex : sagittalIndex,
                      decoration: const InputDecoration(
                        labelText: 'Camera mặt phẳng dọc',
                        border: OutlineInputBorder(),
                        isDense: true,
                      ).localized(context),
                      items: indexes
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
                        'Chỉ dùng một camera (mặt phẳng dọc)',
                        style: TextStyle(fontSize: 11),
                      ),
                      onChanged: (value) => setDialogState(
                        () => singleCameraMode = value ?? false,
                      ),
                    ),
                    if (!singleCameraMode && frontalIndex == sagittalIndex)
                      const Text(
                        'Hai vai trò phải dùng hai camera khác nhau.',
                        style:
                            TextStyle(fontSize: 10, color: AppColors.critical),
                      ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('HỦY'),
                ),
                FilledButton.icon(
                  onPressed: !singleCameraMode && frontalIndex == sagittalIndex
                      ? null
                      : () => Navigator.pop(
                            dialogContext,
                            _CameraRoleSelection(
                              frontalIndex: frontalIndex,
                              sagittalIndex: sagittalIndex,
                              singleCameraMode: singleCameraMode,
                            ),
                          ),
                  icon: const Icon(Icons.check, size: 16),
                  label: const Text('ÁP DỤNG'),
                ),
              ],
            ),
          );
        },
      );
      if (selection == null) return;
      operation = 'áp dụng cấu hình hai camera';
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
          .timeout(_cameraConfigureTimeout);
      if (apply.statusCode != 200) {
        throw Exception('Không thể áp dụng camera: ${apply.body}');
      }
      await Future<void>.delayed(const Duration(milliseconds: 500));
      await _refreshPreparationStatus();
      if (!mounted) return;
      setState(() {});
      AppAlert.show(
        context,
        'Đã áp dụng cài đặt camera. Kiểm tra hai góc quay trước khi ghi hình.',
        tone: AppAlertTone.success,
      );
    } on TimeoutException {
      if (!mounted) return;
      AppAlert.show(
        context,
        'Quá thời gian khi $operation. Backend có thể vẫn đang kiểm tra driver camera. '
        'Hãy đóng Camera/Zoom/Meet, rút cắm lại USB rồi thử một lần nữa.',
        tone: AppAlertTone.error,
      );
    } catch (error) {
      if (!mounted) return;
      AppAlert.show(
        context,
        error.toString(),
        tone: AppAlertTone.error,
      );
    } finally {
      if (mounted) setState(() => _configuringCamera = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;
    final session = provider.activeSession;

    if (patient == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.person_search_outlined,
                size: 64, color: AppColors.textSecondary),
            const SizedBox(height: 16),
            const Text(
              'Chưa chọn bệnh nhân',
              style: TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 16,
                  color: AppColors.textPrimary),
            ),
            const SizedBox(height: 8),
            const Text(
              'Vui lòng chọn bệnh nhân hoặc thêm bệnh án mới ở Tab Bệnh nhân.',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: () => provider.setTabIndex(0),
              icon: const Icon(Icons.people_outline, color: AppColors.onAccent),
              label: const Text(
                'QUAY LẠI HỒ SƠ BỆNH NHÂN',
                style: TextStyle(
                    color: AppColors.onAccent, fontWeight: FontWeight.bold),
              ),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.accent,
                padding:
                    const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8)),
              ),
            ),
          ],
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.all(16.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Left column: Camera view alignment check
          Expanded(
            flex: 3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.arrow_back,
                          color: AppColors.accent, size: 20),
                      onPressed: () => provider.setTabIndex(0),
                      tooltip: context.tr('Quay lại Hồ sơ bệnh nhân'),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Row(
                        children: [
                          const Flexible(
                            child: Text(
                              'Xem trước góc quay Camera & Đo lường sinh học',
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                                color: AppColors.textPrimary,
                              ),
                            ),
                          ),
                          if (session?.isReference == true) ...[
                            const SizedBox(width: 10),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 3,
                              ),
                              decoration: BoxDecoration(
                                color:
                                    AppColors.warning.withValues(alpha: 0.12),
                                borderRadius: BorderRadius.circular(5),
                                border: Border.all(
                                  color:
                                      AppColors.warning.withValues(alpha: 0.55),
                                ),
                              ),
                              child: const Text(
                                'THU MẪU THAM CHIẾU',
                                style: TextStyle(
                                  fontSize: 9,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.warning,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    OutlinedButton.icon(
                      onPressed:
                          _configuringCamera ? null : _showCameraSetupDialog,
                      icon: _configuringCamera
                          ? const SizedBox(
                              width: 15,
                              height: 15,
                              child:
                                  CircularProgressIndicator(strokeWidth: 1.8),
                            )
                          : const Icon(Icons.video_settings_outlined, size: 17),
                      label: const Text('CÀI CAMERA'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.accent,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton.icon(
                      onPressed: _connectingFsr ? null : _connectFsr,
                      icon: _connectingFsr
                          ? const SizedBox(
                              width: 15,
                              height: 15,
                              child:
                                  CircularProgressIndicator(strokeWidth: 1.8),
                            )
                          : Icon(
                              Icons.sensors_outlined,
                              size: 17,
                              color: _fsrReady
                                  ? AppColors.accentGreen
                                  : AppColors.accent,
                            ),
                      label: Text(_fsrReady ? 'FSR 2/2' : 'CÀI FSR'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: _fsrReady
                            ? AppColors.accentGreen
                            : AppColors.accent,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                      ),
                    ),
                    const SizedBox(width: 6),
                    IconButton.outlined(
                      onPressed: session == null
                          ? null
                          : provider.openReferenceReplayInScan,
                      icon: const Icon(Icons.play_circle_outline, size: 18),
                      tooltip: context.tr('Phát mẫu tham chiếu ở màn Scan'),
                      style: IconButton.styleFrom(
                        foregroundColor: AppColors.accent,
                        minimumSize: const Size(38, 38),
                        maximumSize: const Size(38, 38),
                        padding: EdgeInsets.zero,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  'Chân giả bên ${patient.prostheticLeg == LegSide.left ? 'TRÁI' : 'PHẢI'} phải ở phía gần camera ngang. '
                  'Chỉ các frame thấy rõ hông–gối–cổ chân với visibility ≥ 0,70 mới được dùng tính góc.',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: Row(
                    children: [
                      // Camera View 1 (Front View)
                      Expanded(
                        child: _buildCameraPreview(
                          title: 'Góc chụp trước (Frontal Camera)',
                          streamUrl:
                              'http://localhost:8000/video_feed_0?raw=true',
                          connected: _camera0Connected,
                          poseDetected: _camera0PoseDetected,
                          captureFps: _camera0CaptureFps,
                          overlayLines: [
                            const _LineOverlay(isVertical: true, position: 0.5),
                            const _LineOverlay(
                                isVertical: false, position: 0.35),
                          ],
                        ),
                      ),
                      const SizedBox(width: 16),
                      // Camera View 2 (Sagittal View)
                      Expanded(
                        child: _buildCameraPreview(
                          title: 'Góc chụp ngang (Sagittal Camera)',
                          streamUrl:
                              'http://localhost:8000/video_feed_1?raw=true',
                          connected: _camera1Connected,
                          poseDetected: _camera1PoseDetected,
                          captureFps: _camera1CaptureFps,
                          overlayLines: [
                            const _LineOverlay(
                                isVertical: false, position: 0.5),
                            const _LineOverlay(
                                isVertical: false, position: 0.75),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                // Action: Start testing session
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: AppColors.panel,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        _camerasReady
                            ? Icons.check_circle_outline
                            : Icons.warning_amber_rounded,
                        color: _camerasReady
                            ? AppColors.accent
                            : AppColors.warning,
                        size: 24,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _camerasReady
                                  ? 'Camera đạt điều kiện ghi ổn định'
                                  : _cameraHardwareReady
                                      ? 'Có thể quay · pose sẽ được sàng lọc khi phân tích'
                                      : 'Chưa thể bắt đầu ghi',
                              style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: AppColors.textPrimary,
                                  fontSize: 14),
                            ),
                            Text(
                              _cameraReadinessText,
                              style: const TextStyle(
                                  color: AppColors.textSecondary, fontSize: 12),
                            ),
                            const SizedBox(height: 3),
                            Row(
                              children: [
                                Icon(
                                  Icons.sensors,
                                  size: 13,
                                  color: _fsrReady
                                      ? AppColors.accentGreen
                                      : AppColors.warning,
                                ),
                                const SizedBox(width: 5),
                                Flexible(
                                  child: Text(
                                    _fsrReadinessText,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      color: _fsrReady
                                          ? AppColors.accentGreen
                                          : AppColors.textSecondary,
                                      fontSize: 11,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.accent,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 24, vertical: 16),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8)),
                        ),
                        onPressed: () async {
                          if (!_cameraHardwareReady) {
                            AppAlert.show(
                              context,
                              _cameraReadinessText,
                              tone: AppAlertTone.error,
                            );
                            return;
                          }
                          if (!_camerasReady) {
                            AppAlert.show(
                              context,
                              'Video vẫn được lưu đầy đủ; frame pose chưa đạt sẽ tự bị loại khỏi biểu đồ.',
                              tone: AppAlertTone.warning,
                            );
                          }
                          await _savePatientDetails(provider);
                          // Switch to Tab 3 (Scan / Quét & Ghi hình)
                          provider.setTabIndex(2);
                        },
                        icon: const Icon(Icons.play_circle_outline,
                            color: AppColors.onAccent),
                        label: Text(
                          session?.isReference == true
                              ? 'VÀO THU VIDEO MẪU'
                              : 'BẮT ĐẦU GHI HÌNH',
                          style: const TextStyle(
                              color: AppColors.onAccent,
                              fontWeight: FontWeight.bold),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 20),
          // Right column: Clinical settings & Notes
          Expanded(
            flex: 2,
            child: Container(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              decoration: BoxDecoration(
                color: AppColors.panel,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.border),
              ),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text.rich(
                      TextSpan(
                        children: [
                          TextSpan(text: context.tr('Hồ sơ lâm sàng: ')),
                          TextSpan(text: patient.name),
                        ],
                      ),
                      translate: false,
                      style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: AppColors.textPrimary),
                    ),
                    const SizedBox(height: 12),
                    // Demographic details
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        _buildPatientDetailChip(
                            Icons.cake_outlined, '${patient.age} tuổi'),
                        _buildPatientDetailChip(
                            Icons.height, '${patient.heightCm} cm'),
                        _buildPatientDetailChip(
                            Icons.scale_outlined, '${patient.weightKg} kg'),
                        _buildPatientDetailChip(
                            Icons.accessibility_new,
                            patient.prostheticLeg == LegSide.left
                                ? 'Giả Trái'
                                : 'Giả Phải'),
                      ],
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'Số đo hiệu chuẩn camera',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Expanded(
                          child: TextFormField(
                            controller: _leftLegController,
                            decoration: const InputDecoration(
                              labelText: 'Chân trái (cm)',
                              hintText: 'Hông–mắt cá',
                              isDense: true,
                            ).localized(context),
                            keyboardType: const TextInputType.numberWithOptions(
                                decimal: true),
                            validator: _validateLegLength,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: TextFormField(
                            controller: _rightLegController,
                            decoration: const InputDecoration(
                              labelText: 'Chân phải (cm)',
                              hintText: 'Hông–mắt cá',
                              isDense: true,
                            ).localized(context),
                            keyboardType: const TextInputType.numberWithOptions(
                                decimal: true),
                            validator: _validateLegLength,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    const Divider(color: AppColors.border),
                    const SizedBox(height: 12),
                    // Injury History & Goals
                    const Text('Tiền sử chấn thương & Bệnh lý',
                        style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 13,
                            color: AppColors.textSecondary)),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _injuryController,
                      maxLines: 2,
                      style: const TextStyle(fontSize: 13),
                      decoration: InputDecoration(
                        hintText:
                            'Nhập thông tin chấn thương, năm phẫu thuật, tình trạng mỏm cụt...',
                        filled: true,
                        fillColor: AppColors.sidebar,
                        border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                            borderSide: BorderSide.none),
                      ).localized(context),
                    ),
                    const SizedBox(height: 12),
                    const Text('Mục tiêu phục hồi / Điều chỉnh van',
                        style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 13,
                            color: AppColors.textSecondary)),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _goalsController,
                      maxLines: 2,
                      style: const TextStyle(fontSize: 13),
                      decoration: InputDecoration(
                        hintText:
                            'Mục tiêu căn chỉnh van (ví dụ: Giảm khập khiễng, tăng đối xứng lực...)',
                        filled: true,
                        fillColor: AppColors.sidebar,
                        border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                            borderSide: BorderSide.none),
                      ).localized(context),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton.icon(
                          onPressed: () => _savePatientDetails(provider),
                          icon: const Icon(Icons.save_outlined,
                              size: 16, color: AppColors.accent),
                          label: const Text('Lưu hồ sơ & số đo',
                              style: TextStyle(
                                  color: AppColors.accent,
                                  fontSize: 12,
                                  fontWeight: FontWeight.bold)),
                        ),
                      ],
                    ),
                    const Divider(color: AppColors.border),
                    const SizedBox(height: 8),
                    // Clinical Notes panel
                    const Text('Nhật ký Ghi chú Lâm sàng',
                        style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 14,
                            color: AppColors.textPrimary)),
                    const SizedBox(height: 8),
                    Expanded(
                      child: patient.clinicalNotes.isEmpty
                          ? const Center(
                              child: Text(
                                'Chưa có ghi chú nào. Hãy thêm ghi chú mới bên dưới.',
                                style: TextStyle(
                                    color: AppColors.textSecondary,
                                    fontSize: 12),
                              ),
                            )
                          : ListView.builder(
                              itemCount: patient.clinicalNotes.length,
                              itemBuilder: (context, index) {
                                final note = patient.clinicalNotes[index];
                                final isHistory = note.noteType == 'history';
                                return Container(
                                  margin: const EdgeInsets.only(bottom: 8),
                                  padding: const EdgeInsets.all(8),
                                  decoration: BoxDecoration(
                                    color: isHistory
                                        ? Colors.blueGrey
                                            .withValues(alpha: 0.15)
                                        : Colors.redAccent
                                            .withValues(alpha: 0.1),
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(
                                      color: isHistory
                                          ? Colors.blue.withValues(alpha: 0.2)
                                          : Colors.red.withValues(alpha: 0.2),
                                    ),
                                  ),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        mainAxisAlignment:
                                            MainAxisAlignment.spaceBetween,
                                        children: [
                                          Container(
                                            padding: const EdgeInsets.symmetric(
                                                horizontal: 6, vertical: 2),
                                            decoration: BoxDecoration(
                                              color: isHistory
                                                  ? Colors.blue
                                                      .withValues(alpha: 0.2)
                                                  : Colors.red
                                                      .withValues(alpha: 0.2),
                                              borderRadius:
                                                  BorderRadius.circular(4),
                                            ),
                                            child: Text(
                                              isHistory
                                                  ? 'TIỀN SỬ'
                                                  : 'TRIỆU CHỨNG',
                                              style: TextStyle(
                                                fontSize: 9,
                                                fontWeight: FontWeight.bold,
                                                color: isHistory
                                                    ? Colors.blue[300]
                                                    : Colors.red[300],
                                              ),
                                            ),
                                          ),
                                          Text(
                                            _formatTime(note.createdAt),
                                            style: const TextStyle(
                                                fontSize: 10,
                                                color: AppColors.textSecondary),
                                          ),
                                        ],
                                      ),
                                      const SizedBox(height: 6),
                                      Text(note.content,
                                          translate: false,
                                          style: const TextStyle(
                                              fontSize: 12,
                                              color: AppColors.textSecondary)),
                                    ],
                                  ),
                                );
                              },
                            ),
                    ),
                    const SizedBox(height: 8),
                    // Note inputs
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _noteController,
                            style: const TextStyle(fontSize: 12),
                            decoration: InputDecoration(
                              hintText:
                                  'Nhập ghi chú hoặc biểu hiện lâm sàng mới...',
                              filled: true,
                              fillColor: AppColors.sidebar,
                              contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 10, vertical: 8),
                              border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(8),
                                  borderSide: BorderSide.none),
                            ).localized(context),
                          ),
                        ),
                        const SizedBox(width: 8),
                        DropdownButton<String>(
                          value: _selectedNoteType,
                          dropdownColor: AppColors.panel,
                          underline: const SizedBox(),
                          items: const [
                            DropdownMenuItem(
                                value: 'history',
                                child: Text('Tiền sử',
                                    style: TextStyle(fontSize: 12))),
                            DropdownMenuItem(
                                value: 'symptom',
                                child: Text('Triệu chứng',
                                    style: TextStyle(fontSize: 12))),
                          ],
                          onChanged: (val) {
                            if (val != null) {
                              setState(() {
                                _selectedNoteType = val;
                              });
                            }
                          },
                        ),
                        const SizedBox(width: 4),
                        IconButton(
                          style: IconButton.styleFrom(
                            backgroundColor: AppColors.accent,
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8)),
                          ),
                          onPressed: () => _addClinicalNote(provider),
                          icon: const Icon(Icons.add,
                              color: AppColors.onAccent, size: 18),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPatientDetailChip(IconData icon, String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.sidebar,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: AppColors.accent),
          const SizedBox(width: 4),
          Text(label,
              style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                  color: AppColors.textPrimary)),
        ],
      ),
    );
  }

  Widget _buildCameraPreview({
    required String title,
    required String streamUrl,
    required bool connected,
    required bool poseDetected,
    required double captureFps,
    required List<_LineOverlay> overlayLines,
  }) {
    final statusText = !_backendOnline
        ? 'BACKEND CHƯA KHỞI ĐỘNG'
        : !connected
            ? 'CAMERA CHƯA NHẬN HÌNH'
            : !poseDetected
                ? 'CHƯA THẤY TOÀN THÂN'
                : 'OK · ${captureFps.toStringAsFixed(1)} FPS';
    final statusColor =
        connected && poseDetected ? AppColors.accent : AppColors.warning;
    return Container(
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          // Video Feed
          Positioned.fill(
            child: connected
                ? createVideoStreamWidget(streamUrl)
                : ColoredBox(
                    color: const Color(0xFF0B1220),
                    child: Center(
                      child: Text(
                        !_backendOnline
                            ? 'Backend chưa chạy · không thể tải camera'
                            : 'Đang chờ khung hình từ camera',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 11,
                        ),
                      ),
                    ),
                  ),
          ),
          // Calibration Grid Overlay
          Positioned.fill(
            child: CustomPaint(
              painter: _GridPainter(overlayLines: overlayLines),
            ),
          ),
          // Labels & HUD
          Positioned(
            top: 8,
            left: 8,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.black87,
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                title,
                style: const TextStyle(
                    color: AppColors.onAccent,
                    fontSize: 11,
                    fontWeight: FontWeight.bold),
              ),
            ),
          ),
          Positioned(
            bottom: 8,
            right: 8,
            child: Row(
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: statusColor.withValues(alpha: 0.85),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        connected && poseDetected
                            ? Icons.check
                            : Icons.info_outline,
                        color: AppColors.onAccent,
                        size: 10,
                      ),
                      const SizedBox(width: 2),
                      Text(statusText,
                          style: const TextStyle(
                              color: AppColors.onAccent,
                              fontSize: 9,
                              fontWeight: FontWeight.bold)),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _formatTime(DateTime time) {
    return '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')} ${time.day}/${time.month}';
  }

  String? _validateLegLength(String? value) {
    if (value == null || value.trim().isEmpty) return 'Cần nhập số đo';
    final parsed = double.tryParse(value.trim());
    if (parsed == null || parsed < 20 || parsed > 150) return '20 - 150 cm';
    return null;
  }
}

class _LineOverlay {
  const _LineOverlay({required this.isVertical, required this.position});
  final bool isVertical;
  final double position; // 0.0 to 1.0 representation
}

class _GridPainter extends CustomPainter {
  _GridPainter({required this.overlayLines});
  final List<_LineOverlay> overlayLines;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.accent.withValues(alpha: 0.4)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    for (final line in overlayLines) {
      if (line.isVertical) {
        final x = size.width * line.position;
        canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
      } else {
        final y = size.height * line.position;
        canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
