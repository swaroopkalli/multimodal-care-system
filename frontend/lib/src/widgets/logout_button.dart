import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../screens/dashboard_shell.dart';

/// App-bar action that ends the session and returns to the portal selection.
class LogoutButton extends StatelessWidget {
  const LogoutButton({super.key});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: 'Log out',
      icon: const Icon(Icons.logout),
      onPressed: () async {
        await ApiClient().clearToken();
        if (!context.mounted) return;
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const DashboardShell()),
          (_) => false,
        );
      },
    );
  }
}
