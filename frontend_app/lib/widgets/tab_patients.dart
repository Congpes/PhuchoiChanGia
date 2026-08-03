import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';

class TabPatients extends StatelessWidget {
  const TabPatients({super.key});

  void _showAddPatientDialog(BuildContext context) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => const AddPatientDialog(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final patients = provider.patients;
    final activePatient = provider.activePatient;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Left Column: Patient List
        _PatientListPanel(
          provider: provider,
          patients: patients,
          activePatient: activePatient,
          onAddPressed: () => _showAddPatientDialog(context),
        ),

        // Right Column: Patient Detail & Clinical Actions
        Expanded(
          child: activePatient == null
              ? const Center(
                  child: Text(
                    'Vui lòng chọn hoặc thêm bệnh nhân để tiếp tục',
                    style: TextStyle(color: AppColors.textSecondary),
                  ),
                )
              : SingleChildScrollView(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _PatientDetailCard(patient: activePatient),
                      const SizedBox(height: 32),
                      const Text(
                        'Hành động kiểm tra lâm sàng',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
                      ),
                      const SizedBox(height: 16),
                      _ClinicalActionCard(
                        patient: activePatient,
                        provider: provider,
                      ),
                    ],
                  ),
                ),
        ),
      ],
    );
  }
}

/// Panel danh sách hồ sơ bệnh án bên trái
class _PatientListPanel extends StatefulWidget {
  const _PatientListPanel({
    required this.provider,
    required this.patients,
    required this.activePatient,
    required this.onAddPressed,
  });

  final SessionProvider provider;
  final List<Patient> patients;
  final Patient? activePatient;
  final VoidCallback onAddPressed;

  @override
  State<_PatientListPanel> createState() => _PatientListPanelState();
}

class _PatientListPanelState extends State<_PatientListPanel> {
  late final TextEditingController _searchController;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController();
    _searchController.addListener(_onSearchChanged);
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _onSearchChanged() {
    setState(() {
      _query = _searchController.text.trim().toLowerCase();
    });
  }

  List<Patient> _getRecentPatients(List<Patient> patientsList) {
    final sorted = List<Patient>.from(patientsList);
    sorted.sort((a, b) {
      final aTime = a.sessions.isNotEmpty
          ? a.sessions.map((s) => s.createdAt).reduce((curr, next) => curr.isAfter(next) ? curr : next)
          : DateTime.fromMillisecondsSinceEpoch(0);
      final bTime = b.sessions.isNotEmpty
          ? b.sessions.map((s) => s.createdAt).reduce((curr, next) => curr.isAfter(next) ? curr : next)
          : DateTime.fromMillisecondsSinceEpoch(0);
      if (aTime != bTime) {
        return bTime.compareTo(aTime); // newest first
      }
      return b.id.compareTo(a.id); // fallback to ID descending
    });
    return sorted;
  }

  @override
  Widget build(BuildContext context) {
    List<Patient> displayPatients;
    final isSearching = _query.isNotEmpty;

    if (isSearching) {
      displayPatients = widget.patients.where((p) {
        return p.name.toLowerCase().contains(_query) || p.id.toLowerCase().contains(_query);
      }).toList();
    } else {
      displayPatients = _getRecentPatients(widget.patients);
    }

    return Container(
      width: 320,
      decoration: const BoxDecoration(
        color: AppColors.sidebar,
        border: Border(right: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 16, right: 16, top: 16, bottom: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'Hồ sơ bệnh nhân',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                ),
                IconButton(
                  tooltip: 'Thêm bệnh án mới',
                  style: IconButton.styleFrom(
                    backgroundColor: AppColors.accent.withValues(alpha: 0.15),
                  ),
                  onPressed: widget.onAddPressed,
                  icon: const Icon(Icons.add, color: AppColors.accent),
                ),
              ],
            ),
          ),
          
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: TextFormField(
              controller: _searchController,
              decoration: InputDecoration(
                isDense: true,
                hintText: 'Tìm kiếm bệnh nhân...',
                prefixIcon: const Icon(Icons.search, size: 18, color: AppColors.textSecondary),
                suffixIcon: isSearching
                    ? IconButton(
                        icon: const Icon(Icons.clear, size: 16),
                        onPressed: () => _searchController.clear(),
                        padding: EdgeInsets.zero,
                        constraints: const BoxConstraints(),
                      )
                    : null,
                contentPadding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ),
          ),
          
          const Divider(height: 1),
          
          if (widget.patients.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Text(
                isSearching ? 'Kết quả tìm thấy (${displayPatients.length})' : 'Bệnh nhân gần đây',
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: AppColors.textSecondary,
                  letterSpacing: 0.5,
                ),
              ),
            ),

          Expanded(
            child: widget.provider.isLoading && widget.patients.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : displayPatients.isEmpty
                    ? Center(
                        child: Text(
                          isSearching ? 'Không tìm thấy kết quả' : 'Chưa có bệnh nhân nào',
                          style: const TextStyle(color: AppColors.textSecondary),
                        ),
                      )
                    : ListView.separated(
                        itemCount: displayPatients.length,
                        separatorBuilder: (context, index) => const Divider(height: 1),
                        itemBuilder: (context, index) {
                          final p = displayPatients[index];
                          final isSelected = widget.activePatient?.id == p.id;
                          return ListTile(
                            selected: isSelected,
                            selectedTileColor: AppColors.accent.withValues(alpha: 0.1),
                            title: Text(
                              p.name,
                              style: const TextStyle(fontWeight: FontWeight.bold),
                            ),
                            subtitle: Text(
                              'ID: ${p.id} | ${p.age} tuổi | Chân giả: ${p.prostheticLeg == LegSide.left ? 'Trái' : 'Phải'}',
                              style: const TextStyle(fontSize: 12),
                            ),
                            leading: CircleAvatar(
                              backgroundColor: isSelected ? AppColors.accent : AppColors.panel,
                              child: Icon(
                                Icons.person,
                                color: isSelected ? Colors.black : AppColors.textSecondary,
                              ),
                            ),
                            onTap: () => widget.provider.selectPatient(p),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}

/// Thẻ hiển thị thông tin hồ sơ chi tiết của bệnh nhân
class _PatientDetailCard extends StatelessWidget {
  const _PatientDetailCard({required this.patient});

  final Patient patient;

  @override
  Widget build(BuildContext context) {
    return Container(
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
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      patient.name,
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Mã định danh bệnh án: ${patient.id}',
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          const Divider(),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final double itemWidth = constraints.maxWidth > 600 ? (constraints.maxWidth - 48) / 5 : (constraints.maxWidth - 24) / 2;
              return Wrap(
                spacing: 12,
                runSpacing: 16,
                children: [
                  SizedBox(width: itemWidth, child: _buildDetailItem('Tuổi', '${patient.age} tuổi')),
                  SizedBox(width: itemWidth, child: _buildDetailItem('Chiều cao', '${patient.heightCm} cm')),
                  SizedBox(width: itemWidth, child: _buildDetailItem('Cân nặng', '${patient.weightKg} kg')),
                  SizedBox(
                    width: itemWidth,
                    child: _buildDetailItem(
                      'Chân lành sinh học',
                      patient.healthyLeg == LegSide.left ? 'Chân Trái (L)' : 'Chân Phải (R)',
                      color: patient.healthyLeg == LegSide.left ? AppColors.leftLeg : AppColors.rightLeg,
                    ),
                  ),
                  SizedBox(
                    width: itemWidth,
                    child: _buildDetailItem(
                      'Chân giả lắp đặt',
                      patient.prostheticLeg == LegSide.left ? 'Chân Trái (L)' : 'Chân Phải (R)',
                      color: patient.prostheticLeg == LegSide.left ? AppColors.leftLeg : AppColors.rightLeg,
                    ),
                  ),
                ],
              );
            },
          ),
          const SizedBox(height: 20),
          const Divider(),
          const SizedBox(height: 12),
          const Text('Tiền sử bệnh lý & Chấn thương', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: AppColors.textSecondary)),
          const SizedBox(height: 6),
          Text(
            patient.injuryHistory.isNotEmpty ? patient.injuryHistory : 'Chưa có thông tin tiền sử bệnh lý.',
            style: const TextStyle(fontSize: 14, color: Colors.white70, height: 1.4),
          ),
          const SizedBox(height: 16),
          const Text('Mục tiêu điều trị & Căn chỉnh van', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: AppColors.textSecondary)),
          const SizedBox(height: 6),
          Text(
            patient.treatmentGoals.isNotEmpty ? patient.treatmentGoals : 'Chưa có thông tin mục tiêu điều trị.',
            style: const TextStyle(fontSize: 14, color: Colors.white70, height: 1.4),
          ),
        ],
      ),
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
          overflow: TextOverflow.ellipsis,
        ),
      ],
    );
  }
}

/// Hộp hành động kích hoạt phiên kiểm định lâm sàng
class _ClinicalActionCard extends StatefulWidget {
  const _ClinicalActionCard({
    required this.patient,
    required this.provider,
  });

  final Patient patient;
  final SessionProvider provider;

  @override
  State<_ClinicalActionCard> createState() => _ClinicalActionCardState();
}

class _ClinicalActionCardState extends State<_ClinicalActionCard> {
  bool _isCreatingSession = false;

  Future<void> _handleStartSession(BuildContext context) async {
    setState(() => _isCreatingSession = true);
    try {
      await widget.provider.startNewSession();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppColors.accent,
            content: Text('Khởi tạo phiên kiểm định mới thành công! Đang chuyển hướng...'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        showDialog(
          context: context,
          builder: (context) => AlertDialog(
            backgroundColor: AppColors.panel,
            title: const Text('Lỗi khởi tạo phiên'),
            content: Text(
              'Không thể kết nối API hoặc Server đang ngoại tuyến.\n\nChi tiết lỗi: $e\n\nVui lòng khởi chạy FastAPI server.',
              style: const TextStyle(color: Colors.white70),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('ĐÓNG', style: TextStyle(color: AppColors.accent)),
              ),
            ],
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isCreatingSession = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasOldSessions = widget.patient.sessions.isNotEmpty;

    return Container(
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
          _isCreatingSession
              ? const CircularProgressIndicator()
              : FilledButton.icon(
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.black,
                  ),
                  onPressed: widget.provider.isLoading ? null : () => _handleStartSession(context),
                  icon: const Icon(Icons.rocket_launch, size: 20),
                  label: const Text(
                    'BẮT ĐẦU PHIÊN KHÁM MỚI',
                    style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 0.8),
                  ),
                ),
          if (hasOldSessions) ...[
            const SizedBox(height: 16),
            Text(
              'Bệnh nhân có ${widget.patient.sessions.length} phiên khám cũ trong lịch sử.',
              style: const TextStyle(fontSize: 11, color: AppColors.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}

/// Dialog Stateful để thêm bệnh nhân mới với Form Validation
class AddPatientDialog extends StatefulWidget {
  const AddPatientDialog({super.key});

  @override
  State<AddPatientDialog> createState() => AddPatientDialogState();
}

class AddPatientDialogState extends State<AddPatientDialog> {
  final _formKey = GlobalKey<FormState>();
  
  late final TextEditingController _nameController;
  late final TextEditingController _ageController;
  late final TextEditingController _heightController;
  late final TextEditingController _weightController;

  LegSide _healthyLeg = LegSide.left;
  LegSide _prostheticLeg = LegSide.right;
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    _nameController = TextEditingController();
    _ageController = TextEditingController();
    _heightController = TextEditingController();
    _weightController = TextEditingController();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _ageController.dispose();
    _heightController.dispose();
    _weightController.dispose();
    super.dispose();
  }

  Future<void> _submitForm(BuildContext context) async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() => _isSubmitting = true);
    
    final name = _nameController.text.trim();
    final age = int.parse(_ageController.text.trim());
    final height = double.parse(_heightController.text.trim());
    final weight = double.parse(_weightController.text.trim());

    try {
      final provider = context.read<SessionProvider>();
      await provider.createPatient(
        name,
        age,
        height,
        weight,
        _healthyLeg,
        _prostheticLeg,
      );
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Tạo hồ sơ bệnh án thành công!')),
        );
        Navigator.of(context).pop();
      }
    } catch (e) {
      if (mounted) {
        showDialog(
          context: context,
          builder: (context) => AlertDialog(
            backgroundColor: AppColors.panel,
            title: const Text('Lỗi kết nối'),
            content: Text(
              'Không thể ghi nhận bệnh án lên Database.\n\nChi tiết lỗi: $e\n\nVui lòng kiểm tra kết nối với FastAPI server.',
              style: const TextStyle(color: Colors.white70),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('ĐÓNG', style: TextStyle(color: AppColors.accent)),
              ),
            ],
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AppColors.panel,
      title: const Text('Thêm bệnh án mới', style: TextStyle(fontWeight: FontWeight.bold)),
      content: SizedBox(
        width: 450,
        child: SingleChildScrollView(
          child: Form(
            key: _formKey,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextFormField(
                  controller: _nameController,
                  decoration: const InputDecoration(
                    labelText: 'Họ và tên bệnh nhân *',
                    hintText: 'Nhập họ tên đầy đủ',
                  ),
                  validator: (val) {
                    if (val == null || val.trim().isEmpty) {
                      return 'Họ tên không được để trống';
                    }
                    if (val.trim().length < 3) {
                      return 'Tên quá ngắn (tối thiểu 3 ký tự)';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 16),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: TextFormField(
                        controller: _ageController,
                        decoration: const InputDecoration(
                          labelText: 'Tuổi *',
                          hintText: 'VD: 45',
                        ),
                        keyboardType: TextInputType.number,
                        validator: (val) {
                          if (val == null || val.trim().isEmpty) {
                            return 'Yêu cầu nhập tuổi';
                          }
                          final parsed = int.tryParse(val.trim());
                          if (parsed == null || parsed <= 0 || parsed > 120) {
                            return 'Tuổi từ 1 - 120';
                          }
                          return null;
                        },
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: TextFormField(
                        controller: _heightController,
                        decoration: const InputDecoration(
                          labelText: 'Chiều cao (cm) *',
                          hintText: 'VD: 172.5',
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        validator: (val) {
                          if (val == null || val.trim().isEmpty) {
                            return 'Yêu cầu nhập chiều cao';
                          }
                          final parsed = double.tryParse(val.trim());
                          if (parsed == null || parsed < 30 || parsed > 250) {
                            return 'Chiều cao 30 - 250 cm';
                          }
                          return null;
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _weightController,
                  decoration: const InputDecoration(
                    labelText: 'Cân nặng (kg) *',
                    hintText: 'VD: 64.0',
                  ),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: (val) {
                    if (val == null || val.trim().isEmpty) {
                      return 'Yêu cầu nhập cân nặng';
                    }
                    final parsed = double.tryParse(val.trim());
                    if (parsed == null || parsed < 2 || parsed > 250) {
                      return 'Cân nặng 2 - 250 kg';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 24),
                const Divider(),
                const SizedBox(height: 12),
                
                // Dropdown chân lành sinh học
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Chân lành sinh học:', style: TextStyle(fontSize: 13)),
                    DropdownButton<LegSide>(
                      value: _healthyLeg,
                      dropdownColor: AppColors.panel,
                      items: const [
                        DropdownMenuItem(value: LegSide.left, child: Text('Trái (Left)')),
                        DropdownMenuItem(value: LegSide.right, child: Text('Phải (Right)')),
                      ],
                      onChanged: (val) {
                        if (val != null) {
                          setState(() {
                            _healthyLeg = val;
                            // Đề xuất mặc định chân đối diện cho chân giả
                            _prostheticLeg = val == LegSide.left ? LegSide.right : LegSide.left;
                          });
                        }
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 8),

                // Dropdown chân giả lắp đặt (Độc lập lựa chọn, có default tự động đề xuất)
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Chân giả lắp đặt:', style: TextStyle(fontSize: 13)),
                    DropdownButton<LegSide>(
                      value: _prostheticLeg,
                      dropdownColor: AppColors.panel,
                      items: const [
                        DropdownMenuItem(value: LegSide.left, child: Text('Trái (Left)')),
                        DropdownMenuItem(value: LegSide.right, child: Text('Phải (Right)')),
                      ],
                      onChanged: (val) {
                        if (val != null) {
                          setState(() {
                            _prostheticLeg = val;
                          });
                        }
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  '* Mặc định chân giả lắp đặt ở phía đối diện chân lành. Trường hợp cụt cả hai chân hoặc đặc biệt khác, bạn có thể chỉnh thủ công chân giả giống chân lành.',
                  style: TextStyle(fontSize: 11, color: AppColors.textSecondary, fontStyle: FontStyle.italic),
                ),
                const SizedBox(height: 8),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _isSubmitting ? null : () => Navigator.of(context).pop(),
          child: const Text('HỦY BỎ', style: TextStyle(color: AppColors.textSecondary)),
        ),
        _isSubmitting
            ? const Padding(
                padding: EdgeInsets.symmetric(horizontal: 16),
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              )
            : FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  foregroundColor: Colors.black,
                ),
                onPressed: () => _submitForm(context),
                child: const Text('TẠO BỆNH ÁN'),
              ),
      ],
    );
  }
}
