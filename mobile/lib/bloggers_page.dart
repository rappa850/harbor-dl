import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'blogger_page.dart';
import 'widgets.dart';

const _sorts = [('recent', '最近更新'), ('count', '作品最多'), ('name', '名称')];

/// Everyone whose videos are in the library, searchable, with the profile picture and numbers from their subscription.
class BloggersPage extends StatefulWidget {
  const BloggersPage({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<BloggersPage> createState() => _BloggersPageState();
}

class _BloggersPageState extends State<BloggersPage> {
  final _search = TextEditingController();
  List<Blogger>? _items;
  String _sort = 'recent', _query = '';
  String? _error;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final query = _query, sort = _sort;
    try {
      final items = await widget.api.bloggers(query: query, sort: sort);
      // a slower answer for an older search must not overwrite the newer one
      if (mounted && query == _query && sort == _sort) {
        setState(() {
          _items = items;
          _error = null;
        });
      }
    } on Unauthorized {
      widget.onLogout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  void _typed(String text) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      _query = text.trim();
      _load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final items = _items, session = widget.api.session;
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        bottom: false,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Padding(
              padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: Text('博主', style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w700))),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: TextField(
              controller: _search,
              onChanged: _typed,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: '搜索博主',
                prefixIcon: const Icon(Icons.search),
                filled: true,
                fillColor: Colors.white10,
                isDense: true,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () {
                          _search.clear();
                          _query = '';
                          _load();
                          setState(() {});
                        }),
              ),
            ),
          ),
          SizedBox(
            height: 52,
            child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
              for (final (id, label) in _sorts)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                  child: ChoiceChip(
                      label: Text(label),
                      selected: _sort == id,
                      onSelected: (_) {
                        setState(() => _sort = id);
                        _load();
                      }),
                ),
            ]),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _load,
              child: items == null
                  ? Center(
                      child: _error == null
                          ? const CircularProgressIndicator(strokeWidth: 2)
                          : Column(mainAxisSize: MainAxisSize.min, children: [
                              Text(_error!, style: const TextStyle(color: Colors.white54)),
                              TextButton(onPressed: _load, child: const Text('重试')),
                            ]))
                  : items.isEmpty
                      ? ListView(children: [
                          const SizedBox(height: 120),
                          Center(child: Text(_query.isEmpty ? '库里还没有博主，先去下载一些视频' : '没有找到“$_query”', style: const TextStyle(color: Colors.white54))),
                        ])
                      : ListView.builder(
                          itemCount: items.length,
                          itemBuilder: (context, i) {
                            final blogger = items[i];
                            final meta = [
                              '${blogger.count} 个作品',
                              if (blogger.followers != null) '${formatCount(blogger.followers!)} 粉丝',
                              if (blogger.platform.isNotEmpty) platformLabel(blogger.platform),
                            ].join(' · ');
                            return ListTile(
                              contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                              leading: Avatar(session: session, name: blogger.author, path: blogger.avatar, size: 52),
                              title: Text(blogger.author, maxLines: 1, overflow: TextOverflow.ellipsis),
                              subtitle: Text(blogger.signature.isEmpty ? meta : '$meta\n${blogger.signature}',
                                  maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white54)),
                              isThreeLine: blogger.signature.isNotEmpty,
                              trailing: const Icon(Icons.chevron_right, color: Colors.white38),
                              onTap: () async {
                                await openBlogger(context, widget.api, widget.onLogout, blogger.author, known: blogger);
                              },
                            );
                          }),
            ),
          ),
        ]),
      ),
    );
  }
}
