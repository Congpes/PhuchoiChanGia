import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../theme/app_theme.dart';
import 'fsr_force_phase_dashboard.dart';

class FsrForcePhaseAnalysis extends StatefulWidget {
  const FsrForcePhaseAnalysis({super.key, required this.scanId});

  final String scanId;

  @override
  State<FsrForcePhaseAnalysis> createState() => _FsrForcePhaseAnalysisState();
}

class _FsrForcePhaseAnalysisState extends State<FsrForcePhaseAnalysis> {
  Map<String, dynamic>? _analysis;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant FsrForcePhaseAnalysis oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.scanId != widget.scanId) _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await http.get(
        Uri.parse(
            'http://127.0.0.1:8000/scans/${widget.scanId}/fsr-analysis?window=7'),
      );
      if (response.statusCode != 200) {
        throw Exception('Backend trả mã ${response.statusCode}');
      }
      final data = jsonDecode(response.body);
      if (data is! Map<String, dynamic>) {
        throw Exception('Dữ liệu FSR không đúng định dạng');
      }
      if (mounted) setState(() => _analysis = data);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Text(
          _error!,
          style: const TextStyle(color: AppColors.critical),
          textAlign: TextAlign.center,
        ),
      );
    }
    final regions = _analysis?['regions'];
    if (regions is! Map || regions.isEmpty) {
      return const Center(
        child: Text(
          'Clip này chưa có đủ dữ liệu FSR để dựng ba pha lực.\n'
          'Hãy ghi lại khi hai tấm FSR đã kết nối.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.textSecondary),
        ),
      );
    }
    return FsrForcePhaseDashboard(analysis: _analysis!);
  }
}
