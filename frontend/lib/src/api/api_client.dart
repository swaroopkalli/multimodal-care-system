import 'dart:async';
import 'dart:convert';

import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.message, {this.status});
  final String message;
  final int? status;

  @override
  String toString() => message;
}

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  factory ApiClient() => _instance;

  final FlutterSecureStorage _storage = const FlutterSecureStorage();
  late String _baseUrl;

  // Local models can take a while to answer.
  static const _timeout = Duration(seconds: 150);

  ApiClient._internal() {
    final configured = dotenv.isInitialized ? dotenv.env['BACKEND_URL'] : null;
    _baseUrl = (configured == null || configured.isEmpty)
        ? 'http://127.0.0.1:5000'
        : configured;
    if (_baseUrl.endsWith('/')) {
      _baseUrl = _baseUrl.substring(0, _baseUrl.length - 1);
    }
    if (!_baseUrl.endsWith('/api')) {
      _baseUrl = '$_baseUrl/api';
    }
  }

  Future<Map<String, String>> _getHeaders() async {
    final token = await _storage.read(key: 'jwt_token');
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Future<void> saveSession(String token, String role) async {
    await _storage.write(key: 'jwt_token', value: token);
    await _storage.write(key: 'jwt_role', value: role);
  }

  Future<String?> sessionRole() async {
    if (await _storage.read(key: 'jwt_token') == null) return null;
    return _storage.read(key: 'jwt_role');
  }

  Future<void> clearToken() async {
    await _storage.delete(key: 'jwt_token');
    await _storage.delete(key: 'jwt_role');
  }

  Future<bool> hasToken() async {
    return await _storage.read(key: 'jwt_token') != null;
  }

  Future<Map<String, dynamic>> post(String endpoint, Map<String, dynamic> body) async {
    final uri = Uri.parse('$_baseUrl$endpoint');
    final headers = await _getHeaders();
    try {
      final response = await http
          .post(uri, headers: headers, body: jsonEncode(body))
          .timeout(_timeout);
      return _handleResponse(response);
    } on TimeoutException {
      throw ApiException('The server took too long to respond.');
    }
  }

  Future<Map<String, dynamic>> get(String endpoint) async {
    final uri = Uri.parse('$_baseUrl$endpoint');
    final headers = await _getHeaders();
    try {
      final response = await http.get(uri, headers: headers).timeout(_timeout);
      return _handleResponse(response);
    } on TimeoutException {
      throw ApiException('The server took too long to respond.');
    }
  }

  Map<String, dynamic> _handleResponse(http.Response response) {
    Map<String, dynamic> decoded = {};
    if (response.body.isNotEmpty) {
      try {
        final parsed = jsonDecode(response.body);
        if (parsed is Map<String, dynamic>) decoded = parsed;
      } catch (_) {}
    }
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return decoded;
    }
    if (response.statusCode == 401) {
      // Expired or invalid session.
      clearToken();
    }
    final error = decoded['error'] ?? decoded['msg'];
    throw ApiException(
      error is String ? error : 'Error ${response.statusCode}',
      status: response.statusCode,
    );
  }
}
