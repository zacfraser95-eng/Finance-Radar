"""Standards-based public event feeds for Finance Radar.

Only current, source-backed listings are syndicated. Never publish social-bio
leads or last-known records as confirmed events.
"""
from __future__ import annotations
import datetime as dt
import re
from xml.etree import ElementTree as ET
from email.utils import format_datetime
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo('Australia/Sydney')
SITE = 'https://zacfraser95-eng.github.io/Finance-Radar/'


def confirmed_events(events: list[dict], today: dt.date) -> list[dict]:
    result = []
    for e in events:
        if e.get('collection_status') != 'current':
            continue
        start = e.get('starts_at', '')
        if not isinstance(start, str) or not re.match(r'^\d{4}-\d{2}-\d{2}(?:T.*)?$', start):
            continue
        try:
            date = dt.date.fromisoformat(start[:10])
        except ValueError:
            continue
        if date < today:
            continue
        link = e.get('registration_url') or (e.get('source_urls') or [''])[0]
        if not isinstance(link, str) or not link.startswith('https://'):
            continue
        result.append(e)
    return sorted(result, key=lambda e: e['starts_at'])


def ical_escape(value: str) -> str:
    return str(value).replace('\\', '\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n','\\n').replace(';','\\;').replace(',','\\,')


def ical_fold(line: str) -> str:
    """Fold at <=75 UTF-8 octets per physical line (RFC 5545)."""
    out = []
    cur = ''
    count = 0
    for ch in line:
        size = len(ch.encode('utf-8'))
        if count + size > 75:
            out.append(cur)
            cur = ' '
            count = 1
        cur += ch
        count += size
    out.append(cur)
    return '\r\n'.join(out)


def iso_utc(value: str) -> str:
    timestamp = dt.datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError('Timestamp must be timezone aware')
    return timestamp.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def calendar_ics(events: list[dict], today: dt.date, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Generation clock must be timezone aware')
    parts = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Finance Radar//Student Events//EN',
        'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:Finance Radar - Confirmed Events',
        'X-WR-TIMEZONE:Australia/Sydney',
        'X-WR-CALDESC:Currently confirmed UNSW and Sydney finance events. Check organiser details.'
    ]
    for e in confirmed_events(events, today):
        date = dt.date.fromisoformat(e['starts_at'][:10])
        title = e['title']
        link = e.get('registration_url') or e['source_urls'][0]
        description = 'Organiser: ' + e.get('organiser', 'See organiser')
        description += '\nEligibility: ' + e.get('eligibility', 'Check with organiser')
        description += '\nOriginal listing: ' + link
        parts.extend([
            'BEGIN:VEVENT',
            'UID:' + ical_escape(str(e['id'])) + '@finance-radar.unsw-student',
            'DTSTAMP:' + now.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        ])
        if len(e['starts_at']) == 10:
            parts.extend([
                'DTSTART;VALUE=DATE:' + date.strftime('%Y%m%d'),
                'DTEND;VALUE=DATE:' + (date + dt.timedelta(days=1)).strftime('%Y%m%d')
            ])
        else:
            try:
                parts.append('DTSTART:' + iso_utc(e['starts_at']))
            except ValueError:
                parts.pop()  # Leave out malformed event entirely (UID/DTSTAMP handled below)
                parts.pop()
                parts.pop()
                continue
            if e.get('ends_at'):
                try:
                    start_time = dt.datetime.fromisoformat(e['starts_at'])
                    end_time = dt.datetime.fromisoformat(e['ends_at'])
                    if end_time > start_time:
                        parts.append('DTEND:' + iso_utc(e['ends_at']))
                except (ValueError, TypeError):
                    pass
        parts.extend([
            'SUMMARY:' + ical_escape(title),
            'DESCRIPTION:' + ical_escape(description),
            'LOCATION:' + ical_escape(e.get('location', 'See organiser')),
            'URL:' + link, 'END:VEVENT'
        ])
    parts.append('END:VCALENDAR')
    return '\r\n'.join(ical_fold(x) for x in parts) + '\r\n'


def events_rss(events: list[dict], today: dt.date, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    root = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(root, 'channel')
    for name, value in (
        ('title', 'Finance Radar - Confirmed UNSW Finance Events'),
        ('link', SITE),
        ('description', 'Currently verified student finance, careers and networking events.'),
        ('language', 'en-AU'),
        ('lastBuildDate', format_datetime(now.astimezone(dt.timezone.utc), usegmt=True))
    ):
        ET.SubElement(channel, name).text = value
    for e in confirmed_events(events, today):
        item = ET.SubElement(channel, 'item')
        link = e.get('registration_url') or e['source_urls'][0]
        text = e['starts_at'][:10] + ' | ' + e.get('organiser', '')
        text += ' | ' + e.get('eligibility', 'Confirm eligibility with organiser')
        for name, value in (
            ('title', e['title']),
            ('link', link),
            ('guid', SITE + '#'+str(e['id'])),
            ('description', text)
        ):
            child = ET.SubElement(item, name)
            if name == 'guid':
                child.set('isPermaLink', 'false')
            child.text = value
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'
