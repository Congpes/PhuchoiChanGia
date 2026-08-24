import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/session_provider.dart';
import '../config/measurement_config.dart';
import '../theme/app_theme.dart';

class TimelineBar extends StatefulWidget {
  const TimelineBar({super.key});

  @override
  State<TimelineBar> createState() => _TimelineBarState();
}

class _TimelineBarState extends State<TimelineBar> {
  int _selectedTab = 0;
  static const _tabs = ['Video', 'Text', 'Gait Cycle', 'Angles'];

  @override
  Widget build(BuildContext context) {
    final session = context.watch<SessionProvider>().session;
    const maxSec = MeasurementConfig.recordingDurationSec;

    return Container(
      height: 84,
      decoration: const BoxDecoration(
        color: AppColors.sidebar,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Column(
        children: [
          Row(
            children: [
              Text(
                '${session.playbackSec.toStringAsFixed(3)} s',
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 13,
                  color: AppColors.accent,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: SliderTheme(
                  data: SliderTheme.of(context).copyWith(
                    trackHeight: 4,
                    thumbShape:
                        const RoundSliderThumbShape(enabledThumbRadius: 6),
                  ),
                  child: Slider(
                    value: session.playbackSec.clamp(0, maxSec),
                    min: 0,
                    max: maxSec,
                    onChanged: (v) =>
                        context.read<SessionProvider>().setPlaybackSec(v),
                  ),
                ),
              ),
              Text(
                '/ ${maxSec.toStringAsFixed(0)}s',
                style: const TextStyle(
                    fontSize: 11, color: AppColors.textSecondary),
              ),
            ],
          ),
          Row(
            children: List.generate(_tabs.length, (i) {
              final selected = _selectedTab == i;
              return Padding(
                padding: const EdgeInsets.only(right: 4),
                child: TextButton(
                  onPressed: () => setState(() => _selectedTab = i),
                  style: TextButton.styleFrom(
                    backgroundColor: selected
                        ? AppColors.accent.withValues(alpha: 0.15)
                        : Colors.transparent,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: Text(
                    _tabs[i],
                    style: TextStyle(
                      fontSize: 11,
                      color:
                          selected ? AppColors.accent : AppColors.textSecondary,
                    ),
                  ),
                ),
              );
            }),
          ),
        ],
      ),
    );
  }
}
