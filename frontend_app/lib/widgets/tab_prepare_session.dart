import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
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
  String _selectedNoteType = 'history';
  bool _configuringCamera = false;

  static const _cameraDiscoveryTimeout = Duration(seconds: 30);
  static const _cameraConfigureTimeout = Duration(seconds: 15);

  @override
  void initState() {
    super.initState();
    _injuryController = TextEditingController();
    _goalsController = TextEditingController();
    _noteController = TextEditingController();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final patient = context.watch<SessionProvider>().activePatient;
    if (patient != null) {
      _injuryController.text = patient.injuryHistory;
      _goalsController.text = patient.treatmentGoals;
    }
  }

  @override
  void dispose() {
    _injuryController.dispose();
    _goalsController.dispose();
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _savePatientDetails(SessionProvider provider) async {
    final patient = provider.activePatient;
    if (patient == null) return;
    await provider.updatePatientDetails(
      patient.id,
      patient.name,
      patient.age,
      patient.heightCm,
      patient.weightKg,
      patient.healthyLeg,
      patient.prostheticLeg,
      _injuryController.text,
      _goalsController.text,
    );
    if (!mounted) return;
    AppAlert.show(
      context,
      'Đã cập nhật tiền sử chấn thương và mục tiêu điều trị.',
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
          .get(Uri.parse('http://127.0.0.1:8000/camera/devices'))
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
          var frontalIndex = configuredIndex('frontalIndex') ??
              (indexes.length >= 3
                  ? indexes[indexes.length - 2]
                  : indexes.first);
          var sagittalIndex = configuredIndex('sagittalIndex') ??
              (indexes.length >= 3
                  ? indexes.last
                  : indexes.length > 1
                      ? indexes[1]
                      : indexes.first);
          var singleCameraMode = configuration['singleCameraMode'] == true;

          String labelFor(int index) {
            final device = devices.firstWhere(
              (item) => (item['index'] as num?)?.toInt() == index,
            );
            final width = device['width']?.toString() ?? '?';
            final height = device['height']?.toString() ?? '?';
            return 'Camera $index · $width×$height';
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
                    const Text(
                      'Chọn camera cho góc chính diện và mặt phẳng dọc. Có thể đổi ngay trong phiên; hai luồng hình sẽ tạm dừng vài giây khi áp dụng.',
                      style: TextStyle(
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
                      ),
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
                      ),
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
                      tooltip: 'Quay lại Hồ sơ bệnh nhân',
                    ),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text(
                        'Xem trước góc quay Camera & Đo lường sinh học',
                        style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                            color: AppColors.textPrimary),
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
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  'Chân giả bên ${patient.prostheticLeg == LegSide.left ? 'TRÁI' : 'PHẢI'} phải ở phía gần camera ngang. '
                  'Chỉ các frame thấy rõ hông–gối–cổ chân với visibility ≥ 0,80 mới được dùng tính góc.',
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
                          streamUrl: 'http://localhost:8000/video_feed_0',
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
                          streamUrl: 'http://localhost:8000/video_feed_1',
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
                      const Icon(Icons.info_outline,
                          color: AppColors.accent, size: 24),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Đồng bộ hóa Insole & Camera thành công',
                              style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: AppColors.textPrimary,
                                  fontSize: 14),
                            ),
                            Text(
                              'Giao tiếp Bluetooth (FSR Matrix) và Video Stream đã sẵn sàng ghi hình dáng đi.',
                              style: TextStyle(
                                  color: AppColors.textSecondary, fontSize: 12),
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
                          await _savePatientDetails(provider);
                          // Switch to Tab 3 (Scan / Quét & Ghi hình)
                          provider.setTabIndex(2);
                        },
                        icon: const Icon(Icons.play_circle_outline,
                            color: AppColors.onAccent),
                        label: const Text(
                          'BẮT ĐẦU GHI HÌNH',
                          style: TextStyle(
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
              padding: const EdgeInsets.all(16),
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
                    Text(
                      'Hồ sơ lâm sàng: ${patient.name}',
                      style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: AppColors.textPrimary),
                    ),
                    const SizedBox(height: 16),
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
                    const SizedBox(height: 16),
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
                      ),
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
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton.icon(
                          onPressed: () => _savePatientDetails(provider),
                          icon: const Icon(Icons.save_outlined,
                              size: 16, color: AppColors.accent),
                          label: const Text('Lưu thông tin bệnh lý',
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
                            ),
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
    required List<_LineOverlay> overlayLines,
  }) {
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
          Positioned.fill(child: createVideoStreamWidget(streamUrl)),
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
                    color: AppColors.accent.withValues(alpha: 0.8),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Row(
                    children: [
                      Icon(Icons.check, color: AppColors.onAccent, size: 10),
                      SizedBox(width: 2),
                      Text('ALIGNMENT: OK',
                          style: TextStyle(
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
