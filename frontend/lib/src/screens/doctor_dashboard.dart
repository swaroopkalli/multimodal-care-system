import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../models/care_event.dart';
import '../widgets/logout_button.dart';
import '../widgets/metric_tile.dart';
import '../widgets/mini_bar_chart.dart';
import '../widgets/section_card.dart';
import '../widgets/status_chip.dart';
import '../widgets/formatted_text.dart';

class DoctorDashboard extends StatefulWidget {
  const DoctorDashboard({super.key});

  @override
  State<DoctorDashboard> createState() => _DoctorDashboardState();
}

class _DoctorDashboardState extends State<DoctorDashboard> {
  final ApiClient _apiClient = ApiClient();
  List<dynamic> _patients = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await _apiClient.get('/patients');
      if (!mounted) return;
      setState(() => _patients = (response['patients'] as List?) ?? []);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'Could not load patients: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Doctor Portal'),
        centerTitle: true,
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
          const LogoutButton(),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const SectionCard(
            title: 'Patients',
            child: Text('Patients assigned to you. A flag means the wearable data changed '
                'noticeably from the patient\'s own history in the last 7 days.'),
          ),
          const SizedBox(height: 12),
          if (_loading) const Center(child: CircularProgressIndicator()),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: Colors.redAccent)),
          if (!_loading && _error == null && _patients.isEmpty)
            const SectionCard(
              title: 'No patients yet',
              child: Text('Patients appear here when they register with your username '
                  'as their doctor.'),
            ),
          for (final p in _patients)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                child: ListTile(
                  contentPadding: const EdgeInsets.all(14),
                  leading: CircleAvatar(
                    child: Text((p['name'] as String).characters.first.toUpperCase()),
                  ),
                  title: Text(p['name'] as String),
                  subtitle: Text(p['last_reading'] == null
                      ? 'No wearable data yet'
                      : 'Last reading ${(p['last_reading'] as String).split('.').first.replaceFirst('T', ' ')} UTC'),
                  trailing: StatusChip(
                    level: (p['recent_anomalies'] as int) > 0
                        ? RiskLevel.monitor
                        : RiskLevel.normal,
                  ),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => _DoctorPatientDetail(
                        patientId: p['id'] as int,
                        name: p['name'] as String,
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _DoctorPatientDetail extends StatefulWidget {
  const _DoctorPatientDetail({required this.patientId, required this.name});

  final int patientId;
  final String name;

  @override
  State<_DoctorPatientDetail> createState() => _DoctorPatientDetailState();
}

class _DoctorPatientDetailState extends State<_DoctorPatientDetail> {
  final ApiClient _apiClient = ApiClient();
  final TextEditingController _noteController = TextEditingController();

  bool _isSubmittingNote = false;
  String? _noteMessage;
  bool _noteFailed = false;

  bool _isLoadingSummary = false;
  String? _aiSummary;

  List<dynamic> _savedNotes = [];
  bool _isLoadingNotes = false;
  String? _notesError;

  Map<String, dynamic>? _summary;
  String? _summaryError;

  @override
  void initState() {
    super.initState();
    _fetchNotes();
    _fetchSummary();
  }

  @override
  void dispose() {
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _fetchSummary() async {
    try {
      final response = await _apiClient.get('/patients/${widget.patientId}/summary');
      if (!mounted) return;
      setState(() => _summary = response);
    } catch (e) {
      if (!mounted) return;
      setState(() => _summaryError = 'Could not load wearable summary: $e');
    }
  }

  Future<void> _fetchNotes() async {
    setState(() {
      _isLoadingNotes = true;
      _notesError = null;
    });
    try {
      final response = await _apiClient.get('/doctor_notes/${widget.patientId}');
      if (!mounted) return;
      setState(() => _savedNotes = (response['notes'] as List?) ?? []);
    } catch (e) {
      if (!mounted) return;
      setState(() => _notesError = 'Could not load notes: $e');
    } finally {
      if (mounted) setState(() => _isLoadingNotes = false);
    }
  }

  Future<void> _submitNote() async {
    final note = _noteController.text.trim();
    if (note.isEmpty) return;

    setState(() {
      _isSubmittingNote = true;
      _noteMessage = null;
    });

    try {
      await _apiClient.post('/doctor_notes', {
        'patient_id': widget.patientId,
        'note': note,
      });
      if (!mounted) return;
      setState(() {
        _noteFailed = false;
        _noteMessage = 'Note saved successfully.';
        _noteController.clear();
      });
      _fetchNotes();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _noteFailed = true;
        _noteMessage = 'Failed to save note: $e';
      });
    } finally {
      if (mounted) setState(() => _isSubmittingNote = false);
    }
  }

  Future<void> _generateSummary() async {
    setState(() {
      _isLoadingSummary = true;
      _aiSummary = null;
    });

    try {
      final response = await _apiClient.post('/staff/chat', {
        'patient_id': widget.patientId,
        'query': 'Please provide a clinical summary based on recent data.',
      });
      if (!mounted) return;
      setState(() => _aiSummary = response['response'] as String?);
    } catch (e) {
      if (!mounted) return;
      setState(() => _aiSummary = 'Error generating summary: $e');
    } finally {
      if (mounted) setState(() => _isLoadingSummary = false);
    }
  }

  List<dynamic> get _daily => (_summary?['daily'] as List?) ?? [];
  List<dynamic> get _anomalies => (_summary?['anomalies'] as List?) ?? [];

  List<String> _dayLabels() =>
      _daily.map((d) => (d['day'] as String).substring(8)).toList();

  @override
  Widget build(BuildContext context) {
    final live = _summary?['live'] as Map<String, dynamic>?;
    final simulated = _daily.any((d) => d['is_simulated'] == true);
    final sleepValues = _daily
        .map((d) => d['sleep_minutes'] == null ? 0.0 : (d['sleep_minutes'] as num) / 60.0)
        .toList()
        .cast<double>();
    final hrValues = _daily
        .map((d) => d['hr_mean'] == null ? 0.0 : (d['hr_mean'] as num).toDouble())
        .toList()
        .cast<double>();

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.name),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SectionCard(
            title: 'Wearable status',
            action: StatusChip(
              level: _anomalies.isEmpty ? RiskLevel.normal : RiskLevel.monitor,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_summaryError != null)
                  Text(_summaryError!, style: const TextStyle(color: Colors.redAccent))
                else if (_summary == null)
                  const Center(child: CircularProgressIndicator())
                else ...[
                  Text(live == null
                      ? 'No live reading yet.'
                      : 'Latest heart rate ${live['heartrate']} bpm '
                          '(smoothed ${live['heartrate_ewma'] == null ? 'n/a' : (live['heartrate_ewma'] as num).toStringAsFixed(0)} bpm)'),
                  if (simulated || live?['is_simulated'] == true)
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Text('Includes SIMULATED (synthetic) data.',
                          style: TextStyle(color: Colors.amber)),
                    ),
                  const SizedBox(height: 8),
                  if (_anomalies.isEmpty)
                    const Text('No unusual changes detected against this patient\'s own history.')
                  else
                    for (final a in _anomalies)
                      Text('• ${a['day']}: ${a['signal']} ${a['direction']} '
                          '(${a['severity']}${a['is_simulated'] == true ? ', simulated' : ''})'),
                ],
              ],
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(
                label: 'Medications',
                value: '${_summary?['medication_count'] ?? 0}',
                unit: 'recorded',
                status: RiskLevel.normal,
              ),
              MetricTile(
                label: 'Anomalies',
                value: '${_anomalies.length}',
                unit: 'recent',
                status: _anomalies.isEmpty ? RiskLevel.normal : RiskLevel.monitor,
              ),
            ],
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Mean heart rate (bpm, by day)',
            child: hrValues.isEmpty
                ? const Text('No daily data yet.')
                : MiniBarChart(
                    values: hrValues,
                    labels: _dayLabels(),
                    color: const Color(0xFF14213D),
                  ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Sleep (hours, by day)',
            child: sleepValues.isEmpty
                ? const Text('No daily data yet.')
                : MiniBarChart(
                    values: sleepValues,
                    labels: _dayLabels(),
                    color: const Color(0xFF256D85),
                  ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'AI Clinical Analysis',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_aiSummary != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: FormattedText(
                      _aiSummary!,
                      style: const TextStyle(fontSize: 14, height: 1.4),
                    ),
                  ),
                const Text(
                  'Diagnostic support only: it summarises records and trends and never '
                  'recommends medication or treatment.',
                  style: TextStyle(fontSize: 12, color: Colors.grey),
                ),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    icon: _isLoadingSummary
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.analytics),
                    label: const Text('Generate Summary'),
                    onPressed: _isLoadingSummary ? null : _generateSummary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Add Clinical Note',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: _noteController,
                  minLines: 3,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    labelText: 'Note',
                    hintText: 'Example: Review insomnia trend if it persists.',
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        _noteMessage ?? '',
                        style: TextStyle(
                            color: _noteFailed ? Colors.redAccent : Colors.green),
                      ),
                    ),
                    ElevatedButton(
                      onPressed: _isSubmittingNote ? null : _submitNote,
                      child: _isSubmittingNote
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Save Note'),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Saved Clinical Notes',
            child: _isLoadingNotes
                ? const Center(child: CircularProgressIndicator())
                : _notesError != null
                    ? Text(_notesError!, style: const TextStyle(color: Colors.redAccent))
                    : _savedNotes.isEmpty
                        ? const Text('No notes saved yet.')
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: _savedNotes.map((note) {
                              final dateStr = note['created_at'] != null
                                  ? note['created_at'].toString().split('T')[0]
                                  : 'Unknown date';
                              return Padding(
                                padding: const EdgeInsets.only(bottom: 8.0),
                                child: Container(
                                  width: double.infinity,
                                  padding: const EdgeInsets.all(12),
                                  decoration: BoxDecoration(
                                    color: Theme.of(context).cardColor,
                                    borderRadius: BorderRadius.circular(12),
                                    border: Border.all(color: const Color(0x22FFFFFF)),
                                  ),
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        dateStr,
                                        style: const TextStyle(
                                            fontSize: 12, color: Colors.grey),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(note['note'] ?? ''),
                                    ],
                                  ),
                                ),
                              );
                            }).toList(),
                          ),
          ),
        ],
      ),
    );
  }
}
