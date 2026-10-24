import 'package:flutter/material.dart';

import '../state/care_state.dart';
import 'architecture_screen.dart';
import 'caretaker_dashboard.dart';
import 'doctor_dashboard.dart';
import 'patient_dashboard.dart';
import 'auth_screen.dart';

class DashboardShell extends StatefulWidget {
  const DashboardShell({super.key});

  @override
  State<DashboardShell> createState() => _DashboardShellState();
}

class _DashboardShellState extends State<DashboardShell>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  final CareState _careState = CareState();

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..forward();
  }

  @override
  void dispose() {
    _controller.dispose();
    _careState.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('MindBridge', style: TextStyle(fontWeight: FontWeight.w800)),
        centerTitle: true,
        actions: [
          IconButton(
            tooltip: 'System architecture',
            icon: const Icon(Icons.account_tree_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const ArchitectureScreen()),
            ),
          ),
        ],
      ),
      body: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          final value = Curves.easeOutBack.transform(_controller.value);
          return SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 40),
            child: Column(
              children: [
                const SizedBox(height: 20),
                const Text(
                  'Select Your Portal',
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w800,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 40),
                Wrap(
                  spacing: 20,
                  runSpacing: 20,
                  alignment: WrapAlignment.center,
                  children: [
                    _PortalCard(
                      delay: 0.10,
                      controller: _controller,
                      title: 'Patient',
                      icon: Icons.favorite,
                      colors: const [Color(0xFF256D85), Color(0xFF7A5CFA)],
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => PatientDashboard(careState: _careState),
                        ),
                      ),
                    ),
                    _PortalCard(
                      delay: 0.20,
                      controller: _controller,
                      title: 'Caretaker',
                      icon: Icons.verified_user,
                      colors: const [Color(0xFF1B7F5C), Color(0xFFE28413)],
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => CaretakerDashboard(careState: _careState),
                        ),
                      ),
                    ),
                    _PortalCard(
                      delay: 0.30,
                      controller: _controller,
                      title: 'Doctor',
                      icon: Icons.medical_information,
                      colors: const [Color(0xFF14213D), Color(0xFF4A5568)],
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => const DoctorDashboard()),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _PortalCard extends StatelessWidget {
  const _PortalCard({
    required this.controller,
    required this.delay,
    required this.title,
    required this.icon,
    required this.colors,
    required this.onTap,
  });

  final AnimationController controller;
  final double delay;
  final String title;
  final IconData icon;
  final List<Color> colors;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final raw = ((controller.value - delay) / (1 - delay)).clamp(0.0, 1.0);
    final value = Curves.easeOutCubic.transform(raw);

    return Transform.scale(
      scale: 0.96 + (0.04 * value),
      child: Opacity(
        opacity: value,
        child: InkWell(
          borderRadius: BorderRadius.circular(24),
          onTap: onTap,
          child: Ink(
            width: 140,
            height: 140,
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: colors,
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(24),
              boxShadow: [
                BoxShadow(
                  color: colors.first.withOpacity(0.4),
                  blurRadius: 12,
                  offset: const Offset(0, 6),
                ),
              ],
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(icon, color: Colors.white, size: 42),
                const SizedBox(height: 12),
                Text(
                  title,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                      ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
