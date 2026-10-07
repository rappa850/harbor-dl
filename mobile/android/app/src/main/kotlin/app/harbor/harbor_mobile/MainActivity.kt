package app.harbor.harbor_mobile

import android.app.PictureInPictureParams
import android.content.res.Configuration
import android.os.Build
import android.util.Rational
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/// Picture-in-picture for the feed. Flutter tells us whether the current page may float (a video is playing) and asks
/// for it explicitly from a button; leaving the app while allowed enters it automatically. Entering and leaving is
/// reported back so the feed does not pause itself when the activity goes to the background.
class MainActivity : FlutterActivity() {
    private var channel: MethodChannel? = null
    private var allowed = false

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "harbor/pip").also { channel ->
            channel.setMethodCallHandler { call, result ->
                when (call.method) {
                    "allow" -> {
                        allowed = call.arguments as? Boolean ?: false
                        result.success(null)
                    }
                    "enter" -> result.success(enter())
                    "supported" -> result.success(Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                    else -> result.notImplemented()
                }
            }
        }
    }

    private fun enter(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return false
        val params = PictureInPictureParams.Builder().setAspectRatio(Rational(9, 16)).build()
        return try {
            enterPictureInPictureMode(params)
        } catch (e: IllegalStateException) {
            false
        }
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        if (allowed) enter()
    }

    override fun onPictureInPictureModeChanged(isInPictureInPictureMode: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
        channel?.invokeMethod("changed", isInPictureInPictureMode)
    }
}
