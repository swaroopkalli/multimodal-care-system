enum RiskLevel { normal, monitor, escalate }

enum ActorRole { patient, caretaker, doctor }

class DailyLog {
  const DailyLog({
    required this.mood,
    required this.sleepHours,
    required this.medicationTaken,
    required this.sideEffects,
    required this.journal,
    required this.caretakerValidated,
  });

  final int mood;
  final double sleepHours;
  final bool medicationTaken;
  final List<String> sideEffects;
  final String journal;
  final bool caretakerValidated;
}

class WearableSignal {
  const WearableSignal({
    required this.label,
    required this.value,
    required this.unit,
    required this.status,
  });

  final String label;
  final String value;
  final String unit;
  final RiskLevel status;
}

class CareInsight {
  const CareInsight({
    required this.title,
    required this.body,
    required this.level,
  });

  final String title;
  final String body;
  final RiskLevel level;
}

class DecisionSnapshot {
  const DecisionSnapshot({
    required this.stressScore,
    required this.riskLevel,
    required this.summary,
    required this.patientGuidance,
    required this.caretakerAlert,
    required this.doctorSummary,
  });

  final int stressScore;
  final RiskLevel riskLevel;
  final String summary;
  final String patientGuidance;
  final String caretakerAlert;
  final String doctorSummary;
}
