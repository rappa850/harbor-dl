import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Picture-in-picture, backed by `MainActivity.kt`. The native side reports when the window shrinks or grows back so
/// the feed can keep playing while the app is in the corner of the screen.
class Pip {
  Pip._();

  static const _channel = MethodChannel('harbor/pip');

  /// True while the app is shown as a floating window.
  static final inPip = ValueNotifier<bool>(false);
  static bool _wired = false;

  static void _wire() {
    if (_wired) return;
    _wired = true;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'changed') inPip.value = call.arguments as bool? ?? false;
    });
  }

  static Future<bool> supported() async {
    _wire();
    try {
      return await _channel.invokeMethod<bool>('supported') ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false; // tests and other platforms
    }
  }

  /// Let the system shrink the app into a window when the user leaves it (only while a video is playing).
  static Future<void> allow(bool on) async {
    _wire();
    try {
      await _channel.invokeMethod<void>('allow', on);
    } on PlatformException {
      // best effort
    } on MissingPluginException {
      // tests and other platforms
    }
  }

  static Future<bool> enter() async {
    _wire();
    try {
      return await _channel.invokeMethod<bool>('enter') ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }
}
