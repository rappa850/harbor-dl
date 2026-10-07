import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'api.dart';
import 'feed_page.dart';

/// Round picture from the server (needs the bearer header), or the first letter of [name] while there is none.
class Avatar extends StatelessWidget {
  const Avatar({super.key, required this.session, required this.name, this.path, this.size = 48});

  final Session session;
  final String name;
  final String? path;
  final double size;

  @override
  Widget build(BuildContext context) {
    final letter = Center(
        child: Text(name.isEmpty ? '?' : name.characters.first.toUpperCase(),
            style: TextStyle(color: Colors.white, fontSize: size * 0.42, fontWeight: FontWeight.w600)));
    return ClipOval(
      child: SizedBox(
        width: size,
        height: size,
        child: ColoredBox(
          color: Colors.white12,
          child: path == null
              ? letter
              : CachedNetworkImage(
                  imageUrl: session.url(path!),
                  httpHeaders: session.headers,
                  fit: BoxFit.cover,
                  fadeInDuration: const Duration(milliseconds: 120),
                  errorWidget: (_, _, _) => letter),
        ),
      ),
    );
  }
}

class BackBar extends StatelessWidget {
  const BackBar({super.key, this.title = ''});

  final String title;

  @override
  Widget build(BuildContext context) => Row(children: [
        IconButton(onPressed: () => Navigator.of(context).maybePop(), icon: const Icon(Icons.arrow_back, color: Colors.white)),
        Expanded(
            child: Text(title,
                maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w600))),
      ]);
}

/// Full-screen feed over the current page, starting at [seed.index]; completes when the user comes back.
Future<void> openFeed(BuildContext context,
    {required Api api, required VoidCallback onLogout, required FeedSeed seed, required String mode, String author = ''}) {
  return Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => FeedPage(api: api, onLogout: onLogout, mode: mode, author: author, initial: seed, header: const BackBar())));
}

String formatDuration(num? seconds) {
  if (seconds == null || seconds <= 0) return '';
  final total = seconds.round();
  final minutes = total ~/ 60, rest = total % 60;
  return '${minutes.toString().padLeft(2, '0')}:${rest.toString().padLeft(2, '0')}';
}

String formatCount(int n) => n >= 10000 ? '${(n / 10000).toStringAsFixed(n >= 100000 ? 0 : 1)} 万' : '$n';
