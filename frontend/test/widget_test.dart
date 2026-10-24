import 'package:flutter_test/flutter_test.dart';
import 'package:mindbridge_frontend/src/app.dart';

void main() {
  testWidgets('renders role-based mental health triage shell', (tester) async {
    await tester.pumpWidget(const MindBridgeApp());

    expect(find.text('MindBridge'), findsOneWidget);
    expect(find.text('Patient Portal'), findsOneWidget);
    expect(find.text('Caretaker Portal'), findsOneWidget);
    expect(find.text('Doctor Portal'), findsOneWidget);
    expect(
        find.text('Hybrid intelligence, three human views.'), findsOneWidget);
  });
}
