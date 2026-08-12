import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/analysis_segment.dart';
import '../providers/session_provider.dart';
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
    final session = context.watch<SessionProvider>().session;
    final maxSec = duration < 1 ? 1.0 : duration;
    final value = session.playbackSec.clamp(0.0, maxSec);
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
                SizedBox(
                  width: 58,
                  child: Text(
                    '${value.toStringAsFixed(1)} s',
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 10,
                      color: AppColors.accent,
                    ),
                  ),
                ),
                Expanded(
                  child: SliderTheme(
                    data: SliderTheme.of(context).copyWith(
                      trackHeight: 2,
                      thumbShape: const RoundSliderThumbShape(
                        enabledThumbRadius: 5,
                      ),
                      overlayShape: const RoundSliderOverlayShape(
                        overlayRadius: 10,
                      ),
                    ),
                    child: Slider(
                      value: value,
                      min: 0,
                      max: maxSec,
                      onChanged: context.read<SessionProvider>().setPlaybackSec,
                    ),
                  ),
                ),
                SizedBox(
                  width: 58,
                  child: Text(
                    '${maxSec.toStringAsFixed(1)} s',
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
