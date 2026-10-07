import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Cache sizes offered in the settings sheet, in MB.
const kCacheChoices = [512, 1024, 2048, 4096];

/// Data-saving preferences, kept on the device.
class AppSettings {
  AppSettings(this._prefs);

  final SharedPreferences _prefs;

  static Future<AppSettings> load() async => AppSettings(await SharedPreferences.getInstance());

  /// Only prefetch upcoming videos on Wi-Fi (or Ethernet). The current video always plays.
  bool get wifiOnlyPrefetch => _prefs.getBool('wifiOnlyPrefetch') ?? true;
  Future<void> setWifiOnlyPrefetch(bool value) => _prefs.setBool('wifiOnlyPrefetch', value);

  /// Repeat the current video instead of moving on to the next when it ends.
  bool get loopOne => _prefs.getBool('loopOne') ?? false;
  Future<void> setLoopOne(bool value) => _prefs.setBool('loopOne', value);

  int get cacheMb => _prefs.getInt('cacheMb') ?? 1024;
  Future<void> setCacheMb(int value) => _prefs.setInt('cacheMb', value);

  int get cacheBytes => cacheMb * 1024 * 1024;
}

/// True on Wi-Fi or Ethernet. Unknown connectivity counts as "yes" so a flaky plugin never disables prefetch for good.
Future<bool> onUnmeteredNetwork() async {
  try {
    final result = await Connectivity().checkConnectivity();
    if (result.isEmpty || result.contains(ConnectivityResult.none)) return true;
    return result.contains(ConnectivityResult.wifi) || result.contains(ConnectivityResult.ethernet);
  } catch (_) {
    return true;
  }
}
