import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';

class SyncedVideoController extends ChangeNotifier {
  bool _playing = true;
  double _positionSeconds = 0;
  double _playbackRate = 1.0;

  bool get isPlaying => _playing;
  double get positionSeconds => _positionSeconds;
  double get durationSeconds => 0;
  double get playbackRate => _playbackRate;
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

  void setPlaybackRate(double value) {
    if (!value.isFinite) return;
    _playbackRate = value.clamp(0.25, 2.0).toDouble();
    notifyListeners();
  }
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
