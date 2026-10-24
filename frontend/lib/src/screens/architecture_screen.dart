import 'package:flutter/material.dart';

import '../widgets/section_card.dart';

class ArchitectureScreen extends StatelessWidget {
  const ArchitectureScreen({super.key});

  static const _layers = [
    ('Input Layer', 'Patient check-ins + caretaker validation'),
    ('Data Layer', 'Structured logs, side effects, journal text'),
    ('Rule Engine', 'Safety guardrails and escalation triggers'),
    ('Stress Engine', 'Risk scoring from behavior and simulated signals'),
    ('RAG System', 'FAISS retrieval grounded in onboarding knowledge'),
    ('Decision Layer', 'Normal, Monitor, or Escalate'),
  ];

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'System Positioning',
          child: Text(
            'A modular, multi-actor mental health monitoring system where structured behavioral data drives a rule-based safety engine, while RAG enhances user understanding.',
            style: Theme.of(context).textTheme.bodyLarge,
          ),
        ),
        const SizedBox(height: 12),
        SectionCard(
          title: 'Hybrid Intelligence Architecture',
          child: Column(
            children: _layers
                .map(
                  (layer) => _ArchitectureStep(
                    title: layer.$1,
                    description: layer.$2,
                  ),
                )
                .toList(),
          ),
        ),
        const SizedBox(height: 12),
        const SectionCard(
          title: 'Wearable Strategy',
          child: Text(
            'MVP: manual inputs feed derived signals and simulated wearable values into the same stress engine. Future versions can swap simulated values for real wearable integrations without changing the decision layer.',
          ),
        ),
        const SizedBox(height: 12),
        const SectionCard(
          title: 'Backend Contract',
          child: Text(
            'Flutter calls Flask APIs for logs, decisions, RAG guidance, alerts, and summaries. Supabase stores structured records, FAISS serves local retrieval, and Groq or OpenAI formats grounded responses.',
          ),
        ),
      ],
    );
  }
}

class _ArchitectureStep extends StatelessWidget {
  const _ArchitectureStep({
    required this.title,
    required this.description,
  });

  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 34,
            height: 34,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primaryContainer,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(
              Icons.arrow_downward,
              size: 18,
              color: Theme.of(context).colorScheme.onPrimaryContainer,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                ),
                const SizedBox(height: 3),
                Text(description),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
