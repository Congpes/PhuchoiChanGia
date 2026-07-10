import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../services/mock_gait_service.dart';
import '../theme/app_theme.dart';
import 'camera_panel.dart';

class TabScan extends StatelessWidget {
  const TabScan({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;
    final session = provider.activeSession;

    if (patient == null || session == null) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.person_search_outlined, size: 64, color: AppColors.textSecondary),
            SizedBox(height: 16),
            Text(
              'Chưa chọn bệnh nhân hoặc phiên khám',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
            ),
            SizedBox(height: 8),
            Text(
              'Vui lòng bắt đầu phiên khám mới hoặc chọn bệnh nhân ở Tab Bệnh nhân.',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
            ),
          ],
        ),
      );
    }

    final isBaseline = session.phase == SessionPhase.baseline;
    final scanNumber = session.scans.length + 1;
    final labelText = isBaseline
        ? 'Đang ghi: Baseline (chân lành)'
        : 'Đang ghi: Đánh giá chân giả - Scan #$scanNumber';

    final maxSec = MockGaitService.recordDurationSec;
    final remaining = maxSec - session.recordingElapsedSec;

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
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        color: session.isRecording ? AppColors.critical : AppColors.accent,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      labelText,
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

          // Camera Panels
          Expanded(
            child: Row(
              children: [
                CameraPanel(
                  title: 'Cam 1 — Chính diện (Frontal)',
                  subtitle: 'Symmetry · Hip drop · Trục cơ thể',
                  isRecording: session.isRecording,
                  controller: null,
                ),
                CameraPanel(
                  title: 'Cam 2 — Góc bên (Sagittal 90°)',
                  subtitle: 'Góc gối · Gót chạm · Nhịp bước',
                  isRecording: session.isRecording,
                  controller: null,
                  videoStreamUrl: 'http://localhost:8000/video_feed',
                ),
              ],
            ),
          ),

          // Record Controls Panel
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
            decoration: const BoxDecoration(
              color: AppColors.sidebar,
              border: Border(top: BorderSide(color: AppColors.border)),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (session.isRecording) ...[
                  LinearProgressIndicator(
                    value: session.recordingElapsedSec / maxSec,
                    backgroundColor: AppColors.border,
                    color: AppColors.critical,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Đang quét: ${remaining.clamp(0, 999).toStringAsFixed(1)}s còn lại',
                    style: const TextStyle(fontSize: 12, color: AppColors.critical, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 12),
                ],
                Row(
                  children: [
                    // Playback Timer Text
                    Text(
                      '${session.playbackSec.toStringAsFixed(3)} s',
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 14,
                        color: AppColors.accent,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(width: 16),

                    // Slider Timeline
                    Expanded(
                      child: SliderTheme(
                        data: SliderTheme.of(context).copyWith(
                          trackHeight: 4,
                          thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
                        ),
                        child: Slider(
                          value: session.playbackSec.clamp(0, maxSec),
                          min: 0,
                          max: maxSec,
                          onChanged: session.isRecording
                              ? null
                              : (v) => provider.setPlaybackSec(v),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '/ ${maxSec.toStringAsFixed(0)}s',
                      style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                    ),
                    const SizedBox(width: 24),

                    // Record Button
                    FilledButton.icon(
                      onPressed: provider.isLoading
                          ? null
                          : (session.isRecording ? provider.stopRecording : provider.startRecording),
                      style: FilledButton.styleFrom(
                        backgroundColor: session.isRecording ? AppColors.warning : AppColors.critical,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                      ),
                      icon: Icon(session.isRecording ? Icons.stop : Icons.fiber_manual_record, size: 20),
                      label: Text(
                        session.isRecording ? 'DỪNG QUÉT' : 'RECORD (10s)',
                        style: const TextStyle(fontWeight: FontWeight.bold, letterSpacing: 0.8),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
