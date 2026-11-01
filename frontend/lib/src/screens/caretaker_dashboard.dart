import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../models/care_event.dart';
import '../state/care_state.dart';
import '../widgets/logout_button.dart';
import '../widgets/section_card.dart';
import '../widgets/status_chip.dart';

class CaretakerDashboard extends StatefulWidget {
  const CaretakerDashboard({required this.careState, super.key});

  final CareState careState;

  @override
  State<CaretakerDashboard> createState() => _CaretakerDashboardState();
}

class _CaretakerDashboardState extends State<CaretakerDashboard> {
  int _index = 0;
  bool _didntSleep = false;
  bool _restless = false;
  bool _seemsBetter = false;

  final ApiClient _apiClient = ApiClient();
  List<dynamic> _patients = [];
  int? _patientId;
  Map<String, dynamic>? _overview;
  String? _loadError;

  bool _isLoadingSummary = false;
  String? _ragSummary;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _loadPatients();
  }

  Future<void> _loadPatients() async {
    try {
      final response = await _apiClient.get('/patients');
      if (!mounted) return;
      final list = (response['patients'] as List?) ?? [];
      setState(() {
        _patients = list;
        _patientId = list.isEmpty ? null : list.first['id'] as int;
      });
      await _loadOverview();
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadError = 'Could not load patients: $e');
    }
  }

  Future<void> _loadOverview() async {
    final id = _patientId;
    if (id == null) return;
    try {
      final response = await _apiClient.get('/patients/$id/summary');
      if (!mounted) return;
      setState(() {
        _overview = response;
        _ragSummary = null;
        _loadError = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadError = 'Could not load patient data: $e');
    }
  }

  Future<void> _fetchRagSummary() async {
    final id = _patientId;
    if (id == null) return;
    setState(() {
      _isLoadingSummary = true;
      _ragSummary = null;
    });

    try {
      final response = await _apiClient.post('/staff/chat', {
        'patient_id': id,
        'query': 'Please provide a concise clinical summary of this patient.',
      });
      if (!mounted) return;
      setState(() => _ragSummary = response['response'] as String?);
    } catch (e) {
      if (!mounted) return;
      setState(() => _ragSummary = 'Error fetching summary: $e');
    } finally {
      if (mounted) setState(() => _isLoadingSummary = false);
    }
  }

  Future<void> _saveObservations() async {
    final id = _patientId;
    if (id == null || _isSaving) return;
    setState(() => _isSaving = true);
    try {
      await _apiClient.post('/caretaker/observations', {
        'patient_id': id,
        'did_not_sleep': _didntSleep,
        'restless': _restless,
        'seems_better': _seemsBetter,
        'medication_confirmed': widget.careState.caretakerMedicationConfirmed,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Observations saved.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Could not save observations: $e')));
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }

  List<dynamic> get _anomalies => (_overview?['anomalies'] as List?) ?? [];

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
        actions: const [LogoutButton()],
      ),
      body: Column(
        children: [
          if (_patients.length > 1)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: DropdownButton<int>(
                isExpanded: true,
                value: _patientId,
                items: [
                  for (final p in _patients)
                    DropdownMenuItem(value: p['id'] as int, child: Text(p['name'] as String)),
                ],
                onChanged: (value) {
                  setState(() => _patientId = value);
                  _loadOverview();
                },
              ),
            ),
          Expanded(
            child: AnimatedBuilder(
              animation: widget.careState,
              builder: (context, _) => AnimatedSwitcher(
                duration: const Duration(milliseconds: 260),
                child: pages[_index],
              ),
            ),
          ),
        ],
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

  Widget _noPatient(Key key) {
    return ListView(
      key: key,
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'No patient',
          child: Text(_loadError ??
              'No patients are assigned to you yet. Patients appear here when they '
                  'register with your username as their caretaker.'),
        ),
      ],
    );
  }

  Widget _dashboard(BuildContext context) {
    if (_patientId == null) return _noPatient(const ValueKey('caretaker-dashboard'));
    final live = _overview?['live'] as Map<String, dynamic>?;

    return ListView(
      key: const ValueKey('caretaker-dashboard'),
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Patient Status',
          action: StatusChip(
            level: _anomalies.isEmpty ? RiskLevel.normal : RiskLevel.monitor,
          ),
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
              Text(live == null
                  ? 'No live wearable reading yet.'
                  : 'Latest heart rate ${live['heartrate']} bpm'
                      '${live['is_simulated'] == true ? ' (simulated data)' : ''}.'),
              if (_loadError != null)
                Text(_loadError!, style: const TextStyle(color: Colors.redAccent)),
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
                subtitle: const Text('Saved with your next observation'),
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
                onChanged: (value) => setState(() => _didntSleep = value ?? false),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Restless'),
                value: _restless,
                onChanged: (value) => setState(() => _restless = value ?? false),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Seems better'),
                value: _seemsBetter,
                onChanged: (value) => setState(() => _seemsBetter = value ?? false),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _isSaving ? null : _saveObservations,
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
    if (_patientId == null) return _noPatient(const ValueKey('caretaker-alerts'));
    return ListView(
      key: const ValueKey('caretaker-alerts'),
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Alerts',
          child: _anomalies.isEmpty
              ? const Text('No unusual changes detected against this patient\'s own history.')
              : Column(
                  children: _anomalies
                      .map(
                        (a) => ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.warning_amber),
                          title: Text('${a['signal']} ${a['direction']} on ${a['day']}'),
                          subtitle: Text(
                              'Observed ${(a['observed'] as num).toStringAsFixed(0)}, usual '
                              '${(a['baseline'] as num).toStringAsFixed(0)}'
                              '${a['is_simulated'] == true ? ' · simulated data' : ''}'),
                          trailing: StatusChip(level: RiskLevel.monitor),
                        ),
                      )
                      .toList(),
                ),
        ),
      ],
    );
  }

  Widget _summary(BuildContext context) {
    if (_patientId == null) return _noPatient(const ValueKey('caretaker-rag-summary'));
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
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2))
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
