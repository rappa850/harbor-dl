import 'package:flutter_test/flutter_test.dart';
import 'package:harbor_mobile/pip.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('without the native side picture-in-picture is simply unavailable', () async {
    expect(await Pip.supported(), isFalse);
    expect(await Pip.enter(), isFalse);
    await Pip.allow(true); // must not throw
    expect(Pip.inPip.value, isFalse);
  });
}
