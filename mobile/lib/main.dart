import 'package:flutter/material.dart';

import 'api.dart';
import 'login_page.dart';
import 'shell.dart';

void main() => runApp(const HarborApp());

class HarborApp extends StatefulWidget {
  const HarborApp({super.key});

  @override
  State<HarborApp> createState() => _HarborAppState();
}

class _HarborAppState extends State<HarborApp> {
  Session? _session;
  bool _ready = false;
  String _lastServer = '';

  @override
  void initState() {
    super.initState();
    Session.restore().then((s) => setState(() {
          _session = s;
          _lastServer = s?.server ?? '';
          _ready = true;
        }));
  }

  @override
  Widget build(BuildContext context) {
    final Widget home;
    if (!_ready) {
      home = const Scaffold(body: Center(child: CircularProgressIndicator()));
    } else if (_session == null) {
      home = LoginPage(initialServer: _lastServer, onLogin: (s) => setState(() => _session = s));
    } else {
      home = Shell(
          key: ValueKey(_session!.token),
          api: Api(_session!),
          onLogout: () => setState(() {
                _lastServer = _session?.server ?? '';
                _session = null;
              }));
    }
    return MaterialApp(
      title: 'Harbor',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal, brightness: Brightness.dark), useMaterial3: true),
      home: home,
    );
  }
}
