import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../services/mock_gait_service.dart';
import '../theme/app_theme.dart';

class AnalysisSidebar extends StatelessWidget {
  const AnalysisSidebar({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final session = provider.session;

    return Container(
      width: 280,
      color: AppColors.sidebar,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Header(),
          const Divider(height: 1),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(vertical: 8),
              children: [
                _SectionTitle('Phiên tinh chỉnh'),
                _PhaseTile(
                  label: '1. Baseline chân lành',
                  phase: SessionPhase.baseline,
                  current: session.phase,
                  onTap: () => provider.setPhase(SessionPhase.baseline),
                ),
                _PhaseTile(
                  label: '2. Quét đánh giá',
                  phase: SessionPhase.scan1,
                  current: session.phase,
                  onTap: () => provider.setPhase(SessionPhase.scan1),
                ),
                _PhaseTile(
                  label: '3. Phân tích & đề xuất',
                  phase: SessionPhase.analyze,
                  current: session.phase,
                  enabled: session.scan1 != null,
                  onTap: () => provider.setPhase(SessionPhase.analyze),
                ),
                _PhaseTile(
                  label: '4. Quét xác minh',
                  phase: SessionPhase.scan2,
                  current: session.phase,
                  enabled: session.scan1 != null,
                  onTap: () => provider.startRescan(),
                ),
                const SizedBox(height: 12),
                _SectionTitle('Cấu hình'),
                _LegSelector(
                  label: 'Chân lành',
                  leftSelected: session.healthyLeg == LegSide.left,
                  onLeft: () => provider.setHealthyLeg(LegSide.left),
                  onRight: () => provider.setHealthyLeg(LegSide.right),
                ),
                _ProstheticSelector(session: session, provider: provider),
                const SizedBox(height: 12),
                _SectionTitle('Recording'),
                _RecordingControl(provider: provider, session: session),
                const SizedBox(height: 12),
                _SectionTitle('Đề xuất tinh chỉnh'),
                ...session.recommendations.map((r) => _RecommendationCard(r: r)),
                if (session.recommendations.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    child: Text(
                      'Quét xong sẽ hiện gợi ý chỉnh chân trái/phải.',
                      style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
                    ),
                  ),
                if (provider.comparisonSummary != null) ...[
                  const SizedBox(height: 8),
                  _SectionTitle('So sánh Before / After'),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Text(
                      provider.comparisonSummary!,
                      style: const TextStyle(fontSize: 11, color: AppColors.accentGreen),
                    ),
                  ),
                ],
                if (session.phase == SessionPhase.analyze && session.scan1 != null)
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: FilledButton.icon(
                      onPressed: provider.goToAdjustPhase,
                      icon: const Icon(Icons.build_outlined, size: 18),
                      label: const Text('Đã chỉnh → Quét lại'),
                    ),
                  ),
              ],
            ),
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(8),
            child: OutlinedButton.icon(
              onPressed: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Xuất báo cáo — sẽ tích hợp ở bước sau')),
                );
              },
              icon: const Icon(Icons.summarize_outlined, size: 18),
              label: const Text('Report'),
            ),
          ),
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AppColors.accent.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Icon(Icons.accessibility_new, color: AppColors.accent, size: 22),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'AI-ProGait',
                      style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                    ),
                    Text(
                      'Dashboard Analysis',
                      style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
      child: Text(
        text.toUpperCase(),
        style: const TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w700,
          color: AppColors.textSecondary,
          letterSpacing: 0.8,
        ),
      ),
    );
  }
}

class _PhaseTile extends StatelessWidget {
  const _PhaseTile({
    required this.label,
    required this.phase,
    required this.current,
    required this.onTap,
    this.enabled = true,
  });

  final String label;
  final SessionPhase phase;
  final SessionPhase current;
  final VoidCallback onTap;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final isActive = _phaseIndex(current) >= _phaseIndex(phase);
    final isCurrent = current == phase ||
        (phase == SessionPhase.scan1 && current == SessionPhase.analyze);

    return ListTile(
      dense: true,
      enabled: enabled,
      leading: Icon(
        isActive ? Icons.check_circle : Icons.radio_button_unchecked,
        size: 18,
        color: isCurrent ? AppColors.accent : AppColors.textSecondary,
      ),
      title: Text(label, style: TextStyle(fontSize: 13, color: enabled ? null : AppColors.textSecondary)),
      selected: isCurrent,
      selectedTileColor: AppColors.accent.withValues(alpha: 0.12),
      onTap: enabled ? onTap : null,
    );
  }

  int _phaseIndex(SessionPhase p) {
    switch (p) {
      case SessionPhase.setup:
      case SessionPhase.baseline:
        return 0;
      case SessionPhase.scan1:
        return 1;
      case SessionPhase.analyze:
      case SessionPhase.adjust:
        return 2;
      case SessionPhase.scan2:
      case SessionPhase.report:
        return 3;
    }
  }
}

class _LegSelector extends StatelessWidget {
  const _LegSelector({
    required this.label,
    required this.leftSelected,
    required this.onLeft,
    required this.onRight,
  });

  final String label;
  final bool leftSelected;
  final VoidCallback onLeft;
  final VoidCallback onRight;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: _LegChip(
                  label: 'Trái (L)',
                  color: AppColors.leftLeg,
                  selected: leftSelected,
                  onTap: onLeft,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _LegChip(
                  label: 'Phải (R)',
                  color: AppColors.rightLeg,
                  selected: !leftSelected,
                  onTap: onRight,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LegChip extends StatelessWidget {
  const _LegChip({
    required this.label,
    required this.color,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final Color color;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? color.withValues(alpha: 0.25) : AppColors.panel,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: selected ? color : AppColors.border),
          ),
          alignment: Alignment.center,
          child: Text(label, style: TextStyle(fontSize: 12, color: selected ? color : AppColors.textSecondary)),
        ),
      ),
    );
  }
}

class _ProstheticSelector extends StatelessWidget {
  const _ProstheticSelector({required this.session, required this.provider});

  final GaitSession session;
  final SessionProvider provider;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Chân giả', style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          const SizedBox(height: 6),
          DropdownButtonFormField<ProstheticSide>(
            value: session.prostheticLeg,
            decoration: const InputDecoration(
              isDense: true,
              contentPadding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              border: OutlineInputBorder(),
            ),
            items: const [
              DropdownMenuItem(value: ProstheticSide.left, child: Text('Chân trái (giả)')),
              DropdownMenuItem(value: ProstheticSide.right, child: Text('Chân phải (giả)')),
            ],
            onChanged: (v) {
              if (v != null) provider.setProstheticLeg(v);
            },
          ),
        ],
      ),
    );
  }
}

class _RecordingControl extends StatelessWidget {
  const _RecordingControl({required this.provider, required this.session});

  final SessionProvider provider;
  final GaitSession session;

  @override
  Widget build(BuildContext context) {
    final remaining = MockGaitService.recordDurationSec - session.recordingElapsedSec;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (session.isRecording)
            LinearProgressIndicator(
              value: session.recordingElapsedSec / MockGaitService.recordDurationSec,
              backgroundColor: AppColors.border,
              color: AppColors.critical,
            ),
          if (session.isRecording)
            Padding(
              padding: const EdgeInsets.only(top: 4, bottom: 8),
              child: Text(
                'Đang quét: ${remaining.clamp(0, 999).toStringAsFixed(1)}s',
                style: const TextStyle(fontSize: 11, color: AppColors.critical),
              ),
            ),
          FilledButton.icon(
            onPressed: session.isRecording ? provider.stopRecording : provider.startRecording,
            style: FilledButton.styleFrom(
              backgroundColor: session.isRecording ? AppColors.warning : AppColors.accent,
            ),
            icon: Icon(session.isRecording ? Icons.stop : Icons.fiber_manual_record, size: 18),
            label: Text(session.isRecording ? 'Dừng quét' : 'Record (10s)'),
          ),
        ],
      ),
    );
  }
}

class _RecommendationCard extends StatelessWidget {
  const _RecommendationCard({required this.r});

  final AdjustmentRecommendation r;

  @override
  Widget build(BuildContext context) {
    final color = switch (r.severity) {
      RecommendationSeverity.critical => AppColors.critical,
      RecommendationSeverity.warning => AppColors.warning,
      RecommendationSeverity.info => AppColors.accent,
    };

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            r.issue,
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color),
          ),
          const SizedBox(height: 4),
          Text(r.suggestion, style: const TextStyle(fontSize: 11)),
          if (r.deltaDegrees > 0)
            Text(
              'Δ ${r.deltaDegrees.toStringAsFixed(0)}°',
              style: TextStyle(fontSize: 10, color: color),
            ),
        ],
      ),
    );
  }
}
