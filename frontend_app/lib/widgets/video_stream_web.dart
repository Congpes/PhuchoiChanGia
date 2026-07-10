import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';

Widget createVideoStreamWidget(String url) {
  final viewType = 'mjpeg-stream-${url.hashCode}';
  ui_web.platformViewRegistry.registerViewFactory(
    viewType,
    (int viewId) => html.ImageElement()
      ..src = url
      ..style.width = '100%'
      ..style.height = '100%'
      ..style.border = 'none'
      ..style.objectFit = 'contain',
  );
  return HtmlElementView(viewType: viewType);
}
