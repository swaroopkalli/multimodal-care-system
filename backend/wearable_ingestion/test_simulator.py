"""Unit tests for synthetic simulator behavior; no Redis or database needed."""

import random
import unittest

from simulator import PatientSimulationState, _generate_vitals


class SimulatorTests(unittest.TestCase):
    def test_scenario_ranges_are_not_capped_at_old_limit(self):
        state = PatientSimulationState(random.Random(4))
        self.assertGreater(max(state.next_heart_rate("elevated") for _ in range(30)), 105)
        low = PatientSimulationState(random.Random(4))
        self.assertLess(min(low.next_heart_rate("low") for _ in range(30)), 58)

    def test_normal_scenario_reproducible_and_not_always_elevated(self):
        a = PatientSimulationState(random.Random(17))
        b = PatientSimulationState(random.Random(17))
        seq_a = [a.next_heart_rate() for _ in range(80)]
        seq_b = [b.next_heart_rate() for _ in range(80)]
        self.assertEqual(seq_a, seq_b)
        self.assertTrue(all(35 <= x <= 105 for x in seq_a))
        self.assertGreater(len(set(seq_a)), 5)

    def test_behavior_metrics_persist_per_patient_and_refresh_by_interval(self):
        patient_a = PatientSimulationState(random.Random(1), behavioral_interval=1800)
        patient_b = PatientSimulationState(random.Random(2), behavioral_interval=1800)
        first = _generate_vitals(1, 1, patient_a, now=100, scenario="normal")
        repeated = _generate_vitals(1, 2, patient_a, now=1700, scenario="normal")
        refreshed = _generate_vitals(1, 3, patient_a, now=1900, scenario="normal")
        other = _generate_vitals(2, 1, patient_b, now=100, scenario="normal")
        self.assertEqual((first["sleep_minutes"], first["screentime_minutes"]),
                         (repeated["sleep_minutes"], repeated["screentime_minutes"]))
        self.assertNotEqual((first["sleep_minutes"], first["screentime_minutes"]),
                            (refreshed["sleep_minutes"], refreshed["screentime_minutes"]))
        self.assertNotEqual((first["sleep_minutes"], first["screentime_minutes"]),
                            (other["sleep_minutes"], other["screentime_minutes"]))
        self.assertEqual(set(first), {"event_id", "device_id", "patient_id", "sequence",
                                      "measured_at", "simulation", "pedometer", "sleep_minutes",
                                      "screentime_minutes", "heartrate", "source", "schema_version"})
        self.assertIs(first["simulation"], True)
        self.assertEqual(first["source"], "simulator")

    def test_pedometer_increments_monotonically(self):
        state = PatientSimulationState(random.Random(42), initial_steps=1500)
        steps = [state.next_pedometer() for _ in range(100)]
        # Must start from baseline and never decrease
        self.assertGreaterEqual(steps[0], 1500)
        for i in range(1, len(steps)):
            self.assertGreaterEqual(steps[i], steps[i - 1], f"Step decreased at index {i}: {steps[i]} < {steps[i-1]}")
        # Over 100 ticks, it should accumulate progress
        self.assertGreater(steps[-1], steps[0])

    def test_generated_vitals_pedometer_does_not_decrease(self):
        state = PatientSimulationState(random.Random(99), initial_steps=2000)
        events = [_generate_vitals(1, i, state) for i in range(1, 20)]
        step_counts = [e["pedometer"] for e in events]
        for i in range(1, len(step_counts)):
            self.assertGreaterEqual(step_counts[i], step_counts[i - 1])
        self.assertGreater(step_counts[-1], step_counts[0])


if __name__ == "__main__":
    unittest.main()
