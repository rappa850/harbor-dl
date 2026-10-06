"""Kodi-style <movie> NFO, the format Jellyfin and Emby read from the folder next to a video."""
import re
import xml.etree.ElementTree as ET

INVALID = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]')


def text(value):
    return INVALID.sub('', str(value))


def build_movie_nfo(meta):
    """meta: title, original_title, plot, premiered ('YYYY-MM-DD'), dateadded, runtime_minutes, duration_seconds,
    author, platform, platform_name, work_id, source_url, tags, poster. Returns the document as text."""
    root = ET.Element('movie')

    def add(parent, name, value, **attrs):
        if value in (None, '', []):
            return None
        node = ET.SubElement(parent, name, {k: text(v) for k, v in attrs.items()})
        node.text = text(value)
        return node

    add(root, 'title', meta['title'])
    add(root, 'originaltitle', meta.get('original_title') or meta['title'])
    add(root, 'sorttitle', meta['title'])
    add(root, 'plot', meta.get('plot'))
    premiered = meta.get('premiered')
    if premiered:
        add(root, 'premiered', premiered)
        add(root, 'releasedate', premiered)
        add(root, 'year', premiered[:4])
    add(root, 'dateadded', meta.get('dateadded'))
    add(root, 'runtime', meta.get('runtime_minutes'))
    author = meta.get('author')
    add(root, 'director', author)
    add(root, 'credits', author)
    add(root, 'studio', meta.get('platform_name'))
    add(root, 'genre', meta.get('platform_name'))
    for tag in meta.get('tags') or []:
        add(root, 'tag', tag)
    if author:
        actor = ET.SubElement(root, 'actor')
        add(actor, 'name', author)
        add(actor, 'role', '创作者')
    add(root, 'uniqueid', meta.get('work_id'), type=meta.get('platform') or 'harbor', default='true')
    add(root, 'website', meta.get('source_url'))
    add(root, 'thumb', meta.get('poster'), aspect='poster')
    seconds = meta.get('duration_seconds')
    if seconds:
        details = ET.SubElement(ET.SubElement(ET.SubElement(root, 'fileinfo'), 'streamdetails'), 'video')
        add(details, 'durationinseconds', int(seconds))
    add(root, 'lockdata', 'true')
    ET.indent(root, space='  ')
    return '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n' + ET.tostring(root, encoding='unicode') + '\n'
