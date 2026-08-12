import 'dart:math' as math;

import 'package:flutter/material.dart';

class FootPressureMap extends StatelessWidget {
  const FootPressureMap({
    super.key,
    required this.matrix,
    required this.isLeft,
    required this.scaleMax,
    this.rawAdc = false,
  });

  final List<List<double>>? matrix;
  final bool isLeft;
  final double scaleMax;
  final bool rawAdc;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _FootPressurePainter(
        matrix: matrix,
        isLeft: isLeft,
        scaleMax: scaleMax,
        rawAdc: rawAdc,
      ),
    );
  }
}

class _FootPressurePainter extends CustomPainter {
  const _FootPressurePainter({
    required this.matrix,
    required this.isLeft,
    required this.scaleMax,
    this.rawAdc = false,
  });

  final List<List<double>>? matrix;
  final bool isLeft;
  final double scaleMax;
  final bool rawAdc;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    if (isLeft) {
      canvas.translate(size.width, 0);
      canvas.scale(-1, 1);
    }

    final foot = _footPath(size);
    canvas.drawPath(
      foot,
      Paint()
        ..color = const Color(0xFFE7EDF3)
        ..style = PaintingStyle.fill,
    );
    canvas.save();
    canvas.clipPath(foot);

    final values = matrix ?? const <List<double>>[];
    if (scaleMax > 0) {
      for (var row = 0; row < math.min(12, values.length); row++) {
        for (var column = 0;
            column < math.min(4, values[row].length);
            column++) {
          final value = values[row][column];
          if (value <= 0) continue;
          final center = _sensorCenter(size, row, column);
          final color = rawAdc
              ? _rawAdcColor(value)
              : _demoColor((value / scaleMax).clamp(0.0, 1.0));
          final cellSize = math.min(size.width * 0.16, size.height * 0.065);
          final cell = Rect.fromCenter(
            center: center,
            width: cellSize,
            height: cellSize,
          );
          canvas.drawRRect(
            RRect.fromRectAndRadius(cell, Radius.circular(cellSize * 0.12)),
            Paint()..color = color,
          );
        }
      }
    }

    canvas.restore();
    canvas.drawPath(
      foot,
      Paint()
        ..color = const Color(0xFF6D7E91)
        ..strokeWidth = math.max(1.2, size.width * 0.014)
        ..style = PaintingStyle.stroke,
    );
    canvas.restore();
  }

  Path _footPath(Size size) {
    double x(double value) => value * size.width;
    double y(double value) => value * size.height;
    return Path()
      ..moveTo(x(0.50), y(0.015))
      ..cubicTo(x(0.27), y(0.005), x(0.12), y(0.13), x(0.12), y(0.30))
      ..cubicTo(x(0.12), y(0.42), x(0.21), y(0.49), x(0.22), y(0.60))
      ..cubicTo(x(0.23), y(0.72), x(0.17), y(0.86), x(0.27), y(0.95))
      ..cubicTo(x(0.38), y(1.015), x(0.62), y(1.015), x(0.73), y(0.95))
      ..cubicTo(x(0.83), y(0.86), x(0.77), y(0.72), x(0.74), y(0.62))
      ..cubicTo(x(0.71), y(0.52), x(0.73), y(0.46), x(0.82), y(0.39))
      ..cubicTo(x(0.93), y(0.30), x(0.90), y(0.13), x(0.73), y(0.055))
      ..cubicTo(x(0.66), y(0.025), x(0.58), y(0.015), x(0.50), y(0.015))
      ..close();
  }

  Offset _sensorCenter(Size size, int row, int column) {
    const xPositions = [0.25, 0.42, 0.59, 0.75];
    final y = 0.075 + ((11 - row) / 11) * 0.86;
    return Offset(size.width * xPositions[column], size.height * y);
  }

  Color _rawAdcColor(double value) {
    if (value >= 4000) return const Color(0xFF22A06B);
    if (value >= 3000) return const Color(0xFFFACC15);
    if (value >= 2000) return const Color(0xFFF59E0B);
    if (value >= 1000) return const Color(0xFFEA580C);
    return const Color(0xFFDC2626);
  }

  Color _demoColor(double ratio) {
    if (ratio < 0.20) return const Color(0xFF22A06B);
    if (ratio < 0.40) return const Color(0xFFFACC15);
    if (ratio < 0.65) return const Color(0xFFF59E0B);
    if (ratio < 0.82) return const Color(0xFFEA580C);
    return const Color(0xFFDC2626);
  }

  @override
  bool shouldRepaint(covariant _FootPressurePainter oldDelegate) =>
      oldDelegate.matrix != matrix ||
      oldDelegate.isLeft != isLeft ||
      oldDelegate.scaleMax != scaleMax ||
      oldDelegate.rawAdc != rawAdc;
}
