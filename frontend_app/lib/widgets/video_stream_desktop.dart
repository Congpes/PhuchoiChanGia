import 'package:flutter/material.dart';

class SyncedVideoController extends ChangeNotifier {
  bool _playing = true;
  double _positionSeconds = 0;

  bool get isPlaying => _playing;
  double get positionSeconds => _positionSeconds;
  double get durationSeconds => 0;
  bool get isReady => false;

  void play() {
    _playing = true;
    notifyListeners();
  }

  void pause() {
    _playing = false;
    notifyListeners();
  }

  void toggle() => _playing ? pause() : play();

  void seek(double seconds) {
    _positionSeconds = seconds < 0 ? 0 : seconds;
    notifyListeners();
  }

  void skip(double seconds) => seek(_positionSeconds + seconds);
}

Widget createVideoStreamWidget(String url) {
  return Image.network(
    url,
    fit: BoxFit.contain,
    gaplessPlayback: true,
    errorBuilder: (context, error, stackTrace) => const Center(
      child: Icon(Icons.broken_image, color: Colors.red),
    ),
  );
}

Widget createVideoFileWidget(
  String url, {
  SyncedVideoController? controller,
  String? streamKey,
}) {
  return const ColoredBox(
    color: Color(0xFF0B1220),
    child: Center(
      child: Text('Video m?u hi?n h? tr? tr?n Flutter Web'),
    ),
  );
}
