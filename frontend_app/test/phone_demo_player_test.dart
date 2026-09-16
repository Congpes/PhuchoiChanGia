import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_progait/widgets/phone_demo_player.dart';

void main() {
  testWidgets('Phone demos expose both views and do not claim measured FSR',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
      body: PhoneDemoPlayer(key: ValueKey('phone-01'), demoId: 'phone-01'),
    )));
    expect(find.text('CHÍNH DIỆN'), findsOneWidget);
    expect(find.text('MẶT PHẲNG DỌC'), findsOneWidget);
    expect(find.textContaining('chưa xác nhận đồng bộ'), findsOneWidget);
    expect(find.textContaining('chưa có dữ liệu FSR'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
      body: PhoneDemoPlayer(key: ValueKey('phone-02'), demoId: 'phone-02'),
    )));
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
