import 'package:flutter/material.dart';

import 'console_models.dart';

const kQualities = [('best', '最高画质'), ('1080', '1080p'), ('720', '720p'), ('480', '480p')];

/// Only the fields the user changed, in the shape `PATCH /api/subscriptions/{id}` takes. Empty = nothing to save.
Map<String, dynamic> settingsChanges(Subscription sub,
    {required String nickname, required num interval, required bool auto, required bool nfo, required String quality}) {
  final trimmed = nickname.trim();
  return {
    if (trimmed.isNotEmpty && trimmed != sub.nickname) 'nickname': trimmed,
    if (interval.round() != sub.updateInterval.round()) 'update_interval': interval,
    if (auto != sub.autoDownload) 'auto_download': auto,
    if (nfo != sub.generateNfo) 'generate_nfo': nfo,
    if (quality != sub.quality) 'quality': quality,
  };
}

/// Edit form shown as a bottom sheet; resolves to the changes to send, or null when cancelled / nothing changed.
Future<Map<String, dynamic>?> editSubscriptionSettings(BuildContext context, Subscription sub) {
  return showModalBottomSheet<Map<String, dynamic>>(
    context: context,
    isScrollControlled: true,
    builder: (_) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: _SettingsForm(sub: sub),
    ),
  );
}

class _SettingsForm extends StatefulWidget {
  const _SettingsForm({required this.sub});

  final Subscription sub;

  @override
  State<_SettingsForm> createState() => _SettingsFormState();
}

class _SettingsFormState extends State<_SettingsForm> {
  late final _name = TextEditingController(text: widget.sub.nickname);
  late num _interval = widget.sub.paused ? 0 : widget.sub.updateInterval;
  late bool _auto = widget.sub.autoDownload, _nfo = widget.sub.generateNfo;
  late String _quality = kQualities.any((q) => q.$1 == widget.sub.quality) ? widget.sub.quality : 'best';

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('订阅设置', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
          const SizedBox(height: 16),
          TextField(controller: _name, decoration: const InputDecoration(labelText: '昵称', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            initialValue: kIntervals.any((i) => i.$1 == _interval.round()) ? _interval.round() : null,
            decoration: const InputDecoration(labelText: '检查频率', border: OutlineInputBorder()),
            items: [for (final (value, label) in kIntervals) DropdownMenuItem(value: value, child: Text(label))],
            onChanged: (v) => setState(() => _interval = v ?? _interval),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _quality,
            decoration: const InputDecoration(labelText: '下载画质', border: OutlineInputBorder()),
            items: [for (final (value, label) in kQualities) DropdownMenuItem(value: value, child: Text(label))],
            onChanged: (v) => setState(() => _quality = v ?? _quality),
          ),
          SwitchListTile(
              contentPadding: EdgeInsets.zero, title: const Text('发现新作品时自动下载'), value: _auto, onChanged: (v) => setState(() => _auto = v)),
          SwitchListTile(
              contentPadding: EdgeInsets.zero, title: const Text('生成 NFO（媒体服务器用）'), value: _nfo, onChanged: (v) => setState(() => _nfo = v)),
          const SizedBox(height: 8),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
            const SizedBox(width: 8),
            FilledButton(
              onPressed: () {
                final changes = settingsChanges(widget.sub, nickname: _name.text, interval: _interval, auto: _auto, nfo: _nfo, quality: _quality);
                Navigator.pop(context, changes.isEmpty ? null : changes);
              },
              child: const Text('保存'),
            ),
          ]),
        ]),
      ),
    );
  }
}
