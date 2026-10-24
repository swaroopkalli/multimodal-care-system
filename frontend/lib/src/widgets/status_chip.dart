import 'package:flutter/material.dart';

import '../models/care_event.dart';

class StatusChip extends StatelessWidget {
  const StatusChip({required this.level, super.key});

  final RiskLevel level;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (level) {
      RiskLevel.normal => ('Normal', const Color(0xFF1B7F5C)),
      RiskLevel.monitor => ('Monitor', const Color(0xFFE28413)),
      RiskLevel.escalate => ('Escalate', const Color(0xFFC92A2A)),
    };

    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(24),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Text(
          label,
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: color,
                fontWeight: FontWeight.w700,
              ),
        ),
      ),
    );
  }
}
