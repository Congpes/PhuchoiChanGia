import 'package:flutter/material.dart';

class AppColors {
  static const background = Color(0xFFF3F5F7);
  static const panel = Color(0xFFFFFFFF);
  static const sidebar = Color(0xFFE8EDF2);
  static const surfaceMuted = Color(0xFFF7F8FA);
  static const border = Color(0xFFC7CFD8);
  static const accent = Color(0xFF245A8D);
  static const accentGreen = Color(0xFF356F63);
  static const leftLeg = Color(0xFFA94442);
  static const rightLeg = Color(0xFF245A8D);
  static const baseline = Color(0xFF6B7683);
  static const warning = Color(0xFFA56B24);
  static const critical = Color(0xFFA33A3A);
  static const textPrimary = Color(0xFF1D2733);
  static const textSecondary = Color(0xFF5E6975);
  static const onAccent = Color(0xFFFFFFFF);
}

class AppTheme {
  static ThemeData get scientific {
    final base = ThemeData.light(useMaterial3: true);
    return base.copyWith(
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: base.colorScheme.copyWith(
        primary: AppColors.accent,
        secondary: AppColors.accentGreen,
        surface: AppColors.panel,
        onSurface: AppColors.textPrimary,
        error: AppColors.critical,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.sidebar,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        surfaceTintColor: Colors.transparent,
      ),
      dividerTheme: const DividerThemeData(color: AppColors.border),
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textPrimary,
        displayColor: AppColors.textPrimary,
      ),
      inputDecorationTheme: const InputDecorationTheme(
        filled: true,
        fillColor: AppColors.panel,
        enabledBorder:
            OutlineInputBorder(borderSide: BorderSide(color: AppColors.border)),
        focusedBorder: OutlineInputBorder(
            borderSide: BorderSide(color: AppColors.accent, width: 1.4)),
      ),
      cardTheme: const CardThemeData(
        color: AppColors.panel,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.accent,
          foregroundColor: AppColors.onAccent,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
        ),
      ),
    );
  }
}
