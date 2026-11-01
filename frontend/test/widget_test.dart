import 'package:flutter_test/flutter_test.dart';
import 'package:mindbridge_frontend/src/app.dart';

void main() {
  testWidgets('splash leads to the portal selection', (tester) async {
    await tester.pumpWidget(const MindBridgeApp());

    // Splash screen first.
    expect(find.text('MindBridge'), findsOneWidget);

    // After the splash animation the three portals are offered.
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();

    expect(find.text('Select Your Portal'), findsOneWidget);
    expect(find.text('Patient'), findsOneWidget);
    expect(find.text('Caretaker'), findsOneWidget);
    expect(find.text('Doctor'), findsOneWidget);
  });
}
