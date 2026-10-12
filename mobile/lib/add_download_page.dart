import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';
import 'widgets.dart';

/// Paste a link or share text -> the server resolves it -> choose a quality -> queue the download.
class AddDownloadPage extends StatefulWidget {
  const AddDownloadPage({super.key, required this.api, required this.onLogout, this.initialText = ''});

  final Api api;
  final VoidCallback onLogout;

  /// Text handed over by the system share sheet or the clipboard.
  final String initialText;

  @override
  State<AddDownloadPage> createState() => _AddDownloadPageState();
}

class _AddDownloadPageState extends State<AddDownloadPage> {
  late final _text = TextEditingController(text: widget.initialText);
  MediaInfo? _info;
  FormatChoice? _format;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    if (widget.initialText.trim().length >= 10) WidgetsBinding.instance.addPostFrameCallback((_) => _parse());
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _paste() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    if (data?.text != null) {
      setState(() {
        _text.text = data!.text!.trim();
        _info = null;
        _error = null;
      });
    }
  }

  Future<void> _parse() async {
    final text = _text.text.trim();
    if (text.length < 10) {
      setState(() => _error = '请先粘贴链接或分享文本');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      final info = await widget.api.parseLink(text);
      if (!mounted) return;
      setState(() {
        _info = info;
        _format = info.formats.isEmpty ? null : info.formats.first;
        _busy = false;
      });
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '$e';
        });
      }
    }
  }

  Future<void> _start() async {
    final info = _info, format = _format;
    if (info == null || format == null) return;
    setState(() => _busy = true);
    try {
      await widget.api.createTask(info, format);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已加入下载队列')));
        Navigator.pop(context, true);
      }
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final info = _info;
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Column(children: [
          const BackBar(title: '添加下载'),
          Expanded(
            child: ListView(padding: const EdgeInsets.all(16), children: [
              TextField(
                  controller: _text,
                  enabled: !_busy,
                  maxLines: 4,
                  minLines: 2,
                  onChanged: (_) => setState(() {
                        _info = null;
                        _error = null;
                      }),
                  decoration: const InputDecoration(labelText: '链接或分享文本', border: OutlineInputBorder())),
              Row(children: [
                TextButton.icon(onPressed: _busy ? null : _paste, icon: const Icon(Icons.content_paste, size: 18), label: const Text('粘贴')),
                const Spacer(),
                FilledButton(onPressed: _busy ? null : _parse, child: Text(_busy && info == null ? '解析中…' : '解析')),
              ]),
              if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: const TextStyle(color: Colors.redAccent))),
              if (info != null) ...[
                const Divider(height: 32),
                Text(info.title, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
                Text([if (info.author.isNotEmpty) info.author, if (formatDuration(info.duration).isNotEmpty) formatDuration(info.duration)].join(' · '),
                    style: const TextStyle(color: Colors.white54)),
                const SizedBox(height: 12),
                if (info.formats.isEmpty)
                  const Text('没有可用的格式', style: TextStyle(color: Colors.orangeAccent))
                else
                  RadioGroup<FormatChoice>(
                    groupValue: _format,
                    onChanged: (v) => setState(() => _format = v),
                    child: Column(children: [
                      for (final format in info.formats)
                        RadioListTile<FormatChoice>(
                            dense: true, value: format, enabled: !_busy, title: Text(format.label), subtitle: format.kind == 'audio' ? const Text('只下载音频') : null),
                    ]),
                  ),
                const SizedBox(height: 12),
                FilledButton(onPressed: _busy || _format == null ? null : _start, child: Text(_busy ? '正在提交…' : '开始下载')),
              ],
            ]),
          ),
        ]),
      ),
    );
  }
}
