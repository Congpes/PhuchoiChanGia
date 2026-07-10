export 'video_stream_stub.dart'
    if (dart.library.html) 'video_stream_web.dart'
    if (dart.library.io) 'video_stream_desktop.dart';
