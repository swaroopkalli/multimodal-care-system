import 'package:flutter/material.dart';

/// A widget that parses and renders text with Markdown-style formatting:
/// - **bold** with `**...**`
/// - *italics* with `*...*` or `_..._`
/// - __underline__ with `__...__` or `<u>...</u>`
/// - ***bold italic*** with `***...***`
/// - ___underline italic___ with `___...___`
/// - nested styles (e.g. `**bold and _italic_**`, `__**bold underline**__`)
/// - inline `code` with backticks `` `...` ``
class FormattedText extends StatelessWidget {
  const FormattedText(
    this.text, {
    super.key,
    this.style,
    this.textAlign,
    this.maxLines,
    this.overflow,
  });

  final String text;
  final TextStyle? style;
  final TextAlign? textAlign;
  final int? maxLines;
  final TextOverflow? overflow;

  static final RegExp _markdownPattern = RegExp(
    r'(`[^`\n]+`)' // 1: inline code
    r'|(\*\*\*(?!\s)[^\*\n]+?(?<!\s)\*\*\*)' // 2: bold-italic ***
    r'|(_{3}(?![\s_])[^_]+?(?<![\s_])_{3})' // 3: underline-italic ___
    r'|(\*\*(?!\s)[^\*\n]+?(?<!\s)\*\*)' // 4: bold **
    r'|(__(?![\s_])[^_]+?(?<![\s_])__|<u>.*?</u>)' // 5: underline __ or <u>
    r'|((?<!\w)\*(?!\s)[^\*\n]+?(?<!\s)\*(?!\w))' // 6: italic *
    r'|((?<!\w)_(?![\s_])[^_]+?(?<![\s_])_(?!\w))', // 7: italic _
  );

  static TextStyle _buildSpanStyle(
    TextStyle baseStyle, {
    required bool isBold,
    required bool isItalic,
    required bool isUnderline,
    required bool isCode,
  }) {
    var resolved = baseStyle;
    if (isBold) {
      resolved = resolved.copyWith(fontWeight: FontWeight.bold);
    }
    if (isItalic) {
      resolved = resolved.copyWith(fontStyle: FontStyle.italic);
    }
    if (isUnderline) {
      resolved = resolved.copyWith(
        decoration: TextDecoration.underline,
        decorationColor: resolved.color,
      );
    }
    if (isCode) {
      resolved = resolved.copyWith(
        fontFamily: 'monospace',
        backgroundColor: const Color(0x1AFFFFFF),
      );
    }
    return resolved;
  }

  /// Recursively parses [text] into [InlineSpan]s based on markdown syntax tokens.
  static List<InlineSpan> parseSpans(
    String text, {
    required TextStyle baseStyle,
    bool isBold = false,
    bool isItalic = false,
    bool isUnderline = false,
    bool isCode = false,
    int depth = 0,
  }) {
    if (text.isEmpty) return const [];
    if (depth > 6) {
      return [
        TextSpan(
          text: text,
          style: _buildSpanStyle(
            baseStyle,
            isBold: isBold,
            isItalic: isItalic,
            isUnderline: isUnderline,
            isCode: isCode,
          ),
        ),
      ];
    }

    final matches = _markdownPattern.allMatches(text);
    if (matches.isEmpty) {
      return [
        TextSpan(
          text: text,
          style: _buildSpanStyle(
            baseStyle,
            isBold: isBold,
            isItalic: isItalic,
            isUnderline: isUnderline,
            isCode: isCode,
          ),
        ),
      ];
    }

    final spans = <InlineSpan>[];
    var lastEnd = 0;

    for (final match in matches) {
      if (match.start > lastEnd) {
        spans.add(
          TextSpan(
            text: text.substring(lastEnd, match.start),
            style: _buildSpanStyle(
              baseStyle,
              isBold: isBold,
              isItalic: isItalic,
              isUnderline: isUnderline,
              isCode: isCode,
            ),
          ),
        );
      }

      final matched = match.group(0)!;

      if (match.group(1) != null) {
        // `code`
        final inner = matched.substring(1, matched.length - 1);
        spans.addAll(
          parseSpans(
            inner,
            baseStyle: baseStyle,
            isBold: isBold,
            isItalic: isItalic,
            isUnderline: isUnderline,
            isCode: true,
            depth: depth + 1,
          ),
        );
      } else if (match.group(2) != null) {
        // ***bold italic***
        final inner = matched.substring(3, matched.length - 3);
        spans.addAll(
          parseSpans(
            inner,
            baseStyle: baseStyle,
            isBold: true,
            isItalic: true,
            isUnderline: isUnderline,
            isCode: isCode,
            depth: depth + 1,
          ),
        );
      } else if (match.group(3) != null) {
        // ___underline italic___
        final inner = matched.substring(3, matched.length - 3);
        spans.addAll(
          parseSpans(
            inner,
            baseStyle: baseStyle,
            isBold: isBold,
            isItalic: true,
            isUnderline: true,
            isCode: isCode,
            depth: depth + 1,
          ),
        );
      } else if (match.group(4) != null) {
        // **bold**
        final inner = matched.substring(2, matched.length - 2);
        spans.addAll(
          parseSpans(
            inner,
            baseStyle: baseStyle,
            isBold: true,
            isItalic: isItalic,
            isUnderline: isUnderline,
            isCode: isCode,
            depth: depth + 1,
          ),
        );
      } else if (match.group(5) != null) {
        // __underline__ or <u>underline</u>
        final inner = matched.startsWith('<u>')
            ? matched.substring(3, matched.length - 4)
            : matched.substring(2, matched.length - 2);
        spans.addAll(
          parseSpans(
            inner,
            baseStyle: baseStyle,
            isBold: isBold,
            isItalic: isItalic,
            isUnderline: true,
            isCode: isCode,
            depth: depth + 1,
          ),
        );
      } else if (match.group(6) != null) {
        // *italic*
        final inner = matched.substring(1, matched.length - 1);
        spans.addAll(
          parseSpans(
            inner,
            baseStyle: baseStyle,
            isBold: isBold,
            isItalic: true,
            isUnderline: isUnderline,
            isCode: isCode,
            depth: depth + 1,
          ),
        );
      } else if (match.group(7) != null) {
        // _italic_
        final inner = matched.substring(1, matched.length - 1);
        spans.addAll(
          parseSpans(
            inner,
            baseStyle: baseStyle,
            isBold: isBold,
            isItalic: true,
            isUnderline: isUnderline,
            isCode: isCode,
            depth: depth + 1,
          ),
        );
      }

      lastEnd = match.end;
    }

    if (lastEnd < text.length) {
      spans.add(
        TextSpan(
          text: text.substring(lastEnd),
          style: _buildSpanStyle(
            baseStyle,
            isBold: isBold,
            isItalic: isItalic,
            isUnderline: isUnderline,
            isCode: isCode,
          ),
        ),
      );
    }

    return spans;
  }

  @override
  Widget build(BuildContext context) {
    final baseStyle = style ?? DefaultTextStyle.of(context).style;
    final spans = parseSpans(text, baseStyle: baseStyle);

    return Text.rich(
      TextSpan(children: spans, style: baseStyle),
      textAlign: textAlign,
      maxLines: maxLines,
      overflow: overflow,
    );
  }
}
