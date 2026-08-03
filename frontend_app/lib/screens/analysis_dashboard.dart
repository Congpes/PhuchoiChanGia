import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/tab_patients.dart';
import '../widgets/tab_prepare_session.dart';
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
    _tabController = TabController(length: 8, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  void _showBlockedMessage(BuildContext context, String message) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor: Colors.redAccent,
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 4),
        content: Row(
          children: [
            const Icon(Icons.lock_outline, color: Colors.white),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                message,
                style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white, fontSize: 13),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _handleMenuSelection(BuildContext context, SessionProvider provider, int value) {
    if (value >= 0 && value <= 7) {
      final targetIndex = value;
      String? blockedMessage;

      if (targetIndex == 1) {
        if (provider.activePatient == null) {
          blockedMessage = 'Vui lòng chọn hoặc thêm bệnh nhân tại Tab 1 trước.';
        }
      } else if (targetIndex == 2) {
        if (provider.activePatient == null) {
          blockedMessage = 'Vui lòng chọn hoặc thêm bệnh nhân tại Tab 1 trước.';
        } else if (provider.activeSession == null) {
          blockedMessage = 'Vui lòng chuẩn bị phiên khám tại Tab 2 trước.';
        }
      } else if (targetIndex == 3) {
        if (provider.activePatient == null) {
          blockedMessage = 'Vui lòng chọn bệnh nhân và khởi động phiên khám trước.';
        } else if (provider.activeSession == null) {
          blockedMessage = 'Chưa có phiên khám nào. Vui lòng bắt đầu tại Tab 1.';
        }
      } else if (targetIndex == 4) {
        if (provider.activePatient == null) {
          blockedMessage = 'Vui lòng chọn bệnh nhân để xem lịch sử khám.';
        }
      }

      if (blockedMessage != null) {
        _showBlockedMessage(context, blockedMessage);
      } else {
        provider.setTabIndex(targetIndex);
      }
    } else if (value == 8) {
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (context) => const AddPatientDialog(),
      );
    } else if (value == 9) {
      showDialog(
        context: context,
        builder: (context) => AlertDialog(
          backgroundColor: AppColors.panel,
          title: const Row(
            children: [
              Icon(Icons.storage, color: AppColors.accent),
              SizedBox(width: 8),
              Text('Kết nối Cơ sở dữ liệu SQLite'),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _dbInfoItem('Công nghệ lưu trữ', 'SQLite 3 (Relational Database)'),
              _dbInfoItem('Vị trí Tệp dữ liệu', 'backend/gait_analysis.db'),
              _dbInfoItem('Bảng lưu trữ', 'patients, sessions, scans, segments, clinical_notes, exercises, practice_attempts'),
              _dbInfoItem('Trạng thái kết nối', 'ONLINE (Connected via FastAPI on :8000)'),
              _dbInfoItem('Số hồ sơ bệnh án hiện tại', '${provider.patients.length} hồ sơ'),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('ĐÓNG', style: TextStyle(color: AppColors.accent, fontWeight: FontWeight.bold)),
            ),
          ],
        ),
      );
    }
  }

  Widget _dbInfoItem(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          const SizedBox(height: 4),
          Text(value, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white)),
        ],
      ),
    );
  }

  Widget _buildMenuButton(BuildContext context, SessionProvider provider) {
    final patient = provider.activePatient;
    final text = patient != null ? patient.name : 'Menu tiện ích';
    final icon = patient != null ? Icons.person : Icons.menu;

    return PopupMenuButton<int>(
      color: AppColors.panel,
      surfaceTintColor: Colors.transparent,
      offset: const Offset(0, 48),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: AppColors.sidebar,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircleAvatar(
              radius: 10,
              backgroundColor: AppColors.accent.withValues(alpha: 0.2),
              child: Icon(icon, size: 12, color: AppColors.accent),
            ),
            const SizedBox(width: 8),
            Text(
              text,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.white),
            ),
            const SizedBox(width: 4),
            const Icon(Icons.arrow_drop_down, size: 16, color: AppColors.textSecondary),
          ],
        ),
      ),
      onSelected: (value) {
        _handleMenuSelection(context, provider, value);
      },
      itemBuilder: (context) => [
        const PopupMenuItem(
          value: 0,
          child: Row(
            children: [
              Icon(Icons.people_outline, size: 18, color: AppColors.textSecondary),
              SizedBox(width: 10),
              Text('1. Hồ sơ bệnh nhân', style: TextStyle(fontSize: 13)),
            ],
          ),
        ),
        const PopupMenuItem(
          value: 1,
          child: Row(
            children: [
              Icon(Icons.note_alt_outlined, size: 18, color: AppColors.textSecondary),
              SizedBox(width: 10),
              Text('2. Chuẩn bị phiên khám', style: TextStyle(fontSize: 13)),
            ],
          ),
        ),
        const PopupMenuItem(
          value: 2,
          child: Row(
            children: [
              Icon(Icons.videocam_outlined, size: 18, color: AppColors.textSecondary),
              SizedBox(width: 10),
              Text('3. Quét & Ghi hình', style: TextStyle(fontSize: 13)),
            ],
          ),
        ),
        const PopupMenuItem(
          value: 3,
          child: Row(
            children: [
              Icon(Icons.analytics_outlined, size: 18, color: AppColors.textSecondary),
              SizedBox(width: 10),
              Text('4. Phân tích dáng đi', style: TextStyle(fontSize: 13)),
            ],
          ),
        ),
        const PopupMenuItem(
          value: 4,
          child: Row(
            children: [
              Icon(Icons.history_outlined, size: 18, color: AppColors.textSecondary),
              SizedBox(width: 10),
              Text('5. Lịch sử & So sánh', style: TextStyle(fontSize: 13)),
            ],
          ),
        ),
        const PopupMenuDivider(),
        const PopupMenuItem(
          value: 8,
          child: Row(
            children: [
              Icon(Icons.add, size: 18, color: AppColors.accent),
              SizedBox(width: 10),
              Text('Thêm bệnh án mới', style: TextStyle(fontSize: 13, color: AppColors.accent, fontWeight: FontWeight.bold)),
            ],
          ),
        ),
        const PopupMenuItem(
          value: 9,
          child: Row(
            children: [
              Icon(Icons.storage_outlined, size: 18, color: Colors.white70),
              SizedBox(width: 10),
              Text('Thông tin Cơ sở dữ liệu', style: TextStyle(fontSize: 13)),
            ],
          ),
        ),
      ],
    );
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
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
              child: _buildMenuButton(context, provider),
            ),
          ),
        ],
      ),
      body: TabBarView(
        controller: _tabController,
        physics: const NeverScrollableScrollPhysics(), // prevent swiping gestures during active workflows
        children: [
          const TabPatients(),
          const TabPrepareSession(),
          const TabScan(),
          const TabAnalysis(),
          const TabHistory(),
          const Center(child: Text('Tab 6: Chọn bài tập (Để sau)')),
          const Center(child: Text('Tab 7: Luyện tập phục hồi (Để sau)')),
          const Center(child: Text('Tab 8: Tổng kết luyện tập (Để sau)')),
        ],
      ),
    );
  }
}
