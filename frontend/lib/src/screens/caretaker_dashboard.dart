import 'package:flutter/material.dart';

import '../data/demo_data.dart';
import '../models/care_event.dart';
import '../services/decision_service.dart';
import '../state/care_state.dart';
import '../widgets/metric_tile.dart';
import '../widgets/mini_bar_chart.dart';
import '../widgets/section_card.dart';
import '../widgets/status_chip.dart';
import '../api/api_client.dart';

class CaretakerDashboard extends StatefulWidget {
  const CaretakerDashboard({required this.careState, super.key});

  final CareState careState;

  @override
  State<CaretakerDashboard> createState() => _CaretakerDashboardState();
}

class _CaretakerDashboardState extends State<CaretakerDashboard> {
  int _index = 0;
  bool _didntSleep = true;
  bool _restless = true;
  bool _seemsBetter = false;

  final ApiClient _apiClient = ApiClient();
  bool _isLoadingSummary = false;
  String? _ragSummary;

  Future<void> _fetchRagSummary() async {
    setState(() {
      _isLoadingSummary = true;
      _ragSummary = null;
    });

    try {
      final response = await _apiClient.post('/staff/chat', {
        'patient_id': 1,
        'query': 'Please provide a concise clinical summary of this patient.',
      });
      setState(() {
        _ragSummary = response['response'];
      });
    } catch (e) {
      setState(() {
        _ragSummary = 'Error fetching summary: $e';
      });
    } finally {
      setState(() {
        _isLoadingSummary = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      _dashboard(context),
      _alerts(context),
      _summary(context),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('Caretaker Portal'),
        centerTitle: true,
      ),
      body: AnimatedBuilder(
        animation: widget.careState,
        builder: (context, _) => AnimatedSwitcher(
          duration: const Duration(milliseconds: 260),
          child: pages[_index],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (value) => setState(() => _index = value),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_customize_outlined),
            selectedIcon: Icon(Icons.dashboard_customize),
            label: 'Dashboard',
          ),
          NavigationDestination(
            icon: Icon(Icons.notifications_active_outlined),
            selectedIcon: Icon(Icons.notifications_active),
            label: 'Alerts',
          ),
          NavigationDestination(
            icon: Icon(Icons.summarize_outlined),
            selectedIcon: Icon(Icons.summarize),
            label: 'RAG Summarize',
          ),
        ],
      ),
    );
  }

  Widget _dashboard(BuildContext context) {
    final snapshot = const DecisionService().evaluate(DemoData.currentLog);

    return ListView(
      key: const ValueKey('caretaker-dashboard'),
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Patient Status',
          action: StatusChip(level: snapshot.riskLevel),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                widget.careState.patientStatus,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
              ),
              const SizedBox(height: 10),
              Text(snapshot.caretakerAlert),
            ],
          ),
        ),
        const SizedBox(height: 12),
        SectionCard(
          title: 'Adherence and Monitoring',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Confirm medication was taken'),
                subtitle: const Text('Shared with patient portal'),
                value: widget.careState.caretakerMedicationConfirmed,
                onChanged: widget.careState.setCaretakerMedicationConfirmed,
              ),
              const Divider(),
              Text(
                'Add observation',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Did not sleep'),
                value: _didntSleep,
                onChanged: (value) =>
                    setState(() => _didntSleep = value ?? false),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Restless'),
                value: _restless,
                onChanged: (value) =>
                    setState(() => _restless = value ?? false),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Seems better'),
                value: _seemsBetter,
                onChanged: (value) =>
                    setState(() => _seemsBetter = value ?? false),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Observations saved.')),
                    );
                  },
                  child: const Text('Save Observations'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _alerts(BuildContext context) {
    return ListView(
      key: const ValueKey('caretaker-alerts'),
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Alerts',
          child: Column(
            children: DemoData.insights
                .map(
                  (insight) => ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(
                      insight.level == RiskLevel.monitor
                          ? Icons.warning_amber
                          : Icons.check_circle_outline,
                    ),
                    title: Text(insight.title),
                    subtitle: Text(insight.body),
                    trailing: StatusChip(level: insight.level),
                  ),
                )
                .toList(),
          ),
        ),
      ],
    );
  }

  Widget _summary(BuildContext context) {
    return ListView(
      key: const ValueKey('caretaker-rag-summary'),
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Patient RAG Summary',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_ragSummary != null) ...[
                Text(_ragSummary!),
                const SizedBox(height: 16),
              ],
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  icon: _isLoadingSummary
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.analytics),
                  label: const Text('Generate Patient Summary'),
                  onPressed: _isLoadingSummary ? null : _fetchRagSummary,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
