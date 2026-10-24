import '../models/care_event.dart';

class DecisionService {
  const DecisionService();

  DecisionSnapshot evaluate(DailyLog log) {
    var score = 28;

    if (log.mood <= 2) score += 18;
    if (log.sleepHours < 5) score += 20;
    if (!log.medicationTaken) score += 22;
    if (log.sideEffects.contains('Restlessness')) score += 12;
    if (!log.caretakerValidated) score += 8;

    final riskLevel = switch (score) {
      >= 70 => RiskLevel.escalate,
      >= 45 => RiskLevel.monitor,
      _ => RiskLevel.normal,
    };

    return DecisionSnapshot(
      stressScore: score.clamp(0, 100).toInt(),
      riskLevel: riskLevel,
      summary:
          'Monitor: sleep disruption is the main contributor to risk today.',
      patientGuidance:
          'This can happen in early onboarding weeks. Try a low-stimulation evening routine and log sleep again tomorrow. This is guidance, not a diagnosis or prescription.',
      caretakerAlert:
          'Validate medication timing, observe restlessness tonight, and escalate only if risk language or severe deterioration appears.',
      doctorSummary:
          'Weekly issue: insomnia may increase dropout risk. Adherence remains protected through caretaker validation.',
    );
  }
}
