enum LegSide { left, right }

enum SessionPhase { setup, baseline, scan1, analyze, adjust, scan2, report }


class GaitCycleCurve {
  const GaitCycleCurve({
    required this.label,
    required this.angles,
    this.colorHex,
  });

  final String label;
  final List<double> angles;
  final int? colorHex;

  double get maxAngle =>
      angles.isEmpty ? 0 : angles.reduce((a, b) => a > b ? a : b);

  double get minAngle =>
      angles.isEmpty ? 0 : angles.reduce((a, b) => a < b ? a : b);
}

class ScanResult {
  const ScanResult({
    required this.id,
    required this.label,
    required this.durationSec,
    required this.leftKnee,
    required this.rightKnee,
    required this.leftAnkle,
    required this.rightAnkle,
    required this.leftHip,
    required this.rightHip,
    this.pelvicTilt,
    this.cadence,
    this.strideLength,
    this.actualAdjustmentDegrees = 0.0,
    this.actualAdjustmentNotes = '',
    this.recordedAt,
    this.plantarLoadSymmetry,
    this.copTrajectory = const [],
    this.fatigueFlag = 0,
    this.fatigueSlope = 0.0,
    this.segmentId,
  });

  final String id;
  final String label;
  final double durationSec;
  final GaitCycleCurve leftKnee;
  final GaitCycleCurve rightKnee;
  final GaitCycleCurve leftAnkle;
  final GaitCycleCurve rightAnkle;
  final GaitCycleCurve leftHip;
  final GaitCycleCurve rightHip;
  final GaitCycleCurve? pelvicTilt;
  final double? cadence;
  final double? strideLength;
  final double actualAdjustmentDegrees;
  final String actualAdjustmentNotes;
  final DateTime? recordedAt;
  final double? plantarLoadSymmetry;
  final List<dynamic> copTrajectory; // list of dicts/maps
  final int fatigueFlag;
  final double fatigueSlope;
  final String? segmentId;

  ScanResult copyWith({
    String? id,
    String? label,
    double? durationSec,
    GaitCycleCurve? leftKnee,
    GaitCycleCurve? rightKnee,
    GaitCycleCurve? leftAnkle,
    GaitCycleCurve? rightAnkle,
    GaitCycleCurve? leftHip,
    GaitCycleCurve? rightHip,
    GaitCycleCurve? pelvicTilt,
    double? cadence,
    double? strideLength,
    double? actualAdjustmentDegrees,
    String? actualAdjustmentNotes,
    DateTime? recordedAt,
    double? plantarLoadSymmetry,
    List<dynamic>? copTrajectory,
    int? fatigueFlag,
    double? fatigueSlope,
    String? segmentId,
  }) {
    return ScanResult(
      id: id ?? this.id,
      label: label ?? this.label,
      durationSec: durationSec ?? this.durationSec,
      leftKnee: leftKnee ?? this.leftKnee,
      rightKnee: rightKnee ?? this.rightKnee,
      leftAnkle: leftAnkle ?? this.leftAnkle,
      rightAnkle: rightAnkle ?? this.rightAnkle,
      leftHip: leftHip ?? this.leftHip,
      rightHip: rightHip ?? this.rightHip,
      pelvicTilt: pelvicTilt ?? this.pelvicTilt,
      cadence: cadence ?? this.cadence,
      strideLength: strideLength ?? this.strideLength,
      actualAdjustmentDegrees: actualAdjustmentDegrees ?? this.actualAdjustmentDegrees,
      actualAdjustmentNotes: actualAdjustmentNotes ?? this.actualAdjustmentNotes,
      recordedAt: recordedAt ?? this.recordedAt,
      plantarLoadSymmetry: plantarLoadSymmetry ?? this.plantarLoadSymmetry,
      copTrajectory: copTrajectory ?? this.copTrajectory,
      fatigueFlag: fatigueFlag ?? this.fatigueFlag,
      fatigueSlope: fatigueSlope ?? this.fatigueSlope,
      segmentId: segmentId ?? this.segmentId,
    );
  }
}

class AdjustmentRecommendation {
  const AdjustmentRecommendation({
    required this.leg,
    required this.issue,
    required this.deltaDegrees,
    required this.suggestion,
    this.severity = RecommendationSeverity.warning,
  });

  final LegSide leg;
  final String issue;
  final double deltaDegrees;
  final String suggestion;
  final RecommendationSeverity severity;
}

enum RecommendationSeverity { info, warning, critical }

class ClinicalNote {
  const ClinicalNote({
    required this.id,
    required this.patientId,
    required this.sessionId,
    this.pinnedScanId,
    required this.noteType,
    required this.content,
    required this.createdAt,
  });

  final String id;
  final String patientId;
  final String sessionId;
  final String? pinnedScanId;
  final String noteType; // 'history' or 'symptom'
  final String content;
  final DateTime createdAt;
}

class GaitSession {
  GaitSession({
    this.id = '',
    DateTime? createdAt,
    this.phase = SessionPhase.setup,
    this.baseline,
    List<ScanResult>? scans,
    this.recommendations = const [],
    this.isRecording = false,
    this.recordingElapsedSec = 0,
    this.playbackSec = 0,
    this.isPracticeMode = false,
  })  : createdAt = createdAt ?? DateTime.now(),
        scans = scans ?? [];

  final String id;
  final DateTime createdAt;
  SessionPhase phase;
  ScanResult? baseline;
  List<ScanResult> scans;
  List<AdjustmentRecommendation> recommendations;
  bool isRecording;
  double recordingElapsedSec;
  double playbackSec;
  bool isPracticeMode;

  // Backward compatibility getters
  ScanResult? get scan1 => scans.isNotEmpty ? scans.first : null;
  ScanResult? get scan2 => scans.length > 1 ? scans[1] : null;

  ScanResult? get activeScan {
    switch (phase) {
      case SessionPhase.baseline:
        return baseline;
      case SessionPhase.scan1:
      case SessionPhase.analyze:
      case SessionPhase.adjust:
        return scan1;
      case SessionPhase.scan2:
      case SessionPhase.report:
        return scan2 ?? scan1;
      default:
        return scan1 ?? baseline;
    }
  }

  GaitSession copyWith({
    String? id,
    DateTime? createdAt,
    SessionPhase? phase,
    ScanResult? baseline,
    List<ScanResult>? scans,
    List<AdjustmentRecommendation>? recommendations,
    bool? isRecording,
    double? recordingElapsedSec,
    double? playbackSec,
    bool? isPracticeMode,
  }) {
    return GaitSession(
      id: id ?? this.id,
      createdAt: createdAt ?? this.createdAt,
      phase: phase ?? this.phase,
      baseline: baseline ?? this.baseline,
      scans: scans ?? this.scans,
      recommendations: recommendations ?? this.recommendations,
      isRecording: isRecording ?? this.isRecording,
      recordingElapsedSec: recordingElapsedSec ?? this.recordingElapsedSec,
      playbackSec: playbackSec ?? this.playbackSec,
      isPracticeMode: isPracticeMode ?? this.isPracticeMode,
    );
  }
}

class Patient {
  Patient({
    required this.id,
    required this.name,
    required this.age,
    required this.heightCm,
    required this.weightKg,
    required this.healthyLeg,
    required this.prostheticLeg,
    this.injuryHistory = '',
    this.treatmentGoals = '',
    this.clinicalNotes = const [],
    List<GaitSession>? sessions,
  }) : sessions = sessions ?? [];

  final String id;
  final String name;
  final int age;
  final double heightCm;
  final double weightKg;
  final LegSide healthyLeg;
  final LegSide prostheticLeg;
  final String injuryHistory;
  final String treatmentGoals;
  final List<ClinicalNote> clinicalNotes;
  final List<GaitSession> sessions;

  Patient copyWith({
    String? id,
    String? name,
    int? age,
    double? heightCm,
    double? weightKg,
    LegSide? healthyLeg,
    LegSide? prostheticLeg,
    String? injuryHistory,
    String? treatmentGoals,
    List<ClinicalNote>? clinicalNotes,
    List<GaitSession>? sessions,
  }) {
    return Patient(
      id: id ?? this.id,
      name: name ?? this.name,
      age: age ?? this.age,
      heightCm: heightCm ?? this.heightCm,
      weightKg: weightKg ?? this.weightKg,
      healthyLeg: healthyLeg ?? this.healthyLeg,
      prostheticLeg: prostheticLeg ?? this.prostheticLeg,
      injuryHistory: injuryHistory ?? this.injuryHistory,
      treatmentGoals: treatmentGoals ?? this.treatmentGoals,
      clinicalNotes: clinicalNotes ?? this.clinicalNotes,
      sessions: sessions ?? this.sessions,
    );
  }
}
