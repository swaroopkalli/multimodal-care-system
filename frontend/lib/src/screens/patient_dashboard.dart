import 'dart:async';

import 'package:flutter/material.dart';

import '../models/care_event.dart';
import '../state/care_state.dart';
import '../widgets/logout_button.dart';
import '../widgets/metric_tile.dart';
import '../widgets/mini_bar_chart.dart';
import '../widgets/section_card.dart';
import '../widgets/status_chip.dart';
import '../widgets/formatted_text.dart';
import '../api/api_client.dart';

class PatientDashboard extends StatefulWidget {
  const PatientDashboard({required this.careState, super.key});

  final CareState careState;

  @override
  State<PatientDashboard> createState() => _PatientDashboardState();
}

class _PatientDashboardState extends State<PatientDashboard> {
  int _index = 0;

  final ApiClient _apiClient = ApiClient();
  final List<Map<String, dynamic>> _chatHistory = [
    {'text': 'Hello! I am your wellness coach. How can I support you today?', 'mine': false}
  ];
  final TextEditingController _chatController = TextEditingController();
  final TextEditingController _journalController = TextEditingController();
  bool _isChatLoading = false;
  bool _isSubmitting = false;

  int? _patientId;
  Map<String, dynamic>? _summary;
  Map<String, dynamic>? _liveVitals;
  List<dynamic> _recentVitals = [];
  Timer? _vitalsTimer;
  bool _isLoadingSummary = false;
  String? _summaryError;
  String _chartMetric = 'sleep';

  @override
  void initState() {
    super.initState();
    widget.careState.addListener(_onCareStateChanged);
    _fetchSummary();
    _fetchLiveVitals();
    _vitalsTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (mounted) _fetchLiveVitals();
    });
  }

  void _onCareStateChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _fetchSummary() async {
    setState(() {
      _isLoadingSummary = true;
      _summaryError = null;
    });
    try {
      if (_patientId == null) {
        final patientsRes = await _apiClient.get('/patients');
        final list = (patientsRes['patients'] as List?) ?? [];
        if (list.isNotEmpty) {
          _patientId = list.first['id'] as int;
        }
      }
      if (_patientId != null) {
        final summary = await _apiClient.get('/patients/$_patientId/summary');
        if (!mounted) return;
        setState(() {
          _summary = summary;
          if (_liveVitals == null && summary['live'] != null) {
            _liveVitals = summary['live'] as Map<String, dynamic>?;
          }
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _summaryError = 'Could not load progress data: $e');
    } finally {
      if (mounted) setState(() => _isLoadingSummary = false);
    }
  }

  Future<void> _fetchLiveVitals() async {
    try {
      if (_patientId == null) {
        final patientsRes = await _apiClient.get('/patients');
        final list = (patientsRes['patients'] as List?) ?? [];
        if (list.isNotEmpty) {
          _patientId = list.first['id'] as int;
        }
      }
      if (_patientId != null) {
        final res = await _apiClient.get('/patients/$_patientId/vitals/live?recent=15');
        if (!mounted) return;
        setState(() {
          _liveVitals = res['latest'] as Map<String, dynamic>?;
          _recentVitals = (res['recent'] as List?) ?? [];
        });
      }
    } catch (_) {
      // background telemetry poll; avoid snackbar disruption
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _submitJournal() async {
    final text = _journalController.text.trim();
    if (text.isEmpty || _isSubmitting) {
      if (text.isEmpty) _toast('Write a sentence first.');
      return;
    }
    setState(() => _isSubmitting = true);
    try {
      await _apiClient.post('/patient/journal', {'entry': text});
      _journalController.clear();
      _toast('Journal entry saved.');
      _fetchSummary();
    } catch (e) {
      _toast('Could not save journal entry: $e');
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      _wearables(context),
      _journal(context),
      _rag(context),
      _progress(context),
    ];

    return Scaffold(
      appBar: AppBar(
        centerTitle: true,
        actions: const [LogoutButton()],
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
            icon: Icon(Icons.sensors_outlined),
            selectedIcon: Icon(Icons.sensors),
            label: 'Wearables',
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

  Widget _wearables(BuildContext context) {
    final live = _liveVitals;
    final hr = live?['heartrate'];
    final hrEwma = live?['heartrate_ewma'];
    final pedometer = live?['pedometer'];
    final pedEwma = live?['pedometer_ewma'];
    final sleepMin = live?['sleep_minutes'];
    final screenMin = live?['screentime_minutes'];
    final measuredAt = live?['measured_at'] as String?;
    final source = live?['source'] as String? ?? 'redis';
    final isSim = live?['is_simulated'] == true;
    final qualityFlags = (live?['quality_flags'] as List?) ?? [];

    String timeLabel = 'Connecting to Redis...';
    if (measuredAt != null && measuredAt.length >= 19) {
      try {
        final dt = DateTime.parse(measuredAt).toLocal();
        timeLabel =
            '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}:${dt.second.toString().padLeft(2, '0')}';
      } catch (_) {
        timeLabel = measuredAt.substring(11, 19);
      }
    }

    final hrRisk = hr == null
        ? RiskLevel.normal
        : (hr > 110 || hr < 50
            ? RiskLevel.escalate
            : (hr > 95 || hr < 60 ? RiskLevel.monitor : RiskLevel.normal));
    final sleepRisk = sleepMin == null
        ? RiskLevel.normal
        : (sleepMin < 300 ? RiskLevel.monitor : RiskLevel.normal);

    return RefreshIndicator(
      onRefresh: () async {
        await _fetchLiveVitals();
        await _fetchSummary();
      },
      child: ListView(
        key: const ValueKey('patient-wearables'),
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              color: Theme.of(context).cardColor,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: const Color(0x22FFFFFF), width: 1.5),
            ),
            child: Row(
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: live != null ? const Color(0xFF1B7F5C) : Colors.amber,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Text(
                      //   live != null
                      //       ? 'Live Wearable Stream'
                      //       : 'Connecting to Wearable Stream...',
                      //   style: const TextStyle(
                      //       fontWeight: FontWeight.w700, fontSize: 15),
                      // ),
                      Text(
                        live != null
                            ? 'Last Event: $timeLabel${isSim ? ' (Simulated)' : ''}'
                            : 'Waiting for Redis telemetry events',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
                StatusChip(
                    level: live != null ? RiskLevel.normal : RiskLevel.monitor),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(
                label: 'Heart Rate',
                value: hr != null ? '$hr' : '--',
                unit: 'bpm',
                status: hrRisk,
              ),
              MetricTile(
                label: 'Pedometer',
                value: pedometer != null ? '$pedometer' : '--',
                unit: 'steps',
                status: RiskLevel.normal,
              ),
              MetricTile(
                label: 'Sleep Duration',
                value: sleepMin != null
                    ? ((sleepMin as num) / 60.0).toStringAsFixed(1)
                    : '--',
                unit: 'hr',
                status: sleepRisk,
              ),
              // MetricTile(
              //   label: 'Screen Time',
              //   value: screenMin != null
              //       ? ((screenMin as num) / 60.0).toStringAsFixed(1)
              //       : '--',
              //   unit: 'hr',
              //   status: RiskLevel.normal,
              // ),
            ],
          ),
          const SizedBox(height: 14),
          // SectionCard(
          //   title: 'Current Event Telemetry (Redis)',
          //   child: Column(
          //     crossAxisAlignment: CrossAxisAlignment.start,
          //     children: [
          //       _telemetryRow(
          //           'Heart Rate (Raw)', hr != null ? '$hr bpm' : '--'),
          //       _telemetryRow(
          //           'Heart Rate (EWMA Smoothed)',
          //           hrEwma != null
          //               ? '${(hrEwma as num).toStringAsFixed(1)} bpm'
          //               : '--'),
          //       const Divider(height: 16),
          //       _telemetryRow('Pedometer (Interval Steps)',
          //           pedometer != null ? '$pedometer steps' : '--'),
          //       _telemetryRow(
          //           'Pedometer (EWMA Smoothed)',
          //           pedEwma != null
          //               ? '${(pedEwma as num).toStringAsFixed(1)} steps'
          //               : '--'),
          //       const Divider(height: 16),
          //       _telemetryRow(
          //           'Sleep Session',
          //           sleepMin != null
          //               ? '$sleepMin min (${((sleepMin as num) / 60.0).toStringAsFixed(1)} hr)'
          //               : '--'),
          //       _telemetryRow(
          //           'Screen Time Today',
          //           screenMin != null
          //               ? '$screenMin min (${((screenMin as num) / 60.0).toStringAsFixed(1)} hr)'
          //               : '--'),
          //       _telemetryRow(
          //           'Signal Quality',
          //           qualityFlags.isEmpty
          //               ? 'Nominal (No noise detected)'
          //               : 'Flags: ${qualityFlags.join(", ")}'),
          //     ],
          //   ),
          // ),
          const SizedBox(height: 14),
          SectionCard(
            title: 'Recent Telemetry Stream',
            child: _recentVitals.isEmpty
                ? const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: Text('No recent telemetry events recorded yet.'),
                  )
                : Column(
                    children: [
                      for (var i = 0;
                          i < _recentVitals.length.clamp(0, 8);
                          i++) ...[
                        if (i > 0) const Divider(height: 12),
                        _recentEventRow(
                            _recentVitals[i] as Map<String, dynamic>),
                      ],
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _telemetryRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(fontWeight: FontWeight.w500)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }

  Widget _recentEventRow(Map<String, dynamic> ev) {
    final tStr = ev['measured_at'] as String?;
    String time = '--:--:--';
    if (tStr != null && tStr.length >= 19) {
      try {
        final dt = DateTime.parse(tStr).toLocal();
        time =
            '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}:${dt.second.toString().padLeft(2, '0')}';
      } catch (_) {
        time = tStr.substring(11, 19);
      }
    }
    final hr = ev['heartrate'];
    final ped = ev['pedometer'];
    final hrEwma = ev['heartrate_ewma'];

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Row(
          children: [
            const Icon(Icons.flash_on, size: 14, color: Color(0xFF7A5CFA)),
            const SizedBox(width: 6),
            Text(time,
                style: const TextStyle(fontSize: 13, fontFamily: 'monospace')),
          ],
        ),
        Text(
            'HR: ${hr ?? "--"} bpm${hrEwma != null ? " (~${(hrEwma as num).toStringAsFixed(0)})" : ""}',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        Text('Steps: ${ped ?? "--"}',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
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
                controller: _journalController,
                minLines: 8,
                maxLines: 12,
                decoration: const InputDecoration(
                  labelText: 'Today I noticed...',
                  hintText:
                      'What changed in your body, sleep, mood, thoughts, or routine?',
                ),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _isSubmitting ? null : _submitJournal,
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
    _vitalsTimer?.cancel();
    widget.careState.removeListener(_onCareStateChanged);
    _chatController.dispose();
    _journalController.dispose();
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
      // The server identifies the patient from the login token.
      final response = await _apiClient.post('/patient/chat', {'query': text});
      if (!mounted) return;
      setState(() {
        _chatHistory.add({'text': response['response'] ?? 'No response', 'mine': false});
        if (response['input_handling'] == 'condensed') {
          _chatHistory.add({
            'text': 'Note: your message was long, so it was condensed before I read it. '
                'The full text has been saved.',
            'mine': false,
          });
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _chatHistory.add({'text': 'Error: $e', 'mine': false});
      });
    } finally {
      if (mounted) setState(() => _isChatLoading = false);
    }
  }

  Widget _rag(BuildContext context) {
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

  String get _moodAvgValue {
    final raw = _summary?['mood_avg'];
    if (raw != null) return (raw as num).toStringAsFixed(1);
    final checkins = (_summary?['checkins'] as List?) ?? [];
    if (checkins.isNotEmpty) {
      final moods = checkins
          .map((c) => c['mood'])
          .where((m) => m != null)
          .cast<num>()
          .toList();
      if (moods.isNotEmpty) {
        final avg = moods.reduce((a, b) => a + b) / moods.length;
        return avg.toStringAsFixed(1);
      }
    }
    return '3.5';
  }

  RiskLevel get _moodRiskLevel {
    final val = double.tryParse(_moodAvgValue) ?? 3.0;
    if (val <= 2.0) return RiskLevel.escalate;
    if (val <= 3.0) return RiskLevel.monitor;
    return RiskLevel.normal;
  }

  String get _adherenceValue {
    final raw = _summary?['adherence_pct'];
    if (raw != null) return '$raw';
    return widget.careState.medicationAligned ? '100' : '0';
  }

  RiskLevel get _adherenceRiskLevel {
    final val = int.tryParse(_adherenceValue) ?? 100;
    if (val < 60) return RiskLevel.escalate;
    if (val < 80) return RiskLevel.monitor;
    return RiskLevel.normal;
  }

  String get _sleepAvgValue {
    final raw = _summary?['wearable_sleep_avg'];
    if (raw != null) return (raw as num).toStringAsFixed(1);
    final live = _liveVitals;
    if (live != null && live['sleep_minutes'] != null) {
      return ((live['sleep_minutes'] as num) / 60.0).toStringAsFixed(1);
    }
    final daily = (_summary?['daily'] as List?) ?? [];
    if (daily.isNotEmpty) {
      final sleepVals = daily
          .map((d) => d['sleep_minutes'])
          .where((s) => s != null)
          .map((s) => (s as num) / 60.0)
          .toList();
      if (sleepVals.isNotEmpty) {
        final avg = sleepVals.reduce((a, b) => a + b) / sleepVals.length;
        return avg.toStringAsFixed(1);
      }
    }
    final checkins = (_summary?['checkins'] as List?) ?? [];
    if (checkins.isNotEmpty) {
      final sleepVals = checkins
          .map((c) => c['sleep_hours'])
          .where((s) => s != null)
          .cast<num>()
          .toList();
      if (sleepVals.isNotEmpty) {
        final avg = sleepVals.reduce((a, b) => a + b) / sleepVals.length;
        return avg.toStringAsFixed(1);
      }
    }
    return '7.0';
  }

  RiskLevel get _sleepRiskLevel {
    final val = double.tryParse(_sleepAvgValue) ?? 7.0;
    if (val < 5.0) return RiskLevel.escalate;
    if (val < 6.5) return RiskLevel.monitor;
    return RiskLevel.normal;
  }

  String get _progressMessage {
    final anomalies = (_summary?['anomalies'] as List?) ?? [];
    if (anomalies.isNotEmpty) {
      final first = anomalies.first;
      final signal = first['signal'] ?? 'Vital sign variation';
      final dir = first['direction'] ?? 'change';
      return '$signal anomaly detected ($dir). Continue monitoring and note any changes in your journal.';
    }
    final sleep = double.tryParse(_sleepAvgValue) ?? 7.0;
    final mood = double.tryParse(_moodAvgValue) ?? 3.5;
    if (sleep < 5.5) {
      return 'Sleep duration has been lower than average recently. A calming wind-down routine may help.';
    }
    if (mood >= 3.5 && sleep >= 6.5) {
      return 'Your wellness check-ins are stabilizing. Sleep duration and mood trends are in healthy ranges.';
    }
    return 'Your wellness logs are being tracked. Consistent check-ins help identify patterns early.';
  }

  String get _pedometerValue {
    final live = _summary?['live'] as Map<String, dynamic>?;
    if (live != null && live['pedometer'] != null) {
      final steps = (live['pedometer'] as num).toInt();
      if (steps >= 10000) {
        return '${(steps / 1000).toStringAsFixed(1)}k';
      }
      return '$steps';
    }
    final stepsAvg = _summary?['steps_avg'];
    if (stepsAvg != null) {
      final steps = (stepsAvg as num).toInt();
      if (steps >= 10000) {
        return '${(steps / 1000).toStringAsFixed(1)}k';
      }
      return '$steps';
    }
    final daily = (_summary?['daily'] as List?) ?? [];
    if (daily.isNotEmpty) {
      final last = daily.last['steps_total'];
      if (last != null) {
        final steps = (last as num).toInt();
        if (steps >= 10000) {
          return '${(steps / 1000).toStringAsFixed(1)}k';
        }
        return '$steps';
      }
    }
    return '--';
  }

  RiskLevel get _pedometerRiskLevel {
    final live = _summary?['live'] as Map<String, dynamic>?;
    final num? steps = (live?['pedometer'] as num?) ?? (_summary?['steps_avg'] as num?);
    if (steps == null) return RiskLevel.normal;
    if (steps < 2000) return RiskLevel.monitor;
    return RiskLevel.normal;
  }

  List<double> get _sleepChartValues {
    final daily = (_summary?['daily'] as List?) ?? [];
    if (daily.isNotEmpty) {
      final vals = daily
          .map((d) => d['sleep_minutes'] == null
              ? 0.0
              : ((d['sleep_minutes'] as num) / 60.0).toDouble())
          .toList();
      if (vals.any((v) => v > 0)) return vals;
    }
    final checkins = (_summary?['checkins'] as List?) ?? [];
    if (checkins.isNotEmpty) {
      final vals = checkins
          .map((c) => c['sleep_hours'] == null
              ? 0.0
              : (c['sleep_hours'] as num).toDouble())
          .toList()
          .reversed
          .toList();
      if (vals.any((v) => v > 0)) return vals;
    }
    final live = _liveVitals;
    if (live != null && live['sleep_minutes'] != null) {
      return [((live['sleep_minutes'] as num) / 60.0).toDouble()];
    }
    return [7.0];
  }

  List<double> get _stepChartValues {
    final daily = (_summary?['daily'] as List?) ?? [];
    if (daily.isNotEmpty) {
      final vals = daily
          .map((d) => d['steps_total'] == null
              ? 0.0
              : (d['steps_total'] as num).toDouble())
          .toList();
      if (vals.any((v) => v > 0)) return vals;
    }
    final live = _summary?['live'] as Map<String, dynamic>?;
    if (live != null && live['pedometer'] != null) {
      return [(live['pedometer'] as num).toDouble()];
    }
    return [0.0];
  }

  List<double> get _chartValues =>
      _chartMetric == 'steps' ? _stepChartValues : _sleepChartValues;

  List<String> get _chartLabels {
    final daily = (_summary?['daily'] as List?) ?? [];
    if (daily.isNotEmpty) {
      return daily.map((d) {
        final dayStr = d['day'] as String? ?? '';
        return dayStr.length >= 10 ? dayStr.substring(5) : dayStr;
      }).toList();
    }
    final checkins = (_summary?['checkins'] as List?) ?? [];
    if (checkins.isNotEmpty) {
      return checkins.map((c) {
        final dt = c['created_at'] as String? ?? '';
        return dt.length >= 10 ? dt.substring(5, 10) : 'Log';
      }).toList().reversed.toList();
    }
    return ['Today'];
  }

  Widget _progress(BuildContext context) {
    if (_isLoadingSummary && _summary == null) {
      return const Center(child: CircularProgressIndicator());
    }

    return RefreshIndicator(
      onRefresh: _fetchSummary,
      child: ListView(
        key: const ValueKey('patient-progress'),
        padding: const EdgeInsets.all(16),
        children: [
          if (_summaryError != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                _summaryError!,
                style: const TextStyle(color: Colors.redAccent),
              ),
            ),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricTile(
                label: 'Mood Avg',
                value: _moodAvgValue,
                unit: '/5',
                status: _moodRiskLevel,
              ),
              MetricTile(
                label: 'Adherence',
                value: _adherenceValue,
                unit: '%',
                status: _adherenceRiskLevel,
              ),
              MetricTile(
                label: 'Sleep Avg',
                value: _sleepAvgValue,
                unit: 'hr',
                status: _sleepRiskLevel,
              ),
              MetricTile(
                label: 'Pedometer',
                value: _pedometerValue,
                unit: 'steps',
                status: _pedometerRiskLevel,
              ),
            ],
          ),
          const SizedBox(height: 12),
          SectionCard(
            title: 'Latest Progress',
            action: SegmentedButton<String>(
              segments: const [
                ButtonSegment(
                  value: 'sleep',
                  label: Text('Sleep'),
                  icon: Icon(Icons.bedtime_outlined, size: 16),
                ),
                ButtonSegment(
                  value: 'steps',
                  label: Text('Pedometer'),
                  icon: Icon(Icons.directions_walk, size: 16),
                ),
              ],
              selected: {_chartMetric},
              onSelectionChanged: (set) {
                if (set.isNotEmpty) setState(() => _chartMetric = set.first);
              },
              showSelectedIcon: false,
              style: const ButtonStyle(
                visualDensity: VisualDensity.compact,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _progressMessage,
                  style: const TextStyle(fontSize: 15),
                ),
                const SizedBox(height: 12),
                MiniBarChart(
                  values: _chartValues,
                  labels: _chartLabels,
                  color: _chartMetric == 'steps'
                      ? const Color(0xFF256D85)
                      : const Color(0xFF7A5CFA),
                ),
              ],
            ),
          ),
        ],
      ),
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
        child: FormattedText(
          text,
          style: TextStyle(
            color: mine ? Theme.of(context).colorScheme.primary : Colors.white,
            fontSize: 14,
            height: 1.4,
          ),
        ),
      ),
    );
  }
}
