import 'package:flutter/material.dart';

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
