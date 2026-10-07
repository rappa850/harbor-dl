import 'package:flutter/material.dart';

import 'api.dart';
import 'feed_page.dart';

const _tabs = [('random', '推荐'), ('latest', '最新'), ('favorites', '收藏'), ('history', '历史')];

/// The feed with a mode switcher on top. Each mode is its own feed (own pagination, own players).
class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  String _mode = 'random';

  void _openAuthor(String author) => Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => FeedPage(
          api: widget.api,
          onLogout: widget.onLogout,
          mode: 'latest',
          author: author,
          header: _AuthorBar(author: author))));

  @override
  Widget build(BuildContext context) {
    return FeedPage(
      key: ValueKey(_mode),
      api: widget.api,
      onLogout: widget.onLogout,
      mode: _mode,
      onAuthor: _openAuthor,
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

class _AuthorBar extends StatelessWidget {
  const _AuthorBar({required this.author});

  final String author;

  @override
  Widget build(BuildContext context) => Row(children: [
        IconButton(onPressed: () => Navigator.of(context).maybePop(), icon: const Icon(Icons.arrow_back, color: Colors.white)),
        Expanded(
            child: Text('@$author',
                maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w600))),
      ]);
}
