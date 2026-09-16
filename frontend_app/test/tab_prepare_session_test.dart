import 'dart:convert';

import 'package:ai_progait/l10n/app_language.dart';
import 'package:ai_progait/models/gait_data.dart';
import 'package:ai_progait/providers/session_provider.dart';
import 'package:ai_progait/widgets/tab_prepare_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('hidden preparation tab stops both raw camera streams',
      (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final cameraStatus = jsonEncode({
      'backendOnline': true,
      'camera0': {
        'connected': true,
        'poseDetected': true,
        'captureFps': 20,
        'poseFps': 10,
        'reliablePoseFps': 8,
        'poseDetectionRate': 1,
        'reliablePoseRate': 1,
        'imageQuality': {'qualityReady': true, 'qualityReasons': <String>[]},
      },
      'camera1': {
        'connected': true,
        'poseDetected': true,
        'captureFps': 20,
        'poseFps': 10,
        'reliablePoseFps': 8,
        'poseDetectionRate': 1,
        'reliablePoseRate': 1,
        'imageQuality': {'qualityReady': true, 'qualityReasons': <String>[]},
      },
      'configuration': {'singleCameraMode': false},
      'synchronization': {
        'synchronized': true,
        'recentPairedSamples': 10,
        'recentFallbackSamples': 0,
      },
    });

    await http.runWithClient(() async {
      final provider = SessionProvider();
      final languageController = AppLanguageController();
      addTearDown(provider.dispose);
      addTearDown(languageController.dispose);
      await Future<void>.value();
      provider.selectPatient(
        Patient(
          id: 'patient-test',
          name: 'Người thử',
          age: 30,
          heightCm: 170,
          weightKg: 60,
          healthyLeg: LegSide.left,
          prostheticLeg: LegSide.right,
          sessions: [GaitSession(id: 'session-test')],
        ),
      );
      provider.setTabIndex(1);

      await tester.pumpWidget(
        AppLanguageScope(
          controller: languageController,
          child: ChangeNotifierProvider.value(
            value: provider,
            child: const MaterialApp(
              home: Scaffold(body: TabPrepareSession()),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 20));

      Finder rawStreams() => find.byWidgetPredicate(
            (widget) =>
                widget is Image &&
                widget.image is NetworkImage &&
                ((widget.image as NetworkImage).url.contains('raw=true')),
          );
      expect(rawStreams(), findsNWidgets(2));

      provider.setTabIndex(2);
      await tester.pump();

      expect(rawStreams(), findsNothing);

      await tester.pumpWidget(const SizedBox.shrink());
    }, () {
      return MockClient((request) async {
        switch (request.url.path) {
          case '/patients':
            return http.Response('[]', 200);
          case '/camera-status':
            return http.Response(cameraStatus, 200);
          case '/fsr/latest':
            return http.Response(
              jsonEncode({
                'left': null,
                'right': null,
                'serialStatus': {
                  'ports': <String>[],
                  'connectedPorts': <String>[],
                  'lastError': '',
                },
              }),
              200,
            );
          default:
            return http.Response('{}', 404);
        }
      });
    });
  });
}
