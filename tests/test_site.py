from pathlib import Path
SITE=(Path(__file__).resolve().parents[1]/'index.html').read_text()
def test_homepage_event_spotlight_is_dynamic():
    assert 'id="spotlight-title"' in SITE
    assert 'function renderSpotlight()' in SITE
    assert 'THU 05 NOV · 6:00 PM' not in SITE
def test_current_day_sydney_date_stamp_is_locale_independent():
    assert 'const todayStamp=' in SITE
    assert 'e.starts_at>=today' in SITE
    assert "'en-CA'" not in SITE
def test_feedback_links_are_present():
    assert 'issues/new?template=suggest-event.yml' in SITE
    assert 'issues/new?template=bug-report.yml' in SITE

def test_feed_subscription_links_and_sydney_date_only_fix():
    assert 'webcal://zacfraser95-eng.github.io/Finance-Radar/events.ics' in SITE
    assert 'href="./events.xml"' in SITE
    assert "e.starts_at+'T00:00:00Z'" in SITE

def test_email_form_uses_independent_provider_and_clear_consent():
    assert 'action="https://simple-newsletter.com/v1/subscriptions/"' in SITE
    assert 'method="get"' in SITE
    assert 'name="uri" value="https://zacfraser95-eng.github.io/Finance-Radar/events.xml"' in SITE
    assert 'name="email" type="email"' in SITE
    assert 'I agree to send my email address to Simple Newsletter' in SITE
    assert 'Email confirmation required' in SITE
    assert 'not to Finance Radar or GitHub' in SITE

def test_site_verification_is_clear_and_unconfirmed_hidden_by_default():
    assert 'id="lastknown"' in SITE
    assert 'includeLastKnown=false' in SITE
    assert 'include previously listed' in SITE.lower()
    assert 'id="verification-summary"' in SITE
    assert 'Verified on source' in SITE

def test_editorial_identity_is_used_without_decorative_graphics():
    stylesheet=(Path(__file__).resolve().parents[1]/'editorial.css').read_text()
    assert '<link rel="stylesheet" href="./editorial.css"' in SITE
    assert 'What’s on<br><span>in finance.</span>' in SITE
    assert '<div class="orbit">' not in SITE
    assert 'background:radial-gradient' not in stylesheet
    assert 'color-scheme:light' in stylesheet
    assert "font:400 clamp(" in stylesheet

def test_deployment_includes_editorial_css():
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/refresh-and-publish.yml').read_text()
    assert 'cp index.html editorial.css _site/' in workflow

def test_interactive_controls_preserved_in_redesign():
    for key in ['id="events"','id="calendargrid"','id="search"','id="restricted"','id="lastknown"','id="email-updates"','id="modal"','id="saved-events"']:
        assert key in SITE

def test_compact_layout_keeps_actions():
    assert '<div class="quicklinks"' in SITE
    assert 'id="savedcount"' in SITE
    assert 'class="more-filters"' in SITE
    assert '<details class="mail-section" id="email-updates">' in SITE
    assert 'class="feedbackline"' in SITE
    assert '<div class="under">' not in SITE

def test_verified_calendar_and_category_filters():
    assert 'data-filter="other"' in SITE
    assert 'includeLastKnown=false' in SITE
    assert "calendarIncludeRestricted||e.fit!=='restricted'" in SITE

def test_clickable_event_titles():
    assert 'class="event-name event-title"' in SITE

def test_calendar_shows_matching_eligibility_and_month_agenda():
    assert 'id="calendar-restricted"' in SITE
    assert 'id="calendar-agenda"' in SITE
    assert 'calendarIncludeRestricted=false' in SITE
    assert 'Events this month' in SITE

def test_event_links_and_focus_restoration():
    assert "window.location.pathname+'#event='+encodeURIComponent(e.id)" in SITE
    assert "location.hash.match(/^#event=(.+)$/)" in SITE
    assert 'data-share="' in SITE
    assert 'previousEventFocus.focus()' in SITE
    assert "e.key==='Tab'" in SITE

def test_no_fabricated_end_times_or_disabled_date_only():
    assert 'DTSTART;VALUE=DATE:' in SITE
    assert 'DTEND;VALUE=DATE:' in SITE
    assert "if(e.ends_at&&Date.parse(e.ends_at)>Date.parse(e.starts_at))" in SITE
    assert "e.ends_at||new Date(localDate(e).getTime()+3600000)" not in SITE

def test_known_finished_events_and_orphan_bookmarks():
    assert 'if(Number.isFinite(end)&&end<=clock)return false;' in SITE
    assert 'validSavedIds' in SITE
