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

SOCIAL_HUB = '''<html><title>FINSOC | Linktree</title><main>
<a href="https://docs.google.com/forms/d/e/sample/viewform">FINSOC x Credit Analyst: Commercial Banking &amp; Credit Analysis Workshop</a>
<a href="https://www.eventbrite.com.au/e/panel-123">UNSW Finance Trading &amp; Markets Panel</a>
<a href="https://www.eventbrite.com.au/e/old-456">Investment Banking Careers Panel 2025</a>
<a href="https://www.eventbrite.com.au/e/nightclub-789">Halloween Nightclub</a>
<a href="https://forms.gle/membership">Sign up for membership</a>
</main><footer><a href="https://www.eventbrite.com.au/e/unrelated-999">Finance Society Conference</a></footer></html>'''
EVENTBRITE_CONFIRMED='''<html><h1>Finance Trading & Markets Panel</h1><script type="application/ld+json">{"@context":"https://schema.org","@type":"Event","name":"Finance Trading & Markets Panel","startDate":"2026-11-20T18:00:00+11:00","endDate":"2026-11-20T20:00:00+11:00","location":{"@type":"Place","name":"UNSW Sydney"}}</script></html>'''
EVENTBRITE_OLD='''<html><script type="application/ld+json">{"@type":"Event","name":"Investment Banking Careers Panel","startDate":"2025-10-15T18:00:00+11:00"}</script></html>'''


def test_social_bio_only_dated_external_events_make_calendar():
    calls=[]
    def fetch(u):
        calls.append(u)
        if u.endswith('/panel-123'):return EVENTBRITE_CONFIRMED
        if u.endswith('/old-456'):return EVENTBRITE_OLD
        raise AssertionError('Should not fetch unrelated or form: '+u)
    events,signals=collect.parse_social_hub(SOCIAL_HUB,'social_finsoc',TODAY,fetch_detail=fetch)
    assert len(events)==1
    assert events[0]['starts_at']=='2026-11-20T18:00:00+11:00'
    assert events[0]['sources']==['FINSOC','Dated registration page']
    assert events[0]['registration_url'].endswith('/panel-123')
    assert all('eventbrite' not in s['url'] for s in signals)
    assert len(signals)==1  # Credit Analyst undated; prior-year event omitted
    assert any('Credit Analysis' in s['title'] for s in signals)
    assert 'nightclub' not in str(signals).lower()
    assert 'unrelated' not in str(signals).lower()
    assert len(calls)==1


def test_social_bio_cannot_import_fake_or_malicious_urls():
    raw='''<html><main>
      <a href="https://www.eventbrite.com.au.evil.net/e/123">Investment Banking Networking</a>
      <a href="javascript:alert(1)">Finance Careers Event</a>
      <a href="https://docs.google.com/forms/d/e/xyz/viewform">Director Recruitment Application</a>
    </main></html>'''
    e,l=collect.parse_social_hub(raw,'social_unit',TODAY,fetch_detail=lambda _:pytest.fail('unsafe fetch'))
    assert e==[] and l==[]


def test_social_hub_empty_fresh_not_phantom_event(tmp_path):
    (tmp_path/'snapshot.json').write_text(json.dumps({'events':[], 'sources':[]}))
    raw='<html><h1>Linktree</h1><main><a href="https://forms.gle/dummy">FINSOC Finance Networking Workshop</a></main></html>'
    feed,report=collect.collect(today=TODAY,fetcher=lambda _:raw,source_keys=['social_finsoc'],folder=tmp_path)
    assert feed['events']==[]
    assert len(feed['signals'])==1
    assert report['sources']['social_finsoc']['status']=='links_only'
    assert report['new_event_ids']==[]
    assert (tmp_path/'signals.json').is_file()


def test_social_hub_missing_public_links_does_not_fake_posts():
    e,signals=collect.parse_social_hub('<html><h1>Linktree @finsocunsw</h1></html>','social_finsoc',TODAY)
    assert e==[] and signals==[]


PUBLIC_FB_SOURCE='''<html><h2>UPCOMING EVENTS.</h2>
  <a href="https://www.facebook.com/events/3420424424785763">FINSOC event</a>
  <a href="https://www.facebook.com/events/3420424424785763?ref=feed">Duplicate</a>
  <a href="https://www.facebook.com.evil.org/events/3420424424785763">Malicious</a>
</html>'''
PUBLIC_FB_DETAIL='''<html><head><meta property="og:title" content="FINSOC Investment Banking Networking Evening">
  <meta property="og:description" content="Event in Sydney, NSW, Australia by UNSW Finance and Banking Society on Thursday, November 26 2026"></head></html>'''


def test_public_facebook_event_metadata_only():
    calls=[]
    def fetch(url):
        calls.append(url)
        return PUBLIC_FB_DETAIL
    found=collect.parse_public_facebook_events(PUBLIC_FB_SOURCE,TODAY,fetch_detail=fetch)
    assert len(found)==1
    assert found[0]['starts_at']=='2026-11-26'
    assert found[0]['registration_url']=='https://www.facebook.com/events/3420424424785763'
    assert len(calls)==1


def test_public_facebook_event_missing_year_or_private_page_ignored():
    def fetch(url):
        return '<html><meta property="og:title" content="Investment Banking Evening"><meta property="og:description" content="Log in to Facebook to view"></html>'
    assert collect.parse_public_facebook_events(PUBLIC_FB_SOURCE,TODAY,fetch_detail=fetch)==[]


def test_public_facebook_event_expired_ignored():
    past=PUBLIC_FB_DETAIL.replace('November 26 2026','June 25 2026')
    assert collect.parse_public_facebook_events(PUBLIC_FB_SOURCE,TODAY,fetch_detail=lambda _:past)==[]


def test_publication_feeds_reject_stale_and_generic_articles():
    old='''<rss><channel><item><title>UNSW Investment Banking Evening</title><pubDate>Wed, 14 Oct 2025 00:00:00 GMT</pubDate><link>https://www.unit.org.au/old-event</link></item></channel></rss>'''
    assert collect.parse_newsletter_mentions(old,'unit_publications',TODAY)==[]
    generic='''<rss><channel><item><title>2026 Term 3 Week 2</title><pubDate>Wed, 14 Oct 2026 00:00:00 GMT</pubDate><link>https://www.unit.org.au/market-wrap/one</link></item></channel></rss>'''
    assert collect.parse_newsletter_mentions(generic,'unit_publications',TODAY)==[]


def test_publication_feeds_recent_titled_newsletter_is_unverified_only():
    pub='''<rss><channel><item><title>Investment Banking Networking Evening</title><pubDate>Wed, 28 Oct 2026 00:00:00 GMT</pubDate><link>https://www.unit.org.au/announcements/event</link></item></channel></rss>'''
    leads=collect.parse_newsletter_mentions(pub,'unit_publications',TODAY)
    assert len(leads)==1
    assert leads[0]['status']=='date_unverified'
    assert leads[0]['url'].endswith('/event')


def test_public_newsletter_bsoc_rejects_old_and_accepts_recent():
    archive='''<html><a href="/p/bsoc-upcoming-events">BSOC Upcoming Events!</a></html>'''
    def detail(url):
        return '<html><h1>BSOC Upcoming Events!</h1>Jun 30, 2025</html>'
    assert collect.parse_newsletter_mentions(archive,'bsoc_publications',TODAY,fetch_detail=detail)==[]
    def newer(url):
        return '<html><h1>BSOC Upcoming Events!</h1>Oct 30, 2026</html>'
    leads=collect.parse_newsletter_mentions(archive,'bsoc_publications',TODAY,fetch_detail=newer)
    assert len(leads)==1 and leads[0]['status']=='date_unverified'


def test_fmaa_facebook_outbound_redirect_cannot_escape_allowlist():
    safe='https://l.facebook.com/l.php?u=https%3A%2F%2Fform.jotform.com%2Fabc%2Ffinance-evening&h=something'
    assert collect.unwrap_public_registration_url(safe)=='https://form.jotform.com/abc/finance-evening'
    unsafe='https://l.facebook.com/l.php?u=https%3A%2F%2Fform.jotform.com.attacker.com%2Fsteal'
    assert collect.unwrap_public_registration_url(unsafe)==unsafe


EXPIRED_FB='''<html><main><a href="https://www.eventbrite.com.au/e/old-finance-12345">Finance Careers Networking Evening</a></main></html>'''
EXPIRED_FORM='''<html><main><a href="https://form.jotform.com/test/old-esg">ESG Industry Insights Evening Register</a></main></html>'''

def test_expired_eventbrite_never_appears_as_new_lead():
    old='<html><h1>Event ended</h1><h2>Finance Careers Networking Evening</h2>Wednesday, October 14</html>'
    found,leads=collect.parse_social_hub(EXPIRED_FB,'social_finsoc',TODAY,fetch_detail=lambda _:old)
    assert found==[] and leads==[]

def test_expired_jotform_never_appears_as_new_lead():
    old='<html><h1>FMAA ESG Evening</h1><p>Event Details: Date: 29 October 2026 Time: 5:45pm - 8pm</p></html>'
    found,leads=collect.parse_social_hub(EXPIRED_FORM,'social_fmaa',dt.date(2026,11,1),fetch_detail=lambda _:old)
    assert found==[] and leads==[]

def test_unknown_form_date_remains_unverified_lead():
    found,leads=collect.parse_social_hub(EXPIRED_FORM,'social_fmaa',TODAY,fetch_detail=lambda _:'<h1>ESG workshop</h1>')
    assert found==[] and len(leads)==1 and leads[0]['status']=='date_unverified'

def test_future_form_date_remains_unverified_without_event_schema():
    found,leads=collect.parse_social_hub(EXPIRED_FORM,'social_fmaa',dt.date(2026,11,1),fetch_detail=lambda _:'<p>Event Details: Date: 15 December 2026 Time: 5pm</p>')
    assert found==[] and len(leads)==1

def test_expired_links_not_returned_from_collector(tmp_path):
    (tmp_path/'snapshot.json').write_text(json.dumps({'events': [], 'sources': []}))
    html='''<html><main><a href="https://www.eventbrite.com.au/e/old-finance-12345">Finance Networking Event</a><a href="https://form.jotform.com/test/old-esg">ESG Industry Insights Evening Register</a></main></html>'''
    def fetched(u):
        if u.startswith('https://linktr.ee/'):return html
        if 'eventbrite.com' in u:return '<h1>Event ended</h1>'
        if 'jotform.com' in u:return '<p>Event Details: Date: 29 October 2026 Time: 5:45pm</p>'
        raise AssertionError(u)
    feed,health=collect.collect(today=dt.date(2026,11,1),fetcher=fetched,source_keys=['social_fmaa'],folder=tmp_path)
    assert feed['events']==[] and feed['signals']==[]
    assert health['sources']['social_fmaa']['status']=='accessible_empty'
