import datetime as dt
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect
import notify
import pytest

TODAY=dt.date(2026,10,31)

UNIT_HOME='''<html><h2>Upcoming Events</h2><h3>Exploring Legal and Financial Careers</h3><p>Morgan Stanley is inviting pre-penultimate students to the Evening with Morgan Stanley event.</p><p>Thursday, 5th November</p><p>6-8 pm, Morgan Stanley Office, CBD</p><a href="https://forms.gle/example">REGISTER HERE</a><h2>UNIT Scroll</h2><p>10 January 2028 irrelevant</p></html>'''
UNIT_CALENDAR='''<html><h1>Upcoming UNIT Events</h1><article><h1>Exploring Legal and Financial Careers</h1><time>Thursday 23 July 2026</time><time>6:00 pm</time><time>8:00 pm</time></article></html>'''
FMAA_INDEX='''<html><h1>OUR EVENTS</h1><article><h2>McKinsey &amp; Company&#39;s 2026 AI and The Path to Progress Workshop</h2><p>November 26, 2026 10:00 AM</p><a href="/event/mckinsey-ai">Find Out More</a></article></html>'''
FMAA_DETAIL='''<html><h1>McKinsey &amp; Company's 2026 AI and The Path to Progress Workshop</h1><div>November 26, 2026 10:00 AM</div><p>Time: 10:00am - 3:00pm</p><p>Eligibility: Penultimate-year undergraduate and Master's students only.</p></html>'''
UNSW='''<html><h1>Events | Employability</h1><div class="event"><time>Mon 2 Nov 2026</time><a href="https://www.eventbrite.com.au/e/123">All students and recent graduates Leveraging LinkedIn workshop | online 4:00 PM - 5:00 PM Read more</a></div></html>'''
FINSOC='''<html><h2>UPCOMING EVENTS.</h2><a href="https://www.facebook.com/test">workshop Aug 17, 2026 FINS2615 Workshop VIEW ON FACEBOOK</a><h2>PAST HIGHLIGHTS</h2><a href="https://www.facebook.com/test2">networking Nov 8, 2026 Old panel VIEW ON FACEBOOK</a></html>'''


def fake_fetch(url):
    if url=='https://www.unit.org.au/':return UNIT_HOME
    if url=='https://www.unit.org.au/upcoming-events':return UNIT_CALENDAR
    if url=='https://www.fmaa.com.au/events':return FMAA_INDEX
    if url=='https://www.fmaa.com.au/event/mckinsey-ai':return FMAA_DETAIL
    if url=='https://www.unsw.edu.au/employability/events-news/events':return UNSW
    if url=='https://www.unswfinsoc.org.au/':return FINSOC
    raise RuntimeError('not in stub '+url)


def test_unit_does_not_misread_unrelated_dates():
    found=collect.parse_unit_home(UNIT_HOME,TODAY)
    assert len(found)==1
    assert found[0]['title']=='Evening with Morgan Stanley'
    assert found[0]['starts_at']=='2026-11-05T18:00:00+11:00'
    assert found[0]['registration_url']=='https://forms.gle/example'
    assert collect.parse_unit_home('<h2>Upcoming Events</h2><h3>No scheduled dates yet</h3><h2>UNIT Scroll</h2>12 Dec 2026',TODAY)==[]


def test_unit_archive_past_events_is_healthy_empty():
    assert collect.parse_unit_calendar(UNIT_CALENDAR,TODAY)==[]


def test_fmaa_restricted_without_guessing():
    found=collect.parse_fmaa(FMAA_INDEX,TODAY,fetch_detail=fake_fetch)
    assert len(found)==1
    assert found[0]['fit']=='restricted'
    assert found[0]['starts_at']=='2026-11-26T10:00:00+11:00'
    assert found[0]['ends_at']=='2026-11-26T15:00:00+11:00'


def test_finsoc_no_past_highlights_leak():
    assert collect.parse_finsoc(FINSOC,TODAY)==[]


def test_unsw_career_and_date():
    events=collect.parse_unsw(UNSW,TODAY)
    assert len(events)==1
    assert events[0]['starts_at'].startswith('2026-11-02T16:00:00')


def test_malformed_source_is_error_not_fake_event():
    with pytest.raises(ValueError):collect.parse_fmaa('<h1>not the source</h1>',TODAY)
    assert collect.parse_date('22 November',dt.date(2026,11,23))==dt.date(2026,11,22)
    assert collect.parse_date('5 Jan',dt.date(2026,12,30))==dt.date(2027,1,5)


def test_duplicate_sources_restriction_carries():
    a=collect.event('FMAA','McKinsey AI and the Path to Progress',dt.date(2026,11,26),'10:00am','https://www.fmaa.com.au/event/mckinsey-ai',today=TODAY)
    b=collect.event('UNSW Employability','McKinsey AI & the Path to Progress',dt.date(2026,11,26),'10:00am','https://www.unsw.edu.au/',today=TODAY,eligibility='Penultimate-year students only.')
    result=collect.unique([a,b])
    assert len(result)==1 and len(result[0]['sources'])==2 and result[0]['fit']=='restricted'


def test_two_runs_detect_new_events_once(tmp_path):
    (tmp_path/'snapshot.json').write_text(json.dumps({'events':[],'sources':[]}))
    payload,health=collect.collect(today=TODAY,fetcher=fake_fetch,folder=tmp_path)
    assert len(payload['events'])==3
    assert health['new_event_ids']==[] # initial import never triggers alerts
    assert health['sources']['unit_calendar']['status']=='accessible_empty'
    assert health['sources']['finsoc']['status']=='accessible_empty'
    _,health2=collect.collect(today=TODAY,fetcher=fake_fetch,folder=tmp_path)
    assert health2['new_event_ids']==[]
    more='''<html><h1>Events | Employability</h1><div><time>Mon 2 Nov 2026</time><a href="https://www.eventbrite.com.au/e/123">All students and recent graduates Leveraging LinkedIn workshop | online 4:00 PM - 5:00 PM Read more</a></div><div><time>Mon 9 Nov 2026</time><a href="https://www.eventbrite.com.au/e/222">Investment Banking Careers Panel 5:00 PM - 6:30 PM Read more</a></div></html>'''
    def updated(url):return more if url==collect.SOURCES['unsw'][1] else fake_fetch(url)
    payload3,health3=collect.collect(today=TODAY,fetcher=updated,folder=tmp_path)
    assert len(health3['new_event_ids'])==1
    assert any('Investment Banking Careers Panel'==e['title'] for e in payload3['events'])
    _,health4=collect.collect(today=TODAY,fetcher=updated,folder=tmp_path)
    assert health4['new_event_ids']==[]


def test_collector_outage_preserves_last_known_and_flags(tmp_path):
    (tmp_path/'snapshot.json').write_text(json.dumps({'events':[],'sources':[]}))
    collect.collect(today=TODAY,fetcher=fake_fetch,folder=tmp_path)
    def failed(url):raise RuntimeError('HTTP 503')
    data,h=collect.collect(today=TODAY,fetcher=failed,folder=tmp_path)
    assert all(s['status']=='error' for s in h['sources'].values())
    assert data['events'] and all(e['collection_status']=='last_known' for e in data['events'])
    assert not h['new_event_ids']
    data,h=collect.collect(today=dt.date(2026,11,10),fetcher=failed,folder=tmp_path)
    assert not data['events'] # expire stale records instead of silently advertising as current


def test_no_email_without_verified_credentials(monkeypatch):
    for key in ('RESEND_API_KEY','RADAR_RECIPIENT_EMAIL','RADAR_FROM_EMAIL'):monkeypatch.delenv(key,raising=False)
    assert notify.notify()==0


def test_unsw_dynamic_without_dates_is_flagged():
    with pytest.raises(ValueError,match='No dated event cards'):
        collect.parse_unsw('<h1>Employability Events</h1><p>Browse industry workshops and opportunities.</p>', TODAY)


def test_schema_org_public_event_fallback():
    raw='''<html><h1>Events</h1><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Event","name":"Trading & Markets Networking Panel","startDate":"2026-11-10T18:30:00+11:00","endDate":"2026-11-10T20:00:00+11:00","location":{"@type":"Place","name":"UNSW Kensington"},"url":"https://events.example.edu/panel"}]}</script></html>'''
    found=collect.jsonld_events(raw,'UNSW Employability','https://www.unsw.edu.au/employability/events-news/events',TODAY)
    assert len(found)==1
    assert found[0]['starts_at']=='2026-11-10T18:30:00+11:00'
    assert found[0]['location']=='UNSW Kensington'
    assert found[0]['ends_at']=='2026-11-10T20:00:00+11:00'


def test_same_directory_url_is_not_duplicate_event():
    a=collect.event('UNIT','Finance Careers Evening',dt.date(2026,11,5),'6:00pm','https://www.unit.org.au/',today=TODAY)
    b=collect.event('UNIT','Trading Career Workshop',dt.date(2026,11,5),'7:00pm','https://www.unit.org.au/',today=TODAY)
    assert len(collect.unique([a,b]))==2


def test_unsw_read_more_link_has_title_in_parent_card():
    """UNSW commonly puts only Read more inside the registration anchor."""
    html='''<html><h1>Events | Employability</h1><div class="event">
      <span>Mon 2 Nov 2026</span><span>All students and recent graduates</span>
      <strong>Leveraging LinkedIn workshop | online</strong>
      <span>4:00 PM - 5:00 PM</span><p>Learn how to research industries.</p>
      <a href="https://www.eventbrite.com.au/e/real-event-123">Read more</a>
    </div></html>'''
    records=collect.parse_unsw(html,TODAY)
    assert len(records)==1
    assert records[0]['title']=='Leveraging LinkedIn workshop'
    assert records[0]['starts_at']=='2026-11-02T16:00:00+11:00'
    assert records[0]['registration_url']=='https://www.eventbrite.com.au/e/real-event-123'


def test_fmaa_valid_old_detail_and_one_failed_link_is_not_total_failure():
    """Past listings plus a broken detail link aren't a total parser outage."""
    page='''<h1>OUR EVENTS</h1><a href="/event/old">Old event</a>
      <a href="/event/broken">Broken event</a>'''
    def fetch(url):
        if url.endswith('/broken'): raise RuntimeError('HTTP 404')
        return '<h1>Finance Careers Evening</h1><p>June 1, 2026 6:00 PM</p>'
    assert collect.parse_fmaa(page,TODAY,fetch_detail=fetch)==[]


def test_unsw_read_more_not_a_reason_to_import_unrelated_event():
    html='''<h1>Events</h1><div><span>Wed 11 Nov 2026</span>
      <strong>Physics and Nuclear Reactor Workshop | online</strong>
      <span>3:00 PM - 4:00 PM</span><a href="https://www.eventbrite.com.au/e/123">Read more</a>
      </div>'''
    assert collect.parse_unsw(html,TODAY)==[]


def test_source_url_hostname_is_checked_not_substring():
    html='''<h1>Events</h1><div>Mon 2 Nov 2026 Investment Banking Evening
      6:00 PM - 7:00 PM <a href="https://eventbrite.com.au.bad-example.com/e/123">Read more</a>
    </div>'''
    assert collect.parse_unsw(html,TODAY)==[]
