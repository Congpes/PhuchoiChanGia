import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'providers/session_provider.dart';
import 'screens/analysis_dashboard.dart';
import 'theme/app_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AiProGaitApp());
}

class AiProGaitApp extends StatelessWidget {
  const AiProGaitApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => SessionProvider(),
      child: MaterialApp(
        title: 'AI-ProGait',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.scientific,
        home: const AnalysisDashboard(),
      ),
    );
  }
}
