import 'package:flutter/material.dart';
import 'package:camera/camera.dart';

import '../theme/app_theme.dart';
import 'video_stream.dart';

class CameraPanel extends StatelessWidget {
  const CameraPanel({
    super.key,
    required this.title,
    required this.subtitle,
    this.isRecording = false,
    this.showSkeletonHint = true,
    this.controller,
    this.videoStreamUrl,
  });

  final String title;
  final String subtitle;
  final bool isRecording;
  final bool showSkeletonHint;
  final CameraController? controller;
  final String? videoStreamUrl;

  @override
  Widget build(BuildContext context) {
    final hasLocalCamera = controller != null && controller!.value.isInitialized;
    final hasBackendStream = videoStreamUrl != null;

    return Expanded(
      child: Container(
        margin: const EdgeInsets.all(4),
        decoration: BoxDecoration(
          color: AppColors.panel,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (hasBackendStream)
              createVideoStreamWidget(videoStreamUrl!)
            else if (hasLocalCamera)
              ClipRect(
                child: FittedBox(
                  fit: BoxFit.contain,
                  child: SizedBox(
                    width: controller!.value.previewSize!.height,
                    height: controller!.value.previewSize!.width,
                    child: CameraPreview(controller!),
                  ),
                ),
              )
            else
              CustomPaint(painter: _GridPainter()),
            Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (!hasLocalCamera && !hasBackendStream) ...[
                    Icon(Icons.videocam_outlined,
                        size: 48, color: AppColors.textSecondary.withValues(alpha: 0.5)),
                    const SizedBox(height: 8),
                    Text(
                      'Camera preview',
                      style: TextStyle(color: AppColors.textSecondary.withValues(alpha: 0.7)),
                    ),
                    const SizedBox(height: 4),
                  ],
                  Text(
                    subtitle,
                    style: TextStyle(
                      color: (hasLocalCamera || hasBackendStream) ? Colors.white70 : AppColors.textSecondary,
                      fontSize: 12,
                      shadows: (hasLocalCamera || hasBackendStream) ? [const Shadow(color: Colors.black, blurRadius: 4)] : null,
                    ),
                  ),
                ],
              ),
            ),
            if (showSkeletonHint && !hasBackendStream) const _SkeletonOverlayHint(),
            Positioned(
              left: 8,
              top: 8,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                color: Colors.black54,
                child: Text(
                  title,
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                ),
              ),
            ),
            if (isRecording)
              Positioned(
                right: 8,
                top: 8,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: AppColors.critical.withValues(alpha: 0.9),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.fiber_manual_record, size: 10, color: Colors.white),
                      SizedBox(width: 4),
                      Text('REC', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold)),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _SkeletonOverlayHint extends StatelessWidget {
  const _SkeletonOverlayHint();

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _SkeletonPainter(),
      child: const SizedBox.expand(),
    );
  }
}

class _GridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.border.withValues(alpha: 0.3)
      ..strokeWidth = 0.5;

    for (var i = 1; i < 8; i++) {
      final x = size.width * i / 8;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var i = 1; i < 6; i++) {
      final y = size.height * i / 6;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _SkeletonPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFFFFD60A).withValues(alpha: 0.45)
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;

    final cx = size.width * 0.5;
    final head = Offset(cx, size.height * 0.12);
    final shoulder = Offset(cx, size.height * 0.22);
    final hip = Offset(cx, size.height * 0.48);
    final knee = Offset(cx, size.height * 0.68);
    final ankle = Offset(cx, size.height * 0.88);

    canvas.drawCircle(head, 12, paint);
    canvas.drawLine(head, shoulder, paint);
    canvas.drawLine(shoulder, hip, paint);
    canvas.drawLine(hip, knee, paint);
    canvas.drawLine(knee, ankle, paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
