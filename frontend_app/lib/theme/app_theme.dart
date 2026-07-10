import 'package:flutter/material.dart';

class AppColors {
  static const background = Color(0xFF0F1419);
  static const panel = Color(0xFF1A2332);
  static const sidebar = Color(0xFF152238);
  static const border = Color(0xFF2A3F5F);
  static const accent = Color(0xFF00B4D8);
  static const accentGreen = Color(0xFF06D6A0);
  static const leftLeg = Color(0xFFE63946);
  static const rightLeg = Color(0xFF4CC9F0);
  static const baseline = Color(0xFF94A3B8);
  static const warning = Color(0xFFF4A261);
  static const critical = Color(0xFFE63946);
  static const textPrimary = Color(0xFFF1F5F9);
  static const textSecondary = Color(0xFF94A3B8);
}

class AppTheme {
  static ThemeData get dark {
    final base = ThemeData.dark(useMaterial3: true);
    return base.copyWith(
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: base.colorScheme.copyWith(
        primary: AppColors.accent,
        secondary: AppColors.accentGreen,
        surface: AppColors.panel,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.sidebar,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
      ),
      dividerTheme: const DividerThemeData(color: AppColors.border),
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textPrimary,
        displayColor: AppColors.textPrimary,
      ),
    );
  }
}
