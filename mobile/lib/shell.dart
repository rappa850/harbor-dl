import 'package:flutter/material.dart';

import 'api.dart';
import 'blogger_page.dart';
import 'bloggers_page.dart';
import 'home_page.dart';
import 'me_page.dart';

/// Bottom navigation over the three main tabs. A tab is built on first visit and then kept, so the feed keeps its
/// place; the feed is told when it is covered so it stops playing.
class Shell extends StatefulWidget {
  const Shell({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _tab = 0;
  final _visited = {0};

  @override
  Widget build(BuildContext context) {
    final pages = <Widget Function()>[
      () => HomePage(
          api: widget.api,
          active: _tab == 0,
          onLogout: widget.onLogout,
          onAuthor: (author) => openBlogger(context, widget.api, widget.onLogout, author)),
      () => BloggersPage(api: widget.api, onLogout: widget.onLogout),
      () => MePage(api: widget.api, onLogout: widget.onLogout),
    ];
    return Scaffold(
      backgroundColor: Colors.black,
      body: IndexedStack(index: _tab, children: [for (var i = 0; i < pages.length; i++) _visited.contains(i) ? pages[i]() : const SizedBox()]),
      bottomNavigationBar: NavigationBar(
        backgroundColor: Colors.black,
        height: 60,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() {
          _tab = i;
          _visited.add(i);
        }),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.play_circle_outline), selectedIcon: Icon(Icons.play_circle), label: '首页'),
          NavigationDestination(icon: Icon(Icons.people_outline), selectedIcon: Icon(Icons.people), label: '博主'),
          NavigationDestination(icon: Icon(Icons.person_outline), selectedIcon: Icon(Icons.person), label: '我的'),
        ],
      ),
    );
  }
}
