import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';

final Set<String> _registeredViewTypes = <String>{};

Widget createVideoStreamWidget(String url) {
  final viewType = 'mjpeg-stream-${url.hashCode}';
  if (_registeredViewTypes.add(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int viewId) => html.ImageElement()
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
