import 'package:flutter/material.dart';

import '../models/analysis_segment.dart';
import '../theme/app_theme.dart';

class RecordingTimeline extends StatelessWidget {
  const RecordingTimeline({
    super.key,
    required this.duration,
    required this.segments,
    this.pendingStart,
  });

  final double duration;
  final List<AnalysisSegment> segments;
  final double? pendingStart;

  @override
  Widget build(BuildContext context) {
    final elapsed = duration < 0 ? 0.0 : duration;
    final maxSec = duration < 1 ? 1.0 : duration;
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
                        message:
                            '${segment.label}: ${segment.start.toStringAsFixed(1)}\u2013${segment.end.toStringAsFixed(1)} s',
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
                    label: 'Thời gian ghi trực tiếp',
                    value: '${elapsed.toStringAsFixed(1)} giây',
                    readOnly: true,
                    child: SizedBox(
                      height: 18,
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          Positioned(
                            left: 0,
                            right: 0,
                            child: Container(
                              height: 3,
                              decoration: BoxDecoration(
                                color: elapsed > 0
                                    ? AppColors.accent
                                    : AppColors.border,
                                borderRadius: BorderRadius.circular(2),
                              ),
                            ),
                          ),
                          Positioned(
                            left: elapsed > 0 ? null : 0,
                            right: elapsed > 0 ? 0 : null,
                            child: Container(
                              width: 10,
                              height: 10,
                              decoration: BoxDecoration(
                                color: elapsed > 0
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
                SizedBox(
                  width: 58,
                  child: Text(
                    '${elapsed.toStringAsFixed(1)} s',
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
