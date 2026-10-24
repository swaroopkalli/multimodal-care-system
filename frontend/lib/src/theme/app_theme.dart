import 'package:flutter/material.dart';

class AppTheme {
  const AppTheme._();

  static ThemeData get dark {
    const seed = Color(0xFF00E5FF); // Vibrant Cyan
    const darkSurface = Color(0xFF1E2235); // Glassy dark blue
    const background = Color(0xFF0D1117);

    return ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: seed,
        brightness: Brightness.dark,
        primary: seed,
        secondary: const Color(0xFFB388FF),
        tertiary: const Color(0xFFFF4081),
        surface: darkSurface,
        background: background,
      ),
      scaffoldBackgroundColor: Colors.transparent, // Allow global gradient to show through
      appBarTheme: const AppBarTheme(
        centerTitle: false,
        elevation: 0,
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
      ),
      cardTheme: CardThemeData(
        color: darkSurface,
        elevation: 12,
        shadowColor: Colors.black.withOpacity(0.6),
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: Color(0x22FFFFFF), width: 1.5),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF2A2E45),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: seed, width: 2),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: const Color(0xFF111424),
        indicatorColor: seed.withOpacity(0.2),
        labelTextStyle: MaterialStateProperty.all(
          const TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.w600),
        ),
        iconTheme: MaterialStateProperty.resolveWith((states) {
          if (states.contains(MaterialState.selected)) {
            return const IconThemeData(color: seed);
          }
          return const IconThemeData(color: Colors.white54);
        }),
      ),
    );
  }
}

