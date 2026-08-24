import 'dart:async';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

final Set<String> _registeredViewTypes = <String>{};

class SyncedVideoController extends ChangeNotifier {
  final Map<String, web.HTMLVideoElement> _videos = {};
  Timer? _ticker;
  bool _playing = true;
  double _positionSeconds = 0;
  double _durationSeconds = 0;

  bool get isPlaying => _playing;
  double get positionSeconds => _positionSeconds;
  double get durationSeconds => _durationSeconds;
  bool get isReady => _durationSeconds > 0;

  void attach(String key, web.HTMLVideoElement video) {
    _videos[key] = video;
    _ticker ??= Timer.periodic(
      const Duration(milliseconds: 100),
      (_) => _synchronize(),
    );
    video.onLoadedMetadata.listen((_) {
      if (video.duration.isFinite && video.duration > 0) {
        final duration = video.duration.toDouble();
        _durationSeconds = _durationSeconds == 0
            ? duration
            : _durationSeconds < duration
                ? _durationSeconds
                : duration;
      }
      _setTime(video, _positionSeconds);
      if (_playing) {
        video.play();
      }
      notifyListeners();
    });
  }

  void _synchronize() {
    if (_videos.isEmpty) return;
    final leader = _videos.values.first;
    if (leader.duration.isFinite && leader.duration > 0) {
      _durationSeconds = leader.duration.toDouble();
    }
    if (leader.currentTime.isFinite) {
      _positionSeconds = leader.currentTime.toDouble();
    }
    if (_playing) {
      for (final video in _videos.values) {
        if ((video.currentTime - _positionSeconds).abs() > 0.10) {
          _setTime(video, _positionSeconds);
        }
        if (video.paused) {
          video.play();
        }
      }
    }
    notifyListeners();
  }

  void play() {
    _playing = true;
    for (final video in _videos.values) {
      _setTime(video, _positionSeconds);
      video.play();
    }
    notifyListeners();
  }

  void pause() {
    _playing = false;
    for (final video in _videos.values) {
      video.pause();
    }
    notifyListeners();
  }

  void toggle() => _playing ? pause() : play();

  void seek(double seconds) {
    final maximum = _durationSeconds > 0 ? _durationSeconds : seconds;
    _positionSeconds = seconds.clamp(0, maximum).toDouble();
    for (final video in _videos.values) {
      _setTime(video, _positionSeconds);
    }
    notifyListeners();
  }

  void skip(double seconds) => seek(_positionSeconds + seconds);

  static void _setTime(web.HTMLVideoElement video, double seconds) {
    try {
      video.currentTime = seconds;
    } catch (_) {
      // Metadata may not be available during the first widget frame.
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    for (final video in _videos.values) {
      video.pause();
    }
    _videos.clear();
    super.dispose();
  }
}

Widget createVideoStreamWidget(String url) {
  final viewType = 'mjpeg-stream-${url.hashCode}';
  if (_registeredViewTypes.add(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int viewId) => web.HTMLImageElement()
        ..src = url
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.border = 'none'
        ..style.objectFit = 'contain'
        ..style.backgroundColor = '#0b1220',
    );
  }
  return HtmlElementView(viewType: viewType);
}

Widget createVideoFileWidget(
  String url, {
  SyncedVideoController? controller,
  String? streamKey,
}) {
  final controllerId = controller == null ? 0 : identityHashCode(controller);
  final key = streamKey ?? url;
  final viewType = 'video-file-${url.hashCode}-$controllerId-${key.hashCode}';
  if (_registeredViewTypes.add(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int viewId) {
        final video = web.HTMLVideoElement()
          ..src = url
          ..autoplay = controller?.isPlaying ?? true
          ..loop = true
          ..muted = true
          ..controls = false
          ..preload = 'auto'
          ..style.width = '100%'
          ..style.height = '100%'
          ..style.border = 'none'
          ..style.objectFit = 'contain'
          ..style.backgroundColor = '#0b1220';
        video.setAttribute('playsinline', 'true');
        controller?.attach(key, video);
        video.onCanPlay.listen((_) {
          if (controller?.isPlaying ?? true) {
            video.play();
          }
        });
        return video;
      },
    );
  }
  return HtmlElementView(viewType: viewType);
}
