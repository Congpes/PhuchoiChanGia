import 'dart:math' as math;
import 'dart:ui' as ui;

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
    required this.rawAdc,
  });

  static const _heatStops = <double>[0, 0.16, 0.32, 0.50, 0.68, 0.84, 1];
  static const _heatColors = <Color>[
    Color(0xFF4389C7),
    Color(0xFF19A9D1),
    Color(0xFF13A875),
    Color(0xFF75D054),
    Color(0xFFF1E51D),
    Color(0xFFF7941D),
    Color(0xFFD9271C),
  ];

  final List<List<double>>? matrix;
  final bool isLeft;
  final double scaleMax;
  final bool rawAdc;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;

    canvas.save();
    final angle = isLeft ? 0.035 : -0.035;
    canvas.translate(size.width / 2, size.height / 2);
    canvas.rotate(angle);
    canvas.scale(0.94, 0.94);
    canvas.translate(-size.width / 2, -size.height / 2);

    final foot = _footPath(size);
    final values = _normalizedMatrix();

    canvas.drawPath(
      foot,
      Paint()
        ..color = const Color(0xFFDCE8F2)
        ..style = PaintingStyle.fill,
    );

    if (values != null) {
      canvas.save();
      canvas.clipPath(foot);
      _paintSmoothHeatmap(canvas, size, _blur(values));
      canvas.restore();
    }

    canvas.drawPath(
      foot,
      Paint()
        ..color = const Color(0xFF647A91)
        ..strokeWidth = math.max(1.25, size.width * 0.012)
        ..style = PaintingStyle.stroke,
    );
    canvas.restore();
  }

  List<List<double>>? _normalizedMatrix() {
    final values = matrix;
    if (values == null || values.length != 12) return null;
    if (values.any((row) => row.length != 4)) return null;

    return List.generate(12, (row) {
      return List.generate(4, (column) {
        final value = values[row][column];
        final ratio = rawAdc
            ? ((4000.0 - value) / 3000.0).clamp(0.0, 1.0).toDouble()
            : scaleMax <= 0
                ? 0.0
                : (value / scaleMax).clamp(0.0, 1.0).toDouble();
        return math.pow(ratio, 0.78).toDouble();
      });
    });
  }

  List<List<double>> _blur(List<List<double>> source) {
    final horizontal = List.generate(12, (_) => List.filled(4, 0.0));
    for (var row = 0; row < 12; row++) {
      for (var column = 0; column < 4; column++) {
        final previous = source[row][math.max(0, column - 1)];
        final current = source[row][column];
        final next = source[row][math.min(3, column + 1)];
        horizontal[row][column] = (previous + 2 * current + next) / 4;
      }
    }

    final result = List.generate(12, (_) => List.filled(4, 0.0));
    for (var row = 0; row < 12; row++) {
      for (var column = 0; column < 4; column++) {
        final previous = horizontal[math.max(0, row - 1)][column];
        final current = horizontal[row][column];
        final next = horizontal[math.min(11, row + 1)][column];
        result[row][column] = (previous + 2 * current + next) / 4;
      }
    }
    return result;
  }

  void _paintSmoothHeatmap(
    Canvas canvas,
    Size size,
    List<List<double>> values,
  ) {
    final columns = (size.width / 4).round().clamp(24, 48).toInt();
    final rows = (size.height / 4).round().clamp(60, 112).toInt();
    final positions = <Offset>[];
    final colors = <Color>[];
    final indices = <int>[];

    for (var row = 0; row <= rows; row++) {
      final y = row / rows;
      for (var column = 0; column <= columns; column++) {
        final x = column / columns;
        positions.add(Offset(x * size.width, y * size.height));
        colors.add(_heatColor(_sampleBicubic(values, x, y)));
      }
    }

    final stride = columns + 1;
    for (var row = 0; row < rows; row++) {
      for (var column = 0; column < columns; column++) {
        final topLeft = row * stride + column;
        final topRight = topLeft + 1;
        final bottomLeft = topLeft + stride;
        final bottomRight = bottomLeft + 1;
        indices.addAll([
          topLeft,
          bottomLeft,
          topRight,
          topRight,
          bottomLeft,
          bottomRight,
        ]);
      }
    }

    final vertices = ui.Vertices(
      ui.VertexMode.triangles,
      positions,
      colors: colors,
      indices: indices,
    );
    canvas.drawVertices(
      vertices,
      BlendMode.modulate,
      Paint()
        ..color = Colors.white
        ..isAntiAlias = true,
    );
  }

  double _sampleBicubic(
    List<List<double>> values,
    double normalizedX,
    double normalizedY,
  ) {
    final columnPosition = (((normalizedX - 0.14) / 0.72) * 3).clamp(0.0, 3.0);
    final rowPosition = (((normalizedY - 0.035) / 0.93) * 11).clamp(0.0, 11.0);
    final column = columnPosition.floor();
    final row = rowPosition.floor();
    final tx = columnPosition - column;
    final ty = rowPosition - row;

    final rowSamples = List<double>.generate(4, (offset) {
      final sourceRow = (row + offset - 1).clamp(0, 11).toInt();
      return _catmullRom(
        values[sourceRow][(column - 1).clamp(0, 3).toInt()],
        values[sourceRow][column.clamp(0, 3).toInt()],
        values[sourceRow][(column + 1).clamp(0, 3).toInt()],
        values[sourceRow][(column + 2).clamp(0, 3).toInt()],
        tx,
      );
    });

    return _catmullRom(
      rowSamples[0],
      rowSamples[1],
      rowSamples[2],
      rowSamples[3],
      ty,
    ).clamp(0.0, 1.0).toDouble();
  }

  double _catmullRom(
    double first,
    double second,
    double third,
    double fourth,
    double amount,
  ) {
    final amount2 = amount * amount;
    final amount3 = amount2 * amount;
    return 0.5 *
        ((2 * second) +
            (-first + third) * amount +
            (2 * first - 5 * second + 4 * third - fourth) * amount2 +
            (-first + 3 * second - 3 * third + fourth) * amount3);
  }

  Color _heatColor(double ratio) {
    final value = ratio.clamp(0.0, 1.0).toDouble();
    for (var index = 0; index < _heatStops.length - 1; index++) {
      final start = _heatStops[index];
      final end = _heatStops[index + 1];
      if (value <= end) {
        final local = ((value - start) / (end - start)).clamp(0.0, 1.0);
        return Color.lerp(
          _heatColors[index],
          _heatColors[index + 1],
          local,
        )!;
      }
    }
    return _heatColors.last;
  }

  Path _footPath(Size size) {
    double x(double value) => (isLeft ? value : 1 - value) * size.width;
    double y(double value) => value * size.height;

    return Path()
      ..moveTo(x(0.48), y(0.018))
      ..cubicTo(x(0.28), y(0.002), x(0.12), y(0.085), x(0.09), y(0.235))
      ..cubicTo(x(0.06), y(0.36), x(0.14), y(0.45), x(0.22), y(0.525))
      ..cubicTo(x(0.28), y(0.59), x(0.23), y(0.70), x(0.21), y(0.82))
      ..cubicTo(x(0.19), y(0.94), x(0.29), y(0.985), x(0.46), y(0.99))
      ..cubicTo(x(0.64), y(0.995), x(0.77), y(0.95), x(0.76), y(0.84))
      ..cubicTo(x(0.75), y(0.73), x(0.66), y(0.64), x(0.68), y(0.56))
      ..cubicTo(x(0.70), y(0.49), x(0.82), y(0.46), x(0.89), y(0.38))
      ..cubicTo(x(0.98), y(0.27), x(0.91), y(0.12), x(0.77), y(0.055))
      ..cubicTo(x(0.68), y(0.014), x(0.58), y(0.01), x(0.48), y(0.018))
      ..close();
  }

  @override
  bool shouldRepaint(covariant _FootPressurePainter oldDelegate) =>
      oldDelegate.matrix != matrix ||
      oldDelegate.isLeft != isLeft ||
      oldDelegate.scaleMax != scaleMax ||
      oldDelegate.rawAdc != rawAdc;
}
