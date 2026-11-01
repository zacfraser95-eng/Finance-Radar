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


CAPITALW_FUTURE='''<html><h1>Upcoming Events</h1><article><h1>Women in Finance Networking Workshop</h1>
<time>Tuesday, November 24, 2026</time><time>6:00 PM</time><time>8:00 PM</time>
<p>Networking with industry professionals for finance students.</p>
<a href="/events/women-in-finance">View Event</a></article>
<article><h1>Old Trading Workshop</h1><time>Tuesday, November 10, 2025</time>
<a href="/events/old">Old</a></article></html>'''

ACCSOC_OLD='''<html><h2>Upcoming Events</h2><article>
<h1>UNSW AccSoc Presents: Careers Fair</h1><time>Monday 14 July 2025</time>
<a href="/upcoming-events/old">View event</a></article></html>'''

FAIC_2026='''<html><h1>Fintech AI Innovation Consortium</h1>
<h3>UNSW Fintech AI Innovation Consortium (FAIC) End of Year Event for 2026</h3>
<h3>Event details</h3><div><ul>
<li><h5>Date</h5><p>Friday 27 November 2026</p></li>
<li><h5>Time</h5><p>2:00pm to 5:00pm</p></li>
<li><h5>Place</h5><p>UNSW (J17 Ainsworth 102)</p></li>
</ul></div><a href="https://luma.com/lxsi2n5i">Secure Your Place</a></html>'''

def test_capitalw_future_career_event_accepted_and_past_rejected():
    found=collect.parse_squarespace_society(CAPITALW_FUTURE,'capitalw',dt.date(2026,11,1))
    assert len(found)==1
    assert found[0]['starts_at'].startswith('2026-11-24T18:00')
    assert found[0]['registration_url'].endswith('/events/women-in-finance')


def test_accounting_society_old_events_not_promoted():
    assert collect.parse_squarespace_society(ACCSOC_OLD,'accsoc',dt.date(2026,11,1))==[]


def test_faic_official_event_is_dated_with_real_time():
    out=collect.parse_faic(FAIC_2026,dt.date(2026,11,1))
    assert len(out)==1
    assert out[0]['starts_at']=='2026-11-27T14:00:00+11:00'
    assert out[0]['ends_at']=='2026-11-27T17:00:00+11:00'
    assert out[0]['registration_url']=='https://luma.com/lxsi2n5i'


def test_faic_year_mismatch_is_not_guessed():
    out=collect.parse_faic(FAIC_2026.replace('End of Year Event for 2026','End of Year Event for 2027'),
                           dt.date(2026,11,1))
    assert out==[]


def test_bsoc_recaps_not_future_events():
    markup='<html><h1>Our Events</h1><h2>EVENT RECAPS</h2><h1>10/12/2026</h1>UNSW BSOC Finance Networking View Event Recap</html>'
    assert collect.parse_bsoc_events(markup,dt.date(2026,11,1))==[]


def test_cma_short_date_and_career_only():
    markup='<html><h1>UNSW Capital Markets Association</h1><h3>Trading Careers Night</h3>'
    markup+='<p>24/11/26 - 6:00 PM</p><p>Trading industry Q&A for students</p>'
    markup+='<h3>CMA Club BBQ</h3><p>25/11/26 - 12:00 PM</p></html>'
    out=collect.parse_cma(markup,dt.date(2026,11,1))
    assert len(out)==1
    assert out[0]['starts_at'].startswith('2026-11-24T18:00')


def test_new_sources_are_monitored_not_made_up(tmp_path):
    (tmp_path/'snapshot.json').write_text(json.dumps({'events':[],'sources':[]}))
    feeds={'capitalw':ACCSOC_OLD.replace('Upcoming Events','Upcoming Events'),
           'accsoc':ACCSOC_OLD,
           'bsoc_calendar':'<h1>Our Events</h1><h2>EVENT RECAPS</h2>'}
    lookup={collect.SOURCES[k][1]:v for k,v in feeds.items()}
    _,health=collect.collect(today=dt.date(2026,11,1),source_keys=['accsoc','bsoc_calendar'],
                            fetcher=lambda u:lookup[u],folder=tmp_path)
    assert health['event_count']==0
    assert health['sources']['accsoc']['status']=='accessible_empty'

def test_first_seen_timestamp_is_preserved_between_rechecks(tmp_path):
    (tmp_path/'snapshot.json').write_text(json.dumps({'events':[], 'sources': []}))
    def fetch(url):
        return UNIT_HOME
    first,_=collect.collect(today=TODAY,fetcher=fetch,source_keys=['unit'],folder=tmp_path)
    assert len(first['events'])==1
    second,_=collect.collect(today=TODAY,fetcher=fetch,source_keys=['unit'],folder=tmp_path)
    assert first['events'][0]['first_seen_at']==second['events'][0]['first_seen_at']



MATHSOC_CROSSPOST='''<html><h1>Upcoming Events</h1><h3>MathSoc x QuantSoc Citadel Securities Trading Night</h3>
<p>UNSW Kensington Campus</p><p>25/11/2026, 6:00:00 pm</p>
<h3>MathSoc Pizza Night</h3><p>27/11/2026, 6:00:00 pm</p>
<h1>Past Events</h1><h3>MathSoc x QuantSoc Jane Street Trading Game</h3>
<p>29/10/2026, 3:00:00 pm</p></html>'''


def test_mathsoc_quant_accepts_only_dated_future_quant_collaborations():
    found=collect.parse_mathsoc_quant(MATHSOC_CROSSPOST,dt.date(2026,11,1))
    assert len(found)==1
    assert 'Citadel' in found[0]['title']
    assert found[0]['starts_at'].startswith('2026-11-25T18:00')


def test_mathsoc_quant_does_not_promote_past_events():
    raw='<html><h1>Upcoming Events</h1><p>No upcoming events found.</p><h1>Past Events</h1><h3>MathSoc x QuantSoc Citadel Securities Trading Game</h3><p>29/10/2026, 3:00:00 pm</p></html>'
    assert collect.parse_mathsoc_quant(raw,dt.date(2026,11,1))==[]


def test_quantsoc_site_is_social_only_and_finsoc_archive_is_not_calendar(tmp_path):
    (tmp_path/'snapshot.json').write_text(json.dumps({'events':[], 'sources':[]}))
    pages={collect.SOURCES['quantsoc_site'][1]:'<h1>QuantSoc</h1><p>Check events on Discord and Facebook</p>',
           collect.SOURCES['finsoc_publications'][1]:'<h1>FINSOC REVIEW</h1><p>Weekly Wrap Volume 39 22 July 2026</p>'}
    feed,health=collect.collect(today=dt.date(2026,11,1),source_keys=['quantsoc_site','finsoc_publications'],
                                fetcher=lambda url:pages[url],folder=tmp_path)
    assert feed['events']==[]
    assert health['sources']['quantsoc_site']['status']=='social_only'
    assert health['sources']['finsoc_publications']['status']=='publications_only'


UNSW_DYNAMIC='<html><h1>Events | Employability</h1><p>Workshops</p><a href="https://www.eventbrite.com.au/e/job-search-strategies-workshop-tickets-1999066649161">Read more</a></html>'
UNSW_DETAIL='''<html><head><meta property="og:title" content="Job Search Strategies workshop">
<meta property="og:description" content="Job search and careers workshop">
<meta property="event:start_time" content="2026-11-12T13:00:00+11:00">
<meta property="event:end_time" content="2026-11-12T14:00:00+11:00"></head>
<body><h1>Job Search Strategies workshop</h1><p>Organised by UNSW Employability</p><p>Online event</p></body></html>'''


def test_unsw_registration_fallback_confirms_dates_and_organiser():
    found=collect.parse_unsw_with_registration_fallback(UNSW_DYNAMIC,TODAY,fetch_detail=lambda _:UNSW_DETAIL)
    assert len(found)==1
    assert found[0]['starts_at']=='2026-11-12T13:00:00+11:00'
    assert found[0]['ends_at']=='2026-11-12T14:00:00+11:00'
    assert found[0]['format']=='Online'
    assert found[0]['registration_url'].endswith('1999066649161')


def test_unsw_registration_rejects_wrong_organiser_and_missing_timezone():
    url='https://www.eventbrite.com.au/e/job-search-strategies-workshop-tickets-1999066649161'
    assert collect.parse_unsw_eventbrite_detail(UNSW_DETAIL.replace('UNSW Employability','Different Organiser'),url,TODAY) is None
    assert collect.parse_unsw_eventbrite_detail(UNSW_DETAIL.replace('2026-11-12T13:00:00+11:00','2026-11-12T13:00:00'),url,TODAY) is None
    assert collect.parse_unsw_eventbrite_detail(UNSW_DETAIL,'https://eventbrite.com.au.evil.net/e/fake-event',TODAY) is None


def test_unsw_registration_expires_after_event():
    url='https://www.eventbrite.com.au/e/job-search-strategies-workshop-tickets-1999066649161'
    assert collect.parse_unsw_eventbrite_detail(UNSW_DETAIL,url,dt.date(2026,11,13)) is None


def test_unsw_dynamic_page_backstop_fetches_verified_registrations():
    page='<html><h1>Events | Employability</h1><p>No visible event cards</p></html>'
    found=collect.parse_unsw_with_registration_fallback(page,TODAY,
          fetch_detail=lambda url:UNSW_DETAIL if url.endswith('1999066649161') else '<h1>Login required</h1>')
    assert len(found)==1


def test_existing_bookmark_id_survives_richer_unsw_import(tmp_path):
    old=collect.event('UNSW Employability','Job Search Strategies workshop',
       dt.date(2026,11,12),'1:00 PM',
       'https://www.eventbrite.com.au/e/job-search-strategies-workshop-tickets-1999066649161',today=TODAY)
    old['id']='unsw-jobsearch-20261112'
    (tmp_path/'feed.json').write_text(json.dumps({'events':[old],'sources':[]}))
    def fetched(url):
        return UNSW_DYNAMIC if url==collect.SOURCES['unsw'][1] else UNSW_DETAIL
    payload,_=collect.collect(today=TODAY,fetcher=fetched,source_keys=['unsw'],folder=tmp_path)
    assert len(payload['events'])==1
    assert payload['events'][0]['id']=='unsw-jobsearch-20261112'
    assert payload['events'][0]['collection_status']=='current'


CFA_ROWS='''<html><h1>CFA Society Australia Upcoming Events</h1><table><tbody>
<tr><td><strong>NSW Chapter | Private equity through the cycle: Investment, value creation and exit</strong>
<p>Explore private equity capital deployment and exits.</p>
<p>Format: In-person</p><p>Open to: Members, Candidates, Industry professionals</p>
<p>Speaker(s): Analysts</p></td><td>BDO Sydney</td>
<td>November 17, 2026 12:15pm - 1:30pm</td>
<td><a href="https://web.cvent.com/event/1a2b3c/summary">Learn More & Register</a></td></tr>
<tr><td><strong>QLD Chapter | Private equity networking</strong>
<p>Open to: Members, Candidates</p></td><td>Riverland, Brisbane</td>
<td>November 19, 2026 5:30pm - 7:30pm</td>
<td><a href="https://web.cvent.com/event/brisbane/summary">Register</a></td></tr>
<tr><td><strong>Online training I Copilot for finance professionals</strong></td>
<td>Online</td><td>November 20, 2026 9:00am - 12:00pm</td>
<td><a href="https://web.cvent.com/event/copilot/summary">Register</a></td></tr>
<tr><td><strong>NSW Chapter | Women in investment: Career stories</strong>
<p>Open to: Members, Candidates</p></td>
<td>Perpetual, Sydney</td><td>November 18, 2026 12:00pm - 2:00pm</td>
<td><a href="https://web.cvent.com/event/women/summary">Register</a></td></tr>
</tbody></table></html>'''

FINMA_LECTURE='''<html><h1>EVENTS</h1><section><h2>Upcoming Events</h2>
<h2>Open Lecture: Finance 101</h2><p>FINMA is holding an introductory finance lecture on 10 November from 5:00–6:30 PM.</p>
<p>The session is free to attend and open to all students, including university students.</p>
<p>Event Details Date: Tuesday, 10 November Time: 5:00 PM – 6:30 PM</p></section>
<h1>PAST EVENTS</h1><p>2025 UBS networking night</p></html>'''


def test_cfa_sydney_private_equity_event_included_with_price_caveat():
    found=collect.parse_cfa_australia(CFA_ROWS,dt.date(2026,11,1))
    assert len(found)==2
    pe=next(e for e in found if 'Private equity' in e['title'])
    assert pe['starts_at']=='2026-11-17T12:15:00+11:00'
    assert pe['ends_at']=='2026-11-17T13:30:00+11:00'
    assert 'non-member' in pe['eligibility']
    assert pe['registration_url']=='https://web.cvent.com/event/1a2b3c/summary'
    women=next(e for e in found if 'Women in investment' in e['title'])
    assert women['fit']=='restricted'


def test_cfa_filters_out_interstate_and_generic_cpd():
    out=collect.parse_cfa_australia(CFA_ROWS,dt.date(2026,11,1))
    assert not any('Brisbane' in e['location'] or 'Copilot' in e['title'] for e in out)


def test_cfa_rejects_injected_registration_domains_and_past():
    bad=CFA_ROWS.replace('https://web.cvent.com/event/1a2b3c/summary','https://web.cvent.com.attacker.net/event/a')
    assert not any('Private equity' in e['title'] for e in collect.parse_cfa_australia(bad,dt.date(2026,11,1)))
    assert collect.parse_cfa_australia(CFA_ROWS,dt.date(2026,12,1))==[]


def test_finma_open_finance_lecture_and_expiry():
    out=collect.parse_finma_student_events(FINMA_LECTURE,dt.date(2026,11,1))
    assert len(out)==1
    assert out[0]['starts_at']=='2026-11-10T17:00:00+11:00'
    assert out[0]['ends_at']=='2026-11-10T18:30:00+11:00'
    assert 'university students' in out[0]['eligibility']
    assert collect.parse_finma_student_events(FINMA_LECTURE,dt.date(2026,11,11))==[]


def test_finma_rejects_missing_open_lecture_or_old_past_event():
    fake=FINMA_LECTURE.replace('Open Lecture: Finance 101','2025 NAB networking evening')
    assert collect.parse_finma_student_events(fake,dt.date(2026,11,1))==[]
    fake=FINMA_LECTURE.replace('5:00 PM – 6:30 PM','6:00 PM – 7:30 PM').replace('5:00–6:30 PM','6:00–7:30 PM')
    assert collect.parse_finma_student_events(fake,dt.date(2026,11,1))==[]


GOOGLE_PUBLIC_REGISTRATION='''<html><head><meta property="og:title"
content="FINSOC x Goliath Academy Financial Modelling Masterclass 2026" /></head>
<body><h1>FINSOC x Goliath Academy Financial Modelling Masterclass 2026</h1>
<p>Event Date: Friday 20 November 2026</p>
<p>Time: 5:30 PM - 7:00 PM</p>
<p>UNSW Kensington</p></body></html>'''
FINSOC_FORM_URL='https://docs.google.com/forms/d/e/1FAIpQLSeEBaqZLF8FAxmg6dWWZuf3lqZyBrCvpY8aatl4812AtGvauQ/viewform'

def test_official_google_form_date_and_time_can_be_confirmed():
    events=collect.parse_public_form_registration(
        GOOGLE_PUBLIC_REGISTRATION,'FINSOC x Goliath Academy Financial Modelling Masterclass 2026',
        FINSOC_FORM_URL,'FINSOC',dt.date(2026,11,1))
    assert len(events)==1
    assert events[0]['starts_at']=='2026-11-20T17:30:00+11:00'
    assert events[0]['ends_at']=='2026-11-20T19:00:00+11:00'
    assert events[0]['registration_url']==FINSOC_FORM_URL


def test_google_form_title_year_alone_does_not_invent_event_date():
    html=GOOGLE_PUBLIC_REGISTRATION.replace('Event Date: Friday 20 November 2026',
       'Stage of degree: First year, Second year')
    assert collect.parse_public_form_registration(html,'FINSOC x Goliath Academy Financial Modelling Masterclass 2026',
       FINSOC_FORM_URL,'FINSOC',dt.date(2026,11,1))==[]


def test_closed_form_and_private_form_are_not_confirmed():
    for body in ('This form is no longer accepting responses','Sign in to continue'):
        assert collect.parse_public_form_registration(
            GOOGLE_PUBLIC_REGISTRATION+body,'FINSOC x Goliath Academy Financial Modelling Masterclass 2026',
            FINSOC_FORM_URL,'FINSOC',dt.date(2026,11,1))==[]


def test_form_without_event_time_does_not_become_fabricated_date():
    html=GOOGLE_PUBLIC_REGISTRATION.replace('Time: 5:30 PM - 7:00 PM','Time: To be announced')
    assert collect.parse_public_form_registration(html,'FINSOC x Goliath Academy Financial Modelling Masterclass 2026',
       FINSOC_FORM_URL,'FINSOC',dt.date(2026,11,1))==[]


def test_finsoc_public_humanitix_host_no_live_events():
    html='<main><h1>UNSW Finance and Banking Society</h1><p>There are no live events.</p></main>'
    assert collect.parse_finsoc_humanitix(html,dt.date(2026,11,1),
                                          fetch_detail=lambda u: (_ for _ in ()).throw(AssertionError('no event'))) == []


def test_finsoc_humanitix_host_requires_organiser_attribution():
    host='<h1>UNSW Finance and Banking Society</h1><a href="https://events.humanitix.com/finsoc-finance-workshop-2026">Workshop</a>'
    page='''<p>Organised by another society</p><script type="application/ld+json">{
        "@type":"Event","name":"Investment Banking Careers Night","startDate":"2026-11-19T18:00:00+11:00",
        "location":{"name":"UNSW"},"url":"https://events.humanitix.com/finsoc-finance-workshop-2026"}</script>'''
    assert collect.parse_finsoc_humanitix(host,dt.date(2026,11,1),
                                          fetch_detail=lambda _:page)==[]


FUTURE_TEST_FORM_URL='https://docs.google.com/forms/d/e/1FAIpQL'+'X'*56+'/viewform'

def test_official_bio_form_without_date_stays_unverified():
    linktree=f'<html><main><a href="{FUTURE_TEST_FORM_URL}">FINSOC x Goliath Academy Financial Modelling Masterclass 2026</a></main></html>'
    html='<h1>FINSOC x Goliath Academy Financial Modelling Masterclass 2026</h1><p>Stage of degree: 1st year</p>'
    confirmed,leads=collect.parse_social_hub(linktree,'social_finsoc',dt.date(2026,11,1),
                                              fetch_detail=lambda _:html)
    assert confirmed==[]
    assert len(leads)==1
    assert 'date and time are not confirmed' in leads[0]['note']


def test_bio_public_form_is_upgraded_only_with_verified_date():
    linktree=f'<html><main><a href="{FUTURE_TEST_FORM_URL}">FINSOC x Goliath Academy Financial Modelling Masterclass 2026</a></main></html>'
    confirmed,leads=collect.parse_social_hub(linktree,'social_finsoc',dt.date(2026,11,1),
                                              fetch_detail=lambda _:GOOGLE_PUBLIC_REGISTRATION)
    assert len(confirmed)==1
    assert leads==[]


def test_completed_finsoc_workshops_not_presented_as_upcoming_registration_leads():
    html='''<html><main><a href="https://docs.google.com/forms/d/e/1FAIpQLSdb-zYvAi7xwbM6zvzl149UEdKEP6iv_GDPDVdK5syqps-Znw/viewform">FINSOC x Credit Analyst: Commercial Banking & Credit Analysis Workshop</a>
    <a href="https://docs.google.com/forms/d/e/1FAIpQLSeEBaqZLF8FAxmg6dWWZuf3lqZyBrCvpY8aatl4812AtGvauQ/viewform">FINSOC x Goliath Academy: Financial Modelling Masterclass</a></main></html>'''
    def no_fetch(_):
        raise AssertionError('Past-event registration forms should never be rechecked')
    current,leads=collect.parse_social_hub(html,'social_finsoc',dt.date(2026,11,1),fetch_detail=no_fetch)
    assert current==[] and leads==[]


UNSW_PUBLIC_FINANCE_INDEX='''<html><h1>Events</h1><p>1 - 14 of 31 Events</p>
<a href="/event/engineering-future-entrepreneurship-paradox">Engineering the Future</a>
<a href="/event/curating-now-ecological-practices">Curating Now</a>
<a href="/event/oceans-of-hope">Oceans of Hope</a></html>'''

UNSW_PUBLIC_FINANCE_DETAIL='''<html><section>
<h1>Engineering the Future: The Entrepreneurship Paradox</h1>
<p>10 November 2026</p><p>5.30pm – 8.30pm AEDT</p>
<p>Australian Museum</p><a href="https://www.eventbrite.com.au/e/engineering-the-future-the-entrepreneurship-paradox-tickets-1996543386013">Register Now</a>
<p>Free for everyone</p><h2>Overview</h2>
<p>Australian investors assess risk, entrepreneurs need capital, funding, and venture investment to scale new ventures.</p>
</section><section><h2>Speakers</h2><p>Research on 20 October 2026</p></section></html>'''

BIRKETT_DETAIL='''<main><h1>Bill Birkett Memorial Lecture 2026</h1>
<p>UNSW School of Accounting, Auditing and Taxation in partnership with CPA Australia.</p>
<a href="https://www.eventbrite.com.au/e/bill-birkett-memorial-lecture-2026-tickets-1999953200861">Register now</a>
<p>Date</p><p>Wednesday 4 November 2026</p>
<p>Time</p><p>4:30 – 8:00 pm</p><p>Location 12-Micron Barangaroo</p></main>'''


def test_official_unsw_investment_panel_discovery_verifies_registration():
    urls=[]
    def fetch(url):
        urls.append(url)
        return UNSW_PUBLIC_FINANCE_DETAIL
    out=collect.parse_unsw_public_events(UNSW_PUBLIC_FINANCE_INDEX,dt.date(2026,11,1),fetch_detail=fetch)
    assert len(out)==1 and len(urls)==1
    e=out[0]
    assert e['starts_at']=='2026-11-10T17:30:00+11:00'
    assert e['ends_at']=='2026-11-10T20:30:00+11:00'
    assert 'Free public event' in e['eligibility']
    assert 'eventbrite.com.au' in e['registration_url']


def test_unrelated_unsw_events_not_imported_as_finance():
    index='<html><h1>Events</h1><a href="/event/finance-picnic-and-art-exhibition">Finance Picnic</a></html>'
    page=UNSW_PUBLIC_FINANCE_DETAIL.replace('Engineering the Future: The Entrepreneurship Paradox','Finance Picnic and Art Exhibition').replace(
        'Australian investors assess risk, entrepreneurs need capital, funding, and venture investment to scale new ventures.',
        'Enjoy a student picnic with artists and bands.')
    result=collect.parse_unsw_public_events(index,dt.date(2026,11,1),fetch_detail=lambda _:page)
    assert result==[]


def test_unsw_investment_calendar_rejects_unverified_dates_and_registration():
    page=UNSW_PUBLIC_FINANCE_DETAIL.replace('10 November 2026','November date TBC')
    url='https://events.unsw.edu.au/event/engineering-future-entrepreneurship-paradox'
    assert collect.parse_unsw_public_event_detail(page,url,dt.date(2026,11,1)) is None
    page=UNSW_PUBLIC_FINANCE_DETAIL.replace('www.eventbrite.com.au','www.eventbrite.com.au.attacker.net')
    assert collect.parse_unsw_public_event_detail(page,url,dt.date(2026,11,1)) is None
    assert collect.parse_unsw_public_event_detail(UNSW_PUBLIC_FINANCE_DETAIL,url,dt.date(2026,11,11)) is None


def test_unsw_accounting_lecture_dated_professional_entry_caveat():
    found=collect.parse_unsw_accounting_lecture(BIRKETT_DETAIL,dt.date(2026,11,1))
    assert len(found)==1
    rec=found[0]
    assert rec['starts_at']=='2026-11-04T16:30:00+11:00'
    assert rec['ends_at']=='2026-11-04T20:00:00+11:00'
    assert 'student eligibility' in rec['eligibility']
    assert rec['registration_url'].endswith('1999953200861')


def test_unsw_accounting_lecture_expired_or_mismatched_not_added():
    assert collect.parse_unsw_accounting_lecture(BIRKETT_DETAIL,dt.date(2026,11,5))==[]
    assert collect.parse_unsw_accounting_lecture(BIRKETT_DETAIL.replace('Wednesday 4 November 2026','Date TBC'),
                                             dt.date(2026,11,1))==[]


def test_unsw_public_events_dynamic_index_fallback_still_verifies_details():
    landing='<html><h1>Events</h1><p>1 - 14 of 31 Events</p></html>'
    checked=[]
    def fetch(url):
        checked.append(url)
        return UNSW_PUBLIC_FINANCE_DETAIL
    found=collect.parse_unsw_public_events(landing,dt.date(2026,11,1),fetch_detail=fetch)
    assert len(found)==1
    assert found[0]['starts_at']=='2026-11-10T17:30:00+11:00'
    assert checked==['https://events.unsw.edu.au/event/engineering-future-entrepreneurship-paradox']


def test_unsw_public_events_explicit_fallback_expires_after_event():
    landing='<html><h1>Events</h1><p>1 - 14 of 31 Events</p></html>'
    seen=[]
    assert collect.parse_unsw_public_events(landing,dt.date(2026,11,11),
         fetch_detail=lambda url:seen.append(url) or UNSW_PUBLIC_FINANCE_DETAIL)==[]
    assert seen==[]


UNSW_INVESTOR_TICKET_HTML='''<html><main><h1>Engineering the Future: The Entrepreneurship Paradox</h1>
<p>Top Organiser By UNSW Engineering</p>
<time>Tuesday 10 November • 5:30 PM - 8:30 PM</time>
<h2>Overview</h2><p>Founders and investors discuss capital, entrepreneurial funding and startup growth.</p>
</main></html>'''


def test_dynamic_unsw_investor_panel_verified_by_official_ticket():
    landing='<html><h1>Events</h1><p>Upcoming Events</p></html>'
    fetched=[]
    def fetch(url):
        fetched.append(url)
        if 'events.unsw.edu.au' in url:
            return UNSW_PUBLIC_FINANCE_DETAIL.replace('10 November 2026','Date loaded dynamically').replace(
                '5.30pm – 8.30pm AEDT','Time loaded dynamically')
        return UNSW_INVESTOR_TICKET_HTML
    out=collect.parse_unsw_public_events(landing,dt.date(2026,11,1),fetch_detail=fetch)
    assert len(out)==1
    assert out[0]['starts_at']=='2026-11-10T17:30:00+11:00'
    assert out[0]['ends_at']=='2026-11-10T20:30:00+11:00'
    assert out[0]['registration_url']==collect.UNSW_INVESTOR_PANEL_TICKET
    assert len(fetched)==2


def test_unsw_ticket_fallback_requires_date_time_organiser_and_not_expired():
    assert collect.parse_unsw_verified_investor_ticket(
        UNSW_INVESTOR_TICKET_HTML.replace('UNSW Engineering','Unknown Organiser'),dt.date(2026,11,1)) is None
    assert collect.parse_unsw_verified_investor_ticket(
        UNSW_INVESTOR_TICKET_HTML.replace('5:30 PM - 8:30 PM','Time TBC'),dt.date(2026,11,1)) is None
    assert collect.parse_unsw_verified_investor_ticket(
        UNSW_INVESTOR_TICKET_HTML.replace('10 November','11 November'),dt.date(2026,11,1)) is None
    assert collect.parse_unsw_verified_investor_ticket(
        UNSW_INVESTOR_TICKET_HTML,dt.date(2026,11,11)) is None


def test_unsw_ticket_fallback_rejects_event_ended():
    assert collect.parse_unsw_verified_investor_ticket(
        UNSW_INVESTOR_TICKET_HTML+' Event ended',dt.date(2026,11,1)) is None


CAFBA_NSW_HTML='''<html><h2>CAFBA End of Year Networking – Sydney</h2>
<dl><strong>Start Date</strong><dd>25 November 2026</dd><strong>Start Time</strong><dd>5:30</dd>
<strong>Venue</strong><dd>Zeta Bar, Hilton Sydney</dd><strong>Who Can Register?</strong><dd>Anyone</dd></dl>
<h3>Connect. Celebrate.</h3><p>Sydney event for the commercial and asset finance community.</p>
<p>Wednesday, 25 November 2026 From 5:30pm Zeta Bar, Hilton Sydney</p></html>'''

RMIA_FREE_HTML='''<html><h4>Event Details</h4><p>Time: 5:00pm AEDT - onwards</p>
<p>Date: 11 November 2026</p><p>Venue: The Sussex Hotel, Rooftop</p>
<p>Registration Fee: FREE</p><p>Enjoy drinks with the NSW risk community.</p>
<a href="https://members.rmia.org.au/_events.registration/step1/eventid/42980">Register</a></html>'''

STEP_EPN_HTML='''<html><section><h2>STEP NSW Emerging Professionals Network | Wednesday 25 November 2026</h2>
<p>Wednesday 25 November 2026 at JustFund in Sydney</p>
<p>The EPN is open to all professional advisors, educators and students with a trusts and estates focus.</p>
<p>17:30 – 18:00 arrival and networking. 18:40 – 21:00 networking.</p>
<p>JustFund | Level 9, 85 Castlereagh Street, Sydney.</p>
<p>COST: STEP Members $25 | Non-Members $30</p>
<a href="https://events.humanitix.com/step-nsw-emerging-professionals-network-or-wednesday-25-november-2026">REGISTER HERE</a></section></html>'''

MYMONEY_ICC_HTML='''<html><h2>Exhibition Centre</h2><h3>SATURDAY 28 - SUNDAY 29 NOVEMBER 2026</h3>
<h1>MyMoney Expo</h1><p>Investors, finance professionals and everyday Australians.
Finance and investing education and networking.</p><a href="https://mymoneyexpo.com/?utm_source=venue">Learn More</a></html>'''

MYMONEY_HOST_HTML='''<html><h1>MyMoney Expo 2026</h1>
<p>Join thousands at MyMoney Expo Sydney – with FREE General Admission.</p>
<p>Hear from finance professionals covering investing, trading, property and wealth.</p>
<a href="https://tickets.lup.com.au/3a45f2ce-3748-4077-8b6f-e47a1987e1aa">Register for Free</a></html>'''


def test_cafba_open_to_anyone_finance_networking_has_no_invented_end():
    e=collect.parse_cafba_sydney_networking(CAFBA_NSW_HTML,dt.date(2026,11,1))
    assert len(e)==1
    assert e[0]['starts_at']=='2026-11-25T17:30:00+11:00'
    assert e[0]['ends_at'] is None
    assert 'Anyone can register' in e[0]['eligibility']
    assert 'CAFBA' in e[0]['organiser']
    assert collect.parse_cafba_sydney_networking(CAFBA_NSW_HTML,dt.date(2026,11,26))==[]


def test_cafba_missing_public_registration_eligibility_not_confirmed():
    assert collect.parse_cafba_sydney_networking(
        CAFBA_NSW_HTML.replace('Anyone','Members only'),dt.date(2026,11,1))==[]


def test_rmia_free_industry_networking_requires_registration_link():
    ev=collect.parse_rmia_sydney_networking(RMIA_FREE_HTML,dt.date(2026,11,1))
    assert len(ev)==1
    assert ev[0]['starts_at']=='2026-11-11T17:00:00+11:00'
    assert ev[0]['fit']=='restricted'
    assert 'student attendance' in ev[0]['eligibility']
    assert collect.parse_rmia_sydney_networking(RMIA_FREE_HTML.replace('members.rmia.org.au','evil.com'),dt.date(2026,11,1))==[]


def test_step_student_eligible_paid_emerging_network():
    ev=collect.parse_step_sydney_emerging_network(STEP_EPN_HTML,dt.date(2026,11,1))
    assert len(ev)==1
    assert ev[0]['starts_at']=='2026-11-25T17:30:00+11:00'
    assert ev[0]['ends_at']=='2026-11-25T21:00:00+11:00'
    assert '$30' in ev[0]['eligibility']
    assert 'students' in ev[0]['eligibility']
    assert collect.parse_step_sydney_emerging_network(STEP_EPN_HTML.replace('and students','only'),dt.date(2026,11,1))==[]


def test_mymoney_requires_both_official_pages_and_free_registration():
    ev=collect.parse_mymoney_expo(MYMONEY_ICC_HTML,dt.date(2026,11,1),
        fetch_detail=lambda _:MYMONEY_HOST_HTML)
    assert len(ev)==1
    assert ev[0]['starts_at']=='2026-11-28'
    assert ev[0]['ends_at'] is None
    assert '28–29 November' in ev[0]['subtitle']
    assert 'Free general admission' in ev[0]['eligibility']
    assert ev[0]['registration_url'].startswith('https://tickets.lup.com.au/')
    assert len(ev[0]['source_urls'])==2


def test_mymoney_does_not_assume_free_when_organiser_page_unavailable():
    assert collect.parse_mymoney_expo(MYMONEY_ICC_HTML,dt.date(2026,11,1),
        fetch_detail=lambda _:MYMONEY_HOST_HTML.replace('FREE General Admission','Ticket price available on request'))==[]
    assert collect.parse_mymoney_expo(MYMONEY_ICC_HTML,dt.date(2026,11,29),
        fetch_detail=lambda _:MYMONEY_HOST_HTML)==[]



def test_schema_fallback_rmia_does_not_imply_student_eligibility():
    rec={'title':'RMIA NSW Chapter | Networking Event — Risk Management Institute of Australasia (RMIA)',
         'starts_at':'2026-11-11T17:00:00+11:00','fit':'high','eligibility':'Confirm eligibility with organiser.'}
    out=collect.enrich_official_industry_listing(rec,'rmia_sydney')
    assert out['fit']=='restricted'
    assert 'not confirmed' in out['eligibility']


def test_schema_fallback_step_retains_published_ticket_costs():
    rec={'title':'STEP NSW Emerging Professionals Network | Wednesday 25 November 2026',
         'starts_at':'2026-11-25T17:30:00+11:00','eligibility':'Confirm eligibility with organiser.'}
    out=collect.enrich_official_industry_listing(rec,'step_emerging')
    assert 'students' in out['eligibility'].lower()
    assert '$25' in out['eligibility'] and '$30' in out['eligibility']
    assert '19 November' in out['eligibility']


def test_unrelated_schema_entries_are_not_relabelled():
    rec={'title':'General Industry Meeting','starts_at':'2026-11-11T10:00:00+11:00',
         'fit':'high','eligibility':'Unknown'}
    assert collect.enrich_official_industry_listing(rec,'rmia_sydney')==rec


def test_sydney_industry_parsers_are_dispatched_and_sources_visible():
    code=Path(collect.__file__).read_text()
    for key in ('cafba_sydney','rmia_sydney','step_emerging','mymoney_expo'):
        assert f"elif key=='{key}':found=" in code
        assert key in collect.SOURCES
    assert "for key in ('cafba_sydney','rmia_sydney','step_emerging','mymoney_expo')" in code



def test_same_industry_event_with_schema_variant_is_deduplicated():
    rmia=collect.parse_rmia_sydney_networking(RMIA_FREE_HTML,dt.date(2026,11,1))[0]
    rmia_schema=dict(rmia,title='RMIA NSW Chapter | Networking Event — Risk Management Institute of Australasia (RMIA)',
                     registration_url=collect.SOURCES['rmia_sydney'][1])
    assert collect.similar(rmia,rmia_schema)
    assert len(collect.unique([rmia,rmia_schema]))==1
    step=collect.parse_step_sydney_emerging_network(STEP_EPN_HTML,dt.date(2026,11,1))[0]
    step_schema=dict(step,title='STEP NSW Emerging Professionals Network | Wednesday 25 November 2026',
                     registration_url=collect.SOURCES['step_emerging'][1])
    assert collect.similar(step,step_schema)
    assert len(collect.unique([step,step_schema]))==1


def test_industry_specific_dedupe_does_not_merge_unrelated_events():
    left={'title':'STEP NSW Emerging Professionals Network | Wednesday 25 November 2026',
          'starts_at':'2026-11-25T17:30:00+11:00','registration_url':'https://stepaustralia.com/events/first'}
    other={'title':'STEP NSW Annual Member Lunch','starts_at':'2026-11-25T12:30:00+11:00',
           'registration_url':'https://stepaustralia.com/events/second'}
    assert not collect.similar(left,other)
