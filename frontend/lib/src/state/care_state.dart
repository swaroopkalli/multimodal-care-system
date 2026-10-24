import 'package:flutter/foundation.dart';

class CareState extends ChangeNotifier {
  bool _patientMedicationTaken = true;
  bool _caretakerMedicationConfirmed = true;
  double _patientStress = 6;
  String _patientStatus = 'Monitoring sleep and restlessness';

  bool get patientMedicationTaken => _patientMedicationTaken;
  bool get caretakerMedicationConfirmed => _caretakerMedicationConfirmed;
  double get patientStress => _patientStress;
  String get patientStatus => _patientStatus;

  bool get medicationAligned =>
      _patientMedicationTaken && _caretakerMedicationConfirmed;

  void setPatientMedicationTaken(bool value) {
    _patientMedicationTaken = value;
    if (value) {
      _caretakerMedicationConfirmed = true;
      _patientStatus = 'Medication logged by patient';
    } else {
      _patientStatus = 'Medication confirmation pending';
    }
    notifyListeners();
  }

  void setCaretakerMedicationConfirmed(bool value) {
    _caretakerMedicationConfirmed = value;
    if (value) {
      _patientMedicationTaken = true;
      _patientStatus = 'Medication verified by caretaker';
    } else {
      _patientStatus = 'Caretaker has not verified medication';
    }
    notifyListeners();
  }

  void setPatientStress(double value) {
    _patientStress = value;
    _patientStatus = value >= 8
        ? 'High stress reported today'
        : value >= 5
            ? 'Moderate stress reported today'
            : 'Patient reports a steadier day';
    notifyListeners();
  }
}
