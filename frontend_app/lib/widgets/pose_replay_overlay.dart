import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

@immutable
class PoseSkeletonVisualStyle {
  const PoseSkeletonVisualStyle({
    required this.color,
    required this.opacity,
    required this.strokeScale,
  });

  final Color color;
  final double opacity;
  final double strokeScale;
}

/// Resolve presentation only; pose acceptance and angle calculation use the
/// independent quality gates supplied by the backend.
@visibleForTesting
PoseSkeletonVisualStyle poseSkeletonVisualStyleFor({
  required String start,
  required String end,
  required double visibility,
}) {
  const leftColor = Color(0xFF1E9ED8);
  const rightColor = Color(0xFFFFC21A);
  const trunkColor = Color(0xFF50E664);
  const highVisibility = 0.80;
  const lowVisibilityOpacity = 0.55;

  final color = start.startsWith('left_') && end.startsWith('left_')
      ? leftColor
      : start.startsWith('right_') && end.startsWith('right_')
          ? rightColor
          : trunkColor;
  final isReliable = visibility >= highVisibility;
  return PoseSkeletonVisualStyle(
    color: color,
    opacity: isReliable ? 1.0 : lowVisibilityOpacity,
    strokeScale: isReliable ? 1.0 : 0.55,
  );
}

class PoseReplayOverlay extends StatefulWidget {
  const PoseReplayOverlay({
    super.key,
    required this.scanId,
    required this.view,
    required this.position,
    required this.analysisRevision,
  });

  final String scanId;
  final String view;
  final double position;
  final int analysisRevision;

  @override
  State<PoseReplayOverlay> createState() => _PoseReplayOverlayState();
}

class _PoseReplayOverlayState extends State<PoseReplayOverlay> {
  List<_PoseFrame> _frames = const [];
  Size _sourceSize = const Size(640, 480);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant PoseReplayOverlay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.scanId != widget.scanId ||
        oldWidget.view != widget.view ||
        oldWidget.analysisRevision != widget.analysisRevision) {
      _load();
    }
  }

  Future<void> _load() async {
    try {
      final response = await http
          .get(
            Uri.parse(
              'http://127.0.0.1:8000/scans/${widget.scanId}/pose-replay'
              '?view=${widget.view}&revision=${widget.analysisRevision}',
            ),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return;
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) return;
      final views = decoded['views'];
      final source = views is Map ? views[widget.view] : null;
      final sourceSizes = decoded['sourceSizes'];
      final sourceSize = sourceSizes is Map ? sourceSizes[widget.view] : null;
      final sourceWidth = sourceSize is List && sourceSize.isNotEmpty
          ? (sourceSize[0] as num?)?.toDouble()
          : null;
      final sourceHeight = sourceSize is List && sourceSize.length > 1
          ? (sourceSize[1] as num?)?.toDouble()
          : null;
      final resolvedSourceSize = sourceWidth != null &&
              sourceHeight != null &&
              sourceWidth > 0 &&
              sourceHeight > 0
          ? Size(sourceWidth, sourceHeight)
          : const Size(640, 480);
      final frames = source is List
          ? source
              .whereType<Map>()
              .map((item) => _PoseFrame.fromJson(
                    Map<String, dynamic>.from(item),
                  ))
              .whereType<_PoseFrame>()
              .toList()
          : <_PoseFrame>[];
      frames.sort((a, b) => a.time.compareTo(b.time));
      if (mounted) {
        setState(() {
          _frames = frames;
          _sourceSize = resolvedSourceSize;
        });
      }
    } catch (_) {
      // Raw video remains usable when no derived pose run is available.
    }
  }

  _PoseFrame? _frameAtPosition() {
    if (_frames.isEmpty) return null;
    var low = 0;
    var high = _frames.length - 1;
    while (low < high) {
      final middle = (low + high) ~/ 2;
      if (_frames[middle].time < widget.position) {
        low = middle + 1;
      } else {
        high = middle;
      }
    }
    final after = _frames[low];
    final before = low > 0 ? _frames[low - 1] : after;
    final nearest = (before.time - widget.position).abs() <=
            (after.time - widget.position).abs()
        ? before
        : after;
    if ((nearest.time - widget.position).abs() > 0.35) return null;
    final span = after.time - before.time;
    if (identical(before, after) || span <= 0 || span > 0.35) return nearest;
    final fraction =
        ((widget.position - before.time) / span).clamp(0.0, 1.0).toDouble();
    return _PoseFrame.interpolate(before, after, fraction);
  }

  @override
  Widget build(BuildContext context) {
    final frame = _frameAtPosition();
    if (frame == null) return const SizedBox.expand();
    return IgnorePointer(
      child: CustomPaint(
        painter: _PoseSkeletonPainter(
          frame.landmarks,
          sagittal: widget.view == 'sagittal',
          sourceSize: _sourceSize,
        ),
        size: Size.infinite,
      ),
    );
  }
}

class _PoseFrame {
  const _PoseFrame({required this.time, required this.landmarks});

  final double time;
  final Map<String, _PosePoint> landmarks;

  static _PoseFrame interpolate(
    _PoseFrame before,
    _PoseFrame after,
    double fraction,
  ) {
    final landmarks = <String, _PosePoint>{};
    for (final name in before.landmarks.keys) {
      final start = before.landmarks[name];
      final end = after.landmarks[name];
      if (start == null || end == null) continue;
      landmarks[name] = _PosePoint(
        start.x + (end.x - start.x) * fraction,
        start.y + (end.y - start.y) * fraction,
        start.visibility < end.visibility ? start.visibility : end.visibility,
      );
    }
    return _PoseFrame(
      time: before.time + (after.time - before.time) * fraction,
      landmarks: landmarks,
    );
  }

  static _PoseFrame? fromJson(Map<String, dynamic> json) {
    final time = (json['time'] as num?)?.toDouble();
    final source = json['landmarks'];
    if (time == null || source is! Map) return null;
    final landmarks = <String, _PosePoint>{};
    for (final entry in source.entries) {
      if (entry.value is! Map) continue;
      final point = _PosePoint.fromJson(
        Map<String, dynamic>.from(entry.value as Map),
      );
      if (point != null) landmarks[entry.key.toString()] = point;
    }
    return landmarks.isEmpty
        ? null
        : _PoseFrame(time: time, landmarks: landmarks);
  }
}

class _PosePoint {
  const _PosePoint(this.x, this.y, this.visibility);

  final double x;
  final double y;
  final double visibility;

  static _PosePoint? fromJson(Map<String, dynamic> json) {
    final x = (json['x'] as num?)?.toDouble();
    final y = (json['y'] as num?)?.toDouble();
    final visibility = (json['visibility'] as num?)?.toDouble() ?? 0;
    if (x == null || y == null || !x.isFinite || !y.isFinite) return null;
    return _PosePoint(x, y, visibility);
  }
}

class _PoseSkeletonPainter extends CustomPainter {
  const _PoseSkeletonPainter(
    this.landmarks, {
    required this.sagittal,
    required this.sourceSize,
  });

  final Map<String, _PosePoint> landmarks;
  final bool sagittal;
  final Size sourceSize;

  static const _connections = <(String, String)>[
    ('left_shoulder', 'right_shoulder'),
    ('left_shoulder', 'left_hip'),
    ('right_shoulder', 'right_hip'),
    ('left_hip', 'right_hip'),
    ('left_hip', 'left_knee'),
    ('left_knee', 'left_ankle'),
    ('left_ankle', 'left_heel'),
    ('left_heel', 'left_foot_index'),
    ('left_ankle', 'left_foot_index'),
    ('right_hip', 'right_knee'),
    ('right_knee', 'right_ankle'),
    ('right_ankle', 'right_heel'),
    ('right_heel', 'right_foot_index'),
    ('right_ankle', 'right_foot_index'),
  ];

  // Display-only gates. Analysis quality thresholds remain intentionally
  // stricter; this lower gate keeps the far leg visible through short overlap.
  static const _minimumVisibility = 0.40;
  static const _highVisibility = 0.80;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final fitted = applyBoxFit(
      BoxFit.contain,
      sourceSize,
      size,
    );
    final imageRect =
        Alignment.center.inscribe(fitted.destination, Offset.zero & size);

    Offset? offsetOf(String name) {
      final point = landmarks[name];
      if (point == null ||
          point.visibility < _minimumVisibility ||
          point.x < 0 ||
          point.x > 1 ||
          point.y < 0 ||
          point.y > 1) {
        return null;
      }
      return Offset(
        imageRect.left + point.x * imageRect.width,
        imageRect.top + point.y * imageRect.height,
      );
    }

    final pointOffsets = <String, Offset?>{
      for (final name in landmarks.keys) name: offsetOf(name),
    };
    final renderedNames = <String>{};
    final shortestSide = size.shortestSide;
    final strokeWidth = (shortestSide * 0.007).clamp(1.8, 3.2).toDouble();

    for (final connection in _connections) {
      if (sagittal &&
          ((connection.$1 == 'left_shoulder' && connection.$2 == 'left_hip') ||
              (connection.$1 == 'right_shoulder' &&
                  connection.$2 == 'right_hip'))) {
        continue;
      }
      final start = offsetOf(connection.$1);
      final end = offsetOf(connection.$2);
      if (start == null || end == null) continue;
      final segmentLength = (end - start).distance;
      if (!segmentLength.isFinite || segmentLength > imageRect.height * 0.48) {
        continue;
      }
      final visibility = [
        landmarks[connection.$1]?.visibility ?? 0,
        landmarks[connection.$2]?.visibility ?? 0,
      ].reduce((a, b) => a < b ? a : b);
      final style = poseSkeletonVisualStyleFor(
        start: connection.$1,
        end: connection.$2,
        visibility: visibility,
      );
      canvas.drawLine(
        start,
        end,
        Paint()
          ..color = style.color.withValues(alpha: style.opacity)
          ..strokeWidth = strokeWidth * style.strokeScale
          ..strokeCap = StrokeCap.round,
      );
      renderedNames.addAll([connection.$1, connection.$2]);
    }

    if (sagittal) {
      final shoulders = ['left_shoulder', 'right_shoulder']
          .map((name) => (name: name, point: pointOffsets[name]))
          .where((item) => item.point != null)
          .toList();
      final hips = ['left_hip', 'right_hip']
          .map((name) => (name: name, point: pointOffsets[name]))
          .where((item) => item.point != null)
          .toList();
      if (shoulders.isNotEmpty && hips.isNotEmpty) {
        Offset centreOf(List<({String name, Offset? point})> items) =>
            items.map((item) => item.point!).reduce((a, b) => a + b) /
            items.length.toDouble();
        final shoulderCentre = centreOf(shoulders);
        final hipCentre = centreOf(hips);
        final centreVisibility = [...shoulders, ...hips]
            .map((item) => landmarks[item.name]?.visibility ?? 0)
            .reduce((a, b) => a < b ? a : b);
        if ((hipCentre - shoulderCentre).distance <= imageRect.height * 0.48) {
          final style = poseSkeletonVisualStyleFor(
            start: 'trunk',
            end: 'trunk',
            visibility: centreVisibility,
          );
          canvas.drawLine(
            shoulderCentre,
            hipCentre,
            Paint()
              ..color = style.color.withValues(alpha: style.opacity)
              ..strokeWidth = strokeWidth * style.strokeScale
              ..strokeCap = StrokeCap.round,
          );
          renderedNames.addAll(shoulders.map((item) => item.name));
          renderedNames.addAll(hips.map((item) => item.name));
        }
      }
    }
    for (final name in renderedNames) {
      final point = offsetOf(name);
      if (point == null) continue;
      final visibility = landmarks[name]?.visibility ?? 0;
      final style = poseSkeletonVisualStyleFor(
        start: name,
        end: name,
        visibility: visibility,
      );
      final scale = visibility >= _highVisibility ? 1.0 : 0.75;
      final outerRadius =
          (strokeWidth * 1.75 * scale).clamp(2.4, 5.0).toDouble();
      final innerRadius =
          (strokeWidth * 1.05 * scale).clamp(1.5, 3.2).toDouble();
      canvas.drawCircle(
        point,
        outerRadius,
        Paint()
          ..color = const Color(0xD9000000).withValues(alpha: style.opacity),
      );
      canvas.drawCircle(
        point,
        innerRadius,
        Paint()..color = style.color.withValues(alpha: style.opacity),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _PoseSkeletonPainter oldDelegate) {
    return oldDelegate.landmarks != landmarks ||
        oldDelegate.sagittal != sagittal ||
        oldDelegate.sourceSize != sourceSize;
  }
}
