import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

enum AppAlertTone { info, success, warning, error }

/// Alert nổi dùng chung, thay thế SnackBar chiếm toàn bộ chiều ngang ở đáy màn hình.
class AppAlert {
  AppAlert._();

  static OverlayEntry? _entry;
  static Timer? _timer;

  static void show(
    BuildContext context,
    String message, {
    AppAlertTone tone = AppAlertTone.info,
    Duration duration = const Duration(seconds: 4),
  }) {
    dismiss();
    final overlay = Overlay.of(context, rootOverlay: true);
    _entry = OverlayEntry(
      builder: (_) => Positioned(
        top: 68,
        right: 16,
        child: SafeArea(
          child: Material(
            color: Colors.transparent,
            child: _AlertCard(
              message: message,
              tone: tone,
              onClose: dismiss,
            ),
          ),
        ),
      ),
    );
    overlay.insert(_entry!);
    _timer = Timer(duration, dismiss);
  }

  static void dismiss() {
    _timer?.cancel();
    _timer = null;
    _entry?.remove();
    _entry = null;
  }
}

class _AlertCard extends StatelessWidget {
  const _AlertCard({
    required this.message,
    required this.tone,
    required this.onClose,
  });

  final String message;
  final AppAlertTone tone;
  final VoidCallback onClose;

  Color get _color => switch (tone) {
        AppAlertTone.info => AppColors.accent,
        AppAlertTone.success => AppColors.accentGreen,
        AppAlertTone.warning => AppColors.warning,
        AppAlertTone.error => AppColors.critical,
      };

  IconData get _icon => switch (tone) {
        AppAlertTone.info => Icons.info_outline,
        AppAlertTone.success => Icons.check_circle_outline,
        AppAlertTone.warning => Icons.warning_amber_outlined,
        AppAlertTone.error => Icons.error_outline,
      };

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 330),
      padding: const EdgeInsets.fromLTRB(10, 8, 6, 8),
      decoration: BoxDecoration(
        color: _color,
        borderRadius: BorderRadius.circular(8),
        boxShadow: const [
          BoxShadow(
            color: Color(0x33000000),
            blurRadius: 10,
            offset: Offset(0, 3),
          ),
        ],
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_icon, size: 15, color: Colors.white),
          const SizedBox(width: 7),
          Flexible(
            child: Text(
              message,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 10,
                height: 1.2,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          IconButton(
            onPressed: onClose,
            icon: const Icon(Icons.close, color: Colors.white, size: 15),
            tooltip: 'Đóng thông báo',
            visualDensity: VisualDensity.compact,
            constraints: const BoxConstraints(minWidth: 24, minHeight: 24),
            padding: EdgeInsets.zero,
          ),
        ],
      ),
    );
  }
}
