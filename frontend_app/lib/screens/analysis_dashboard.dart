import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/tab_patients.dart';
import '../widgets/tab_scan.dart';
import '../widgets/tab_analysis.dart';
import '../widgets/tab_history.dart';

class AnalysisDashboard extends StatefulWidget {
  const AnalysisDashboard({super.key});

  @override
  State<AnalysisDashboard> createState() => _AnalysisDashboardState();
}

class _AnalysisDashboardState extends State<AnalysisDashboard> with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 4, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();

    if (_tabController.index != provider.activeTabIndex) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _tabController.animateTo(provider.activeTabIndex);
        }
      });
    }

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const Icon(Icons.insights, color: AppColors.accent),
            const SizedBox(width: 8),
            const Text(
              'AI-ProGait',
              style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 0.5),
            ),
            const SizedBox(width: 12),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.white10,
                borderRadius: BorderRadius.circular(4),
              ),
              child: const Text(
                'PHÒNG LAB',
                style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: AppColors.textSecondary),
              ),
            ),
          ],
        ),
        bottom: TabBar(
          controller: _tabController,
          labelColor: AppColors.accent,
          unselectedLabelColor: AppColors.textSecondary,
          indicatorColor: AppColors.accent,
          onTap: (index) {
            provider.setTabIndex(index);
          },
          tabs: const [
            Tab(icon: Icon(Icons.people), text: '1. BỆNH NHÂN'),
            Tab(icon: Icon(Icons.videocam), text: '2. QUÉT & GHI'),
            Tab(icon: Icon(Icons.analytics), text: '3. PHÂN TÍCH'),
            Tab(icon: Icon(Icons.history), text: '4. LỊCH SỬ & SO SÁNH'),
          ],
        ),
        actions: [
          if (provider.activePatient != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Center(
                child: Row(
                  children: [
                    const Icon(Icons.person, size: 16, color: AppColors.textSecondary),
                    const SizedBox(width: 6),
                    Text(
                      provider.activePatient!.name,
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
      body: TabBarView(
        controller: _tabController,
        physics: const NeverScrollableScrollPhysics(), // prevent swiping gestures during active workflows
        children: const [
          TabPatients(),
          TabScan(),
          TabAnalysis(),
          TabHistory(),
        ],
      ),
    );
  }
}
