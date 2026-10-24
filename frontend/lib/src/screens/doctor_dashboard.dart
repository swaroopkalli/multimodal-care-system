import 'package:flutter/material.dart';

import '../models/care_event.dart';
import '../widgets/metric_tile.dart';
import '../widgets/mini_bar_chart.dart';
import '../widgets/section_card.dart';
import '../widgets/status_chip.dart';
import '../api/api_client.dart';

class DoctorDashboard extends StatelessWidget {
  const DoctorDashboard({super.key});

  static const _patients = [
    _DoctorPatient(
      name: 'Aarav M.',
      age: 16,
      status: RiskLevel.monitor,
      summary: 'Insomnia may increase dropout risk. Adherence stable.',
      adherence: 86,
      stressTrend: [5, 6, 7, 6, 5, 6, 5],
      sleepTrend: [6, 5, 4, 4, 6, 6, 5],
    ),
    _DoctorPatient(
      name: 'Meera S.',
      age: 15,
      status: RiskLevel.normal,
      summary: 'Mood and adherence improving. No high-risk flags.',
      adherence: 93,
      stressTrend: [6, 5, 5, 4, 4, 3, 3],
      sleepTrend: [5, 6, 6, 7, 7, 7, 8],
    ),
    _DoctorPatient(
      name: 'Kabir R.',
      age: 17,
      status: RiskLevel.escalate,
      summary: 'Repeated missed medication and elevated stress require review.',
      adherence: 61,
      stressTrend: [7, 8, 8, 9, 8, 9, 8],
      sleepTrend: [4, 4, 3, 4, 5, 3, 4],
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Doctor Portal'),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const SectionCard(
            title: 'Patients',
            child: Text('Filtered list ordered by clinical review value.'),
          ),
          const SizedBox(height: 12),
          for (final patient in _patients)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                child: ListTile(
                  contentPadding: const EdgeInsets.all(14),
                  leading: CircleAvatar(
                    child: Text(patient.name.characters.first),
                  ),
                  title: Text(patient.name),
                  subtitle: Text('Age ${patient.age} · ${patient.summary}'),
                  trailing: StatusChip(level: patient.status),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => _DoctorPatientDetail(patient: patient),
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
  const _DoctorPatientDetail({required this.patient});

  final _DoctorPatient patient;

  @override
  State<_DoctorPatientDetail> createState() => _DoctorPatientDetailState();
}

class _DoctorPatientDetailState extends State<_DoctorPatientDetail> {
  final ApiClient _apiClient = ApiClient();
  final TextEditingController _noteController = TextEditingController();
  
  bool _isSubmittingNote = false;
  String? _noteMessage;
  
  bool _isLoadingSummary = false;
  String? _aiSummary;

  List<dynamic> _savedNotes = [];
  bool _isLoadingNotes = false;

  @override
  void initState() {
    super.initState();
    _fetchNotes();
  }

  Future<void> _fetchNotes() async {
    setState(() {
      _isLoadingNotes = true;
    });
    try {
      final response = await _apiClient.get('/doctor_notes/1'); // Hardcoded patient_id
      setState(() {
        _savedNotes = response['notes'] ?? [];
      });
    } catch (e) {
      // Ignore errors for now
    } finally {
      setState(() {
        _isLoadingNotes = false;
      });
    }
  }

  @override
  void dispose() {
    _noteController.dispose();
    super.dispose();
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
        'doctor_id': 1, // Hardcoded for demo
        'patient_id': 1, // Hardcoded for demo
        'note': note,
      });
      setState(() {
        _noteMessage = 'Note saved successfully.';
        _noteController.clear();
      });
      _fetchNotes(); // Refresh notes after saving
    } catch (e) {
      setState(() {
        _noteMessage = 'Failed to save note.';
      });
    } finally {
      setState(() {
        _isSubmittingNote = false;
      });
    }
  }

  Future<void> _generateSummary() async {
    setState(() {
      _isLoadingSummary = true;
      _aiSummary = null;
    });

    try {
      final response = await _apiClient.post('/staff/chat', {
        'patient_id': 1, // Hardcoded for demo
        'query': 'Please provide a clinical summary based on recent data.',
      });
      setState(() {
        _aiSummary = response['response'];
      });
    } catch (e) {
      setState(() {
        _aiSummary = 'Error generating summary: $e';
      });
    } finally {
      setState(() {
        _isLoadingSummary = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.patient.name),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SectionCard(
            title: 'Basic Summary',
            action: StatusChip(level: widget.patient.status),
            child: Text(widget.patient.summary),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(
                label: 'Medication',
                value: '${widget.patient.adherence}',
                unit: '%',
                status: widget.patient.adherence >= 80
                    ? RiskLevel.normal
                    : RiskLevel.escalate,
              ),
              MetricTile(
                label: 'Age',
                value: '${widget.patient.age}',
                unit: 'yrs',
                status: RiskLevel.normal,
              ),
            ],
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Stress Trend',
            child: MiniBarChart(
              values: widget.patient.stressTrend,
              labels: const ['M', 'T', 'W', 'T', 'F', 'S', 'S'],
              color: const Color(0xFF14213D),
            ),
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Sleep Trend',
            child: MiniBarChart(
              values: widget.patient.sleepTrend,
              labels: const ['M', 'T', 'W', 'T', 'F', 'S', 'S'],
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
                    child: Text(_aiSummary!),
                  ),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    icon: _isLoadingSummary 
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.analytics),
                    label: const Text('Generate EWMA Summary'),
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
                    labelText: 'Instruction',
                    hintText: 'Example: Review insomnia trend if it persists.',
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(_noteMessage ?? '', style: const TextStyle(color: Colors.green)),
                    ElevatedButton(
                      onPressed: _isSubmittingNote ? null : _submitNote,
                      child: _isSubmittingNote 
                        ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
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
                                      fontSize: 12,
                                      color: Colors.grey,
                                    ),
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

class _DoctorPatient {
  const _DoctorPatient({
    required this.name,
    required this.age,
    required this.status,
    required this.summary,
    required this.adherence,
    required this.stressTrend,
    required this.sleepTrend,
  });

  final String name;
  final int age;
  final RiskLevel status;
  final String summary;
  final int adherence;
  final List<double> stressTrend;
  final List<double> sleepTrend;
}
