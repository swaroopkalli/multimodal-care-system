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
  List<dynamic> _alerts = [];
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
      Map<String, dynamic> alertsRes = {};
      try {
        alertsRes = await _apiClient.get('/alerts');
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _patients = (response['patients'] as List?) ?? [];
        _alerts = (alertsRes['alerts'] as List?) ?? [];
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'Could not load portal data: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _acknowledgeAlert(int alertId) async {
    try {
      await _apiClient.post('/alerts/$alertId/acknowledge', {});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed to acknowledge: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final unackAlerts = _alerts.where((a) => a['is_acknowledged'] == false).toList();

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
          if (unackAlerts.isNotEmpty) ...[
            SectionCard(
              title: 'Active Clinical Alerts (${unackAlerts.length})',
              action: StatusChip(level: RiskLevel.escalate),
              child: Column(
                children: unackAlerts.map<Widget>((a) {
                  final isCrit = a['severity'] == 'critical';
                  final created = a['created_at'] != null
                      ? (a['created_at'] as String).replaceFirst('T', ' ').split('.').first
                      : '';
                  return Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: isCrit ? Colors.red.withOpacity(0.1) : Colors.amber.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                        color: isCrit ? Colors.red.withOpacity(0.4) : Colors.amber.withOpacity(0.4),
                      ),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          isCrit ? Icons.error_outline : Icons.warning_amber,
                          color: isCrit ? Colors.redAccent : Colors.amber,
                          size: 24,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                    '${a['patient_name'] ?? 'Patient'} · ${(a['alert_type'] ?? 'alert').toString().replaceAll('_', ' ').toUpperCase()}',
                                    style: TextStyle(
                                      fontWeight: FontWeight.bold,
                                      fontSize: 13,
                                      color: isCrit ? Colors.redAccent : Colors.amber,
                                    ),
                                  ),
                                  Text(
                                    created,
                                    style: const TextStyle(fontSize: 11, color: Colors.grey),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(a['message'] ?? '', style: const TextStyle(fontSize: 13)),
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        ElevatedButton(
                          style: ElevatedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                            visualDensity: VisualDensity.compact,
                          ),
                          onPressed: () => _acknowledgeAlert(a['id'] as int),
                          child: const Text('Acknowledge', style: TextStyle(fontSize: 12)),
                        ),
                      ],
                    ),
                  );
                }).toList(),
              ),
            ),
            const SizedBox(height: 12),
          ],
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
  final TextEditingController _directiveController = TextEditingController();

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

  List<dynamic> _directives = [];
  bool _isLoadingDirectives = false;
  bool _isSubmittingDirective = false;

  List<dynamic> _patientJournals = [];
  bool _isLoadingJournals = false;
  final Map<int, TextEditingController> _replyControllers = {};
  int? _submittingReplyId;

  List<dynamic> _chatLogs = [];
  bool _isLoadingChatLogs = false;

  String? _chatDigest;
  List<dynamic> _flaggedExchanges = [];
  bool _isLoadingDigest = false;

  @override
  void initState() {
    super.initState();
    _fetchNotes();
    _fetchSummary();
    _fetchDirectives();
    _fetchPatientJournals();
    _fetchChatDigest();
    _fetchChatHistory();
  }

  @override
  void dispose() {
    _noteController.dispose();
    _directiveController.dispose();
    for (final c in _replyControllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _fetchDirectives() async {
    setState(() => _isLoadingDirectives = true);
    try {
      final res = await _apiClient.get('/patients/${widget.patientId}/directives');
      if (!mounted) return;
      setState(() => _directives = (res['directives'] as List?) ?? []);
    } catch (_) {
    } finally {
      if (mounted) setState(() => _isLoadingDirectives = false);
    }
  }

  Future<void> _submitDirective() async {
    final text = _directiveController.text.trim();
    if (text.isEmpty || _isSubmittingDirective) return;
    setState(() => _isSubmittingDirective = true);
    try {
      await _apiClient.post('/doctor/directives', {
        'patient_id': widget.patientId,
        'directive': text,
      });
      _directiveController.clear();
      _fetchDirectives();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed to save directive: $e')));
    } finally {
      if (mounted) setState(() => _isSubmittingDirective = false);
    }
  }

  Future<void> _fetchPatientJournals() async {
    setState(() => _isLoadingJournals = true);
    try {
      final res = await _apiClient.get('/patients/${widget.patientId}/journals');
      if (!mounted) return;
      setState(() => _patientJournals = (res['journals'] as List?) ?? []);
    } catch (_) {
    } finally {
      if (mounted) setState(() => _isLoadingJournals = false);
    }
  }

  Future<void> _submitJournalReply(int journalId) async {
    final controller = _replyControllers[journalId];
    final text = controller?.text.trim() ?? '';
    if (text.isEmpty || _submittingReplyId != null) return;
    setState(() => _submittingReplyId = journalId);
    try {
      await _apiClient.post('/doctor/journal_reply', {
        'journal_id': journalId,
        'reply': text,
      });
      controller?.clear();
      _fetchPatientJournals();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed to send reply: $e')));
    } finally {
      if (mounted) setState(() => _submittingReplyId = null);
    }
  }

  Future<void> _fetchChatHistory() async {
    setState(() => _isLoadingChatLogs = true);
    try {
      final res = await _apiClient.get('/patients/${widget.patientId}/chat_history');
      if (!mounted) return;
      setState(() => _chatLogs = (res['chat_history'] as List?) ?? []);
    } catch (_) {
    } finally {
      if (mounted) setState(() => _isLoadingChatLogs = false);
    }
  }

  Future<void> _fetchChatDigest() async {
    setState(() => _isLoadingDigest = true);
    try {
      final res = await _apiClient.get('/patients/${widget.patientId}/chat_digest');
      if (!mounted) return;
      setState(() {
        _chatDigest = res['digest'] as String?;
        _flaggedExchanges = (res['flagged_exchanges'] as List?) ?? [];
      });
    } catch (_) {
    } finally {
      if (mounted) setState(() => _isLoadingDigest = false);
    }
  }

  Color _categoryColor(String category) {
    switch (category) {
      case 'Crisis / Escalation':
        return Colors.redAccent;
      case 'Anxiety / Distress':
        return Colors.orangeAccent;
      case 'Sleep Disruption':
        return Colors.lightBlueAccent;
      case 'Physical Symptom':
        return Colors.amberAccent;
      case 'Medication Query':
        return Colors.purpleAccent;
      default:
        return Colors.tealAccent;
    }
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
          const SizedBox(height: 12),
          SectionCard(
            title: 'Patient Care Directives (AI Steering)',
            action: const Icon(Icons.psychology, color: Color(0xFF256D85)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Directives set here are embedded directly into the AI companion prompts at Priority 0. '
                  'The AI will actively steer its tone and guidance to respect your clinical instructions.',
                  style: TextStyle(fontSize: 12, color: Colors.grey),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _directiveController,
                  minLines: 2,
                  maxLines: 4,
                  decoration: const InputDecoration(
                    labelText: 'New Care Directive',
                    hintText: 'e.g. Focus on sleep routine; encourage breathing exercises; avoid vigorous activity.',
                  ),
                ),
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerRight,
                  child: ElevatedButton.icon(
                    icon: _isSubmittingDirective
                        ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.add, size: 16),
                    label: const Text('Save Directive'),
                    onPressed: _isSubmittingDirective ? null : _submitDirective,
                  ),
                ),
                const SizedBox(height: 12),
                if (_isLoadingDirectives)
                  const Center(child: CircularProgressIndicator())
                else if (_directives.isEmpty)
                  const Text('No active care directives set for this patient.', style: TextStyle(color: Colors.grey, fontSize: 13))
                else
                  Column(
                    children: _directives.map<Widget>((d) {
                      final dateStr = d['created_at'] != null
                          ? (d['created_at'] as String).replaceFirst('T', ' ').split('.').first
                          : '';
                      return Container(
                        width: double.infinity,
                        margin: const EdgeInsets.only(bottom: 8),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Theme.of(context).cardColor,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: Colors.teal.withOpacity(0.3)),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text(
                                  'Active Directive · $dateStr',
                                  style: const TextStyle(fontSize: 11, color: Colors.teal, fontWeight: FontWeight.bold),
                                ),
                                const Icon(Icons.check_circle, size: 14, color: Colors.teal),
                              ],
                            ),
                            const SizedBox(height: 6),
                            Text(d['directive'] ?? '', style: const TextStyle(fontSize: 13)),
                          ],
                        ),
                      );
                    }).toList(),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Patient Journals & Doctor Remarks',
            action: const Icon(Icons.rate_review, color: Color(0xFF256D85)),
            child: _isLoadingJournals
                ? const Center(child: CircularProgressIndicator())
                : _patientJournals.isEmpty
                    ? const Text('No journal entries submitted by this patient yet.', style: TextStyle(color: Colors.grey, fontSize: 13))
                    : Column(
                        children: _patientJournals.map<Widget>((j) {
                          final id = j['id'] as int;
                          final entryDate = j['created_at'] != null
                              ? (j['created_at'] as String).replaceFirst('T', ' ').split('.').first
                              : '';
                          final reply = j['doctor_reply'] as String?;
                          final replyAt = j['doctor_reply_at'] != null
                              ? (j['doctor_reply_at'] as String).replaceFirst('T', ' ').split('.').first
                              : '';

                          if (!_replyControllers.containsKey(id)) {
                            _replyControllers[id] = TextEditingController();
                          }

                          return Container(
                            width: double.infinity,
                            margin: const EdgeInsets.only(bottom: 12),
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: Theme.of(context).cardColor,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: const Color(0x22FFFFFF)),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Text(entryDate, style: const TextStyle(fontSize: 11, color: Colors.grey, fontWeight: FontWeight.bold)),
                                    if (reply != null)
                                      const Text('Replied', style: TextStyle(fontSize: 11, color: Colors.teal, fontWeight: FontWeight.bold))
                                    else
                                      const Text('Needs Reply', style: TextStyle(fontSize: 11, color: Colors.amber, fontWeight: FontWeight.bold)),
                                  ],
                                ),
                                const SizedBox(height: 6),
                                Text(j['entry'] ?? '', style: const TextStyle(fontSize: 13)),
                                if (reply != null) ...[
                                  const SizedBox(height: 8),
                                  Container(
                                    width: double.infinity,
                                    padding: const EdgeInsets.all(10),
                                    decoration: BoxDecoration(
                                      color: Colors.teal.withOpacity(0.08),
                                      borderRadius: BorderRadius.circular(8),
                                      border: Border.all(color: Colors.teal.withOpacity(0.3)),
                                    ),
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text('Your Remark ($replyAt):', style: const TextStyle(fontSize: 11, color: Colors.teal, fontWeight: FontWeight.bold)),
                                        const SizedBox(height: 4),
                                        Text(reply, style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic)),
                                      ],
                                    ),
                                  ),
                                ] else ...[
                                  const SizedBox(height: 8),
                                  TextField(
                                    controller: _replyControllers[id],
                                    minLines: 1,
                                    maxLines: 3,
                                    decoration: const InputDecoration(
                                      labelText: 'Write clinical remark for patient',
                                      hintText: 'e.g. Acknowledged, please continue resting.',
                                    ),
                                  ),
                                  const SizedBox(height: 6),
                                  Align(
                                    alignment: Alignment.centerRight,
                                    child: ElevatedButton(
                                      onPressed: _submittingReplyId == id ? null : () => _submitJournalReply(id),
                                      child: _submittingReplyId == id
                                          ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                          : const Text('Send Remark', style: TextStyle(fontSize: 12)),
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          );
                        }).toList(),
                      ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'AI Chat Digest & Clinical Synthesis',
            action: IconButton(
              icon: const Icon(Icons.refresh, size: 20),
              onPressed: _fetchChatDigest,
              tooltip: 'Refresh Digest',
            ),
            child: _isLoadingDigest
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(16),
                      child: CircularProgressIndicator(),
                    ),
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Executive 7-Day Synthesis',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF256D85),
                        ),
                      ),
                      const SizedBox(height: 6),
                      FormattedText(
                        _chatDigest ?? 'No patient chat interactions recorded.',
                        style: const TextStyle(fontSize: 13, height: 1.4),
                      ),
                      if (_flaggedExchanges.isNotEmpty) ...[
                        const SizedBox(height: 14),
                        Row(
                          children: [
                            const Icon(Icons.flag, size: 14, color: Colors.amber),
                            const SizedBox(width: 6),
                            Text(
                              'Flagged Clinical Exchanges (${_flaggedExchanges.length})',
                              style: const TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        ..._flaggedExchanges.map<Widget>((fx) {
                          final cat = fx['category'] as String? ?? 'General';
                          final color = _categoryColor(cat);
                          final ts = fx['created_at'] != null
                              ? (fx['created_at'] as String).replaceFirst('T', ' ').split('.').first
                              : '';
                          return Container(
                            width: double.infinity,
                            margin: const EdgeInsets.only(bottom: 8),
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: color.withOpacity(0.08),
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(color: color.withOpacity(0.3)),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: color.withOpacity(0.2),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: Text(
                                        cat,
                                        style: TextStyle(
                                          fontSize: 10,
                                          fontWeight: FontWeight.bold,
                                          color: color,
                                        ),
                                      ),
                                    ),
                                    Text(ts, style: const TextStyle(fontSize: 10, color: Colors.grey)),
                                  ],
                                ),
                                const SizedBox(height: 6),
                                RichText(
                                  text: TextSpan(
                                    style: const TextStyle(fontSize: 12, color: Colors.white70),
                                    children: [
                                      const TextSpan(
                                        text: 'Patient: ',
                                        style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
                                      ),
                                      TextSpan(text: '${fx['query']}\n'),
                                      const TextSpan(
                                        text: 'AI Coach: ',
                                        style: TextStyle(fontWeight: FontWeight.bold, color: Colors.tealAccent),
                                      ),
                                      TextSpan(text: fx['response'] ?? ''),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          );
                        }).toList(),
                      ],
                    ],
                  ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Raw Chat Transcript (${_chatLogs.length} turns)',
            child: Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                initiallyExpanded: false,
                tilePadding: EdgeInsets.zero,
                title: const Text(
                  'Inspect Full Chat History',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                ),
                subtitle: const Text(
                  'Turn-by-turn log with AI wellness companion',
                  style: TextStyle(fontSize: 11, color: Colors.grey),
                ),
                children: [
                  const SizedBox(height: 8),
                  if (_isLoadingChatLogs)
                    const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()))
                  else if (_chatLogs.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: Text('No patient chat interactions logged yet.', style: TextStyle(color: Colors.grey, fontSize: 13)),
                    )
                  else
                    Column(
                      children: _chatLogs.take(20).map<Widget>((log) {
                        final ts = log['timestamp'] != null
                            ? (log['timestamp'] as String).replaceFirst('T', ' ').split('.').first
                            : '';
                        return Container(
                          width: double.infinity,
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: Theme.of(context).cardColor,
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: const Color(0x15FFFFFF)),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(ts, style: const TextStyle(fontSize: 10, color: Colors.grey)),
                              const SizedBox(height: 4),
                              RichText(
                                text: TextSpan(
                                  style: const TextStyle(fontSize: 12, color: Colors.white70),
                                  children: [
                                    const TextSpan(text: 'Patient: ', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white)),
                                    TextSpan(text: '${log['query']}\n\n'),
                                    const TextSpan(text: 'AI Companion: ', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.tealAccent)),
                                    TextSpan(text: log['response'] ?? ''),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        );
                      }).toList(),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
