import 'package:flutter/material.dart';

class PortalHeader extends StatelessWidget {
  const PortalHeader({
    required this.title,
    required this.subtitle,
    this.center,
    super.key,
  });

  final String title;
  final String subtitle;
  final Widget? center;

  @override
  Widget build(BuildContext context) {
    return AppBar(
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title),
          Text(
            subtitle,
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w400),
          ),
        ],
      ),
      centerTitle: false,
      actions: [
        if (center != null)
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(child: center),
          ),
      ],
    );
  }
}
