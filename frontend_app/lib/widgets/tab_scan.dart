import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'dart:math';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'video_stream.dart';

class TabScan extends StatefulWidget {
  const TabScan({super.key});

  @override
  State<TabScan> createState() => _TabScanState();
}

class _TabScanState extends State<TabScan> {
  double _sliceStart = 0.0;
  double _sliceEnd = 15.0;
  double _totalDuration = 15.0;
  String _scanType = 'scan_1';
  final TextEditingController _noteController = TextEditingController(text: 'Phân tích dáng đi');
  final List<Map<String, dynamic>> _localMarkers = [];

  @override
  void dispose() {
    _noteController.dispose();
    super.dispose();
  }

  void _addMarker(SessionProvider provider, GaitSession session) {
    final offset = session.recordingElapsedSec;
    final markerNote = 'Bất thường lúc ${offset.toStringAsFixed(1)}s';
    provider.addMarker(session.id, offset: offset, note: markerNote);
    setState(() {
      _localMarkers.add({
        'offset': offset,
        'note': markerNote,
      });
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Đã ghim bất thường: $markerNote'),
        backgroundColor: AppColors.warning,
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;
    final session = provider.activeSession;

    if (patient == null || session == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.person_search_outlined, size: 64, color: AppColors.textSecondary),
            const SizedBox(height: 16),
            const Text(
              'Chưa chọn bệnh nhân hoặc phiên khám',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.white),
            ),
            const SizedBox(height: 8),
            const Text(
              'Vui lòng bắt đầu phiên khám mới hoặc chọn bệnh nhân ở Tab Bệnh nhân.',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: () => provider.setTabIndex(0),
              icon: const Icon(Icons.people_outline, color: Colors.black),
              label: const Text(
                'QUAY LẠI HỒ SƠ BỆNH NHÂN',
                style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
              ),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.accent,
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
            ),
          ],
        ),
      );
    }

    final isRecording = session.isRecording;
    if (isRecording) {
      if (session.recordingElapsedSec > _totalDuration) {
        _totalDuration = session.recordingElapsedSec;
      }
    } else {
      if (session.recordingElapsedSec > 0.0) {
        _totalDuration = session.recordingElapsedSec;
      }
    }

    return Container(
      color: AppColors.background,
      child: Column(
        children: [
          // Header Status Bar
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: const BoxDecoration(
              color: AppColors.panel,
              border: Border(bottom: BorderSide(color: AppColors.border)),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.arrow_back, color: AppColors.accent, size: 20),
                      onPressed: () => provider.setTabIndex(1),
                      tooltip: 'Quay lại Bước chuẩn bị',
                    ),
                    const SizedBox(width: 8),
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        color: isRecording ? AppColors.critical : AppColors.accent,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      isRecording ? 'Đang ghi hình dáng đi liên tục...' : 'Đã ghi hình dáng đi - Chờ cắt phân đoạn',
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                    ),
                  ],
                ),
                Text(
                  'Bệnh nhân: ${patient.name} (ID: ${patient.id})',
                  style: const TextStyle(fontSize: 13, color: AppColors.textSecondary),
                ),
              ],
            ),
          ),

          // Central Panels: Live Frontal & Sagittal Streams on left, FSR Heatmap on right
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Cameras on the Left
                Expanded(
                  flex: 3,
                  child: Row(
                    children: [
                      Expanded(
                        child: _buildCameraPreview(
                          title: 'CAM 1 — CHÍNH DIỆN (FRONTAL)',
                          streamUrl: 'http://localhost:8000/video_feed_0',
                          isRecording: isRecording,
                          elapsed: session.recordingElapsedSec,
                        ),
                      ),
                      Expanded(
                        child: _buildCameraPreview(
                          title: 'CAM 2 — TRỤC NGANG (SAGITTAL 90°)',
                          streamUrl: 'http://localhost:8000/video_feed_1',
                          isRecording: isRecording,
                          elapsed: session.recordingElapsedSec,
                        ),
                      ),
                    ],
                  ),
                ),
                // FSR Heatmap on the Right (Placeholder waiting for real hardware)
                const Expanded(
                  flex: 1,
                  child: InsoleHeatmapWidget(),
                ),
              ],
            ),
          ),

          // Bottom Control Panel: Record & Crop segment tools
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
            decoration: const BoxDecoration(
              color: AppColors.sidebar,
              border: Border(top: BorderSide(color: AppColors.border)),
            ),
            child: isRecording
                ? Row(
                    children: [
                      const Icon(Icons.radio_button_checked, color: AppColors.critical, size: 24),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          'Đang ghi nhận dữ liệu 2 Camera... (${session.recordingElapsedSec.toStringAsFixed(1)}s). Bác sĩ có thể bấm nút ghim mốc bất thường.',
                          style: const TextStyle(fontSize: 13, color: AppColors.textSecondary),
                        ),
                      ),
                      // Flag Marker button
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.orange[800],
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                        ),
                        onPressed: () => _addMarker(provider, session),
                        icon: const Icon(Icons.flag, color: Colors.white),
                        label: const Text('GHIM BẤT THƯỜNG', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
                      const SizedBox(width: 16),
                      // Stop recording button
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.critical,
                          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
                        ),
                        onPressed: () async {
                          await provider.stopRecording();
                          setState(() {
                            _sliceStart = 0.0;
                            _sliceEnd = _totalDuration > 10.0 ? 10.0 : _totalDuration;
                          });
                        },
                        icon: const Icon(Icons.stop, color: Colors.white),
                        label: const Text('DỪNG VÀ PHÂN TÍCH', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (_totalDuration > 1.0) ...[
                        const Text(
                          'Phân đoạn dữ liệu dáng đi (Double-slider Crop)',
                          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Colors.white70),
                        ),
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            Text(
                              'Bắt đầu: ${_sliceStart.toStringAsFixed(1)}s',
                              style: const TextStyle(fontFamily: 'monospace', fontSize: 13, color: AppColors.accent, fontWeight: FontWeight.bold),
                            ),
                            Expanded(
                              child: RangeSlider(
                                values: RangeValues(_sliceStart, _sliceEnd),
                                min: 0.0,
                                max: _totalDuration,
                                activeColor: AppColors.accent,
                                inactiveColor: AppColors.border,
                                labels: RangeLabels(
                                  '${_sliceStart.toStringAsFixed(1)}s',
                                  '${_sliceEnd.toStringAsFixed(1)}s',
                                ),
                                onChanged: (values) {
                                  setState(() {
                                    _sliceStart = values.start;
                                    _sliceEnd = values.end;
                                  });
                                },
                              ),
                            ),
                            Text(
                              'Kết thúc: ${_sliceEnd.toStringAsFixed(1)}s (Tổng: ${_totalDuration.toStringAsFixed(1)}s)',
                              style: const TextStyle(fontFamily: 'monospace', fontSize: 13, color: AppColors.accent, fontWeight: FontWeight.bold),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        // Timeline with Markers visual feedback
                        if (_localMarkers.isNotEmpty)
                          Container(
                            height: 24,
                            padding: const EdgeInsets.symmetric(horizontal: 70),
                            child: Stack(
                              children: _localMarkers.map((m) {
                                final offset = m['offset'] as double;
                                final ratio = (offset / _totalDuration).clamp(0.0, 1.0);
                                return Align(
                                  alignment: Alignment(ratio * 2.0 - 1.0, 0.0),
                                  child: Tooltip(
                                    message: m['note'],
                                    child: const Icon(Icons.flag, color: Colors.orange, size: 16),
                                  ),
                                );
                              }).toList(),
                            ),
                          ),
                        const SizedBox(height: 12),
                        // Inputs for Crop Segment
                        Row(
                          children: [
                            Expanded(
                              flex: 2,
                              child: TextField(
                                controller: _noteController,
                                style: const TextStyle(fontSize: 13),
                                decoration: InputDecoration(
                                  labelText: 'Nhãn phiên / Ghi chú phân đoạn',
                                  filled: true,
                                  fillColor: AppColors.panel,
                                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                                ),
                              ),
                            ),
                            const SizedBox(width: 16),
                            Expanded(
                              child: DropdownButtonFormField<String>(
                                value: _scanType,
                                dropdownColor: AppColors.panel,
                                decoration: InputDecoration(
                                  labelText: 'Loại phân tích',
                                  filled: true,
                                  fillColor: AppColors.panel,
                                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                                ),
                                items: const [
                                  DropdownMenuItem(value: 'baseline', child: Text('Baseline chân lành', style: TextStyle(fontSize: 12))),
                                  DropdownMenuItem(value: 'scan_1', child: Text('Scan #1 (Lần đầu)', style: TextStyle(fontSize: 12))),
                                  DropdownMenuItem(value: 'scan_2', child: Text('Scan #2 (Sau tinh chỉnh)', style: TextStyle(fontSize: 12))),
                                ],
                                onChanged: (val) {
                                  if (val != null) {
                                    setState(() {
                                      _scanType = val;
                                    });
                                  }
                                },
                              ),
                            ),
                            const SizedBox(width: 16),
                            // Button crop and save
                            ElevatedButton.icon(
                              style: ElevatedButton.styleFrom(
                                backgroundColor: AppColors.accent,
                                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                              ),
                              onPressed: provider.isLoading
                                  ? null
                                  : () async {
                                      await provider.createSegmentAndScan(
                                        session.id,
                                        _sliceStart,
                                        _sliceEnd,
                                        _scanType,
                                        _noteController.text,
                                      );
                                      // Switch to Tab 4: Phân tích dáng đi (Tab index 3)
                                      provider.setTabIndex(3);
                                    },
                              icon: const Icon(Icons.insights, color: Colors.black),
                              label: const Text(
                                'TẠO PHÂN ĐOẠN & PHÂN TÍCH',
                                style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
                              ),
                            ),
                          ],
                        ),
                      ] else ...[
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Ghi hình dáng đi mới',
                                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: Colors.white),
                                ),
                                Text(
                                  'Nhấp BẮT ĐẦU GHI HÌNH để kích hoạt 2 luồng camera ghi dữ liệu dáng đi.',
                                  style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
                                ),
                              ],
                            ),
                            ElevatedButton.icon(
                              style: ElevatedButton.styleFrom(
                                backgroundColor: AppColors.accent,
                                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                              ),
                              onPressed: () {
                                provider.startRecording();
                                setState(() {
                                  _localMarkers.clear();
                                });
                              },
                              icon: const Icon(Icons.fiber_manual_record, color: Colors.redAccent),
                              label: const Text(
                                'BẮT ĐẦU GHI HÌNH',
                                style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildCameraPreview({
    required String title,
    required String streamUrl,
    required bool isRecording,
    required double elapsed,
  }) {
    return Container(
      margin: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(child: createVideoStreamWidget(streamUrl)),
          // HUD labels
          Positioned(
            top: 12,
            left: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.black87,
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                title,
                style: const TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: AppColors.accent),
              ),
            ),
          ),
          if (isRecording)
            Positioned(
              top: 12,
              right: 12,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.red[900],
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Row(
                  children: [
                    Container(width: 8, height: 8, decoration: const BoxDecoration(color: Colors.redAccent, shape: BoxShape.circle)),
                    const SizedBox(width: 6),
                    Text(
                      'REC: ${elapsed.toStringAsFixed(1)}s',
                      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Colors.white),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class InsoleHeatmapWidget extends StatelessWidget {
  const InsoleHeatmapWidget({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 12, bottom: 12, right: 12, left: 4),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Bản đồ áp lực Insole (FSR)',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Colors.white),
              ),
              Row(
                children: [
                  Icon(Icons.bluetooth_searching, color: Colors.blue[300], size: 14),
                  const SizedBox(width: 4),
                  Text(
                    'Chờ phần cứng',
                    style: TextStyle(fontSize: 10, color: Colors.blue[300], fontWeight: FontWeight.bold),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            'Chỉ số lực Insole thực tế truyền trực tiếp qua Bluetooth. Hiện đã gỡ bộ dữ liệu giả lập ở Client.',
            style: TextStyle(color: AppColors.textSecondary, fontSize: 11),
          ),
          const SizedBox(height: 16),
          Expanded(
            child: Row(
              children: [
                Expanded(child: _buildFootGrid('CHÂN TRÁI')),
                const VerticalDivider(color: AppColors.border, width: 24),
                Expanded(child: _buildFootGrid('CHÂN PHẢI')),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFootGrid(String label) {
    return Column(
      children: [
        Text(
          label,
          style: const TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppColors.textSecondary),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final double cellSize = (min(constraints.maxWidth, constraints.maxHeight) - 24) / 8;
              return Center(
                child: SizedBox(
                  width: cellSize * 8 + 14,
                  height: cellSize * 8 + 14,
                  child: GridView.builder(
                    physics: const NeverScrollableScrollPhysics(),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 8,
                      crossAxisSpacing: 2,
                      mainAxisSpacing: 2,
                    ),
                    itemCount: 64,
                    itemBuilder: (context, index) {
                      final row = index ~/ 8;
                      final col = index % 8;
                      final isFoot = _isCellInFootContour(row, col);
                      
                      return Container(
                        decoration: BoxDecoration(
                          color: isFoot ? Colors.blueGrey.withValues(alpha: 0.15) : Colors.transparent,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      );
                    },
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  bool _isCellInFootContour(int row, int col) {
    if (row == 0) return col >= 3 && col <= 5;
    if (row == 1) return col >= 2 && col <= 6;
    if (row == 2) return col >= 2 && col <= 6;
    if (row == 3) return col >= 2 && col <= 5;
    if (row == 4) return col >= 3 && col <= 5;
    if (row == 5) return col >= 3 && col <= 5;
    if (row == 6) return col >= 3 && col <= 5;
    if (row == 7) return col >= 3 && col <= 5;
    return false;
  }
}
