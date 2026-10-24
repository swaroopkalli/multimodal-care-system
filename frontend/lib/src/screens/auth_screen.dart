import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../state/care_state.dart';
import 'caretaker_dashboard.dart';
import 'doctor_dashboard.dart';
import 'patient_dashboard.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({required this.role, required this.careState, super.key});

  final String role; // 'patient', 'caretaker', 'doctor'
  final CareState careState;

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _apiClient = ApiClient();
  
  bool _isLogin = true;
  bool _isLoading = false;
  String? _errorMessage;

  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _nameController = TextEditingController(); // Only for register

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _nameController.dispose();
    super.dispose();
  }

  String get _roleTitle {
    switch (widget.role) {
      case 'patient':
        return 'Patient';
      case 'caretaker':
        return 'Caretaker';
      case 'doctor':
        return 'Doctor';
      default:
        return 'User';
    }
  }

  Future<void> _submit() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final endpoint = _isLogin ? '/auth/login/${widget.role}' : '/auth/register/${widget.role}';
      
      final payload = {
        'username': _usernameController.text.trim(),
        'password': _passwordController.text,
      };

      if (!_isLogin) {
        payload['name'] = _nameController.text.trim();
      }

      final response = await _apiClient.post(endpoint, payload);

      if (_isLogin) {
        // Successful login should return a token
        final token = response['token'];
        if (token != null) {
          await _apiClient.saveToken(token);
          _navigateToDashboard();
        } else {
          setState(() => _errorMessage = 'No token received from server.');
        }
      } else {
        // Successful registration
        setState(() {
          _isLogin = true;
          _errorMessage = 'Registration successful. Please log in.';
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = e.toString().replaceAll('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  void _navigateToDashboard() {
    Widget dashboard;
    switch (widget.role) {
      case 'patient':
        dashboard = PatientDashboard(careState: widget.careState);
        break;
      case 'caretaker':
        dashboard = CaretakerDashboard(careState: widget.careState);
        break;
      case 'doctor':
        dashboard = const DoctorDashboard();
        break;
      default:
        return;
    }

    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => dashboard),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('$_roleTitle Portal'),
        centerTitle: true,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Container(
            constraints: const BoxConstraints(maxWidth: 400),
            padding: const EdgeInsets.all(32),
            decoration: BoxDecoration(
              color: Theme.of(context).cardColor,
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: const Color(0x22FFFFFF), width: 1.5),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.4),
                  blurRadius: 20,
                  offset: const Offset(0, 8),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  widget.role == 'patient'
                      ? Icons.favorite
                      : widget.role == 'caretaker'
                          ? Icons.verified_user
                          : Icons.medical_information,
                  size: 64,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 24),
                Text(
                  _isLogin ? 'Welcome Back' : 'Create Account',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                        color: Colors.white,
                      ),
                ),
                const SizedBox(height: 32),
                if (!_isLogin) ...[
                  TextField(
                    controller: _nameController,
                    decoration: const InputDecoration(
                      labelText: 'Full Name',
                      prefixIcon: Icon(Icons.badge),
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
                TextField(
                  controller: _usernameController,
                  decoration: const InputDecoration(
                    labelText: 'Username',
                    prefixIcon: Icon(Icons.person),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _passwordController,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    prefixIcon: Icon(Icons.lock),
                  ),
                ),
                const SizedBox(height: 24),
                if (_errorMessage != null) ...[
                  Text(
                    _errorMessage!,
                    style: TextStyle(
                      color: _errorMessage!.contains('successful')
                          ? Colors.greenAccent
                          : Colors.redAccent,
                      fontWeight: FontWeight.bold,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 16),
                ],
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      backgroundColor: Theme.of(context).colorScheme.primary,
                      foregroundColor: Colors.black,
                    ),
                    onPressed: _isLoading ? null : _submit,
                    child: _isLoading
                        ? const SizedBox(
                            width: 24,
                            height: 24,
                            child: CircularProgressIndicator(color: Colors.black),
                          )
                        : Text(
                            _isLogin ? 'Login' : 'Register',
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                          ),
                  ),
                ),
                const SizedBox(height: 16),
                TextButton(
                  onPressed: () {
                    setState(() {
                      _isLogin = !_isLogin;
                      _errorMessage = null;
                    });
                  },
                  child: Text(
                    _isLogin
                        ? 'Need an account? Register here.'
                        : 'Already have an account? Login here.',
                    style: const TextStyle(color: Colors.white70),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
