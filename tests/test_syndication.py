import datetime as dt
import re
from pathlib import Path
from xml.etree import ElementTree as ET
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from syndication import confirmed_events, calendar_ics, events_rss, ical_fold

D=dt.date(2026,11,1)
CURRENT={"id":"evt-001","title":"Finance & Banking Networking","starts_at":"2026-11-05T18:00:00+11:00",
"ends_at":"2026-11-05T20:00:00+11:00","registration_url":"https://www.unit.org.au/event",
"source_urls":["https://www.unit.org.au/event"],"organiser":"UNIT","location":"Sydney CBD",
"eligibility":"Open to first years","collection_status":"current"}


def test_calendar_contains_only_current_future_events():
    current=dict(CURRENT)
    old=dict(CURRENT,id="old",starts_at="2026-10-30T19:00:00+11:00")
    last=dict(CURRENT,id="stale",collection_status="last_known")
    text=calendar_ics([current,old,last],D,dt.datetime(2026,11,1,tzinfo=dt.timezone.utc))
    assert text.count('BEGIN:VEVENT')==1
    assert 'DTSTART:20261105T070000Z' in text
    assert 'DTEND:20261105T090000Z' in text
    assert 'Finance & Banking Networking' in text
    assert 'old@' not in text and 'stale@' not in text


def test_date_only_winter_event_is_allday_and_no_fabricated_time():
    dated=dict(CURRENT,id="allday",starts_at="2027-06-15",ends_at=None)
    output=calendar_ics([dated],dt.date(2027,6,1))
    assert 'DTSTART;VALUE=DATE:20270615' in output
    assert 'DTEND;VALUE=DATE:20270616' in output
    assert 'DTSTART:202706' not in output


def test_start_time_without_end_does_not_invent_one():
    e=dict(CURRENT,ends_at=None)
    out=calendar_ics([e],D)
    assert 'DTSTART:20261105T070000Z' in out
    assert 'DTEND:' not in out


def test_calendar_url_and_escaping_safety_and_long_lines():
    event=dict(CURRENT,title='Finance, Banking; Networking\\nFree event 🌏' * 5)
    out=calendar_ics([event],D)
    assert 'SUMMARY:' in out and r'\,' in out and r'\;' in out and r'\n' in out.replace('\r\n ', '')
    assert all(len(line.encode('utf-8'))<=75 for line in out.split('\r\n'))
    assert out.endswith('END:VCALENDAR\r\n')


def test_rss_well_formed_and_filters_unverified():
    old=dict(CURRENT,id='stale',collection_status='last_known')
    txt=events_rss([CURRENT,old],D)
    root=ET.fromstring(txt)
    assert root.tag=='rss'
    entries=root.findall('./channel/item')
    assert len(entries)==1
    assert entries[0].find('title').text=='Finance & Banking Networking'
    assert 'Event' in root.find('./channel/title').text


def test_no_current_events_still_valid_empty_feeds():
    assert 'BEGIN:VEVENT' not in calendar_ics([],D)
    assert ET.fromstring(events_rss([],D)).find('./channel') is not None


def test_syndication_is_in_public_artifact_package():
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/refresh-and-publish.yml').read_text()
    assert 'cp data/events.ics data/events.xml _site/' in workflow
    assert 'data/events.ics data/events.xml' in workflow

def test_rss_first_seen_is_stable_when_feed_regenerated():
    e=dict(CURRENT,first_seen_at='2026-11-01T10:05:00+11:00')
    a=ET.fromstring(events_rss([e],D,dt.datetime(2026,11,1,tzinfo=dt.timezone.utc)))
    b=ET.fromstring(events_rss([e],D,dt.datetime(2026,11,2,tzinfo=dt.timezone.utc)))
    first=a.find('./channel/item/pubDate').text
    assert first==b.find('./channel/item/pubDate').text
    assert 'Oct' in first

def test_rss_legacy_event_still_has_pubdate():
    assert ET.fromstring(events_rss([CURRENT],D)).find('./channel/item/pubDate') is not None
