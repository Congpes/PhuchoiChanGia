import 'package:flutter_test/flutter_test.dart';

import 'package:ai_progait/widgets/pose_replay_overlay.dart';

void main() {
  test('pose skeleton keeps side colors when confidence is low', () {
    final leftHigh = poseSkeletonVisualStyleFor(
      start: 'left_knee',
      end: 'left_ankle',
      visibility: 0.95,
    );
    final leftLow = poseSkeletonVisualStyleFor(
      start: 'left_knee',
      end: 'left_ankle',
      visibility: 0.45,
    );
    final rightLow = poseSkeletonVisualStyleFor(
      start: 'right_knee',
      end: 'right_ankle',
      visibility: 0.45,
    );

    expect(leftLow.color, leftHigh.color);
    expect(rightLow.color, isNot(leftLow.color));
    expect(leftLow.opacity, lessThan(leftHigh.opacity));
    expect(leftLow.strokeScale, lessThan(leftHigh.strokeScale));
  });
}
