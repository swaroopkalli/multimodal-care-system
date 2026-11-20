import 'package:flutter/material.dart';

class MiniBarChart extends StatelessWidget {
  const MiniBarChart({
    required this.values,
    required this.labels,
    this.color,
    super.key,
  });

  final List<double> values;
  final List<String> labels;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) {
      return const SizedBox(
        height: 148,
        child: Center(child: Text('No trend data available.')),
      );
    }
    final rawMax = values.reduce((a, b) => a > b ? a : b);
    final max = rawMax > 0 ? rawMax : 1.0;
    final barColor = color ?? Theme.of(context).colorScheme.primary;

    return SizedBox(
      height: 148,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (var i = 0; i < values.length; i++)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    AnimatedContainer(
                      duration: const Duration(milliseconds: 450),
                      height: 92 * (values[i] / max),
                      decoration: BoxDecoration(
                        color: barColor.withValues(alpha: 0.85),
                        borderRadius: BorderRadius.circular(6),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(labels[i],
                        style: Theme.of(context).textTheme.labelSmall),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
