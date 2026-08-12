import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/gait_data.dart';
import '../config/measurement_config.dart';
import '../services/gait_analysis_service.dart';

class SessionProvider extends ChangeNotifier {
  SessionProvider({GaitAnalysisService? gaitAnalysisService})
      : _gaitAnalysisService =
            gaitAnalysisService ?? const GaitAnalysisService() {
    fetchPatients();
  }

  final GaitAnalysisService _gaitAnalysisService;
  List<Patient> _patients = [];
  Patient? _activePatient;
  GaitSession? _activeSession;
  int _activeTabIndex = 0;
  bool _isLoading = false;
  Timer? _recordTimer;

  List<Patient> get patients => _patients;
  Patient? get activePatient => _activePatient;
  GaitSession? get activeSession => _activeSession;
  int get activeTabIndex => _activeTabIndex;
  bool get isLoading => _isLoading;

  // Backward compatible getter for existing widgets
  GaitSession get session => _activeSession ?? GaitSession();

  void setTabIndex(int index) {
    _activeTabIndex = index;
    notifyListeners();
  }

  void setPhase(SessionPhase phase) {
    if (_activeSession != null) {
      _activeSession!.phase = phase;
      notifyListeners();
    }
  }

  void setPlaybackSec(double sec) {
    if (_activeSession != null) {
      _activeSession!.playbackSec = sec < 0 ? 0 : sec;
      notifyListeners();
    }
  }

  Future<void> fetchPatients() async {
    _isLoading = true;
    notifyListeners();
    try {
      final response =
          await http.get(Uri.parse('http://localhost:8000/patients')).timeout(
                const Duration(seconds: 4),
              );
      if (response.statusCode == 200) {
        final list = jsonDecode(response.body) as List;
        _patients = list.map((x) => _parsePatient(x)).toList();
        if (_patients.isNotEmpty) {
          if (_activePatient != null) {
            final index =
                _patients.indexWhere((p) => p.id == _activePatient!.id);
            if (index != -1) {
              _activePatient = _patients[index];
              if (_activePatient!.sessions.isNotEmpty) {
                if (_activeSession != null) {
                  final sIndex = _activePatient!.sessions
                      .indexWhere((s) => s.id == _activeSession!.id);
                  _activeSession = sIndex != -1
                      ? _activePatient!.sessions[sIndex]
                      : _activePatient!.sessions.last;
                } else {
                  _activeSession = _activePatient!.sessions.last;
                }
              } else {
                _activeSession = null;
              }
            } else {
              _activePatient = null;
              _activeSession = null;
            }
          } else {
            _activePatient = null;
            _activeSession = null;
          }
        }
      }
    } catch (e) {
      debugPrint('Error fetching patients: $e');
    }
    _isLoading = false;
    notifyListeners();
  }

  Patient _parsePatient(Map<String, dynamic> json) {
    final sessionsList = json['sessions'] as List? ?? [];
    final notesList = json['clinicalNotes'] as List? ?? [];
    return Patient(
      id: json['id'] ?? '',
      name: json['name'] ?? '',
      age: json['age'] ?? 30,
      heightCm: (json['heightCm'] as num?)?.toDouble() ?? 170.0,
      weightKg: (json['weightKg'] as num?)?.toDouble() ?? 60.0,
      healthyLeg: json['healthyLeg'] == 'LEFT' ? LegSide.left : LegSide.right,
      prostheticLeg:
          json['prostheticLeg'] == 'LEFT' ? LegSide.left : LegSide.right,
      injuryHistory: json['injuryHistory'] ?? '',
      treatmentGoals: json['treatmentGoals'] ?? '',
      clinicalNotes: notesList.map((x) => _parseNote(x)).toList(),
      sessions: sessionsList.map((x) => _parseSession(x)).toList(),
    );
  }

  ClinicalNote _parseNote(Map<String, dynamic> json) {
    return ClinicalNote(
      id: json['id'] ?? '',
      patientId: json['patientId'] ?? '',
      sessionId: json['sessionId'] ?? '',
      pinnedScanId: json['pinnedScanId'],
      noteType: json['noteType'] ?? 'history',
      content: json['content'] ?? '',
      createdAt:
          DateTime.parse(json['createdAt'] ?? DateTime.now().toIso8601String()),
    );
  }

  GaitSession _parseSession(Map<String, dynamic> json) {
    final scansList = json['scans'] as List? ?? [];
    return GaitSession(
      id: json['id'] ?? '',
      createdAt:
          DateTime.parse(json['createdAt'] ?? DateTime.now().toIso8601String()),
      phase: SessionPhase.analyze,
      isPracticeMode:
          json['isPracticeMode'] == 1 || json['isPracticeMode'] == true,
      baseline: json['baseline'] != null
          ? _parseScan(json['baseline'], 'baseline')
          : null,
      scans: scansList.map((x) => _parseScan(x, x['scanId'] ?? '')).toList(),
    );
  }

  ScanResult _parseScan(Map<String, dynamic> json, String id) {
    return ScanResult(
      id: id,
      label: json['label'] ?? '',
      durationSec: (json['durationSec'] as num?)?.toDouble() ??
          MeasurementConfig.recordingDurationSec,
      leftKnee: GaitCycleCurve(
        label: 'Gối trái',
        angles: List<double>.from((json['leftKnee'] as List? ?? [])
            .map((x) => (x as num).toDouble())),
      ),
      rightKnee: GaitCycleCurve(
        label: 'Gối phải',
        angles: List<double>.from((json['rightKnee'] as List? ?? [])
            .map((x) => (x as num).toDouble())),
      ),
      leftAnkle: GaitCycleCurve(
        label: 'Cổ chân trái',
        angles: List<double>.from((json['leftAnkle'] as List? ?? [])
            .map((x) => (x as num).toDouble())),
      ),
      rightAnkle: GaitCycleCurve(
        label: 'Cổ chân phải',
        angles: List<double>.from((json['rightAnkle'] as List? ?? [])
            .map((x) => (x as num).toDouble())),
      ),
      leftHip: GaitCycleCurve(
        label: 'Hông trái',
        angles: List<double>.from(
            (json['leftHip'] as List? ?? []).map((x) => (x as num).toDouble())),
      ),
      rightHip: GaitCycleCurve(
        label: 'Hông phải',
        angles: List<double>.from((json['rightHip'] as List? ?? [])
            .map((x) => (x as num).toDouble())),
      ),
      pelvicTilt:
          json['pelvicTilt'] != null && (json['pelvicTilt'] as List).isNotEmpty
              ? GaitCycleCurve(
                  label: 'Nghiêng hông',
                  angles: List<double>.from((json['pelvicTilt'] as List)
                      .map((x) => (x as num).toDouble())),
                )
              : null,
      cadence: (json['cadence'] as num?)?.toDouble(),
      strideLength: (json['strideLength'] as num?)?.toDouble(),
      actualAdjustmentDegrees:
          (json['actualAdjustmentDegrees'] as num?)?.toDouble() ?? 0.0,
      actualAdjustmentNotes: json['actualAdjustmentNotes'] ?? '',
      recordedAt: json['recordedAt'] != null
          ? DateTime.parse(json['recordedAt'])
          : null,
      plantarLoadSymmetry: (json['plantarLoadSymmetry'] as num?)?.toDouble(),
      copTrajectory: json['copTrajectory'] as List? ?? const [],
      fatigueFlag: json['fatigueFlag'] ?? 0,
      fatigueSlope: (json['fatigueSlope'] as num?)?.toDouble() ?? 0.0,
      segmentId: json['segmentId'],
    );
  }

  Future<void> createPatient(String name, int age, double height, double weight,
      LegSide healthy, LegSide prosthetic,
      {String injuryHistory = '', String treatmentGoals = ''}) async {
    _isLoading = true;
    notifyListeners();
    try {
      final body = {
        "name": name,
        "age": age,
        "heightCm": height,
        "weightKg": weight,
        "healthyLeg": healthy == LegSide.left ? "LEFT" : "RIGHT",
        "prostheticLeg": prosthetic == LegSide.left ? "LEFT" : "RIGHT",
        "injuryHistory": injuryHistory,
        "treatmentGoals": treatmentGoals
      };
      final response = await http
          .post(
            Uri.parse('http://localhost:8000/patients'),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final newP = _parsePatient(jsonDecode(response.body));
        _patients.add(newP);
        _activePatient = newP;
        _activeSession = null;
      } else {
        throw Exception("Server phản hồi mã lỗi: ${response.statusCode}");
      }
    } catch (e) {
      debugPrint('Error creating patient: $e');
      _isLoading = false;
      notifyListeners();
      rethrow;
    }
    _isLoading = false;
    notifyListeners();
  }

  Future<void> updatePatientDetails(
      String patientId,
      String name,
      int age,
      double height,
      double weight,
      LegSide healthy,
      LegSide prosthetic,
      String injuryHistory,
      String treatmentGoals) async {
    _isLoading = true;
    notifyListeners();
    try {
      final body = {
        "name": name,
        "age": age,
        "heightCm": height,
        "weightKg": weight,
        "healthyLeg": healthy == LegSide.left ? "LEFT" : "RIGHT",
        "prostheticLeg": prosthetic == LegSide.left ? "LEFT" : "RIGHT",
        "injuryHistory": injuryHistory,
        "treatmentGoals": treatmentGoals
      };
      final response = await http
          .put(
            Uri.parse('http://localhost:8000/patients/$patientId'),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        await fetchPatients();
      } else {
        throw Exception("Server phản hồi mã lỗi: ${response.statusCode}");
      }
    } catch (e) {
      debugPrint('Error updating patient: $e');
    }
    _isLoading = false;
    notifyListeners();
  }

  Future<void> startNewSession({bool isPracticeMode = false}) async {
    if (_activePatient == null) return;
    _isLoading = true;
    notifyListeners();
    try {
      final body = {"isPracticeMode": isPracticeMode};
      final response = await http
          .post(
              Uri.parse(
                  'http://localhost:8000/patients/${_activePatient!.id}/sessions'),
              headers: {"Content-Type": "application/json"},
              body: jsonEncode(body))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final newS = _parseSession(jsonDecode(response.body));
        _activePatient!.sessions.add(newS);
        _activeSession = newS;
        _activeSession!.phase = SessionPhase.baseline; // default tab 2 mode
        _activeTabIndex = 1; // switch to Tab 2
      } else {
        throw Exception("Server phản hồi mã lỗi: ${response.statusCode}");
      }
    } catch (e) {
      debugPrint('Error starting session: $e');
      _isLoading = false;
      notifyListeners();
      rethrow;
    }
    _isLoading = false;
    notifyListeners();
  }

  void selectPatient(Patient patient) {
    _activePatient = patient;
    if (_activePatient!.sessions.isNotEmpty) {
      _activeSession = _activePatient!.sessions.last;
    } else {
      _activeSession = null;
    }
    notifyListeners();
  }

  void selectSession(GaitSession session) {
    _activeSession = session;
    notifyListeners();
  }

  void startRecording() {
    final s = _activeSession;
    if (s == null || s.isRecording || _activePatient == null) return;

    s.isRecording = true;
    s.recordingElapsedSec = 0;

    final healthyStr = _activePatient!.healthyLeg.name.toUpperCase();
    final prostheticStr = _activePatient!.prostheticLeg.name.toUpperCase();

    String scanType = "baseline";
    if (s.phase != SessionPhase.baseline) {
      scanType = "scan_${s.scans.length + 1}";
    }

    http
        .post(Uri.parse(
            'http://localhost:8000/start_recording?session_id=${s.id}&scan_type=$scanType&duration=${MeasurementConfig.recordingDurationSec}&healthy=$healthyStr&prosthetic=$prostheticStr'))
        .catchError((e) {
      debugPrint('Error starting backend recording: $e');
      return http.Response('Error', 500);
    });

    _recordTimer?.cancel();
    _recordTimer = Timer.periodic(const Duration(milliseconds: 100), (timer) {
      s.recordingElapsedSec += 0.1;
      s.playbackSec = s.recordingElapsedSec;
      notifyListeners();
    });
    notifyListeners();
  }

  Future<void> stopRecording() async {
    final s = _activeSession;
    if (s == null || !s.isRecording) return;

    _recordTimer?.cancel();
    _recordTimer = null;
    s.isRecording = false;
    notifyListeners();

    _isLoading = true;
    notifyListeners();

    try {
      // Call backend stop recording to trigger save of default segment
      await http.post(Uri.parse('http://localhost:8000/stop_recording'));
      await Future.delayed(const Duration(milliseconds: 1200));
      await fetchPatients();
      if (_activePatient != null) {
        _activePatient = _patients.firstWhere((p) => p.id == _activePatient!.id,
            orElse: () => _activePatient!);
        if (_activeSession != null) {
          _activeSession = _activePatient!.sessions.firstWhere(
              (se) => se.id == _activeSession!.id,
              orElse: () => _activeSession!);
        }
      }
    } catch (e) {
      debugPrint('Error re-fetching patients: $e');
    }

    _isLoading = false;

    if (s.phase == SessionPhase.baseline) {
      s.phase = SessionPhase.scan1;
      _activeTabIndex =
          3; // Analysis tab showing baseline (Tab 4 in 8-tab system)
    } else {
      s.phase = SessionPhase.analyze;
      _activeTabIndex = 3; // Analysis tab showing results
      if (_activeSession != null &&
          _activeSession!.baseline != null &&
          _activeSession!.scans.isNotEmpty) {
        _activeSession!.recommendations = _gaitAnalysisService.analyze(
          baseline: _activeSession!.baseline,
          scan: _activeSession!.scans.last,
          healthyLeg: _activePatient!.healthyLeg,
          prostheticLeg: _activePatient!.prostheticLeg,
        );
      }
    }

    notifyListeners();
  }

  Future<void> addMarker(String sessionId,
      {double? offset, String note = "Đánh dấu của Bác sĩ"}) async {
    try {
      final body = {"offset": offset, "note": note};
      await http.post(
        Uri.parse('http://localhost:8000/sessions/$sessionId/markers'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(body),
      );
    } catch (e) {
      debugPrint('Error creating marker: $e');
    }
  }

  Future<void> createSegmentAndScan(String sessionId, double startSec,
      double endSec, String scanType, String note) async {
    _isLoading = true;
    notifyListeners();
    try {
      final body = {
        "startOffsetSec": startSec,
        "endOffsetSec": endSec,
        "scanType": scanType,
        "note": note
      };
      final response = await http.post(
        Uri.parse('http://localhost:8000/sessions/$sessionId/segments'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(body),
      );
      if (response.statusCode == 200) {
        await fetchPatients();
        if (_activePatient != null) {
          _activePatient = _patients.firstWhere(
              (p) => p.id == _activePatient!.id,
              orElse: () => _activePatient!);
          _activeSession = _activePatient!.sessions.firstWhere(
              (se) => se.id == _activeSession!.id,
              orElse: () => _activeSession!);
        }
      }
    } catch (e) {
      debugPrint('Error creating segment: $e');
    }
    _isLoading = false;
    notifyListeners();
  }

  Future<void> createClinicalNote(String noteType, String content,
      {String? pinnedScanId}) async {
    final p = _activePatient;
    final s = _activeSession;
    if (p == null || s == null) return;

    _isLoading = true;
    notifyListeners();
    try {
      final body = {
        "sessionId": s.id,
        "noteType": noteType,
        "content": content,
        "pinnedScanId": pinnedScanId
      };
      final response = await http.post(
        Uri.parse('http://localhost:8000/patients/${p.id}/notes'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(body),
      );
      if (response.statusCode == 200) {
        await fetchPatients();
        if (_activePatient != null) {
          _activePatient = _patients.firstWhere(
              (p) => p.id == _activePatient!.id,
              orElse: () => _activePatient!);
        }
      }
    } catch (e) {
      debugPrint('Error creating note: $e');
    }
    _isLoading = false;
    notifyListeners();
  }

  Future<void> saveActualAdjustment(double degrees, String notes) async {
    final s = _activeSession;
    if (s == null || s.scans.isEmpty) return;

    _isLoading = true;
    notifyListeners();

    final activeScan = s.scans.last;
    try {
      final body = {"degrees": degrees, "notes": notes};
      final response = await http.post(
        Uri.parse(
            'http://localhost:8000/scans/${s.id}/${activeScan.id}/adjustment'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(body),
      );
      if (response.statusCode == 200) {
        await fetchPatients();
        if (_activePatient != null) {
          _activePatient = _patients.firstWhere(
              (p) => p.id == _activePatient!.id,
              orElse: () => _activePatient!);
          if (_activeSession != null) {
            _activeSession = _activePatient!.sessions.firstWhere(
                (se) => se.id == _activeSession!.id,
                orElse: () => _activeSession!);
          }
        }
      }
    } catch (e) {
      debugPrint('Error saving adjustment: $e');
    }
    _isLoading = false;
    notifyListeners();
  }

  void startRescan() {
    final s = _activeSession;
    if (s == null) return;
    s.phase = SessionPhase.scan2;
    s.recordingElapsedSec = 0;
    _activeTabIndex = 2; // Tab 3: Scan (Giao diện 8-tab)
    notifyListeners();
  }

  void resetSession() {
    _recordTimer?.cancel();
    if (_activePatient != null) {
      startNewSession();
    }
    notifyListeners();
  }

  String? get comparisonSummary {
    final s = _activeSession;
    if (s == null || s.scans.length < 2) return null;
    return _gaitAnalysisService.compareScans(
      s.scans.first,
      s.scans.last,
      _activePatient!.prostheticLeg,
    );
  }

  Future<String?> startContinuousRecording() async {
    final s = _activeSession;
    final patient = _activePatient;
    if (s == null || patient == null || s.isRecording) return null;
    try {
      final response = await http.post(Uri.parse(
        'http://127.0.0.1:8000/recording/start?session_id=${s.id}'
        '&healthy=${patient.healthyLeg.name.toUpperCase()}'
        '&prosthetic=${patient.prostheticLeg.name.toUpperCase()}',
      ));
      if (response.statusCode != 200) {
        return 'Kh\u00f4ng th\u1ec3 b\u1eaft \u0111\u1ea7u ghi: ${response.body}';
      }
      s.isRecording = true;
      s.recordingElapsedSec = 0;
      s.playbackSec = 0;
      _recordTimer?.cancel();
      _recordTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
        s.recordingElapsedSec += 0.1;
        s.playbackSec = s.recordingElapsedSec;
        notifyListeners();
      });
      notifyListeners();
      return null;
    } catch (error) {
      return 'Kh\u00f4ng nh\u1eadn \u0111\u01b0\u1ee3c ph\u1ea3n h\u1ed3i backend. H\u00e3y kh\u1edfi \u0111\u1ed9ng l\u1ea1i backend.';
    }
  }

  Future<String?> stopContinuousRecording() async {
    final s = _activeSession;
    if (s == null || !s.isRecording) return null;
    final sessionId = s.id;
    final elapsed = s.recordingElapsedSec;
    _recordTimer?.cancel();
    _recordTimer = null;
    s.isRecording = false;
    notifyListeners();
    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:8000/recording/stop'),
      );
      if (response.statusCode != 200) {
        return 'Kh\u00f4ng th\u1ec3 d\u1eebng ghi: ${response.body}';
      }
      await fetchPatients();
      final refreshedPatient =
          _patients.where((p) => p.id == _activePatient?.id).firstOrNull;
      if (refreshedPatient != null) {
        _activePatient = refreshedPatient;
        final refreshedSession = refreshedPatient.sessions
            .where((item) => item.id == sessionId)
            .firstOrNull;
        if (refreshedSession != null) {
          _activeSession = refreshedSession;
          refreshedSession.recordingElapsedSec = elapsed;
          refreshedSession.playbackSec = elapsed;
        }
      }
      notifyListeners();
      return null;
    } catch (error) {
      return 'Kh\u00f4ng nh\u1eadn \u0111\u01b0\u1ee3c ph\u1ea3n h\u1ed3i backend. H\u00e3y kh\u1edfi \u0111\u1ed9ng l\u1ea1i backend.';
    }
  }

  Future<String?> createVirtualSegment(
    double startSec,
    double endSec,
    String note,
  ) async {
    final s = _activeSession;
    if (s == null) return 'Ch\u01b0a c\u00f3 phi\u00ean \u0111o.';
    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:8000/segments-v2/${s.id}'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'startOffsetSec': startSec,
          'endOffsetSec': endSec,
          'scanType': 'segment',
          'note': note,
        }),
      );
      if (response.statusCode != 200) {
        try {
          final body = jsonDecode(response.body);
          return body['detail']?.toString() ??
              'Kh\u00f4ng l\u01b0u \u0111\u01b0\u1ee3c \u0111o\u1ea1n ph\u00e2n t\u00edch.';
        } catch (_) {
          return 'Kh\u00f4ng l\u01b0u \u0111\u01b0\u1ee3c \u0111o\u1ea1n ph\u00e2n t\u00edch.';
        }
      }
      return null;
    } catch (error) {
      return 'Kh\u00f4ng nh\u1eadn \u0111\u01b0\u1ee3c ph\u1ea3n h\u1ed3i backend. H\u00e3y kh\u1edfi \u0111\u1ed9ng l\u1ea1i backend.';
    }
  }

  @override
  void dispose() {
    _recordTimer?.cancel();
    super.dispose();
  }
}
