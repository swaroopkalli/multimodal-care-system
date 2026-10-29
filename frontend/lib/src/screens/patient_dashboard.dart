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

class PatientDashboard extends StatefulWidget {
  const PatientDashboard({required this.careState, super.key});

  final CareState careState;

  @override
  State<PatientDashboard> createState() => _PatientDashboardState();
}

class _PatientDashboardState extends State<PatientDashboard> {
  int _index = 0;
  double _mood = DemoData.currentLog.mood.toDouble();
  double _sleep = DemoData.currentLog.sleepHours;
  double _stress = 6;
  double _energy = 5;
  bool _breakfast = true;
  final Set<String> _sideEffects = {'Restlessness', 'Mild nausea'};

  final ApiClient _apiClient = ApiClient();
  final List<Map<String, dynamic>> _chatHistory = [
    {'text': 'Hello! I am your wellness coach. How can I support you today?', 'mine': false}
  ];
  final TextEditingController _chatController = TextEditingController();
  bool _isChatLoading = false;

  static const _sideEffectOptions = [
    'Restlessness',
    'Nausea',
    'Headache',
    'Dizziness',
    'Dry mouth',
    'Sleep changes',
    'None',
  ];

  @override
  Widget build(BuildContext context) {
    final pages = [
      _checkIn(context),
      _journal(context),
      _rag(context),
      _progress(context),
    ];

    return Scaffold(
      appBar: AppBar(
        title: DecoratedBox(
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.tertiary.withOpacity(0.15),
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: Theme.of(context).colorScheme.tertiary.withOpacity(0.3)),
          ),
          child: const Padding(
            padding: EdgeInsets.symmetric(horizontal: 12, vertical: 7),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.local_fire_department, color: Color(0xFFE28413)),
                SizedBox(width: 4),
                Text('6 day streak'),
              ],
            ),
          ),
        ),
        centerTitle: true,
      ),
      body: AnimatedSwitcher(
        duration: const Duration(milliseconds: 260),
        child: pages[_index],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (value) => setState(() => _index = value),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.check_circle_outline),
            selectedIcon: Icon(Icons.check_circle),
            label: 'Check-in',
          ),
          NavigationDestination(
            icon: Icon(Icons.edit_note_outlined),
            selectedIcon: Icon(Icons.edit_note),
            label: 'Journal',
          ),
          NavigationDestination(
            icon: Icon(Icons.chat_bubble_outline),
            selectedIcon: Icon(Icons.chat_bubble),
            label: 'Issues & Chat',
          ),
          NavigationDestination(
            icon: Icon(Icons.insights_outlined),
            selectedIcon: Icon(Icons.insights),
            label: 'Progress',
          ),
        ],
      ),
    );
  }

  Widget _checkIn(BuildContext context) {
    final snapshot = const DecisionService().evaluate(DemoData.currentLog);

    return ListView(
      key: const ValueKey('patient-checkin'),
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Daily Check-in',
          action: StatusChip(level: snapshot.riskLevel),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _slider('Mood', _mood, 1, 5,
                  (value) => setState(() => _mood = value)),
              _slider('Stress today', _stress, 0, 10, (value) {
                setState(() => _stress = value);
                widget.careState.setPatientStress(value);
              }),
              _slider('Sleep hours', _sleep, 0, 12,
                  (value) => setState(() => _sleep = value)),
              _slider('Energy', _energy, 0, 10,
                  (value) => setState(() => _energy = value)),
              const SizedBox(height: 16),
              Text(
                'Side effects',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: _sideEffectOptions.map((effect) {
                  final selected = _sideEffects.contains(effect);
                  return FilterChip(
                    label: Text(effect),
                    selected: selected,
                    onSelected: (value) {
                      setState(() {
                        if (effect == 'None') _sideEffects.clear();
                        value
                            ? _sideEffects.add(effect)
                            : _sideEffects.remove(effect);
                      });
                    },
                  );
                }).toList(),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Check-in submitted!')),
                    );
                  },
                  child: const Text('Submit Check-in'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _journal(BuildContext context) {
    return ListView(
      key: const ValueKey('patient-journal'),
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.primary.withOpacity(0.1),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Theme.of(context).colorScheme.primary.withOpacity(0.3)),
          ),
          child: Row(
            children: [
              const Icon(Icons.auto_awesome,
                  color: Color(0xFF256D85), size: 34),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  'Journal to keep your streak alive. One honest sentence is enough.',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        SectionCard(
          title: 'Required Journal',
          child: Column(
            children: [
              TextField(
                minLines: 8,
                maxLines: 12,
                decoration: InputDecoration(
                  labelText: 'Today I noticed...',
                  hintText:
                      'What changed in your body, sleep, mood, thoughts, or routine?',
                ),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Journal entry saved!')),
                    );
                  },
                  child: const Text('Submit Journal'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        const SectionCard(
          title: 'Gentle Prompts',
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              Chip(label: Text('What felt easier?')),
              Chip(label: Text('What felt heavy?')),
              Chip(label: Text('What helped you reset?')),
              Chip(label: Text('Any side effect pattern?')),
            ],
          ),
        ),
      ],
    );
  }

  @override
  void dispose() {
    _chatController.dispose();
    super.dispose();
  }

  Future<void> _sendMessage() async {
    final text = _chatController.text.trim();
    if (text.isEmpty || _isChatLoading) return;

    setState(() {
      _chatHistory.add({'text': text, 'mine': true});
      _chatController.clear();
      _isChatLoading = true;
    });

    try {
      final response = await _apiClient.post('/patient/chat', {
        'patient_id': 1, // Hardcoded for demo since Auth is skipped
        'query': text,
      });
      
      setState(() {
        _chatHistory.add({'text': response['response'] ?? 'No response', 'mine': false});
      });
    } catch (e) {
      setState(() {
        _chatHistory.add({
          'text': 'Error: ${e.toString().replaceAll("Exception: ", "")}',
          'mine': false,
        });
      });
    } finally {
      setState(() {
        _isChatLoading = false;
      });
    }
  }

  Widget _rag(BuildContext context) {
    final snapshot = const DecisionService().evaluate(DemoData.currentLog);

    return ListView(
      key: const ValueKey('patient-rag'),
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Side Effects or Issues Chat',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ..._chatHistory.map((msg) => _ChatBubble(
                    text: msg['text'],
                    mine: msg['mine'],
                  )),
              if (_isChatLoading)
                const Padding(
                  padding: EdgeInsets.only(bottom: 12),
                  child: Center(child: CircularProgressIndicator()),
                ),
              const SizedBox(height: 12),
              TextField(
                controller: _chatController,
                minLines: 2,
                maxLines: 4,
                onSubmitted: (_) => _sendMessage(),
                decoration: InputDecoration(
                  labelText: 'Ask your wellness coach',
                  hintText: 'Example: How can I improve my sleep?',
                  suffixIcon: IconButton(
                    icon: const Icon(Icons.send),
                    onPressed: _sendMessage,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        const SectionCard(
          title: 'View Progress',
          child: Text(
            'Progress combines check-ins, journal consistency, adherence, and sleep trend signals.',
          ),
        ),
      ],
    );
  }

  Widget _progress(BuildContext context) {
    return ListView(
      key: const ValueKey('patient-progress'),
      padding: const EdgeInsets.all(16),
      children: const [
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            MetricTile(
              label: 'Mood Avg',
              value: '3.8',
              unit: '/5',
              status: RiskLevel.normal,
            ),
            MetricTile(
              label: 'Adherence',
              value: '86',
              unit: '%',
              status: RiskLevel.normal,
            ),
            MetricTile(
              label: 'Sleep Avg',
              value: '5.9',
              unit: 'hr',
              status: RiskLevel.monitor,
            ),
          ],
        ),
        SizedBox(height: 12),
        SectionCard(
          title: 'Latest Progress',
          child: Column(
            children: [
              Text(
                'Your wellness check-ins are stabilizing. Sleep duration improved compared to yesterday.',
                style: TextStyle(fontSize: 15),
              ),
              SizedBox(height: 12),
              MiniBarChart(
                values: [7, 6, 8, 5, 6, 4, 5],
                labels: ['M', 'T', 'W', 'T', 'F', 'S', 'Today'],
                color: Color(0xFF7A5CFA),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _slider(
    String label,
    double value,
    double min,
    double max,
    ValueChanged<double> onChanged,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('$label: ${value.toStringAsFixed(value % 1 == 0 ? 0 : 1)}'),
        Slider(
          value: value,
          min: min,
          max: max,
          divisions: (max - min).round(),
          label: value.toStringAsFixed(1),
          onChanged: onChanged,
        ),
      ],
    );
  }
}

class _ChatBubble extends StatelessWidget {
  const _ChatBubble({required this.text, required this.mine});

  final String text;
  final bool mine;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(12),
        constraints: const BoxConstraints(maxWidth: 520),
        decoration: BoxDecoration(
          color: mine
              ? Theme.of(context).colorScheme.primary.withOpacity(0.2)
              : Theme.of(context).cardColor,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0x22FFFFFF)),
        ),
        child: Text(
          text,
          style: TextStyle(
            color: mine ? Theme.of(context).colorScheme.primary : Colors.white,
          ),
        ),
      ),
    );
  }
}
