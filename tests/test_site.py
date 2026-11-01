from pathlib import Path
SITE=(Path(__file__).resolve().parents[1]/'index.html').read_text()
def test_homepage_event_spotlight_is_dynamic():
    assert 'id="spotlight-title"' in SITE
    assert 'function renderSpotlight()' in SITE
    assert 'THU 05 NOV · 6:00 PM' not in SITE
def test_current_day_sydney_date_stamp_is_locale_independent():
    assert 'const todayStamp=' in SITE
    assert 'e.starts_at>=todayStamp()' in SITE
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
    assert 'Confirmed in latest scan' in SITE
