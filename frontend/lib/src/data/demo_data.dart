import '../models/care_event.dart';

class DemoData {
  const DemoData._();

  static const currentLog = DailyLog(
    mood: 3,
    sleepHours: 4.5,
    medicationTaken: true,
    sideEffects: ['Restlessness', 'Mild nausea'],
    journal: 'Felt wired at night and could not sleep well.',
    caretakerValidated: true,
  );

  static const wearableSignals = [
    WearableSignal(
      label: 'Resting HR',
      value: '91',
      unit: 'bpm',
      status: RiskLevel.monitor,
    ),
    WearableSignal(
      label: 'Sleep Quality',
      value: '62',
      unit: '%',
      status: RiskLevel.monitor,
    ),
    WearableSignal(
      label: 'Activity',
      value: '3.4k',
      unit: 'steps',
      status: RiskLevel.normal,
    ),
  ];

  static const insights = [
    CareInsight(
      title: 'Insomnia pattern',
      body:
          'Sleep dropped below 5 hours for two nights and restlessness was observed.',
      level: RiskLevel.monitor,
    ),
    CareInsight(
      title: 'Adherence protected',
      body: 'Medication was taken and validated by caretaker input.',
      level: RiskLevel.normal,
    ),
    CareInsight(
      title: 'Escalation guardrail',
      body: 'No self-harm language detected. Continue monitoring side effects.',
      level: RiskLevel.normal,
    ),
  ];

  static const weeklySummary =
      '3 check-ins completed, 86% adherence, sleep instability detected, and no critical safety event.';
}
