import 'package:flutter/material.dart' hide Text;

import '../l10n/localized_text.dart';

import '../theme/app_theme.dart';

enum AnalysisSection { jointAngles, fsrForce, balance }

class AnalysisSectionSwitcher extends StatelessWidget {
  const AnalysisSectionSwitcher({
    super.key,
    required this.selected,
    required this.onChanged,
  });

  final AnalysisSection selected;
  final ValueChanged<AnalysisSection> onChanged;

  @override
  Widget build(BuildContext context) {
    const sections = [
      (
        AnalysisSection.jointAngles,
        'Góc khớp',
        Icons.accessibility_new_outlined,
      ),
      (AnalysisSection.fsrForce, 'Lực FSR', Icons.sensors_outlined),
      (AnalysisSection.balance, 'Thăng bằng', Icons.balance_outlined),
    ];

    return Semantics(
      container: true,
      label: 'Nhóm phân tích',
      child: Container(
        height: 38,
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          color: AppColors.surfaceMuted,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(9),
        ),
        child: Row(
          children: [
            for (final section in sections)
              Expanded(
                child: _SectionButton(
                  selected: selected == section.$1,
                  label: section.$2,
                  icon: section.$3,
                  onTap: () => onChanged(section.$1),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _SectionButton extends StatelessWidget {
  const _SectionButton({
    required this.selected,
    required this.label,
    required this.icon,
    required this.onTap,
  });

  final bool selected;
  final String label;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? AppColors.panel : Colors.transparent,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.symmetric(horizontal: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(6),
            border: selected
                ? Border.all(color: AppColors.accent.withValues(alpha: 0.35))
                : null,
            boxShadow: selected
                ? const [
                    BoxShadow(
                      color: Color(0x14000000),
                      blurRadius: 3,
                      offset: Offset(0, 1),
                    ),
                  ]
                : null,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                icon,
                size: 15,
                color: selected ? AppColors.accent : AppColors.textSecondary,
              ),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
                    color: selected
                        ? AppColors.textPrimary
                        : AppColors.textSecondary,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
