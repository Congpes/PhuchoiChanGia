import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';
import 'synced_video_controls.dart';
import 'video_stream.dart';
import '../demo/phone_demo_timeline.dart';

class PhoneDemoPlayer extends StatefulWidget {
  const PhoneDemoPlayer({super.key, required this.demoId});
  final String demoId;

  @override
  State<PhoneDemoPlayer> createState() => _PhoneDemoPlayerState();
}

class _PhoneDemoPlayerState extends State<PhoneDemoPlayer> {
  late final SyncedVideoController _controller;

  @override
  void initState() {
    super.initState();
    _controller = SyncedVideoController()..setPlaybackRate(1.0);
    _controller.addListener(_publishPosition);
  }

  void _publishPosition() {
    if (widget.demoId == 'phone-02') {
      phoneDemoPosition.value = _controller.positionSeconds;
    }
  }

  @override
  void dispose() {
    _controller.removeListener(_publishPosition);
    _controller.dispose();
    super.dispose();
  }

  Widget _view(String view, String label) => Expanded(
        child: Column(children: [
          Padding(padding: const EdgeInsets.all(8), child: Text(label)),
          Expanded(
              child: createVideoFileWidget(
            'http://127.0.0.1:8000/phone-demos/${widget.demoId}/$view.mp4',
            controller: _controller,
            streamKey: '${widget.demoId}-$view',
          )),
        ]),
      );

  @override
  Widget build(BuildContext context) => Column(children: [
        Expanded(
            child: Row(children: [
          _view('frontal', 'CHÍNH DIỆN'),
          const SizedBox(width: 8),
          _view('sagittal', 'GÓC NGANG'),
        ])),
        SyncedVideoControls(controller: _controller),
        const Padding(
          padding: EdgeInsets.all(6),
          child: Text(
              'Video nguồn · đồng bộ chưa xác nhận · chưa có dữ liệu FSR',
              style: TextStyle(fontSize: 11)),
        ),
      ]);
}
