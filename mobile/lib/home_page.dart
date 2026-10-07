import 'package:flutter/material.dart';

import 'api.dart';
import 'feed_page.dart';

const _tabs = [('random', '推荐'), ('latest', '最新'), ('favorites', '收藏'), ('history', '历史')];

/// The feed with a mode switcher on top. Each mode is its own feed (own pagination, own players).
class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.api, required this.onLogout, required this.onAuthor, this.active = true});

  final Api api;
  final VoidCallback onLogout;
  final Future<void> Function(String author) onAuthor;

  /// False while another tab is showing.
  final bool active;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  String _mode = 'random';

  @override
  Widget build(BuildContext context) {
    return FeedPage(
      key: ValueKey(_mode),
      api: widget.api,
      onLogout: widget.onLogout,
      mode: _mode,
      active: widget.active,
      onAuthor: widget.onAuthor,
      header: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        for (final (id, label) in _tabs)
          TextButton(
            onPressed: _mode == id ? null : () => setState(() => _mode = id),
            child: Text(label,
                style: TextStyle(
                    fontSize: _mode == id ? 18 : 16,
                    fontWeight: _mode == id ? FontWeight.w700 : FontWeight.w400,
                    color: _mode == id ? Colors.white : Colors.white60)),
          ),
      ]),
    );
  }
}
