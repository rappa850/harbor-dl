import 'dart:async';

import 'package:flutter/material.dart';

import 'add_subscription_page.dart';
import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';
import 'subscription_page.dart';
import 'widgets.dart';

/// Every subscription with its state; tap one to control it. Reloads when the tab is shown again and while something syncs.
class SubscriptionsPage extends StatefulWidget {
  const SubscriptionsPage({super.key, required this.api, required this.onLogout, this.active = true, required this.onPlay});

  final Api api;
  final VoidCallback onLogout;
  final bool active;

  /// Opens one downloaded work in the feed player.
  final Future<void> Function(FeedItem item) onPlay;

  @override
  State<SubscriptionsPage> createState() => _SubscriptionsPageState();
}

class _SubscriptionsPageState extends State<SubscriptionsPage> {
  List<Subscription>? _items;
  String? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(SubscriptionsPage old) {
    super.didUpdateWidget(old);
    if (!old.active && widget.active) _load();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final items = await widget.api.subscriptions();
      if (!mounted) return;
      setState(() {
        _items = items;
        _error = null;
      });
      _poll?.cancel();
      if (items.any((s) => s.runtime.isSyncing)) _poll = Timer(const Duration(seconds: 4), () => widget.active ? _load() : null);
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _open(Subscription sub) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => SubscriptionPage(api: widget.api, subscriptionId: sub.id, onLogout: widget.onLogout, onPlay: widget.onPlay)));
    if (mounted) _load();
  }

  Future<void> _add() async {
    final created = await Navigator.of(context).push<Subscription>(
        MaterialPageRoute(builder: (_) => AddSubscriptionPage(api: widget.api, onLogout: widget.onLogout)));
    if (created != null && mounted) {
      await _load();
      if (mounted) _open(created);
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = _items;
    return Scaffold(
      backgroundColor: Colors.black,
      floatingActionButton: FloatingActionButton.extended(onPressed: _add, icon: const Icon(Icons.add), label: const Text('添加订阅')),
      body: SafeArea(
        bottom: false,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Padding(
              padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: Text('订阅', style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w700))),
          if (items != null && items.any((s) => s.needsAttention))
            Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
                child: Text('${items.where((s) => s.needsAttention).length} 个订阅需要处理', style: const TextStyle(color: Colors.orangeAccent))),
          Expanded(
            child: items == null
                ? Center(child: _error == null ? const CircularProgressIndicator() : _Retry(message: _error!, onRetry: _load))
                : RefreshIndicator(
                    onRefresh: _load,
                    child: items.isEmpty
                        ? ListView(children: const [
                            SizedBox(height: 120),
                            Center(child: Text('还没有订阅，点右下角添加', style: TextStyle(color: Colors.white54))),
                          ])
                        : ListView.separated(
                            padding: const EdgeInsets.only(bottom: 96),
                            itemCount: items.length,
                            separatorBuilder: (_, _) => const Divider(height: 1, color: Colors.white10),
                            itemBuilder: (_, i) => _SubscriptionTile(sub: items[i], api: widget.api, onTap: () => _open(items[i])),
                          ),
                  ),
          ),
        ]),
      ),
    );
  }
}

class _Retry extends StatelessWidget {
  const _Retry({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Column(mainAxisSize: MainAxisSize.min, children: [
        Text(message, style: const TextStyle(color: Colors.white70)),
        const SizedBox(height: 8),
        OutlinedButton(onPressed: onRetry, child: const Text('重试')),
      ]);
}

class _SubscriptionTile extends StatelessWidget {
  const _SubscriptionTile({required this.sub, required this.api, required this.onTap});

  final Subscription sub;
  final Api api;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = sub.needsAttention ? Colors.orangeAccent : (sub.runtime.isSyncing ? Colors.lightBlueAccent : Colors.white54);
    return ListTile(
      onTap: onTap,
      leading: Avatar(session: api.session, name: sub.nickname, path: null, size: 44),
      title: Text(sub.nickname, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white)),
      subtitle: Text('${sub.label} · ${sub.runtime.storedVideos} 个作品 · ${sub.stateText}', style: TextStyle(color: color, fontSize: 12)),
      trailing: sub.runtime.isSyncing
          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
          : const Icon(Icons.chevron_right, color: Colors.white38),
    );
  }
}
