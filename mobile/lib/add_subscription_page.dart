import 'package:flutter/material.dart';

import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';
import 'widgets.dart';

/// Pick a kind, paste a link, add. Likes and favorites need no link; a Douyin mix can be picked from the account's collection.
class AddSubscriptionPage extends StatefulWidget {
  const AddSubscriptionPage({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<AddSubscriptionPage> createState() => _AddSubscriptionPageState();
}

class _AddSubscriptionPageState extends State<AddSubscriptionPage> {
  final _link = TextEditingController(), _name = TextEditingController();
  SubscriptionKind _kind = kSubscriptionKinds.first;
  num _interval = 28800;
  bool _auto = false, _busy = false, _loadingMixes = false;
  String? _error;
  List<MixChoice>? _mixes;

  @override
  void dispose() {
    _link.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_kind.needsLink && _link.text.trim().isEmpty) {
      setState(() => _error = '请先填写链接');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final created = await widget.api.addSubscription(_kind, link: _link.text, nickname: _name.text, interval: _interval, autoDownload: _auto);
      if (mounted) Navigator.pop(context, created);
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

  Future<void> _loadMixes() async {
    setState(() {
      _loadingMixes = true;
      _error = null;
    });
    try {
      final mixes = await widget.api.collectedMixes();
      if (mounted) setState(() => _mixes = mixes);
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loadingMixes = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Column(children: [
          const BackBar(title: '添加订阅'),
          Expanded(
            child: ListView(padding: const EdgeInsets.all(16), children: [
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final kind in kSubscriptionKinds)
                  ChoiceChip(
                    label: Text(kind.label),
                    selected: _kind.id == kind.id,
                    onSelected: _busy
                        ? null
                        : (_) => setState(() {
                              _kind = kind;
                              _error = null;
                              _mixes = null;
                              _auto = kind.autoDownloadDefault;
                            }),
                  ),
              ]),
              const SizedBox(height: 16),
              if (_kind.needsLogin)
                const Padding(
                    padding: EdgeInsets.only(bottom: 12),
                    child: Text('读取抖音作品需要登录状态。手机上不能登录，请先在网页端登录抖音一次。', style: TextStyle(color: Colors.white54, fontSize: 12))),
              if (_kind.needsLink) ...[
                TextField(
                    controller: _link,
                    enabled: !_busy,
                    maxLines: 2,
                    minLines: 1,
                    decoration: InputDecoration(labelText: _kind.hint, border: const OutlineInputBorder())),
                if (_kind.id == 'douyin_mix')
                  Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton(
                          onPressed: _busy || _loadingMixes ? null : _loadMixes, child: Text(_loadingMixes ? '读取中…' : '从我收藏的合集里选'))),
                if (_mixes != null)
                  _mixes!.isEmpty
                      ? const Padding(padding: EdgeInsets.all(8), child: Text('没有读取到收藏的合集', style: TextStyle(color: Colors.white54)))
                      : Column(children: [
                          for (final mix in _mixes!)
                            ListTile(
                              dense: true,
                              title: Text(mix.title, style: const TextStyle(color: Colors.white)),
                              subtitle: Text([if (mix.author != null) mix.author!, if (mix.count != null) '${mix.count} 集'].join(' · '),
                                  style: const TextStyle(color: Colors.white54)),
                              onTap: () => setState(() {
                                _link.text = mix.id;
                                _mixes = null;
                              }),
                            ),
                        ]),
              ] else
                Text(_kind.hint, style: const TextStyle(color: Colors.white70)),
              const SizedBox(height: 16),
              TextField(
                  controller: _name,
                  enabled: !_busy,
                  decoration: const InputDecoration(labelText: '自定义昵称（可选）', border: OutlineInputBorder())),
              const SizedBox(height: 16),
              DropdownButtonFormField<int>(
                initialValue: _interval.round(),
                decoration: const InputDecoration(labelText: '检查频率', border: OutlineInputBorder()),
                items: [for (final (value, label) in kIntervals) DropdownMenuItem(value: value, child: Text(label))],
                onChanged: _busy ? null : (v) => setState(() => _interval = v ?? 28800),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('发现新作品时自动下载'),
                subtitle: Text(_kind.source == 'like' || _kind.source == 'favorite'
                    ? '默认关闭：点赞和收藏数量可能很大，先只记录，需要时再下载。'
                    : '关闭时只记录作品，需要时在作品列表里下载。开启后首次扫描到的作品也会入队。'),
                value: _auto,
                onChanged: _busy ? null : (v) => setState(() => _auto = v),
              ),
              if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: const TextStyle(color: Colors.redAccent))),
              const SizedBox(height: 16),
              FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? '正在解析…' : '解析并添加')),
            ]),
          ),
        ]),
      ),
    );
  }
}
