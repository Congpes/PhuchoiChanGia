import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'fsr_region_analysis.dart';
import 'metrics_grid.dart';

class _ClipInfo {
  const _ClipInfo({
    required this.scanId,
    required this.label,
    required this.start,
    required this.end,
    required this.frontalUrl,
    required this.sagittalUrl,
  });

  final String scanId;
  final String label;
  final double start;
  final double end;
  final String frontalUrl;
  final String sagittalUrl;

  factory _ClipInfo.fromJson(Map<String, dynamic> json) => _ClipInfo(
        scanId: json['scanId']?.toString() ?? '',
        label:
            json['label']?.toString() ?? '\u0110o\u1ea1n ph\u00e2n t\u00edch',
        start: (json['startOffsetSec'] as num?)?.toDouble() ?? 0,
        end: (json['endOffsetSec'] as num?)?.toDouble() ?? 0,
        frontalUrl: json['frontalVideoUrl']?.toString() ?? '',
        sagittalUrl: json['sagittalVideoUrl']?.toString() ?? '',
      );
}

class TabAnalysis extends StatefulWidget {
  const TabAnalysis({super.key});

  @override
  State<TabAnalysis> createState() => _TabAnalysisState();
}

class _TabAnalysisState extends State<TabAnalysis> {
  List<_ClipInfo> _clips = [];
  String? _selectedId;
  String? _loadedSessionId;
  bool _loading = false;
  String? _error;
  Timer? _playTimer;
  double _position = 0;
  bool _playing = false;

  @override
  void dispose() {
    _playTimer?.cancel();
    super.dispose();
  }

  Future<void> _load(String sessionId) async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await http.get(
        Uri.parse('http://localhost:8000/sessions/$sessionId/analysis-clips'),
      );
      if (response.statusCode != 200) {
        throw Exception('Backend tr\u1ea3 m\u00e3 ${response.statusCode}');
      }
      final decoded = jsonDecode(response.body) as List;
      final clips = decoded
          .whereType<Map<String, dynamic>>()
          .map(_ClipInfo.fromJson)
          .toList();
      if (!mounted) return;
      setState(() {
        _clips = clips;
        _selectedId = clips.any((clip) => clip.scanId == _selectedId)
            ? _selectedId
            : (clips.isEmpty ? null : clips.first.scanId);
        _loadedSessionId = sessionId;
        if (clips.isNotEmpty) {
          _position =
              clips.firstWhere((clip) => clip.scanId == _selectedId).start;
        }
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patient = provider.activePatient;
    final session = provider.activeSession;
    if (patient == null || session == null) {
      return const Center(
          child: Text(
              'Ch\u01b0a ch\u1ecdn b\u1ec7nh nh\u00e2n ho\u1eb7c phi\u00ean \u0111o.'));
    }
    if (_loadedSessionId != session.id && !_loading) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _load(session.id));
    }

    final selectedClip =
        _clips.where((clip) => clip.scanId == _selectedId).firstOrNull;
    final allScans = <ScanResult>[
      if (session.baseline != null) session.baseline!,
      ...session.scans,
    ];
    final selectedScan =
        allScans.where((scan) => scan.id == selectedClip?.scanId).firstOrNull;

    return Row(
      children: [
        Expanded(
          child: Column(
            children: [
              _titleBar(provider, selectedClip),
              if (selectedClip != null) _videoPair(session.id, selectedClip),
              if (selectedClip != null) _playbackControls(selectedClip),
              Expanded(
                child: selectedScan == null
                    ? _emptyState()
                    : DefaultTabController(
                        length: 2,
                        child: Column(
                          children: [
                            Container(
                              height: 38,
                              color: AppColors.panel,
                              child: const TabBar(
                                tabs: [
                                  Tab(
                                      text:
                                          'CH\u1ec8 S\u1ed0 D\u00c1NG \u0110I'),
                                  Tab(
                                      text:
                                          'FSR \u00b7 3 V\u00d9NG B\u00c0N CH\u00c2N'),
                                ],
                              ),
                            ),
                            Expanded(
                              child: TabBarView(
                                children: [
                                  MetricsGrid(
                                    scan: selectedScan,
                                    baseline: session.baseline,
                                    patient: patient,
                                  ),
                                  FsrRegionAnalysis(scanId: selectedScan.id),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
              ),
            ],
          ),
        ),
        _clipList(session),
      ],
    );
  }

  Widget _titleBar(SessionProvider provider, _ClipInfo? clip) {
    return Container(
      height: 50,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: const BoxDecoration(
        color: AppColors.panel,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        children: [
          IconButton(
            onPressed: () => provider.setTabIndex(2),
            icon: const Icon(Icons.arrow_back),
            tooltip: 'V\u1ec1 m\u00e0n Scan',
          ),
          const SizedBox(width: 6),
          const Text(
            'PH\u00c2N T\u00cdCH \u0110O\u1ea0N D\u00c1NG \u0110I',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
          ),
          if (clip != null) ...[
            const SizedBox(width: 12),
            Text(
              '${clip.start.toStringAsFixed(1)}\u2013${clip.end.toStringAsFixed(1)} s',
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                color: AppColors.accent,
              ),
            ),
          ],
        ],
      ),
    );
  }

  void _selectClip(_ClipInfo clip) {
    _playTimer?.cancel();
    setState(() {
      _selectedId = clip.scanId;
      _position = clip.start;
      _playing = false;
    });
  }

  void _togglePlayback(_ClipInfo clip) {
    if (_playing) {
      _playTimer?.cancel();
      setState(() => _playing = false);
      return;
    }
    if (_position >= clip.end) _position = clip.start;
    setState(() => _playing = true);
    _playTimer = Timer.periodic(const Duration(milliseconds: 200), (timer) {
      if (!mounted || _position + 0.2 >= clip.end) {
        timer.cancel();
        if (mounted) {
          setState(() {
            _position = clip.end;
            _playing = false;
          });
        }
        return;
      }
      setState(() => _position += 0.2);
    });
  }

  Widget _playbackControls(_ClipInfo clip) {
    final value = _position.clamp(clip.start, clip.end);
    return Container(
      height: 48,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      color: AppColors.sidebar,
      child: Row(
        children: [
          IconButton(
            onPressed: () => _togglePlayback(clip),
            icon: Icon(_playing ? Icons.pause : Icons.play_arrow),
            tooltip: _playing ? 'Pause' : 'Play',
          ),
          SizedBox(
            width: 62,
            child: Text(
              '${value.toStringAsFixed(1)} s',
              style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
            ),
          ),
          Expanded(
            child: Slider(
              min: clip.start,
              max: clip.end,
              value: value,
              onChanged: (next) {
                _playTimer?.cancel();
                setState(() {
                  _position = next;
                  _playing = false;
                });
              },
            ),
          ),
          Text(
            '${clip.end.toStringAsFixed(1)} s',
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 11,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _videoPair(String sessionId, _ClipInfo clip) {
    return SizedBox(
      height: 220,
      child: Row(
        children: [
          Expanded(
            child: _recordedVideo(
              'CAM 1 \u00b7 CH\u00cdNH DI\u1ec6N',
              clip.frontalUrl,
            ),
          ),
          Expanded(
            child: _recordedVideo(
              'CAM 2 \u00b7 M\u1eb6T PH\u1eb2NG D\u1eccC',
              clip.sagittalUrl,
            ),
          ),
        ],
      ),
    );
  }

  Widget _recordedVideo(String label, String relativeUrl) {
    final framePath = relativeUrl.split('?').first.replaceFirst(
          '/session-video/',
          '/session-video-frame/',
        );
    final url =
        'http://localhost:8000$framePath?t=${_position.toStringAsFixed(2)}';
    return Container(
      margin: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: relativeUrl.isEmpty
                ? const Center(child: Text('Kh\u00f4ng c\u00f3 video'))
                : Image.network(
                    url,
                    key: ValueKey(url),
                    fit: BoxFit.contain,
                    gaplessPlayback: true,
                  ),
          ),
          Positioned(
            left: 8,
            top: 8,
            child: Container(
              color: const Color(0xD9FFFFFF),
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
              child: Text(
                label,
                style:
                    const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _clipList(GaitSession session) {
    return Container(
      width: 290,
      color: AppColors.sidebar,
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  '\u0110O\u1ea0N \u0110\u00c3 C\u1eaeT',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
                ),
              ),
              IconButton(
                onPressed: _loading ? null : () => _load(session.id),
                icon: const Icon(Icons.refresh, size: 18),
                tooltip: 'N\u1ea1p l\u1ea1i danh s\u00e1ch',
              ),
            ],
          ),
          const Text(
            'Ch\u1ecdn m\u1ed9t \u0111o\u1ea1n \u0111\u1ec3 \u0111\u1ed3ng b\u1ed9 video v\u00e0 bi\u1ec3u \u0111\u1ed3.',
            style: TextStyle(fontSize: 11, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 12),
          if (_loading) const LinearProgressIndicator(minHeight: 2),
          if (_error != null)
            Text(
              _error!,
              style: const TextStyle(fontSize: 11, color: AppColors.critical),
            ),
          Expanded(
            child: _clips.isEmpty && !_loading
                ? const Center(
                    child: Text(
                      'Ch\u01b0a c\u00f3 \u0111o\u1ea1n ph\u00e2n t\u00edch.\nV\u1ec1 tab Scan \u0111\u1ec3 \u0111\u1eb7t m\u1ed1c \u0111\u1ea7u v\u00e0 m\u1ed1c cu\u1ed1i.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 12, color: AppColors.textSecondary),
                    ),
                  )
                : ListView.separated(
                    itemCount: _clips.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (_, index) {
                      final clip = _clips[index];
                      final selected = clip.scanId == _selectedId;
                      return ListTile(
                        selected: selected,
                        selectedTileColor:
                            AppColors.accent.withValues(alpha: 0.09),
                        contentPadding:
                            const EdgeInsets.symmetric(horizontal: 8),
                        title: Text(
                          clip.label,
                          style: const TextStyle(
                              fontSize: 12, fontWeight: FontWeight.w600),
                        ),
                        subtitle: Text(
                          '${clip.start.toStringAsFixed(1)}\u2013${clip.end.toStringAsFixed(1)} s'
                          ' \u00b7 ${(clip.end - clip.start).toStringAsFixed(1)} s',
                          style: const TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 10,
                            color: AppColors.textSecondary,
                          ),
                        ),
                        trailing: selected
                            ? const Icon(Icons.play_arrow,
                                color: AppColors.accent)
                            : null,
                        onTap: () => _selectClip(clip),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _emptyState() {
    return Center(
      child: Text(
        _loading
            ? '\u0110ang n\u1ea1p d\u1eef li\u1ec7u \u0111o\u1ea1n...'
            : 'Ch\u1ecdn m\u1ed9t \u0111o\u1ea1n \u1edf danh s\u00e1ch b\u00ean ph\u1ea3i \u0111\u1ec3 xem k\u1ebft qu\u1ea3.',
        style: const TextStyle(color: AppColors.textSecondary),
      ),
    );
  }
}
