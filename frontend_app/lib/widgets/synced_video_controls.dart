import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'video_stream.dart';

class SyncedVideoControls extends StatelessWidget {
  const SyncedVideoControls({
    super.key,
    required this.controller,
  });

  final SyncedVideoController controller;

  static String _time(double seconds) {
    if (!seconds.isFinite || seconds < 0) return '00:00';
    final total = seconds.floor();
    final minutes = total ~/ 60;
    final remainder = total % 60;
    return '${minutes.toString().padLeft(2, '0')}:'
        '${remainder.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        final duration =
            controller.durationSeconds > 0 ? controller.durationSeconds : 1.0;
        final position =
            controller.positionSeconds.clamp(0.0, duration).toDouble();
        return Container(
          height: 42,
          padding: const EdgeInsets.symmetric(horizontal: 6),
          decoration: const BoxDecoration(
            color: AppColors.panel,
            border: Border(top: BorderSide(color: AppColors.border)),
          ),
          child: Row(
            children: [
              _button(
                icon: Icons.replay_5,
                tooltip: 'L?i 5 gi?y',
                onPressed:
                    controller.isReady ? () => controller.skip(-5) : null,
              ),
              _button(
                icon: controller.isPlaying ? Icons.pause : Icons.play_arrow,
                tooltip: controller.isPlaying ? 'T?m d?ng' : 'Ph?t',
                onPressed: controller.toggle,
                emphasized: true,
              ),
              _button(
                icon: Icons.forward_5,
                tooltip: 'Ti?n 5 gi?y',
                onPressed: controller.isReady ? () => controller.skip(5) : null,
              ),
              SizedBox(
                width: 48,
                child: Text(
                  _time(position),
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 10,
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
              Expanded(
                child: SliderTheme(
                  data: SliderTheme.of(context).copyWith(
                    trackHeight: 2,
                    thumbShape:
                        const RoundSliderThumbShape(enabledThumbRadius: 5),
                    overlayShape:
                        const RoundSliderOverlayShape(overlayRadius: 11),
                  ),
                  child: Slider(
                    min: 0,
                    max: duration,
                    value: position,
                    onChanged: controller.isReady ? controller.seek : null,
                  ),
                ),
              ),
              SizedBox(
                width: 48,
                child: Text(
                  _time(controller.durationSeconds),
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 10,
                    color: AppColors.textSecondary,
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  static Widget _button({
    required IconData icon,
    required String tooltip,
    required VoidCallback? onPressed,
    bool emphasized = false,
  }) {
    return IconButton(
      onPressed: onPressed,
      icon: Icon(icon, size: emphasized ? 22 : 18),
      tooltip: tooltip,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints.tightFor(width: 32, height: 32),
      visualDensity: VisualDensity.compact,
      color: emphasized ? AppColors.accent : AppColors.textSecondary,
    );
  }
}
