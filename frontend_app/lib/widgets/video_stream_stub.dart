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
  return const Center(child: Text('Platform not supported'));
}

Widget createVideoFileWidget(
  String url, {
  SyncedVideoController? controller,
  String? streamKey,
}) {
  return const Center(child: Text('Video playback is not supported'));
}
