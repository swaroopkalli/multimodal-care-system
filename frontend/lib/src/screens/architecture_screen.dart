import 'package:flutter/material.dart';

import '../widgets/section_card.dart';

class ArchitectureScreen extends StatelessWidget {
  const ArchitectureScreen({super.key});

  static const _layers = [
    ('Input Layer', 'Patient check-ins, journal, caretaker observations, wearable events'),
    ('Data Layer', 'PostgreSQL (records), Redis (live wearable values), Neo4j (graph + vectors)'),
    ('Wearable Processing', 'Validation, time-aware EWMA smoothing, daily rollups, anomaly detection'),
    ('Guardrails', 'Independent input and output checks: no prescribing, dosing or diagnoses'),
    ('RAG System', 'Patient-scoped Neo4j vector retrieval using NVIDIA NIM embeddings'),
    ('Language Model', 'NVIDIA NIM chat completions with the configured API key'),
    ('Response', 'Diagnostic-support summaries only; clinicians make decisions'),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('System architecture')),
      body: _content(context),
    );
  }

  Widget _content(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'System Positioning',
          child: Text(
            'A multi-actor mental-health monitoring and diagnostic-support system. Smoothed wearable signals and patient-reported data are retrieved per patient to ground NVIDIA NIM chat responses, with independent safety checks around every exchange.',
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
            'Events flow through a Redis Stream, are validated and EWMA-smoothed, stored in PostgreSQL and mirrored to Redis for live reads. Today the events come from a simulator and are labelled as synthetic everywhere; real devices can use the same contract.',
          ),
        ),
        const SizedBox(height: 12),
        const SectionCard(
          title: 'Backend Contract',
          child: Text(
            'Flutter calls authenticated Flask APIs. PostgreSQL is the system of record, Redis serves live vitals, Neo4j serves patient-scoped vector retrieval, and NVIDIA NIM provides chat and embedding inference.',
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
