import 'package:flutter/material.dart' hide Text;

import '../l10n/app_language.dart';
import '../l10n/localized_text.dart';

import '../models/analysis_segment.dart';
import '../theme/app_theme.dart';

class RecordingTimeline extends StatelessWidget {
  const RecordingTimeline({
    super.key,
    required this.duration,
    required this.segments,
    this.pendingStart,
    this.totalDuration,
  });

  final double duration;
  final List<AnalysisSegment> segments;
  final double? pendingStart;
  final double? totalDuration;

  @override
  Widget build(BuildContext context) {
    final elapsed = duration < 0 ? 0.0 : duration;
    final replayTotal =
        totalDuration != null && totalDuration! > 0 ? totalDuration! : null;
    final maxSec = replayTotal ?? (duration < 1 ? 1.0 : duration);
    final progress = replayTotal == null
        ? (elapsed > 0 ? 1.0 : 0.0)
        : (elapsed / maxSec).clamp(0.0, 1.0);
    return Container(
      height: 64,
      padding: const EdgeInsets.fromLTRB(14, 5, 14, 4),
      decoration: const BoxDecoration(
        color: AppColors.panel,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        children: [
          SizedBox(
            height: 12,
            child: LayoutBuilder(
              builder: (_, constraints) => Stack(
                children: [
                  Positioned(
                    left: 0,
                    right: 0,
                    top: 5,
                    height: 2,
                    child: Container(color: AppColors.border),
                  ),
                  for (final segment in segments)
                    Positioned(
                      left: constraints.maxWidth *
                          (segment.start / maxSec).clamp(0.0, 1.0),
                      width: constraints.maxWidth *
                          ((segment.end - segment.start) / maxSec)
                              .clamp(0.004, 1.0),
                      top: 3,
                      height: 6,
                      child: Tooltip(
                        message: context.tr(
                          '${segment.label}: ${segment.start.toStringAsFixed(1)}\u2013${segment.end.toStringAsFixed(1)} s',
                        ),
                        child: Container(
                          decoration: BoxDecoration(
                            color: AppColors.accentGreen,
                            borderRadius: BorderRadius.circular(2),
                          ),
                        ),
                      ),
                    ),
                  if (pendingStart != null)
                    Positioned(
                      left: constraints.maxWidth *
                              (pendingStart! / maxSec).clamp(0.0, 1.0) -
                          1,
                      top: 0,
                      bottom: 0,
                      child: Container(width: 2, color: AppColors.warning),
                    ),
                ],
              ),
            ),
          ),
          Expanded(
            child: Row(
              children: [
                const SizedBox(
                  width: 58,
                  child: Text(
                    '0.0 s',
                    style: TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 10,
                      color: AppColors.accent,
                    ),
                  ),
                ),
                Expanded(
                  child: Semantics(
                    label: context.tr('Thời gian ghi trực tiếp'),
                    value: context.tr('${elapsed.toStringAsFixed(1)} giây'),
                    readOnly: true,
                    child: SizedBox(
                      height: 18,
                      child: LayoutBuilder(
                        builder: (_, constraints) => Stack(
                          alignment: Alignment.centerLeft,
                          children: [
                            Positioned(
                              left: 0,
                              right: 0,
                              child: Container(
                                height: 3,
                                decoration: BoxDecoration(
                                  color: AppColors.border,
                                  borderRadius: BorderRadius.circular(2),
                                ),
                              ),
                            ),
                            if (progress > 0)
                              Positioned(
                                left: 0,
                                width: constraints.maxWidth * progress,
                                child: Container(
                                  height: 3,
                                  decoration: BoxDecoration(
                                    color: AppColors.accent,
                                    borderRadius: BorderRadius.circular(2),
                                  ),
                                ),
                              ),
                            Positioned(
                              left: (constraints.maxWidth - 10) * progress,
                              child: Container(
                                width: 10,
                                height: 10,
                                decoration: BoxDecoration(
                                  color: progress > 0
                                      ? AppColors.accent
                                      : AppColors.border,
                                  shape: BoxShape.circle,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                SizedBox(
                  width: 58,
                  child: Text(
                    '${(replayTotal ?? elapsed).toStringAsFixed(1)} s',
                    textAlign: TextAlign.end,
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 10,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
                const SizedBox(width: 14),
                Icon(
                  pendingStart == null ? Icons.bookmark_outline : Icons.flag,
                  size: 14,
                  color: pendingStart == null
                      ? AppColors.textSecondary
                      : AppColors.warning,
                ),
                const SizedBox(width: 4),
                Text(
                  pendingStart != null
                      ? 'Ch\u1edd m\u1ed1c cu\u1ed1i'
                      : '${segments.length} \u0111o\u1ea1n \u0111\u00e3 l\u01b0u',
                  style: TextStyle(
                    fontSize: 9,
                    color: pendingStart != null
                        ? AppColors.warning
                        : AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
