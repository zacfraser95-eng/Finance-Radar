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
