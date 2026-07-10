import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/gait_data.dart';
import '../services/mock_gait_service.dart';

class SessionProvider extends ChangeNotifier {
  SessionProvider({MockGaitService? gaitService})
      : _gaitService = gaitService ?? MockGaitService() {
    fetchPatients();
  }

  final MockGaitService _gaitService;
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
      _activeSession!.playbackSec = sec.clamp(0, MockGaitService.recordDurationSec);
      notifyListeners();
    }
  }

  Future<void> fetchPatients() async {
    _isLoading = true;
    notifyListeners();
    try {
      final response = await http.get(Uri.parse('http://localhost:8000/patients')).timeout(
        const Duration(seconds: 4),
      );
      if (response.statusCode == 200) {
        final list = jsonDecode(response.body) as List;
        _patients = list.map((x) => _parsePatient(x)).toList();
        if (_patients.isNotEmpty) {
          if (_activePatient != null) {
            _activePatient = _patients.firstWhere((p) => p.id == _activePatient!.id, orElse: () => _patients.first);
          } else {
            _activePatient = _patients.first;
          }
          if (_activePatient!.sessions.isNotEmpty) {
            _activeSession = _activePatient!.sessions.last;
          } else {
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
    return Patient(
      id: json['id'] ?? '',
      name: json['name'] ?? '',
      age: json['age'] ?? 30,
      heightCm: (json['heightCm'] as num?)?.toDouble() ?? 170.0,
      weightKg: (json['weightKg'] as num?)?.toDouble() ?? 60.0,
      healthyLeg: json['healthyLeg'] == 'LEFT' ? LegSide.left : LegSide.right,
      prostheticLeg: json['prostheticLeg'] == 'LEFT' ? ProstheticSide.left : ProstheticSide.right,
      sessions: sessionsList.map((x) => _parseSession(x)).toList(),
    );
  }

  GaitSession _parseSession(Map<String, dynamic> json) {
    final scansList = json['scans'] as List? ?? [];
    return GaitSession(
      id: json['id'] ?? '',
      createdAt: DateTime.parse(json['createdAt'] ?? DateTime.now().toIso8601String()),
      phase: SessionPhase.analyze,
      baseline: json['baseline'] != null ? _parseScan(json['baseline'], 'baseline') : null,
      scans: scansList.map((x) => _parseScan(x, x['scanId'] ?? '')).toList(),
    );
  }

  ScanResult _parseScan(Map<String, dynamic> json, String id) {
    return ScanResult(
      id: id,
      label: json['label'] ?? '',
      durationSec: (json['durationSec'] as num?)?.toDouble() ?? MockGaitService.recordDurationSec,
      leftKnee: GaitCycleCurve(
        label: 'Gối trái',
        angles: List<double>.from((json['leftKnee'] as List? ?? []).map((x) => (x as num).toDouble())),
      ),
      rightKnee: GaitCycleCurve(
        label: 'Gối phải',
        angles: List<double>.from((json['rightKnee'] as List? ?? []).map((x) => (x as num).toDouble())),
      ),
      leftAnkle: GaitCycleCurve(
        label: 'Cổ chân trái',
        angles: List<double>.from((json['leftAnkle'] as List? ?? []).map((x) => (x as num).toDouble())),
      ),
      rightAnkle: GaitCycleCurve(
        label: 'Cổ chân phải',
        angles: List<double>.from((json['rightAnkle'] as List? ?? []).map((x) => (x as num).toDouble())),
      ),
      pelvicTilt: json['pelvicTilt'] != null && (json['pelvicTilt'] as List).isNotEmpty
          ? GaitCycleCurve(
              label: 'Nghiêng hông',
              angles: List<double>.from((json['pelvicTilt'] as List).map((x) => (x as num).toDouble())),
            )
          : null,
      cadence: (json['cadence'] as num?)?.toDouble(),
      strideLength: (json['strideLength'] as num?)?.toDouble(),
      actualAdjustmentDegrees: (json['actualAdjustmentDegrees'] as num?)?.toDouble() ?? 0.0,
      actualAdjustmentNotes: json['actualAdjustmentNotes'] ?? '',
      recordedAt: json['recordedAt'] != null ? DateTime.parse(json['recordedAt']) : null,
    );
  }

  Future<void> createPatient(String name, int age, double height, double weight, LegSide healthy, ProstheticSide prosthetic) async {
    _isLoading = true;
    notifyListeners();
    try {
      final body = {
        "name": name,
        "age": age,
        "heightCm": height,
        "weightKg": weight,
        "healthyLeg": healthy == LegSide.left ? "LEFT" : "RIGHT",
        "prostheticLeg": prosthetic == ProstheticSide.left ? "LEFT" : "RIGHT"
      };
      final response = await http.post(
        Uri.parse('http://localhost:8000/patients'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(body),
      );
      if (response.statusCode == 200) {
        final newP = _parsePatient(jsonDecode(response.body));
        _patients.add(newP);
        _activePatient = newP;
        _activeSession = null;
      }
    } catch (e) {
      debugPrint('Error creating patient: $e');
    }
    _isLoading = false;
    notifyListeners();
  }

  Future<void> startNewSession() async {
    if (_activePatient == null) return;
    _isLoading = true;
    notifyListeners();
    try {
      final response = await http.post(
        Uri.parse('http://localhost:8000/patients/${_activePatient!.id}/sessions'),
      );
      if (response.statusCode == 200) {
        final newS = _parseSession(jsonDecode(response.body));
        _activePatient!.sessions.add(newS);
        _activeSession = newS;
        _activeSession!.phase = SessionPhase.baseline; // default tab 2 mode
        _activeTabIndex = 1; // switch to Tab 2
      }
    } catch (e) {
      debugPrint('Error starting session: $e');
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

    http.post(Uri.parse(
      'http://localhost:8000/start_recording?session_id=${s.id}&scan_type=$scanType&duration=${MockGaitService.recordDurationSec}&healthy=$healthyStr&prosthetic=$prostheticStr'
    )).catchError((e) {
      debugPrint('Error starting backend recording: $e');
      return http.Response('Error', 500);
    });

    _recordTimer?.cancel();
    _recordTimer = Timer.periodic(const Duration(milliseconds: 100), (timer) {
      s.recordingElapsedSec += 0.1;
      s.playbackSec = s.recordingElapsedSec;

      if (s.recordingElapsedSec >= MockGaitService.recordDurationSec) {
        stopRecording();
      } else {
        notifyListeners();
      }
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
      await Future.delayed(const Duration(milliseconds: 1200));
      await fetchPatients();
      if (_activePatient != null) {
        _activePatient = _patients.firstWhere((p) => p.id == _activePatient!.id, orElse: () => _activePatient!);
        if (_activeSession != null) {
          _activeSession = _activePatient!.sessions.firstWhere((se) => se.id == _activeSession!.id, orElse: () => _activeSession!);
        }
      }
    } catch (e) {
      debugPrint('Error re-fetching patients: $e');
    }

    _isLoading = false;

    if (s.phase == SessionPhase.baseline) {
      s.phase = SessionPhase.scan1;
      _activeTabIndex = 2; // Analysis tab showing baseline
    } else {
      s.phase = SessionPhase.analyze;
      _activeTabIndex = 2; // Analysis tab showing results
      if (_activeSession != null && _activeSession!.baseline != null && _activeSession!.scans.isNotEmpty) {
        _activeSession!.recommendations = _gaitService.analyze(
          baseline: _activeSession!.baseline,
          scan: _activeSession!.scans.last,
          healthyLeg: _activePatient!.healthyLeg,
          prostheticLeg: _activePatient!.prostheticLeg,
        );
      }
    }

    notifyListeners();
  }

  Future<void> saveActualAdjustment(double degrees, String notes) async {
    final s = _activeSession;
    if (s == null || s.scans.isEmpty) return;

    _isLoading = true;
    notifyListeners();

    final activeScan = s.scans.last;
    try {
      final body = {
        "degrees": degrees,
        "notes": notes
      };
      final response = await http.post(
        Uri.parse('http://localhost:8000/scans/${s.id}/${activeScan.id}/adjustment'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode(body),
      );
      if (response.statusCode == 200) {
        await fetchPatients();
        if (_activePatient != null) {
          _activePatient = _patients.firstWhere((p) => p.id == _activePatient!.id, orElse: () => _activePatient!);
          if (_activeSession != null) {
            _activeSession = _activePatient!.sessions.firstWhere((se) => se.id == _activeSession!.id, orElse: () => _activeSession!);
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
    _activeTabIndex = 1; // Tab 2: Scan
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
    return _gaitService.compareScans(
      s.scans.first,
      s.scans.last,
      _activePatient!.prostheticLeg,
    );
  }

  @override
  void dispose() {
    _recordTimer?.cancel();
    super.dispose();
  }
}
