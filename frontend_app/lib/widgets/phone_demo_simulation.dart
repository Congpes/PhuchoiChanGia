import 'dart:convert';
import 'package:flutter/material.dart' hide Text;

import '../l10n/app_language.dart';
import '../l10n/localized_text.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'video_stream.dart';

class PhoneDemoSimulation extends StatefulWidget {
  const PhoneDemoSimulation({super.key, required this.controller});
  final SyncedVideoController controller;
  @override
  State<PhoneDemoSimulation> createState() => _PhoneDemoSimulationState();
}

class _PhoneDemoSimulationState extends State<PhoneDemoSimulation> {
  Map<String, dynamic>? data;
  String? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final response = await http.get(
          Uri.parse('http://127.0.0.1:8000/phone-demos/phone-02/simulation'));
      if (response.statusCode != 200) {
        throw Exception('HTTP ${response.statusCode}');
      }
      final result = jsonDecode(response.body) as Map<String, dynamic>;
      if (mounted) setState(() => data = result);
    } catch (_) {
      if (mounted) setState(() => error = 'Chưa tải được dữ liệu FSR.');
    }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) {
      return TextButton(onPressed: load, child: Text('$error Thử lại'));
    }
    if (data == null) return const LinearProgressIndicator();
    return AnimatedBuilder(
        animation: widget.controller,
        builder: (context, _) {
          final frames = data!['frames'] as List;
          final time = widget.controller.positionSeconds;
          final index = (time * 60).round().clamp(0, frames.length - 1);
          final frame = frames[index] as Map;
          final supported = frame['supportedByCamera'] == true;
          return Container(
            padding: const EdgeInsets.all(8),
            color: const Color(0xffedf4fa),
            child: Column(children: [
              Row(children: [
                const Expanded(
                    child: Text('FSR · 80 kg',
                        style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: Colors.black87))),
                IconButton(
                    tooltip: context.tr('Sao chép dữ liệu JSON kèm nguồn gốc'),
                    icon: const Icon(Icons.copy, size: 16),
                    onPressed: () async {
                      await Clipboard.setData(
                          ClipboardData(text: jsonEncode(data)));
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                                content: Text(
                                    'Đã sao chép dữ liệu kèm nguồn gốc.')));
                      }
                    }),
              ]),
              SizedBox(
                  height: 145,
                  child: Row(children: [
                    for (final side in ['left', 'right'])
                      SizedBox(
                          width: 90,
                          child: Column(children: [
                            Text(
                                '${side == 'left' ? 'Trái' : 'Phải'}: ${supported ? '${(frame[side]['total'] as num).toStringAsFixed(0)} N' : '—'}',
                                style: const TextStyle(
                                    fontSize: 11, color: Colors.black87)),
                            Expanded(
                                child: supported
                                    ? CustomPaint(
                                        size: const Size(65, 120),
                                        painter: _HeatPainter(
                                            frame[side]['forceValues'] as List))
                                    : const Center(
                                        child: Text('Chưa đủ\nmốc camera',
                                            textAlign: TextAlign.center,
                                            style: TextStyle(
                                                fontSize: 10,
                                                color: Colors.black54)))),
                          ])),
                    Expanded(
                        child: CustomPaint(
                            size: Size.infinite,
                            painter: _ForcePainter(frames, time))),
                  ])),
              const Text(
                  'Xanh: trái · Cam: phải · 0–900 N · 0–8 s. Dữ liệu minh họa · chưa hiệu chuẩn; chưa xác nhận tiếp đất/đồng bộ.',
                  style: TextStyle(fontSize: 10, color: Colors.black87)),
              SizedBox(
                  height: 30,
                  child: ListView(scrollDirection: Axis.horizontal, children: [
                    for (final event in data!['cameraStepEstimates'] as List)
                      TextButton(
                          onPressed: () => widget.controller
                              .seek((event['time'] as num).toDouble()),
                          child: Text(
                              '${event['side'] == 'left' ? 'T' : 'P'} ${(event['time'] as num).toStringAsFixed(2)} s',
                              style: const TextStyle(fontSize: 10))),
                  ])),
            ]),
          );
        });
  }
}

class _HeatPainter extends CustomPainter {
  _HeatPainter(this.matrix);
  final List matrix;
  @override
  void paint(Canvas canvas, Size size) {
    for (var r = 0; r < 12; r++) {
      for (var c = 0; c < 4; c++) {
        final level = ((matrix[r][c] as num) / 65).clamp(0.0, 1.0);
        canvas.drawRect(
            Rect.fromLTWH(c * size.width / 4, r * size.height / 12,
                size.width / 4 - 1, size.height / 12 - 1),
            Paint()
              ..color = Color.lerp(
                  const Color(0xffe2e8f0), Colors.deepOrange, level)!);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _HeatPainter oldDelegate) => true;
}

class _ForcePainter extends CustomPainter {
  _ForcePainter(this.frames, this.time);
  final List frames;
  final double time;
  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()..color = Colors.black12;
    for (var i = 0; i <= 3; i++) {
      canvas.drawLine(Offset(0, i * size.height / 3),
          Offset(size.width, i * size.height / 3), grid);
    }
    for (final side in ['left', 'right']) {
      final path = Path();
      var inRun = false;
      for (var i = 0; i < frames.length; i++) {
        final frame = frames[i];
        if (frame['supportedByCamera'] != true) {
          inRun = false;
          continue;
        }
        final x = (frame['time'] as num) / 8 * size.width;
        final y = size.height * (1 - (frame[side]['total'] as num) / 900);
        if (!inRun) {
          path.moveTo(x, y);
        } else {
          path.lineTo(x, y);
        }
        inRun = true;
      }
      canvas.drawPath(
          path,
          Paint()
            ..color = (side == 'left' ? Colors.blue : Colors.orange)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2);
    }
    final x = time.clamp(0, 8) / 8 * size.width;
    canvas.drawLine(
        Offset(x, 0), Offset(x, size.height), Paint()..color = Colors.black54);
  }

  @override
  bool shouldRepaint(covariant _ForcePainter oldDelegate) => true;
}
