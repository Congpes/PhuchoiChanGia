import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'l10n/app_language.dart';
import 'providers/session_provider.dart';
import 'screens/analysis_dashboard.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final languageController = await AppLanguageController.load();
  runApp(AiProGaitApp(languageController: languageController));
}

class AiProGaitApp extends StatefulWidget {
  const AiProGaitApp({super.key, this.languageController});

  final AppLanguageController? languageController;

  @override
  State<AiProGaitApp> createState() => _AiProGaitAppState();
}

class _AiProGaitAppState extends State<AiProGaitApp> {
  late final AppLanguageController _languageController;
  late final bool _ownsLanguageController;

  @override
  void initState() {
    super.initState();
    _ownsLanguageController = widget.languageController == null;
    _languageController = widget.languageController ?? AppLanguageController();
  }

  @override
  void dispose() {
    if (_ownsLanguageController) {
      _languageController.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppLanguageScope(
      controller: _languageController,
      child: AnimatedBuilder(
        animation: _languageController,
        builder: (context, _) => ChangeNotifierProvider(
          create: (_) => SessionProvider(),
          child: MaterialApp(
            title: 'AI-ProGait',
            debugShowCheckedModeBanner: false,
            theme: AppTheme.scientific,
            locale: _languageController.locale,
            supportedLocales: AppLanguage.values
                .map((language) => language.locale)
                .toList(growable: false),
            localizationsDelegates: const [
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            home: const AnalysisDashboard(),
          ),
        ),
      ),
    );
  }
}
