import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';

class TabPatients extends StatefulWidget {
  const TabPatients({super.key});

  @override
  State<TabPatients> createState() => _TabPatientsState();
}

class _TabPatientsState extends State<TabPatients> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _ageController = TextEditingController();
  final _heightController = TextEditingController();
  final _weightController = TextEditingController();

  LegSide _healthyLeg = LegSide.left;
  ProstheticSide _prostheticLeg = ProstheticSide.right;

  @override
  void dispose() {
    _nameController.dispose();
    _ageController.dispose();
    _heightController.dispose();
    _weightController.dispose();
    super.dispose();
  }

  void _showAddPatientDialog(BuildContext context) {
    _nameController.clear();
    _ageController.clear();
    _heightController.clear();
    _weightController.clear();
    _healthyLeg = LegSide.left;
    _prostheticLeg = ProstheticSide.right;

    showDialog(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              backgroundColor: AppColors.sidebar,
              title: const Text('Thêm Hồ Sơ Bệnh Nhân Mới', style: TextStyle(fontWeight: FontWeight.bold)),
              content: SingleChildScrollView(
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      TextFormField(
                        controller: _nameController,
                        decoration: const InputDecoration(
                          labelText: 'Họ và tên',
                          border: OutlineInputBorder(),
                        ),
                        validator: (value) => value == null || value.isEmpty ? 'Vui lòng nhập tên' : null,
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: TextFormField(
                              controller: _ageController,
                              decoration: const InputDecoration(
                                labelText: 'Tuổi',
                                border: OutlineInputBorder(),
                              ),
                              keyboardType: TextInputType.number,
                              validator: (value) => value == null || value.isEmpty ? 'Nhập tuổi' : null,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: TextFormField(
                              controller: _heightController,
                              decoration: const InputDecoration(
                                labelText: 'Chiều cao (cm)',
                                border: OutlineInputBorder(),
                              ),
                              keyboardType: TextInputType.number,
                              validator: (value) => value == null || value.isEmpty ? 'Nhập chiều cao' : null,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _weightController,
                        decoration: const InputDecoration(
                          labelText: 'Cân nặng (kg)',
                          border: OutlineInputBorder(),
                        ),
                        keyboardType: TextInputType.number,
                        validator: (value) => value == null || value.isEmpty ? 'Nhập cân nặng' : null,
                      ),
                      const SizedBox(height: 16),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text('Chân lành', style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
                                RadioListTile<LegSide>(
                                  contentPadding: EdgeInsets.zero,
                                  title: const Text('Trái (L)', style: TextStyle(fontSize: 12)),
                                  value: LegSide.left,
                                  groupValue: _healthyLeg,
                                  onChanged: (v) {
                                    if (v != null) {
                                      setDialogState(() {
                                        _healthyLeg = v;
                                        _prostheticLeg = ProstheticSide.right; // opposite side
                                      });
                                    }
                                  },
                                ),
                                RadioListTile<LegSide>(
                                  contentPadding: EdgeInsets.zero,
                                  title: const Text('Phải (R)', style: TextStyle(fontSize: 12)),
                                  value: LegSide.right,
                                  groupValue: _healthyLeg,
                                  onChanged: (v) {
                                    if (v != null) {
                                      setDialogState(() {
                                        _healthyLeg = v;
                                        _prostheticLeg = ProstheticSide.left; // opposite side
                                      });
                                    }
                                  },
                                ),
                              ],
                            ),
                          ),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text('Chân giả', style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
                                RadioListTile<ProstheticSide>(
                                  contentPadding: EdgeInsets.zero,
                                  title: const Text('Trái (L)', style: TextStyle(fontSize: 12)),
                                  value: ProstheticSide.left,
                                  groupValue: _prostheticLeg,
                                  onChanged: (v) {
                                    if (v != null) {
                                      setDialogState(() {
                                        _prostheticLeg = v;
                                        _healthyLeg = LegSide.right; // opposite side
                                      });
                                    }
                                  },
                                ),
                                RadioListTile<ProstheticSide>(
                                  contentPadding: EdgeInsets.zero,
                                  title: const Text('Phải (R)', style: TextStyle(fontSize: 12)),
                                  value: ProstheticSide.right,
                                  groupValue: _prostheticLeg,
                                  onChanged: (v) {
                                    if (v != null) {
                                      setDialogState(() {
                                        _prostheticLeg = v;
                                        _healthyLeg = LegSide.left; // opposite side
                                      });
                                    }
                                  },
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('Hủy', style: TextStyle(color: AppColors.textSecondary)),
                ),
                FilledButton(
                  onPressed: () {
                    if (_formKey.currentState!.validate()) {
                      context.read<SessionProvider>().createPatient(
                        _nameController.text,
                        int.parse(_ageController.text),
                        double.parse(_heightController.text),
                        double.parse(_weightController.text),
                        _healthyLeg,
                        _prostheticLeg,
                      );
                      Navigator.of(context).pop();
                    }
                  },
                  child: const Text('Tạo mới'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patients = provider.patients;
    final activePatient = provider.activePatient;

    return Row(
      children: [
        // Left Column: Patient List
        Container(
          width: 320,
          decoration: const BoxDecoration(
            color: AppColors.sidebar,
            border: Border(right: BorderSide(color: AppColors.border)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Hồ sơ bệnh nhân',
                      style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                    ),
                    IconButton(
                      tooltip: 'Thêm bệnh nhân',
                      style: IconButton.styleFrom(
                        backgroundColor: AppColors.accent.withValues(alpha: 0.15),
                      ),
                      onPressed: () => _showAddPatientDialog(context),
                      icon: const Icon(Icons.add, color: AppColors.accent),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: provider.isLoading
                    ? const Center(child: CircularProgressIndicator())
                    : patients.isEmpty
                        ? const Center(child: Text('Chưa có bệnh nhân nào', style: TextStyle(color: AppColors.textSecondary)))
                        : ListView.separated(
                            itemCount: patients.length,
                            separatorBuilder: (context, index) => const Divider(height: 1),
                            itemBuilder: (context, index) {
                              final p = patients[index];
                              final isSelected = activePatient?.id == p.id;
                              return ListTile(
                                selected: isSelected,
                                selectedTileColor: AppColors.accent.withValues(alpha: 0.1),
                                title: Text(p.name, style: const TextStyle(fontWeight: FontWeight.bold)),
                                subtitle: Text(
                                  'ID: ${p.id} | ${p.age} tuổi | Chân giả: ${p.prostheticLeg == ProstheticSide.left ? 'Trái' : 'Phải'}',
                                  style: const TextStyle(fontSize: 12),
                                ),
                                leading: CircleAvatar(
                                  backgroundColor: isSelected ? AppColors.accent : AppColors.panel,
                                  child: Icon(
                                    Icons.person,
                                    color: isSelected ? Colors.black : AppColors.textSecondary,
                                  ),
                                ),
                                onTap: () => provider.selectPatient(p),
                              );
                            },
                          ),
              ),
            ],
          ),
        ),

        // Right Column: Patient Detail & Calibration Trigger
        Expanded(
          child: activePatient == null
              ? const Center(child: Text('Vui lòng chọn hoặc thêm bệnh nhân để tiếp tục', style: TextStyle(color: AppColors.textSecondary)))
              : Container(
                  padding: const EdgeInsets.all(24),
                  color: AppColors.background,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Patient Details Card
                      Container(
                        padding: const EdgeInsets.all(20),
                        decoration: BoxDecoration(
                          color: AppColors.panel,
                          border: Border.all(color: AppColors.border),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const CircleAvatar(
                                  radius: 28,
                                  backgroundColor: AppColors.accent,
                                  child: Icon(Icons.person, size: 32, color: Colors.black),
                                ),
                                const SizedBox(width: 16),
                                Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      activePatient.name,
                                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      'Mã định danh bệnh án: ${activePatient.id}',
                                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                            const SizedBox(height: 24),
                            const Divider(),
                            const SizedBox(height: 16),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                _buildDetailItem('Tuổi', '${activePatient.age} tuổi'),
                                _buildDetailItem('Chiều cao', '${activePatient.heightCm} cm'),
                                _buildDetailItem('Cân nặng', '${activePatient.weightKg} kg'),
                                _buildDetailItem(
                                  'Chân lành (Baseline)',
                                  activePatient.healthyLeg == LegSide.left ? 'Chân Trái (L)' : 'Chân Phải (R)',
                                  color: activePatient.healthyLeg == LegSide.left ? AppColors.leftLeg : AppColors.rightLeg,
                                ),
                                _buildDetailItem(
                                  'Chân giả (Căn chỉnh)',
                                  activePatient.prostheticLeg == ProstheticSide.left ? 'Chân Trái (L)' : 'Chân Phải (R)',
                                  color: activePatient.prostheticLeg == ProstheticSide.left ? AppColors.leftLeg : AppColors.rightLeg,
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 32),
                      const Text(
                        'Hành động kiểm tra lâm sàng',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
                      ),
                      const SizedBox(height: 16),

                      // Start Session / Calibration
                      Expanded(
                        child: Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(24),
                          decoration: BoxDecoration(
                            color: AppColors.panel,
                            border: Border.all(color: AppColors.border),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(
                                Icons.play_circle_outline,
                                size: 64,
                                color: AppColors.accent.withValues(alpha: 0.8),
                              ),
                              const SizedBox(height: 16),
                              const Text(
                                'Bắt đầu phiên kiểm định mới',
                                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                              ),
                              const SizedBox(height: 8),
                              const SizedBox(
                                width: 450,
                                child: Text(
                                  'Mỗi phiên khám sẽ tạo một ID phiên riêng biệt. Quy trình bắt đầu bằng việc quét Baseline chân lành 10 giây để lấy dữ liệu chuẩn sinh học riêng của bệnh nhân.',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
                                ),
                              ),
                              const SizedBox(height: 24),
                              FilledButton.icon(
                                style: FilledButton.styleFrom(
                                  padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                                  backgroundColor: AppColors.accent,
                                  foregroundColor: Colors.black,
                                ),
                                onPressed: provider.isLoading ? null : () => provider.startNewSession(),
                                icon: const Icon(Icons.rocket_launch, size: 20),
                                label: const Text(
                                  'BẮT ĐẦU PHIÊN KHÁM MỚI',
                                  style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 0.8),
                                ),
                              ),
                              if (activePatient.sessions.isNotEmpty) ...[
                                const SizedBox(height: 16),
                                Text(
                                  'Bệnh nhân có ${activePatient.sessions.length} phiên khám cũ trong lịch sử.',
                                  style: const TextStyle(fontSize: 11, color: AppColors.textSecondary),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
        ),
      ],
    );
  }

  Widget _buildDetailItem(String label, String value, {Color? color}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.bold,
            color: color ?? Colors.white,
          ),
        ),
      ],
    );
  }
}
