import 'dart:convert';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  factory ApiClient() => _instance;

  final FlutterSecureStorage _storage = const FlutterSecureStorage();
  late String _baseUrl;

  ApiClient._internal() {
    _baseUrl = dotenv.env['BACKEND_URL'] ?? 'http://127.0.0.1:5000/api';
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

  Future<void> saveToken(String token) async {
    await _storage.write(key: 'jwt_token', value: token);
  }

  Future<void> clearToken() async {
    await _storage.delete(key: 'jwt_token');
  }

  Future<bool> hasToken() async {
    return await _storage.read(key: 'jwt_token') != null;
  }

  Future<Map<String, dynamic>> post(String endpoint, Map<String, dynamic> body) async {
    final uri = Uri.parse('$_baseUrl$endpoint');
    final headers = await _getHeaders();
    
    final response = await http.post(
      uri,
      headers: headers,
      body: jsonEncode(body),
    );

    return _handleResponse(response);
  }

  Future<Map<String, dynamic>> get(String endpoint) async {
    final uri = Uri.parse('$_baseUrl$endpoint');
    final headers = await _getHeaders();
    
    final response = await http.get(
      uri,
      headers: headers,
    );

    return _handleResponse(response);
  }

  Map<String, dynamic> _handleResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return {};
      return jsonDecode(response.body);
    } else {
      String errorMessage = 'Error ${response.statusCode}';
      try {
        final body = jsonDecode(response.body);
        if (body['error'] != null) {
          errorMessage = body['error'];
        }
      } catch (_) {}
      throw Exception(errorMessage);
    }
  }
}
