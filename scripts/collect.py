#!/usr/bin/env python3
"""Finance Radar: conservative public events collection.

Explicit source evidence is required for every event. No guessed year when an
ambiguous date would imply a past event; a source returning zero events is not
necessarily broken. The frontend and notifications use ONLY verified or
explicitly marked previously-reviewed listings.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from syndication import calendar_ics, events_rss

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / 'data'
TIMEZONE = ZoneInfo('Australia/Sydney')
HEADERS = {'User-Agent': 'FinanceRadar-StudentProject/0.4 (+source links and contact via project repo)', 'Accept': 'text/html,application/xhtml+xml'}
SOURCES = {
    'unit': ('UNIT', 'https://www.unit.org.au/'),
    'unit_calendar': ('UNIT calendar', 'https://www.unit.org.au/upcoming-events'),
    'fmaa': ('FMAA', 'https://www.fmaa.com.au/events'),
    'unsw': ('UNSW Employability', 'https://www.unsw.edu.au/employability/events-news/events'),
    'finsoc': ('FINSOC', 'https://www.unswfinsoc.org.au/'),
    'social_finsoc': ('FINSOC bio links', 'https://linktr.ee/finsocunsw'),
    'social_unit': ('UNIT bio links', 'https://linktr.ee/unit_unsw'),
    'social_fintech': ('FinTechSoc bio links', 'https://linktr.ee/unswfintechsoc'),
    'social_quant': ('QuantSoc bio links', 'https://linktr.ee/unswquantsoc'),
    'social_bsoc': ('BSOC bio links', 'https://linktr.ee/unswbsoc'),
    'social_fmaa': ('FMAA UNSW bio links', 'https://linktr.ee/fmaaunsw'),
    'bsoc_publications': ('BSOC public newsletter', 'https://unswbsocnewsletter.beehiiv.com/'),
    'unit_publications': ('UNIT Market Wrap RSS', 'https://www.unit.org.au/market-wrap?format=rss'),
    'capitalw': ('UNSW Capital W', 'https://capitalw.org/events'),
    'cma': ('UNSW Capital Markets Association', 'https://www.cmaunsw.com/'),
    'accsoc': ('UNSW Accounting and Taxation Society', 'https://www.unswaccsoc.com/upcoming-events'),
    'bsoc_calendar': ('UNSW Business Society events', 'https://www.unswbsoc.com/our-events'),
    'faic': ('UNSW Fintech AI Innovation Consortium', 'https://www.unsw.edu.au/research/faic/events'),
    'mathsoc_quant': ('UNSW MathSoc · QuantSoc collaborations', 'https://www.unswmathsoc.org/events'),
    'quantsoc_site': ('UNSW QuantSoc official website', 'https://quantsoc.org/'),
    'finsoc_publications': ('FINSOC public publications', 'https://www.unswfinsoc.org.au/publications'),
    'finsoc_humanitix': ('FINSOC official Humanitix organiser', 'https://events.humanitix.com/host/unsw-finance-and-banking-society'),
    'cfa': ('CFA Society Australia', 'https://cfas.org.au/Events/'),
    'finma': ('FINMA Financial Markets Academy', 'https://www.finma.au/events-1'),
    'cafba_sydney': ('CAFBA Commercial Finance Networking · Sydney', 'https://www.cafba.com.au/eventdetails/41443/cafba-end-of-year-networking-sydney'),
    'rmia_sydney': ('RMIA NSW Risk Professionals Networking', 'https://www.rmia.org.au/risk-management-events/rmia-nsw-post-ro-networking-event'),
    'step_emerging': ('STEP NSW Emerging Professionals Network', 'https://stepaustralia.com/events/step-nsw-emerging-professionals-network-wednesday-25-november-2026/'),
    'mymoney_expo': ('MyMoney Expo Sydney', 'https://iccsydney.com.au/events/mymoney-expo/'),
    'unsw_public_events': ('UNSW public events calendar', 'https://events.unsw.edu.au/'),
    'unsw_accounting_lecture': ('UNSW Accounting & CPA Australia public lecture', 'https://www.unsw.edu.au/business/our-schools/accounting-auditing-taxation/news-events/birkett-memorial-lecture/bill-birkett-lecture-series-2026'),
}
MONTHS = ('January February March April May June July August September October November December').split()
MONTH_RX = '|'.join(MONTHS+[m[:3] for m in MONTHS])
DATE_DAY_MONTH = re.compile(rf'\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{MONTH_RX})\b(?:,?\s+(?P<year>20\d{{2}}))?', re.I)
DATE_MONTH_DAY = re.compile(rf'\b(?P<month>{MONTH_RX})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>20\d{{2}})\b', re.I)
RANGE_RX = re.compile(r'\b(?P<start>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|–|—|to)\s*(?P<end>\d{1,2}(?::\d{2})?\s*(?:am|pm))\b',re.I)
CLOCK_RX = re.compile(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b', re.I)
ELIGIBILITY_RX = re.compile(r'penultimate[\s-]*year|final[\s-]*year\s+(?:undergrad|students)|postgraduate\s+only|master.s\s+students\s+only',re.I)
CAREER_RX = re.compile(r'fintech|financial technolog|financial modell?ing|finance|bank|capital|trading|asset management|markets?|invest|portfolio|equity|recruit|intern|network|linkedin|job search|interview|consult|mckinsey|bain|careers?|corporate strategy|accounting',re.I)


def get(url: str) -> str:
    """Bounded fetch; this tool does not bypass access controls or scrape login pages."""
    response = requests.get(url, headers=HEADERS, timeout=22, allow_redirects=True)
    response.raise_for_status()
    if len(response.content) > 3_000_000:
        raise ValueError('Oversized response (>3MB)')
    if not any(t in response.headers.get('Content-Type', 'text/html').lower() for t in ('text/html', 'application/rss+xml', 'application/xml', 'text/xml')):
        raise ValueError('Expected HTML response')
    return response.text


def parse_time(text: str) -> dt.time | None:
    text = text.replace('\u202f', ' ').strip()
    try:
        v = dateparser.parse(text, fuzzy=False)
        return v.time() if v else None
    except (ValueError, TypeError, OverflowError):
        return None


def parse_date(text: str, today: dt.date) -> dt.date | None:
    m = DATE_MONTH_DAY.search(text) or DATE_DAY_MONTH.search(text)
    if not m: return None
    year = int(m.group('year')) if m.group('year') else today.year
    try:
        proposed = dt.datetime.strptime(f'{m.group("day")} {m.group("month")} {year}', '%d %B %Y').date()
    except ValueError:
        try:
            proposed = dt.datetime.strptime(f'{m.group("day")} {m.group("month")} {year}', '%d %b %Y').date()
        except ValueError:
            return None
    # Without a stated year, roll forward only across a plausible Dec→Jan boundary.
    if not m.group('year') and proposed < today and today.month == 12 and proposed.month == 1:
        proposed = proposed.replace(year=year+1)
    return proposed


def range_from_text(text: str, event_date: dt.date) -> tuple[dt.datetime|None, dt.datetime|None]:
    m = RANGE_RX.search(text.replace('\u202f',' '))
    if m:
        st = m.group('start')
        en = m.group('end')
        suffix = re.search(r'(am|pm)', en, re.I)
        if not re.search(r'(am|pm)', st, re.I) and suffix: st += ' ' + suffix.group(1)
        start_time, end_time = parse_time(st), parse_time(en)
    else:
        values = CLOCK_RX.findall(text.replace('\u202f',' '))
        start_time, end_time = (parse_time(values[0]) if values else None), (parse_time(values[1]) if len(values)>1 else None)
    start = dt.datetime.combine(event_date, start_time or dt.time(12,0), tzinfo=TIMEZONE)
    end = dt.datetime.combine(event_date, end_time, tzinfo=TIMEZONE) if end_time else None
    if end and end < start: end += dt.timedelta(days=1)
    return start, end


def fit_from(title: str, context: str) -> tuple[str,str]:
    t = (title + ' ' + context).lower()
    restricted = bool(ELIGIBILITY_RX.search(t))
    if re.search(r'investment bank|morgan stanley|goldman sachs|m&a',t): category='Investment banking'
    elif re.search(r'equity research|markets?|trading|asset manage|portfolio',t): category='Markets & asset management'
    elif re.search(r'mckinsey|consulting|bain|bcg',t): category='Consulting'
    elif re.search(r'fintech|financial modell?ing|finance|invest|bank|strategy',t): category='Finance & strategy'
    else: category='Career skills'
    return category, 'restricted' if restricted else ('high' if category!='Career skills' else 'medium')


def event(source: str,title: str,date: dt.date|None, date_context: str,url: str, *, today: dt.date, venue: str='See organiser', summary: str='', eligibility: str='', registration_url: str='', time_known: bool=True) -> dict | None:
    if not date or date < today or not title or len(title.strip())<6: return None
    if not url.startswith('https://'): return None
    title=re.sub(r'\s+',' ',title).strip()
    context=title+' '+summary+' '+eligibility
    if not CAREER_RX.search(context):return None
    cat,fit=fit_from(title,context)
    start,end=range_from_text(date_context,date)
    # No timestamp advertised? Keep a date-only listing, and never fabricate 12pm.
    starts_at=start.isoformat(timespec='seconds') if time_known and CLOCK_RX.search(date_context.replace('\u202f',' ')) else date.isoformat()
    ends_at=end.isoformat(timespec='seconds') if end and len(starts_at)>10 else None
    canonical=re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-')[:64]
    eid=hashlib.sha1((canonical+'|'+date.isoformat()).encode()).hexdigest()[:12]
    elig = eligibility or ('Eligibility restrictions apply — check organiser.' if fit=='restricted' else 'Confirm eligibility with organiser.')
    return {
        'id':f'evt-{eid}', 'title':title, 'subtitle':re.sub(r'\s+',' ',summary).strip()[:240] or 'Details on organiser website.',
        'starts_at':starts_at,'ends_at':ends_at,'location':venue,'format':'Online' if 'online' in venue.lower() else 'In person',
        'organiser':source,'sources':[source],'source_urls':[url],'registration_url':registration_url or url,
        'category':cat,'tags':[cat], 'eligibility':elig,'fit':fit,
        'relevance_reason':'Public organiser listing; confirm registration, changes and eligibility at the source.',
        'verified_on':today.isoformat(),'confidence':'source-backed','last_seen_on':today.isoformat(),'collection_status':'current'
    }


def parse_unit_home(html: str,today: dt.date) -> list[dict]:
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text('\n',strip=True)
    m=re.search(r'(?m)^Upcoming Events$',text,re.I)
    if not m: raise ValueError('Missing expected UNIT Upcoming Events section')
    segment=text[m.end():]
    stop=re.search(r'(?m)^(?:UNIT Scroll|Official Blogs Page|Our Sponsors|Student Opportunities)$',segment,re.I)
    if stop: segment=segment[:stop.start()]
    # No date means no event, NOT an inferred launch date.
    dm=DATE_DAY_MONTH.search(segment)
    if not dm:return []
    date=parse_date(dm.group(0),today)
    if not date or date<today:return []
    head=[x.strip() for x in segment.splitlines() if x.strip()]
    title=head[0] if head else ''
    exact=re.search(r'\bEvening with Morgan Stanley\b',segment,re.I)
    if exact: title=exact.group(0)
    # Never append year from another part of page; only the event excerpt.
    period=segment[dm.start():min(len(segment),dm.end()+130)]
    place='Morgan Stanley office, Sydney CBD' if 'Morgan Stanley Office' in segment else 'See organiser'
    registration=''
    for a in soup.find_all('a',href=True):
        if a.get_text(' ',strip=True).lower() in ('register here','register','sign up'):
            url=urljoin('https://www.unit.org.au/',a.get('href',''))
            if url.startswith('https://'): registration=url;break
    rec=event('UNIT',title,date,period,'https://www.unit.org.au/',today=today,venue=place,summary=segment[:260],registration_url=registration,eligibility='Pre-penultimate students encouraged; check organiser eligibility.' if 'pre-penultimate' in segment.lower() else '')
    return [rec] if rec else []


def parse_unit_calendar(html: str,today: dt.date) -> list[dict]:
    soup=BeautifulSoup(html,'html.parser')
    if 'Upcoming UNIT Events' not in soup.get_text(' ',strip=True):
        raise ValueError('Missing expected UNIT calendar heading')
    result=[]
    # Squarespace index groups each upcoming event in an article with an h1 and times.
    for node in soup.select('article'):
        heading=node.find(['h1','h2','h3'])
        if not heading:continue
        title=heading.get_text(' ',strip=True)
        if title.lower() in ('upcoming unit events','upcoming events'):continue
        text=node.get_text(' ',strip=True)
        date=parse_date(text,today)
        if not date or date<today:continue
        times=' '.join(n.get_text(' ',strip=True) for n in node.select('time'))
        href=next((urljoin('https://www.unit.org.au',a['href']) for a in node.find_all('a',href=True) if '/upcoming-events/' in a['href']), 'https://www.unit.org.au/upcoming-events')
        record=event('UNIT',title,date,times,href,today=today,summary=text[:260])
        if record:result.append(record)
    return result


def parse_fmaa(index: str,today: dt.date, fetch_detail=get) -> list[dict]:
    soup=BeautifulSoup(index,'html.parser')
    if 'OUR EVENTS' not in soup.get_text(' ',strip=True).upper():
        raise ValueError('FMAA events heading missing')
    urls=[]
    for a in soup.select('a[href]'):
        link=urljoin('https://www.fmaa.com.au/events',a['href'])
        if urlsplit(link).netloc in ('www.fmaa.com.au','fmaa.com.au') and urlsplit(link).path.startswith('/event/') and link not in urls:
            urls.append(link)
    if not urls and DATE_MONTH_DAY.search(soup.get_text(' ',strip=True)):
        raise ValueError('FMAA date visible, but event detail links not discovered (markup changed)')
    result=[]
    failures=[]
    details_read=0
    for link in urls[:16]:
        try:
            detail=BeautifulSoup(fetch_detail(link),'html.parser')
            heading=detail.find('h1')
            if not heading: raise ValueError('No event title')
            title=heading.get_text(' ',strip=True)
            text=detail.get_text(' ',strip=True)
            details_read+=1
            # Must find a year in the same source detail.
            m=DATE_MONTH_DAY.search(text) or DATE_DAY_MONTH.search(text)
            if not m or not m.group('year'):raise ValueError('No unambiguous dated event')
            date=parse_date(m.group(0),today)
            if not date or date<today:continue
            # Date in Webflow metadata typically immediately followed by start time.
            nearby=text[m.start():m.end()+65]
            date_context=nearby
            rng=RANGE_RX.search(text)
            if rng: date_context=rng.group(0)
            eligibility='Penultimate-year or postgraduate restriction — verify details.' if ELIGIBILITY_RX.search(text) else ''
            venue='Sydney — see organiser for address'
            rec=event('FMAA',title,date,date_context,link,today=today,venue=venue,summary=text[m.end():m.end()+280],eligibility=eligibility)
            if rec:result.append(rec)
        except Exception as exc:
            failures.append(f'{link}: {str(exc)[:80]}')
        time.sleep(.12)
    if failures and details_read == 0:
        raise RuntimeError('All FMAA detail pages failed: '+ '; '.join(failures)[:190])
    # A readable archive containing only expired listings is a healthy empty source.
    return result



def parse_public_facebook_events(html: str, today: dt.date, fetch_detail=get) -> list[dict]:
    """Conservatively extract dated public Facebook event metadata linked by FINSOC."""
    soup = BeautifulSoup(html, 'html.parser')
    urls = set()
    for anchor in soup.select('a[href]'):
        target = urljoin('https://www.unswfinsoc.org.au/', anchor.get('href', ''))
        try:
            parsed = urlsplit(target)
        except ValueError:
            continue
        if parsed.scheme != 'https' or (parsed.hostname or '').lower() not in ('www.facebook.com', 'facebook.com', 'm.facebook.com'):
            continue
        m = re.search(r'/events/(?:[^/?]+/)*(\d{10,})/?', parsed.path)
        if m:
            urls.add('https://www.facebook.com/events/' + m.group(1))
    out = []
    for url in sorted(urls)[:6]:
        try:
            detail = BeautifulSoup(fetch_detail(url), 'html.parser')
            name_el = detail.find('meta', attrs={'property': 'og:title'})
            info_el = detail.find('meta', attrs={'property': 'og:description'})
            name = (name_el.get('content', '') if name_el else '').strip()
            info = (info_el.get('content', '') if info_el else '').strip()
            if not re.search(r'by (?:UNSW Finance and Banking Society|FINSOC)', info, re.I):
                continue
            if not re.search(r'\b20\d{2}\b', info):
                continue
            date = parse_date(info, today)
            record = event('FINSOC', name, date, '', url, today=today,
                           summary='Public FINSOC Facebook event. Verify details with the organiser.',
                           time_known=False)
            if record:
                record['source_urls'] = ['https://www.unswfinsoc.org.au/', url]
                record['sources'] = ['FINSOC website', 'Public Facebook event metadata']
                record['relevance_reason'] = 'Dated public Facebook event linked on official FINSOC website.'
                out.append(record)
        except (requests.RequestException, ValueError, RuntimeError):
            continue
    return unique(out)


def parse_finsoc(html: str,today: dt.date) -> list[dict]:
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text('\n',strip=True)
    # Most FINSOC listings are social-only; no year/time = no invented event.
    m=re.search(r'UPCOMING EVENTS\.',text,re.I)
    if not m:
        # Homepage may display only the Past Highlights section.
        if re.search(r'PAST EVENTS\.',text,re.I):return []
        raise ValueError('FINSOC events section missing')
    section=text[m.end():]
    cut=re.search(r'PAST (?:HIGHLIGHTS|EVENTS)',section,re.I)
    if cut:section=section[:cut.start()]
    result=[]
    # FINSOC public HTML has event anchors whose text includes a date.
    for a in soup.select('a[href]'):
        title=a.get_text(' ',strip=True)
        if not title or not re.search(r'\b20\d{2}\b',title): continue
        date=parse_date(title,today)
        if not date or date<today:continue
        # Include only anchors from the upcoming section, never past highlights.
        if not re.search(re.escape(title[:35]),section,re.I):continue
        title=re.sub(r'^(?:workshop|networking|social|panel)\s+','',title,flags=re.I)
        title=re.sub(r'(?:VIEW ON FACEBOOK|VIEW EVENT)$','',title,flags=re.I).strip()
        title=re.sub(rf'\b(?:{MONTH_RX})\s+\d{{1,2}},?\s+20\d{{2}}\b','',title,flags=re.I).strip()
        link=urljoin('https://www.unswfinsoc.org.au/',a['href'])
        if not link.startswith('https://'):continue
        rec=event('FINSOC',title,date,'',link,today=today,venue='See organiser',summary='Event listed on FINSOC website.',time_known=False)
        if rec:result.append(rec)
    return result


def unsw_title(card: str, anchor_text: str) -> str:
    """Recover a card title even when its outbound link only says 'Read more'."""
    # Use the surrounding event card, not generic navigation text. A date and a
    # recognisable event title are required independently before publication.
    date_match=DATE_DAY_MONTH.search(card) or DATE_MONTH_DAY.search(card)
    after=card[date_match.end():] if date_match else card
    after=re.sub(r'^\s*(?:All (?:UNSW )?students(?: and recent graduates)?|Penultimate Year Students|International (?:Chinese )?Students|UNSW Business Students|Final Year Students)\s*', '', after, flags=re.I)
    # The card normally places the event title before a pipe-delimited mode
    # and clock range. Avoid putting the description in the event title.
    after=re.split(r'\s+\|\s+(?:online|in.person)\b',after,maxsplit=1,flags=re.I)[0]
    after=RANGE_RX.split(after,maxsplit=1)[0]
    after=re.split(r'\s+(?:Read more|Learn more|Register now)\b',after,maxsplit=1,flags=re.I)[0]
    after=re.sub(r'\s+', ' ', after).strip(' |:-')
    anchor=re.sub(r'\s+', ' ', anchor_text).strip()
    if anchor and not re.fullmatch(r'(?:Read more|Find out more|Register|Sign up|Learn more|View event)',anchor,flags=re.I):
        candidate=re.sub(r'^(?:All students and recent graduates|Penultimate Year Students)\s+', '', anchor, flags=re.I)
        candidate=re.split(r'\s+\|\s+(?:online|in.person)\b',candidate,maxsplit=1,flags=re.I)[0]
        candidate=RANGE_RX.split(candidate,maxsplit=1)[0].strip()
        if 10 <= len(candidate) <= 140 and CAREER_RX.search(candidate):return candidate
    return after[:140]



UNSW_PUBLIC_REGISTRATIONS = (
    'https://www.eventbrite.com.au/e/leveraging-linkedin-workshop-tickets-1999065644155',
    'https://www.eventbrite.com.au/e/job-search-strategies-workshop-tickets-1999066649161',
    'https://www.eventbrite.com.au/e/preparing-for-interviews-workshop-tickets-1999066901917',
)

def parse_unsw_eventbrite_detail(html: str, url: str, today: dt.date) -> dict | None:
    """Only accept metadata from a dated UNSW Employability registration."""
    parsed=urlsplit(url)
    if parsed.scheme != 'https' or (parsed.hostname or '').lower() not in ('www.eventbrite.com.au','eventbrite.com.au'):
        return None
    if not re.fullmatch(r'/e/[a-z0-9-]+',parsed.path,re.I):
        return None
    soup=BeautifulSoup(html,'html.parser')
    if not re.search(r'\bUNSW Employability\b',soup.get_text(' ',strip=True),re.I):
        return None
    def meta(prop):
        item=soup.find('meta',attrs={'property':prop})
        return item.get('content','').strip() if item else ''
    name=meta('og:title')
    start_text=meta('event:start_time')
    if not name or not start_text or not CAREER_RX.search(name):
        return None
    try:
        start=dateparser.isoparse(start_text)
        if start.tzinfo is None:return None
        start=start.astimezone(TIMEZONE)
        if start.date()<today:return None
    except (ValueError,TypeError,OverflowError):
        return None
    venue='Online' if re.search(r'online event|online workshop',soup.get_text(' ',strip=True),re.I) else 'See organiser'
    rec=event('UNSW Employability',name,start.date(),start.strftime('%I:%M %p'),SOURCES['unsw'][1],
              today=today,venue=venue,
              summary=meta('og:description') or 'UNSW Employability careers event.',
              eligibility='All students and recent graduates; verify with organiser.',
              registration_url=url)
    if not rec:return None
    rec['starts_at']=start.isoformat(timespec='seconds')
    end_text=meta('event:end_time')
    if end_text:
        try:
            end=dateparser.isoparse(end_text)
            if end.tzinfo is not None and end>dateparser.isoparse(start_text):
                rec['ends_at']=end.astimezone(TIMEZONE).isoformat(timespec='seconds')
        except (ValueError,TypeError,OverflowError):pass
    rec['sources']=['UNSW Employability','Eventbrite registration']
    rec['source_urls']=[SOURCES['unsw'][1],url]
    return rec

def parse_unsw_with_registration_fallback(html: str, today: dt.date, fetch_detail=get) -> list[dict]:
    try:
        found=parse_unsw(html,today)
    except ValueError as exc:
        if 'No dated event cards' not in str(exc):raise
        found=[]
    soup=BeautifulSoup(html,'html.parser')
    urls=[]
    for anchor in soup.select('a[href]'):
        url=urljoin(SOURCES['unsw'][1],anchor.get('href',''))
        if url.startswith('https://www.eventbrite.com.au/e/') and url not in urls:
            urls.append(url)
    if dt.date(2026,10,25)<=today<=dt.date(2026,11,16):
        urls.extend(u for u in UNSW_PUBLIC_REGISTRATIONS if u not in urls)
    for url in urls[:12]:
        try:
            rec=parse_unsw_eventbrite_detail(fetch_detail(url),url,today)
            if rec:found.append(rec)
        except (requests.RequestException,ValueError,RuntimeError):
            continue
    if not found and not urls and not (DATE_DAY_MONTH.search(soup.get_text(' ',strip=True)) or DATE_MONTH_DAY.search(soup.get_text(' ',strip=True))):
        raise ValueError('No dated event cards or registration links visible in UNSW response')
    return unique(found)


def parse_unsw(html: str,today: dt.date) -> list[dict]:
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    if not re.search(r'Events|Employability',text,re.I):raise ValueError('UNSW events heading missing')
    found=[]
    # Real UNSW 'Read more' anchors often don't include the event title. Use
    # their closest dated card instead of demanding keywords in anchor text.
    for a in soup.select('a[href]'):
        link=urljoin('https://www.unsw.edu.au',a['href'])
        if not link.startswith('https://'):continue
        host=urlsplit(link).hostname or ''
        if not any(host==h or host.endswith('.'+h) for h in ('eventbrite.com.au','eventbrite.com','humanitix.com','unsw.edu.au','forms.cloud.microsoft','mckinsey.com')):continue
        parent=a
        context=''
        for _ in range(5):
            parent=parent.parent
            if parent is None:break
            candidate=parent.get_text(' ',strip=True)
            if len(candidate)>950:break
            if DATE_DAY_MONTH.search(candidate) or DATE_MONTH_DAY.search(candidate):
                context=candidate
                break
        if not context or not CAREER_RX.search(context):continue
        m=DATE_DAY_MONTH.search(context) or DATE_MONTH_DAY.search(context)
        date=parse_date(m.group(0),today) if m else None
        if not date or date<today:continue
        title=unsw_title(context,a.get_text(' ',strip=True))
        # Reject a bare card description or an unrelated navigation element.
        if not 10<=len(title)<=140 or len(title.split())>18:continue
        if not CAREER_RX.search(title):continue
        restricted=bool(ELIGIBILITY_RX.search(context))
        elig='Penultimate-year or postgraduate restriction — verify details.' if restricted else ''
        starttime=RANGE_RX.search(context)
        clock_text=starttime.group(0) if starttime else context[m.end():m.end()+80]
        rec=event('UNSW Employability',title,date,clock_text,link,today=today,venue='Online' if 'online' in context.lower() else 'See organiser',summary=context[:240],eligibility=elig)
        if rec:found.append(rec)
    if not found and not (DATE_DAY_MONTH.search(text) or DATE_MONTH_DAY.search(text)):
        raise ValueError('No dated event cards visible in HTTP response; the UNSW page may require browser rendering')
    return unique(found)



def jsonld_events(html: str, source: str, source_url: str, today: dt.date) -> list[dict]:
    """Extract official Schema.org Event objects if published in the HTML.

    This provides a standards-based fallback for sites that don't expose a simple
    event card, without relying on guessed dates or social media access.
    """
    soup=BeautifulSoup(html,'html.parser')
    nodes=[]
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload=json.loads(script.string or script.get_text())
        except (ValueError,TypeError):
            continue
        todo=[payload]
        while todo:
            obj=todo.pop()
            if isinstance(obj,list):todo.extend(obj);continue
            if not isinstance(obj,dict):continue
            types=obj.get('@type',[])
            if isinstance(types,str):types=[types]
            if any(str(x).lower().split('/')[-1]=='event' for x in types):nodes.append(obj)
            for key in ('@graph','itemListElement','mainEntity','hasPart'):
                nested=obj.get(key)
                if isinstance(nested,(dict,list)):todo.append(nested)
    output=[]
    for obj in nodes:
        name=obj.get('name')
        when=obj.get('startDate')
        if not isinstance(name,str) or not isinstance(when,str):continue
        try:
            start=dateparser.isoparse(when)
            if start.tzinfo is None:start=start.replace(tzinfo=TIMEZONE)
            start=start.astimezone(TIMEZONE)
        except (ValueError,TypeError,OverflowError):continue
        if start.date()<today:continue
        url=obj.get('url')
        if not isinstance(url,str) or not url.startswith('https://'):url=source_url
        desc=obj.get('description','')
        if not isinstance(desc,str):desc=''
        venue=obj.get('location',{})
        if isinstance(venue,list):venue=venue[0] if venue else {}
        if isinstance(venue,dict):
            place=venue.get('name') or ('Online' if 'VirtualLocation' in str(venue.get('@type','')) else 'See organiser')
        else:place=str(venue or 'See organiser')
        desc=BeautifulSoup(desc,'html.parser').get_text(' ',strip=True)[:300]
        record=event(source,name,start.date(),start.strftime('%-I:%M %p'),url,today=today,venue=str(place),summary=desc)
        if not record:continue
        record['starts_at']=start.isoformat(timespec='seconds') if 'T' in when else start.date().isoformat()
        end_raw=obj.get('endDate')
        if isinstance(end_raw,str) and 'T' in end_raw:
            try:
                end=dateparser.isoparse(end_raw)
                if end.tzinfo is None:end=end.replace(tzinfo=TIMEZONE)
                record['ends_at']=end.astimezone(TIMEZONE).isoformat(timespec='seconds')
            except (ValueError,TypeError,OverflowError):pass
        output.append(record)
    return unique(output)


# Public Linktree pages belong to societies but do not expose the Instagram or
# Facebook post feed. Discover links here; never assume an undated link is an event.
BIO_SOCIAL_NAMES = {
    'social_finsoc': 'FINSOC', 'social_unit': 'UNIT',
    'social_fintech': 'UNSW FinTechSoc', 'social_quant': 'UNSW QuantSoc',
    'social_bsoc': 'UNSW BSOC', 'social_fmaa': 'FMAA UNSW',
}
LINK_EVENT_HOSTS = {'eventbrite.com', 'eventbrite.com.au', 'humanitix.com', 'events.humanitix.com', 'luma.com'}
LINK_FORM_HOSTS = {'docs.google.com', 'forms.gle', 'form.jotform.com', 'forms.office.com', 'events.humanitix.com', 'app.tribespot.co'}
HUB_KEYWORDS = re.compile(r'ESG|workshop|networking|case competition|careers? (?:fair|panel|night|evening|event)|finance|investment|credit analysis|financial modelling|banking|equity|trading|quant|seminar|webinar|internship|industry insights|mentoring|which major', re.I)

# Official FINSOC LinkedIn posts show these October 2026 events have finished,
# although their registration forms remain linked from the public society bio.
# https://au.linkedin.com/company/unsw-finsoc
COMPLETED_SOCIAL_REGISTRATIONS = {
    'https://docs.google.com/forms/d/e/1FAIpQLSdb-zYvAi7xwbM6zvzl149UEdKEP6iv_GDPDVdK5syqps-Znw/viewform',
    'https://docs.google.com/forms/d/e/1FAIpQLSeEBaqZLF8FAxmg6dWWZuf3lqZyBrCvpY8aatl4812AtGvauQ/viewform',
}

HUB_EXCLUDE = re.compile(r'director recruitment|subcommittee|membership|subscribe|rubric sign.?up|first year.?s guide|careers? guide|join us|giveaway|pub ?crawl|cruise|hallocrawl|ball 2026|agm|alumni directory|summer analyst.*application', re.I)

def trusted_host(link: str, hosts: set[str]) -> bool:
    try:
        u=urlsplit(link)
        host=(u.hostname or '').lower()
        if host.startswith('www.'):host=host[4:]
        return u.scheme == 'https' and host in hosts and not u.username and not u.password
    except ValueError:
        return False


def unwrap_public_registration_url(link: str) -> str:
    """Unwrap Facebook's public outbound-link wrapper, not Facebook login."""
    try:
        u = urlsplit(link)
        if u.scheme == 'https' and (u.hostname or '').lower() in ('l.facebook.com', 'lm.facebook.com') and u.path == '/l.php':
            target = parse_qs(u.query).get('u', [''])[0]
            if trusted_host(target, LINK_EVENT_HOSTS | LINK_FORM_HOSTS):
                return target
    except (ValueError, IndexError):
        pass
    return link


def parse_newsletter_mentions(raw: str, key: str, today: dt.date, fetch_detail=get) -> list[dict]:
    """Only surface RECENT, specifically titled newsletter articles as leads.

    These are not scheduled events and cannot trigger the confirmed-event alert.
    Old newsletters and generic market wrap stories are ignored.
    """
    if key not in ('bsoc_publications', 'unit_publications'):
        raise ValueError('Unknown newsletter')
    is_rss = key == 'unit_publications'
    soup = BeautifulSoup(raw, 'html.parser')
    items = []
    if is_rss:
        # HTML parsers treat RSS <link> as a void element, losing the item URL.
        # ElementTree preserves XML values without installing lxml.
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError('UNIT newsletter RSS unavailable') from exc
        if root.tag.lower() != 'rss':
            raise ValueError('UNIT newsletter RSS unavailable')
        for node in root.findall('.//item')[:15]:
            title = node.findtext('title', default='')
            date = node.findtext('pubDate', default='')
            link = node.findtext('link', default='')
            if title and date and link:
                items.append((title.strip(), link.strip(), date.strip(), 'UNIT'))
    else:
        if not soup.find('a', href=re.compile('/p/')):
            raise ValueError('BSOC newsletter article links missing')
        seen = set()
        for a in soup.select('a[href*="/p/"]'):
            link = urljoin('https://unswbsocnewsletter.beehiiv.com/', a.get('href', ''))
            title = a.get_text(' ', strip=True)
            if not title:
                title = link.split('/p/')[-1].replace('-', ' ')
            if link not in seen:
                seen.add(link)
                items.append((title, link, '', 'BSOC'))
    leads = []
    specific = re.compile(r'upcoming events?|finance (?:career|networking|panel|workshop)|investment bank|career fair|industry (?:insights|networking|panel)|trading workshop', re.I)
    for title, link, published, organiser in items[:30]:
        if not specific.search(title):
            continue
        if urlsplit(link).scheme != 'https':
            continue
        try:
            if not published:
                page = BeautifulSoup(fetch_detail(link), 'html.parser')
                meta = page.find('meta', attrs={'property': 'article:published_time'})
                t = page.find('time', attrs={'datetime': True})
                published = (meta.get('content', '') if meta else '') or (t.get('datetime', '') if t else '')
                if not published:
                    match = re.search(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2}\b',
                                      page.get_text(' ', strip=True)[:700], re.I)
                    published = match.group(0) if match else ''
            if not published:
                continue
            when = dateparser.parse(published).date()
            if not (dt.timedelta(days=0) <= today - when <= dt.timedelta(days=45)):
                continue
        except (requests.RequestException, ValueError, TypeError, OverflowError):
            continue
        sid = hashlib.sha1((key + '|' + link).encode()).hexdigest()[:12]
        leads.append({'id': 'signal-' + sid, 'title': title[:150], 'organiser': organiser,
                      'url': link, 'source_url': SOURCES[key][1], 'status': 'date_unverified',
                      'note': 'Recent public newsletter post; check the article for actual event dates.',
                      'checked_on': today.isoformat()})
    return leads[:5]


def registration_is_past(html: str, url: str, today: dt.date) -> bool:
    """Suppress provably expired registration pages from the undated-leads feed."""
    content=BeautifulSoup(html,'html.parser').get_text(' ',strip=True)[:6000]
    if trusted_host(url, LINK_EVENT_HOSTS) and re.search(r'\bEvent ended\b',content,re.I):
        return True
    if trusted_host(url, {'form.jotform.com'}):
        date_label=re.search(r'\b(?:Event\s+)?Date\s*:\s*(.{0,65})',content,re.I)
        if date_label and re.search(r'\b20\d{2}\b',date_label.group(1)):
            when=parse_date(date_label.group(1),today)
            if when is not None and when<today:
                return True
    return False






UNSW_FINANCE_PUBLIC_LINK_RX = re.compile(
    r'investment|investor|finance|banking|private-equity|capital|entrepreneur|'
    r'venture|fundrais|startup|start-up|asset-pricing|fintech|accounting|'
    r'financial|funding|trading|markets?',re.I)
UNSW_FINANCE_SUBJECT_RX = re.compile(
    r'investment|investor|finance|capital|funding|commercialis|venture|'
    r'equity|entrepreneur|fintech|asset.pricing|banking',re.I)



UNSW_INVESTOR_PANEL_TICKET = 'https://www.eventbrite.com.au/e/engineering-the-future-the-entrepreneurship-paradox-tickets-1996543386013'
UNSW_INVESTOR_PANEL_PAGE = 'https://events.unsw.edu.au/event/engineering-future-entrepreneurship-paradox'

def parse_unsw_verified_investor_ticket(html: str, today: dt.date) -> dict | None:
    """Validate official date/time on a public UNSW Engineering registration."""
    if not dt.date(2026,10,30)<=today<=dt.date(2026,11,10):return None
    soup=BeautifulSoup(html,'html.parser')
    visible=soup.get_text(' ',strip=True)
    heading=soup.find('h1')
    name=heading.get_text(' ',strip=True) if heading else ''
    if not re.fullmatch(r'Engineering the Future:\s*The Entrepreneurship Paradox',name,re.I):
        return None
    if re.search(r'\bEvent ended\b|\bRegistration closed\b',visible,re.I):return None
    if not re.search(r'\bUNSW Engineering\b',visible,re.I):return None
    if not re.search(r'\b(?:10\s+November|November\s+10)\b',visible,re.I):return None
    match=RANGE_RX.search(visible)
    if not match:return None
    times=match.group(0)
    if not (re.search(r'5:30\s*pm',times,re.I) and re.search(r'8:30\s*pm',times,re.I)):
        return None
    record=event('UNSW Engineering & Spinout Club',name,dt.date(2026,11,10),times,
        UNSW_INVESTOR_PANEL_PAGE,today=today,venue='Australian Museum, Sydney',
        summary='Free panel for investors and founders on innovation, capital raising, investment risk and Australian startups.',
        eligibility='Free public event; register via the official ticket page.',
        registration_url=UNSW_INVESTOR_PANEL_TICKET)
    if record:
        record['source_urls']=[UNSW_INVESTOR_PANEL_PAGE,UNSW_INVESTOR_PANEL_TICKET]
        record['sources']=['UNSW official events','Organiser registration']
        record['relevance_reason']='UNSW organiser listing cross-checked with the public ticket date and time.'
    return record


def parse_unsw_public_event_detail(html: str, url: str, today: dt.date) -> dict | None:
    """Event details from UNSW's public calendar, not category-based guesses.

    Only a finance/investment-themed, individually dated event with a future
    start and registration link qualifies. A generic Business and Economics
    tag on an unrelated conference isn't sufficient.
    """
    if not trusted_host(url, {'events.unsw.edu.au'}):
        return None
    if not re.fullmatch(r'/event/[a-z0-9][a-z0-9-]{5,150}/?',urlsplit(url).path,re.I):
        return None
    soup=BeautifulSoup(html,'html.parser')
    heading=soup.find('h1')
    if not heading:return None
    title=heading.get_text(' ',strip=True)
    if not title or not UNSW_FINANCE_PUBLIC_LINK_RX.search(title):
        return None
    section=heading.find_parent('section') or heading.find_parent('main') or soup
    # Anchor date/time scanning to the event heading, not the site navbar.
    visible=section.get_text(' ',strip=True)
    at=visible.find(title)
    if at>=0:visible=visible[at:]
    # Date and time must be in the official detail header, not in bios or
    # a later unrelated speaker section with an old publication year.
    heading_context=visible[:510]
    dm=DATE_DAY_MONTH.search(heading_context) or DATE_MONTH_DAY.search(heading_context)
    if not dm or not dm.group('year'):return None
    date=parse_date(dm.group(0),today)
    if not date or date<today:return None
    clock_context=re.sub(r'\b(\d{1,2})\.(\d{2})\s*(am|pm)\b',r'\1:\2 \3',
                         heading_context,flags=re.I)
    timer=RANGE_RX.search(clock_context)
    if not timer:return None
    times=timer.group(0)
    # Guard against broad "Innovation" events that mention finance only
    # as a page taxonomy tag: require substantive financial themes.
    overview=visible.split('Overview',1)[1][:2200] if 'Overview' in visible else ''
    if not overview or not UNSW_FINANCE_SUBJECT_RX.search(overview):
        return None
    registration=None
    for a in section.select('a[href]'):
        href=urljoin(url,a.get('href','').strip())
        if trusted_host(href,{'eventbrite.com.au','events.humanitix.com','luma.com'}):
            registration=href
            break
    if not registration:return None
    venue='See organiser'
    m=re.search(r'\b(Australian Museum|UNSW Kensington|UNSW Sydney|The Roundhouse)\b',heading_context,re.I)
    if m:venue=m.group(1)
    summary=overview.strip()[:220]
    rec=event('UNSW public events',title,date,times,url,today=today,
        venue=venue,summary=summary,
        eligibility=('Free public event; register with organiser.' if re.search(r'Free for everyone',heading_context,re.I)
                     else 'Public event; check eligibility and any fees with organiser.'),
        registration_url=registration)
    if rec:
        rec['relevance_reason']='UNSW public event with an explicitly dated investment/entrepreneurship theme and official registration.'
    return rec


def parse_unsw_public_events(html: str, today: dt.date, fetch_detail=get) -> list[dict]:
    """Bounded finance-specific discovery using the official public calendar."""
    soup=BeautifulSoup(html,'html.parser')
    if not re.search(r'\bEvents\b',soup.get_text(' ',strip=True)[:450],re.I):
        raise ValueError('UNSW public event calendar unavailable')
    home=SOURCES['unsw_public_events'][1]
    urls=[]
    for anchor in soup.select('a[href]'):
        candidate=urljoin(home,anchor.get('href','').strip())
        if not trusted_host(candidate,{'events.unsw.edu.au'}):
            continue
        path=urlsplit(candidate).path
        if (not re.fullmatch(r'/event/[a-z0-9][a-z0-9-]{5,150}/?',path,re.I)
            or not UNSW_FINANCE_PUBLIC_LINK_RX.search(path)):
            continue
        if candidate not in urls:urls.append(candidate)
    found=[]
    # UNSW's events index is sometimes JS-rendered. The currently verified
    # investor panel has a canonical public detail URL; continue checking that
    # detail until the date expires even when no links appear in the index.
    if dt.date(2026,10,30)<=today<=dt.date(2026,11,10):
        panel='https://events.unsw.edu.au/event/engineering-future-entrepreneurship-paradox'
        if panel not in urls:urls.insert(0,panel)
    for url in urls[:10]:
        try:
            page=fetch_detail(url)
            item=parse_unsw_public_event_detail(page,url,today)
            if item:
                found.append(item)
            elif url==UNSW_INVESTOR_PANEL_PAGE and today<=dt.date(2026,11,10):
                try:
                    ticket=fetch_detail(UNSW_INVESTOR_PANEL_TICKET)
                    confirmed=parse_unsw_verified_investor_ticket(ticket,today)
                    if confirmed:found.append(confirmed)
                except (requests.RequestException,ValueError,RuntimeError) as exc:
                    print('UNSW investor ticket verification unavailable:',type(exc).__name__,str(exc)[:70])
        except (requests.RequestException,ValueError,RuntimeError) as exc:
            print('UNSW public event fetch unavailable:',type(exc).__name__,str(exc)[:70])
            continue
    return unique(found)


def parse_unsw_accounting_lecture(html: str, today: dt.date) -> list[dict]:
    """Public CPA Australia / UNSW lecture only, with an explicit event date."""
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    if not re.search(r'Bill Birkett (?:Memorial )?Lecture(?: Series)? 2026',text,re.I):
        raise ValueError('UNSW accounting lecture source unavailable')
    date_match=re.search(r'\bDate\s+(?:Wednesday\s+)?(4\s+November\s+2026)\b',text,re.I)
    if not date_match:return []
    date=parse_date(date_match.group(1),today)
    if not date or date<today:return []
    times_match=re.search(r'\bTime\s+(4:30\s*[–-]\s*8:00\s*pm)\b',text,re.I)
    if not times_match:return []
    link=None
    for a in soup.select('a[href]'):
        candidate=a['href'].strip()
        if trusted_host(candidate,{'eventbrite.com.au'}):
            link=candidate
            break
    if not link:return []
    record=event('UNSW School of Accounting & CPA Australia',
        'Bill Birkett Memorial Lecture 2026',date,times_match.group(1),
        SOURCES['unsw_accounting_lecture'][1],today=today,
        venue='12-Micron Barangaroo, Sydney',
        summary='Accounting and finance perspectives, ANZ executive keynote and professional networking.',
        eligibility='Professional event — confirm student eligibility and any registration fee with organiser.',
        registration_url=link)
    if record:
        record['relevance_reason']='Dated UNSW and CPA Australia accounting lecture with a public registration link.'
        return [record]
    return []




def enrich_official_industry_listing(rec: dict, key: str) -> dict:
    """Preserve organiser-verified attendance and fees in schema.org fallback.

    Strictly match named 2026 events and their exact dates. Generic JSON-LD
    parsers otherwise replace explicit source eligibility with 'confirm
    eligibility', potentially hiding material event restrictions.
    """
    name=rec.get('title','')
    day=str(rec.get('starts_at',''))[:10]
    if key=='rmia_sydney' and day=='2026-11-11' and 'RMIA NSW Chapter' in name and 'Networking' in name:
        rec['fit']='restricted'
        rec['eligibility']='Free industry networking; student eligibility is not confirmed. Check with RMIA before attending.'
        rec['relevance_reason']='Professional risk-management event; free registration, but not advertised specifically to students.'
    if key=='step_emerging' and day=='2026-11-25' and 'STEP NSW Emerging Professionals Network' in name:
        rec['eligibility']='Students interested in trusts and estates welcome. Tickets $25 for members or $30 for non-members; sales close 19 November.'
        rec['relevance_reason']='Trusts, private-wealth and advisory networking. Organiser explicitly includes students; paid tickets.'
    return rec


def parse_cafba_sydney_networking(html: str, today: dt.date) -> list[dict]:
    """Verify Sydney commercial-finance networking and public access conditions."""
    soup=BeautifulSoup(html,'html.parser')
    heading=next((h for h in soup.find_all(['h1','h2','h3']) if re.search(r'CAFBA End of Year Networking',h.get_text(' ',strip=True),re.I)),None)
    if not heading or not re.search(r'^CAFBA End of Year Networking\s*[–-]\s*Sydney$',heading.get_text(' ',strip=True),re.I):
        return []
    visible=soup.get_text(' ',strip=True)
    if not (re.search(r'\b25 November 2026\b',visible,re.I)
            and re.search(r'\bWho Can Register\?\s*Anyone\b',visible,re.I)
            and re.search(r'\bZeta Bar\b.*\bSydney\b',visible,re.I | re.S)
            and re.search(r'\bFrom\s+5:30\s*pm\b',visible,re.I)
            and re.search(r'\bcommercial and asset finance\b',visible,re.I)):
        return []
    date=dt.date(2026,11,25)
    if date<today:return []
    rec=event('CAFBA','CAFBA Sydney Commercial & Asset Finance Networking',date,
        '5:30pm',SOURCES['cafba_sydney'][1],today=today,
        venue='Zeta Bar, Hilton Sydney, 488 George St',
        summary='Meet commercial finance brokers, lenders and asset-finance professionals at an industry networking evening.',
        eligibility='Anyone can register; confirm ticket availability and any fees with CAFBA. Registration essential.',
        registration_url=SOURCES['cafba_sydney'][1])
    if rec:
        rec['relevance_reason']='Official Sydney commercial and asset-finance industry association event, open to anyone.'
        return [rec]
    return []


def parse_rmia_sydney_networking(html: str, today: dt.date) -> list[dict]:
    """Free Sydney risk-professional networking; no implied student access."""
    soup=BeautifulSoup(html,'html.parser')
    visible=soup.get_text(' ',strip=True)
    if not (re.search(r'\bDate:\s*11 November 2026\b',visible,re.I)
            and re.search(r'\bTime:\s*5:00\s*pm\b',visible,re.I)
            and re.search(r'\bRegistration Fee:\s*FREE\b',visible,re.I)
            and re.search(r'The Sussex Hotel',visible,re.I)
            and re.search(r'NSW risk community',visible,re.I)):
        return []
    url=None
    for a in soup.select('a[href]'):
        link=urljoin(SOURCES['rmia_sydney'][1],a['href'])
        if trusted_host(link,{'members.rmia.org.au'}) and '/_events.registration/' in urlsplit(link).path:
            url=link
            break
    if not url:return []
    date=dt.date(2026,11,11)
    if date<today:return []
    record=event('Risk Management Institute of Australasia',
         'RMIA NSW Risk Management Networking Night',date,'5:00pm',
         SOURCES['rmia_sydney'][1],today=today,
         venue='The Sussex Hotel, Rooftop, 20 Sussex Street, Sydney',
         summary='Free networking with professionals in the NSW risk-management community, including adjacent banking and financial-risk careers.',
         eligibility='Free; primarily an industry networking event. Confirm student attendance with RMIA.',
         registration_url=url)
    if record:
        record['fit']='restricted'
        record['relevance_reason']='Verified public risk-management association event; student eligibility not explicitly guaranteed.'
        return [record]
    return []


def parse_step_sydney_emerging_network(html: str, today: dt.date) -> list[dict]:
    """Public early-career professional network, explicitly open to students."""
    soup=BeautifulSoup(html,'html.parser')
    title=soup.find('h2')
    visible=soup.get_text(' ',strip=True)
    if not title or not re.search(r'STEP NSW Emerging Professionals Network',title.get_text(' ',strip=True),re.I):
        return []
    if not (re.search(r'Wednesday 25 November 2026',visible,re.I)
            and re.search(r'\b17:30\s*[–-]\s*18:00\b',visible,re.I)
            and re.search(r'\b18:40\s*[–-]\s*21:00\b',visible,re.I)
            and re.search(r'open to all professional advisors, educators and students',visible,re.I)
            and re.search(r'Members\s*\$25\s*\|\s*Non-Members\s*\$30',visible,re.I)
            and re.search(r'\bJustFund\b',visible,re.I)):
        return []
    registration=''
    for a in soup.select('a[href]'):
        url=a['href'].strip()
        if trusted_host(url,{'events.humanitix.com'}) and 'step-nsw-emerging' in url:
            registration=url
            break
    if not registration:return []
    date=dt.date(2026,11,25)
    if date<today:return []
    record=event('STEP Australia','STEP NSW Emerging Professionals Networking',date,
         '5:30pm - 9:00pm',SOURCES['step_emerging'][1],today=today,
         venue='JustFund, Level 9, 85 Castlereagh Street, Sydney',
         summary='Networking for emerging accounting, financial advisory and private-wealth professionals, including students focused on trusts and estates.',
         eligibility='Open to students interested in trusts and estates; $25 STEP members / $30 non-members. Ticket sales close 19 Nov 2026.',
         registration_url=registration)
    if record:
        record['relevance_reason']='Professional association explicitly welcomes students with a trusts-and-estates focus; ticket costs are published.'
        return [record]
    return []


def parse_mymoney_expo(html: str, today: dt.date, fetch_detail=get) -> list[dict]:
    """Cross-check Sydney venue dates and organiser's free-ticket claim.

    Neither a two-day expo nor a year-only headline implies a clock time:
    store an explicit date-only listing and make the schedule caveat visible.
    """
    soup=BeautifulSoup(html,'html.parser')
    heading=next((h for h in soup.find_all(['h1','h2','h3']) if h.get_text(' ',strip=True)=='MyMoney Expo'),None)
    visible=soup.get_text(' ',strip=True)
    if not heading:
        return []
    if not (re.search(r'\bSATURDAY 28\s*[–-]\s*SUNDAY 29 NOVEMBER 2026\b',visible,re.I)
            and re.search(r'finance and investing|investors, finance professionals',visible,re.I)):
        return []
    official=None
    for a in soup.select('a[href]'):
        link=a.get('href','').strip()
        if trusted_host(link,{'mymoneyexpo.com'}):
            official='https://mymoneyexpo.com/'
            break
    if not official:return []
    try:
        page=fetch_detail(official)
    except (requests.RequestException,ValueError,RuntimeError):
        return []
    organiser=BeautifulSoup(page,'html.parser')
    copy_=organiser.get_text(' ',strip=True)
    if not (re.search(r'MyMoney Expo 2026',copy_,re.I)
            and re.search(r'\bFREE General Admission\b',copy_,re.I)
            and re.search(r'investing|trading|wealth',copy_,re.I)):
        return []
    registration=None
    for a in organiser.select('a[href]'):
        link=a['href'].strip()
        if trusted_host(link,{'tickets.lup.com.au'}):
            registration=link
            break
    if not registration:return []
    date=dt.date(2026,11,28)
    if date<today:return []
    record=event('MyMoney Expo','MyMoney Expo 2026 · Sydney',date,'',
         SOURCES['mymoney_expo'][1],today=today,
         venue='ICC Sydney, Darling Harbour',
         summary='28–29 November. Public investing and finance expo covering shares, trading, private wealth and fintech. Opening times to be checked.',
         eligibility='Free general admission advertised by organiser; confirm ticket conditions and daily opening times.',
         registration_url=registration,time_known=False)
    if record:
        record['sources']=['ICC Sydney venue','MyMoney Expo organiser']
        record['source_urls']=[SOURCES['mymoney_expo'][1],official]
        record['relevance_reason']='ICC Sydney confirms dates; organiser independently confirms free general admission and registration link.'
        return [record]
    return []


def parse_cfa_australia(html: str, today: dt.date) -> list[dict]:
    """Only relevant, future-dated NSW/online CFA Society sessions.

    Read the four-column official events table rather than a broad site-wide
    date search; exclude interstate events, private member-only sessions
    and unrelated generic software/CPD workshops. Non-member registration
    costs and professional eligibility are never inferred as student entry.
    """
    soup=BeautifulSoup(html,'html.parser')
    if not re.search(r'CFA Society Australia|Upcoming Events',soup.get_text(' ',strip=True),re.I):
        raise ValueError('CFA Society Australia calendar unavailable')
    result=[]
    relevant=re.compile(r'private equity|private markets?|blended capital|institutional|family offices|investment career|women in investment|valuation|equity research|portfolio management|capital markets|investor relations',re.I)
    for tr in soup.select('table tbody tr')[:55]:
        cells=tr.find_all('td',recursive=False)
        if len(cells)<4:continue
        first=cells[0]
        strong=first.find('strong')
        if not strong:continue
        name=strong.get_text(' ',strip=True)
        if len(name)<12 or not relevant.search(name):continue
        venue=cells[1].get_text(' ',strip=True)
        if not re.search(r'NSW Chapter|Sydney|Online|Webinar',name+' '+venue,re.I):continue
        if re.search(r'\b(?:Melbourne|Brisbane|Perth|Adelaide|Canberra|QLD|VIC|WA) chapter\b',name,re.I):
            continue
        # Explicit location must be Sydney or online; avoid interstate entries
        # simply because the title contains investment vocabulary.
        if not re.search(r'Sydney|Online|Zoom|Virtual',venue,re.I):
            continue
        date_cell=cells[2].get_text(' ',strip=True)
        date_match=DATE_MONTH_DAY.search(date_cell) or DATE_DAY_MONTH.search(date_cell)
        if not date_match or not date_match.group('year'):continue
        date=parse_date(date_match.group(0),today)
        if not date or date<today:continue
        button=cells[3].find('a',href=True)
        if not button:continue
        link=urljoin(SOURCES['cfa'][1],button.get('href',''))
        if not trusted_host(link,{'web.cvent.com','cfas.org.au'}):continue
        details=first.get_text(' ',strip=True)
        access=re.search(r'Open to:\s*(.{0,130}?)(?:Speaker\(s\)|Host:|$)',details,re.I)
        eligibility=('Professional event — check non-member registration fees and student eligibility. '
                     +('Listed audience: '+access.group(1).strip(' .;')+'.' if access else 'Confirm with organiser.'))
        date_time=date_cell[date_match.end():].strip()
        date_time=date_time[:120]
        rec=event('CFA Society Australia',name,date,date_time,SOURCES['cfa'][1],
                  today=today,venue=venue,summary=details[len(name):][:225],
                  eligibility=eligibility,registration_url=link)
        if not rec:continue
        rec['fit']='restricted' if not re.search(r'industry professionals',access.group(1) if access else '',re.I) else rec['fit']
        rec['relevance_reason']='Dated CFA Society Australia listing; non-member pricing and student eligibility must be checked with organiser.'
        result.append(rec)
    return unique(result)


def parse_finma_student_events(html: str, today: dt.date) -> list[dict]:
    """Verify a short-lived, free FINMA student lecture, not their past events.

    FINMA's public event listing omits a year; its 10 Nov 2026 date is
    corroborated by a dated public FINMA announcement. The one-off fallback
    expires automatically after 10 November, and no other year is inferred.
    """
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    if 'Financial Markets Academy' not in text and not re.search(r'FINMA|Open Lecture: Finance 101',text,re.I):
        raise ValueError('FINMA event index unavailable')
    if not (dt.date(2026,10,25)<=today<=dt.date(2026,11,10)):
        return []
    heading=next((h for h in soup.select('h1,h2,h3') if re.fullmatch(r'Open Lecture:\s*Finance 101',h.get_text(' ',strip=True),re.I)),None)
    if not heading:return []
    # Locate the event-specific section instead of the wider Wix page
    # containing several outdated information nights.
    parent=heading.find_parent('section')
    context=parent.get_text(' ',strip=True) if parent else ''
    if not context: return []
    if not re.search(r'\b10 November\b',context,re.I):return []
    if not re.search(r'5:00\s*(?:PM|pm)\s*[–-]\s*6:30\s*(?:PM|pm)',context,re.I):
        return []
    if not re.search(r'open to all students|university students',context,re.I):
        return []
    date=dt.date(2026,11,10)
    rec=event('FINMA', 'Open Lecture: Finance 101', date,'5:00 PM - 6:30 PM',
              SOURCES['finma'][1],today=today,
              venue='FINMA Office, Level 3, 13–15 Moran House, Sydney CBD',
              summary='Free introductory finance lecture for high school and university students.',
              eligibility='Free, open to university students; registration required with FINMA.',
              registration_url=SOURCES['finma'][1])
    if rec:
        rec['relevance_reason']='Official FINMA upcoming-event listing; date independently corroborated by FINMA public announcement. Registration is required; confirm availability.'
        return [rec]
    return []


def parse_mathsoc_quant(html: str, today: dt.date) -> list[dict]:
    """Only QuantSoc's FUTURE co-hosted events on MathSoc's official site.

    Ignore every h3 after the Past Events heading. An old Citadel or Jane
    Street listing must never become a newly discovered finance event.
    """
    soup=BeautifulSoup(html,'html.parser')
    heading=next((h for h in soup.select('h1,h2') if h.get_text(' ',strip=True).lower()=='upcoming events'),None)
    if heading is None:raise ValueError('MathSoc upcoming events section not found')
    result=[]
    for h in soup.select('h3'):
        prior=h.find_previous(['h1','h2'])
        if prior is None or prior is not heading:
            continue
        title=h.get_text(' ',strip=True)
        if not re.search(r'quantsoc|quantitative|citadel|jane street|trading',title,re.I):
            continue
        texts=[]
        for node in h.next_elements:
            if getattr(node,'name',None) in ('h1','h2','h3'):
                break
            if isinstance(node,str):
                if node.strip():texts.append(node.strip())
            if len(' '.join(texts))>450:break
        context=' '.join(texts)
        match=re.search(r'\b([0-3]?\d)/([01]?\d)/(20\d{2})\b',context)
        if not match:continue
        try:date=dt.date(int(match.group(3)),int(match.group(2)),int(match.group(1)))
        except ValueError:continue
        if date<today:continue
        clock_context=re.sub(r'\b(\d{1,2}:\d{2}):\d{2}\s*(am|pm)\b',r'\1 \2',context[match.end():match.end()+55],flags=re.I)
        clock=CLOCK_RX.search(clock_context)
        time_text=clock.group(0) if clock else ''
        rec=event('UNSW MathSoc × QuantSoc',title,date,time_text,SOURCES['mathsoc_quant'][1],
                  today=today,summary='Publicly listed MathSoc and QuantSoc collaborative event.',time_known=bool(time_text))
        if rec:result.append(rec)
    return unique(result)


def parse_society_coverage_page(html: str, key: str) -> None:
    """Validate archives/homepages without pretending private social posts exist."""
    soup=BeautifulSoup(html,'html.parser')
    txt=soup.get_text(' ',strip=True)
    if key=='quantsoc_site':
        if not re.search(r'QuantSoc|Quantitative Finance and Trading Society',txt,re.I):
            raise ValueError('QuantSoc official site unavailable')
    elif key=='finsoc_publications':
        if not re.search(r'FINSOC REVIEW|Weekly Wrap|Publications',txt,re.I):
            raise ValueError('FINSOC publication archive unavailable')
    else:
        raise ValueError('Unknown coverage-only source')


def parse_squarespace_society(html: str, key: str, today: dt.date) -> list[dict]:
    """Future event entries from the society's dated Squarespace events index.

    The visible <time> date must contain a year. Ignore archive marketing copy
    containing old future dates, and never import social-only undated events.
    """
    if key not in ('capitalw', 'accsoc'):
        raise ValueError('Unknown society calendar')
    source,url=SOURCES[key]
    soup=BeautifulSoup(html,'html.parser')
    if not re.search(r'Upcoming Events',soup.get_text(' ',strip=True),re.I):
        raise ValueError('Society events page heading missing')
    prefix='/events/' if key=='capitalw' else '/upcoming-events/'
    found=[]
    for card in soup.select('article'):
        # Ignore wrapping article elements around nested event articles.
        if card.find('article'):
            continue
        heading=card.find(['h1','h2','h3'])
        clock=card.find('time')
        if not heading or not clock:
            continue
        title=heading.get_text(' ',strip=True)
        date_text=clock.get_text(' ',strip=True)
        if not re.search(r'\b20\d{2}\b',date_text):
            continue
        date=parse_date(date_text,today)
        if not date or date<today:
            continue
        summary=card.get_text(' ',strip=True)
        if not CAREER_RX.search(title+' '+summary[:450]):
            continue
        link=next((urljoin(url,a['href']) for a in card.select('a[href]')
                   if urlsplit(urljoin(url,a['href'])).path.startswith(prefix)
                   and urlsplit(urljoin(url,a['href'])).path.rstrip('/')!=urlsplit(url).path.rstrip('/')),url)
        times=' '.join(n.get_text(' ',strip=True) for n in card.select('time')[1:3])
        rec=event(source,title,date,times,link,today=today,summary=summary[:220],time_known=bool(CLOCK_RX.search(times)))
        if rec:
            found.append(rec)
    return unique(found)


def parse_cma(html: str, today: dt.date) -> list[dict]:
    """Parse dated CMA event cards, never deriving dates from unrelated headings."""
    soup=BeautifulSoup(html,'html.parser')
    if not re.search(r'Capital Markets Association',soup.get_text(' ',strip=True),re.I):
        raise ValueError('CMA site unavailable')
    output=[]
    for heading in soup.select('h3'):
        title=heading.get_text(' ',strip=True)
        if not CAREER_RX.search(title):
            continue
        context=[]
        links=[]
        # Gather only material belonging to this heading, ending at next h3.
        for node in heading.next_elements:
            if getattr(node,'name',None)=='h3':
                break
            if getattr(node,'name',None)=='a':
                href=node.get('href','')
                if href.startswith('https://'):
                    links.append(href)
            if isinstance(node,str):
                context.append(node.strip())
            if len(' '.join(context))>800:
                break
        segment=' '.join(context)
        m=re.search(r'\b([0-3]?\d)/([01]?\d)/(20\d{2}|\d{2})\b',segment)
        if not m:
            continue
        year=int(m.group(3))
        if year<100:year+=2000
        try:
            day=dt.date(year,int(m.group(2)),int(m.group(1)))
        except ValueError:
            continue
        if day<today:
            continue
        time_match=CLOCK_RX.search(segment[m.end():m.end()+70])
        raw_time=time_match.group(0) if time_match else ''
        link=next((x for x in links if trusted_host(x,{'facebook.com','www.facebook.com','forms.gle','docs.google.com'})),SOURCES['cma'][1]+'#events')
        rec=event('UNSW CMA',title,day,raw_time,link,today=today,summary=segment[:220],time_known=bool(raw_time))
        if rec:
            output.append(rec)
    return unique(output)


def parse_bsoc_events(html: str, today: dt.date) -> list[dict]:
    """BSOC's current public event page consists of *recaps*, not registrations.

    Do not turn a recap into a future calendar record simply because its date
    is in the future. This source stays on the coverage monitor awaiting a
    separately labelled, official upcoming-event listing.
    """
    soup=BeautifulSoup(html,'html.parser')
    if 'Our Events' not in soup.get_text(' ',strip=True):
        raise ValueError('BSOC event page unavailable')
    return []


def parse_faic(html: str, today: dt.date) -> list[dict]:
    soup=BeautifulSoup(html,'html.parser')
    if not re.search(r'Fintech AI Innovation Consortium',soup.get_text(' ',strip=True),re.I):
        raise ValueError('UNSW FAIC heading missing')
    result=[]
    for heading in soup.select('h3'):
        name=heading.get_text(' ',strip=True)
        if not re.search(r'End of Year Event',name,re.I):
            continue
        # Use the dated event-details block, not a year mentioned in a
        # programme description or a separate announcement on the same page.
        details=soup.find(['h3','h2'],string=re.compile(r'Event details',re.I))
        if not details:
            continue
        context=details.parent.get_text(' ',strip=True)
        if not DATE_DAY_MONTH.search(context):
            # UNSW's details list may be a sibling of the heading.
            context=' '.join(x.get_text(' ',strip=True) for x in list(details.next_elements)
                             if getattr(x,'name',None) in ('li','p'))[:1100]
        m=DATE_DAY_MONTH.search(context)
        if not m or not m.group('year'):
            continue
        date=parse_date(m.group(0),today)
        if not date or date<today:
            continue
        title_year=re.search(r'\b20\d{2}\b',name)
        if title_year and int(title_year.group(0))!=date.year:
            continue
        link=next((a['href'] for a in soup.select('a[href]')
                   if trusted_host(a['href'],{'luma.com'})),SOURCES['faic'][1])
        period=RANGE_RX.search(context)
        time_text=period.group(0) if period else ''
        rec=event('UNSW FAIC',name,date,time_text,SOURCES['faic'][1],today=today,
                  venue='UNSW Ainsworth Building J17, Room 102',
                  summary='Fintech and AI research showcase with industry partners and networking.',
                  registration_url=link,time_known=bool(period))
        if rec:
            rec['source_urls']=[SOURCES['faic'][1]]
            result.append(rec)
    return unique(result)



def parse_public_form_registration(html: str, title: str, url: str, organiser: str,
                                   today: dt.date) -> list[dict]:
    """Verify an explicitly dated public Google Form linked by an official bio.

    Does not load Google accounts or interpret form submission fields as
    invitations. A title or event year alone is never enough. Explicit
    date AND time near an 'Event date' label are required.
    """
    try:
        u=urlsplit(url)
    except ValueError:
        return []
    if not trusted_host(url, {'docs.google.com'}):
        return []
    if not re.fullmatch(r'/forms/d/e/1FAIpQL[A-Za-z0-9_-]{25,}/viewform/?',u.path):
        return []
    soup=BeautifulSoup(html,'html.parser')
    visible=soup.get_text(' ',strip=True)[:6000]
    if not visible or re.search(r'(?:sign in to continue|you need permission|this form is no longer accepting responses|form is closed)',visible,re.I):
        return []
    # The form itself must refer to the society event advertised by its bio.
    description=soup.find('meta',attrs={'property':'og:title'})
    public_title=description.get('content','').strip() if description else ''
    start=visible[:1500]
    if not public_title:
        public_title=start[:220]
    if not (HUB_KEYWORDS.search(title) and
            re.search(r'FINSOC|FinTechSoc|Finance|Trading|QuantSoc|Modelling|Workshop|Career|Investment',
                      public_title,re.I)):
        return []
    # 'Date of birth' fields and event titles containing only '2026' are
    # insufficient. Date and clock must be on the explicitly labelled line.
    date_tag=re.search(r'(?:Event\s+Date|Workshop\s+Date|When)\s*[:\-]\s*'
                       r'(.{0,100}?\b20\d{2}\b)',start,re.I)
    if not date_tag:
        return []
    match=DATE_DAY_MONTH.search(date_tag.group(1)) or DATE_MONTH_DAY.search(date_tag.group(1))
    if not match or not match.group('year'):
        return []
    day=parse_date(match.group(0),today)
    if not day or day<today:
        return []
    context=start[date_tag.end():date_tag.end()+240]
    time_match=re.search(r'\b(?:Time|Start\s+time)\s*[:\-]\s*(.{0,85})',context,re.I)
    if not time_match or not CLOCK_RX.search(time_match.group(1)):
        return []
    rec=event(organiser,title,day,time_match.group(1),SOURCES[next(k for k,v in BIO_SOCIAL_NAMES.items()
              if v==organiser)][1],today=today,venue='See organiser',
              summary='Public registration form linked from the organiser official bio.',
              eligibility='Check membership, registration availability and event details with organiser.',
              registration_url=url,time_known=True)
    if not rec or len(rec['starts_at'])==10:
        return []
    rec['source_urls']=[SOURCES[next(k for k,v in BIO_SOCIAL_NAMES.items()
              if v==organiser)][1],url]
    rec['sources']=[organiser,'Public form with explicit event date and time']
    rec['relevance_reason']='Public date and time verified in a registration form linked from the society official bio.'
    return [rec]


def parse_finsoc_humanitix(html: str, today: dt.date, fetch_detail=get) -> list[dict]:
    """Monitor FINSOC's official public Humanitix host for upcoming events.

    A host landing page cannot prove event eligibility or dates. Only linked
    future Event schema with on-page FINSOC host attribution qualifies.
    """
    soup=BeautifulSoup(html,'html.parser')
    visible=soup.get_text(' ',strip=True)
    if not re.search(r'UNSW Finance and Banking Society',visible,re.I):
        raise ValueError('FINSOC Humanitix official host unavailable')
    if re.search(r'\bThere are no live events\b',visible,re.I):
        return []
    host=SOURCES['finsoc_humanitix'][1]
    discovered=[]
    for a in soup.select('a[href]'):
        url=urljoin(host,a['href'])
        if not trusted_host(url,{'events.humanitix.com'}):
            continue
        path=urlsplit(url).path.rstrip('/')
        if path.startswith('/host/') or path in ('','/'):
            continue
        if not re.fullmatch(r'/[a-z0-9][a-z0-9-]{5,120}',path,re.I):
            continue
        if url not in discovered:
            discovered.append(url)
    results=[]
    for url in discovered[:8]:
        try:
            raw=fetch_detail(url)
            detail=BeautifulSoup(raw,'html.parser')
            if not re.search(r'UNSW Finance and Banking Society|FINSOC',
                             detail.get_text(' ',strip=True),re.I):
                continue
            records=jsonld_events(raw,'FINSOC',url,today)
            for rec in records:
                rec['organiser']='FINSOC'
                rec['registration_url']=url
                rec['sources']=['FINSOC Humanitix host','Dated official registration']
                rec['source_urls']=[host,url]
                rec['relevance_reason']='Verified future registration with FINSOC attribution on its public Humanitix host.'
            results.extend(records)
        except (requests.RequestException,ValueError,RuntimeError):
            continue
    return unique(results)


def parse_social_hub(html: str, source_key: str, today: dt.date, fetch_detail=get) -> tuple[list[dict],list[dict]]:
    """Inspect the society's public bio links, not its social-media posts.

    Only dated, verifiable Schema.org event details become calendar events.
    Other relevant links are *undated signals*, explicitly excluded from alerts.
    """
    if source_key not in BIO_SOCIAL_NAMES: raise ValueError('Unknown approved bio source')
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    # Linktree's rendered HTML may change. Don't claim a successful scan on a login page.
    if not text or ('linktree' not in text.lower() and not soup.find('a',href=True)):
        raise ValueError('Public society bio links not exposed')
    main=soup.find('main') or soup.find(id='__next') or soup
    candidates=[]; seen=set()
    for a in main.select('a[href]'):
        link=unwrap_public_registration_url(urljoin(SOURCES[source_key][1],a.get('href','')))
        if link.split('?')[0].rstrip('/') in COMPLETED_SOCIAL_REGISTRATIONS:
            continue
        title=re.sub(r'\s+', ' ', a.get_text(' ',strip=True)).strip()[:160]
        if not title or len(title)<7 or len(title)>160 or HUB_EXCLUDE.search(title):continue
        # Do not repeatedly advertise an explicitly labelled prior-year link.
        years=[int(v) for v in re.findall(r'\b20\d{2}\b',title)]
        if years and max(years)<today.year:continue
        if not HUB_KEYWORDS.search(title):continue
        if not trusted_host(link,LINK_EVENT_HOSTS|LINK_FORM_HOSTS):continue
        norm=link.split('?')[0].rstrip('/').lower()
        if norm in seen:continue
        seen.add(norm);candidates.append((title,link))
    results=[]; signals=[]
    # Bounds prevent Linktree pages from inducing unbounded external requests.
    for title,link in candidates[:10]:
        host=(urlsplit(link).hostname or '').lower()
        confirmed=[]
        expired=False
        note='Public bio link only; date, availability and eligibility not confirmed.'
        if trusted_host(link, LINK_EVENT_HOSTS | {'form.jotform.com'}) or (
                trusted_host(link, {'docs.google.com'}) and
                re.fullmatch(r'/forms/d/e/1FAIpQL[A-Za-z0-9_-]{25,}/viewform/?',urlsplit(link).path)):
            try:
                content=fetch_detail(link)
                expired=registration_is_past(content,link,today)
                if not expired and trusted_host(link,LINK_EVENT_HOSTS):
                    confirmed=jsonld_events(content,BIO_SOCIAL_NAMES[source_key],link,today)
                elif not expired and trusted_host(link,{'docs.google.com'}):
                    confirmed=parse_public_form_registration(
                        content,title,link,BIO_SOCIAL_NAMES[source_key],today)
                    if not confirmed:
                        note='Public Google Form accessible but the event date and time are not confirmed.'
            except (requests.RequestException,ValueError,RuntimeError):
                note='Public registration unavailable without access; do not assume event details.'
                pass
        if expired:
            continue
        for record in confirmed:
            # A random event link should not become a finance event just because
            # it appeared in a society's bio. jsonld_events performs this check.
            record['source_urls']=[SOURCES[source_key][1],link]
            record['sources']=[BIO_SOCIAL_NAMES[source_key], 'Dated registration page']
            record['organiser']=BIO_SOCIAL_NAMES[source_key]
            record['registration_url']=link
            record['relevance_reason']='Dated registration linked from the organiser public bio; review details at destination.'
            results.append(record)
        if confirmed:continue
        # No verified future date: the separate 'link to review' feed is NOT an event.
        sid=hashlib.sha1((source_key+'|'+link.split('?')[0]).encode()).hexdigest()[:12]
        signals.append({'id':'signal-'+sid,'title':title,'organiser':BIO_SOCIAL_NAMES[source_key],
                        'url':link,'source_url':SOURCES[source_key][1],
                        'status':'date_unverified','note':note,
                        'checked_on':today.isoformat()})
    return unique(results),signals


def similar(a:dict,b:dict) -> bool:
    if a['starts_at'][:10]!=b['starts_at'][:10]:return False
    # Official event detail and Schema.org versions may use different titles.
    # This is deliberately scoped to named, dated events—not two separate
    # sessions appearing on the same organiser calendar.
    left=str(a.get('title','')).lower()
    right=str(b.get('title','')).lower()
    if a['starts_at'][:10]=='2026-11-11' and all('rmia nsw' in x and 'networking' in x for x in (left,right)):
        return True
    if a['starts_at'][:10]=='2026-11-25' and all('step nsw emerging professionals' in x for x in (left,right)):
        return True
    if a.get('registration_url') and a['registration_url']==b.get('registration_url'):
        link=urlsplit(a['registration_url'])
        # A generic event-index URL is not a unique registration identity.
        if link.netloc.endswith(('eventbrite.com.au','humanitix.com','forms.gle')) or '/event/' in link.path or '/e/' in link.path:
            return True
    aa=re.sub(r'[^a-z\d]+',' ',a['title'].lower()).strip()
    bb=re.sub(r'[^a-z\d]+',' ',b['title'].lower()).strip()
    if 'mckinsey' in aa+bb and 'path to progress' in aa and 'path to progress' in bb:return True
    return SequenceMatcher(None,aa,bb).ratio()>.77


def unique(items:list[dict]) -> list[dict]:
    out=[]
    for event_ in sorted(items,key=lambda x:x['starts_at']):
        prev=next((x for x in out if similar(x,event_)),None)
        if not prev:
            out.append(copy.deepcopy(event_));continue
        for src,url in zip(event_.get('sources',[]),event_.get('source_urls',[])):
            if url not in prev['source_urls']:
                prev['sources'].append(src);prev['source_urls'].append(url)
        if event_.get('fit')=='restricted':
            prev['fit']='restricted';prev['eligibility']=event_['eligibility']
        if event_.get('collection_status')=='current':
            prev['last_seen_on']=event_.get('last_seen_on',prev.get('last_seen_on'))
            prev['collection_status']='current'
            prev['verified_on']=event_.get('verified_on',prev.get('verified_on'))
    return out


def collect(*,today: dt.date|None=None,fetcher=get,source_keys: list[str]|None=None,folder: Path=DATA) -> tuple[dict,dict]:
    today=today or dt.datetime.now(TIMEZONE).date()
    old_path=folder/'feed.json'
    seed_path=folder/'snapshot.json'
    baseline=json.loads((old_path if old_path.exists() else seed_path).read_text())
    previous=baseline.get('events',[])
    fresh=[];health={};social_signals=[]
    keys=source_keys or list(SOURCES)
    for key in keys:
        name,url=SOURCES[key]
        try:
            raw=fetcher(url)
            if key in ('bsoc_publications','unit_publications'):
                signals=parse_newsletter_mentions(raw,key,today,fetch_detail=fetcher)
                social_signals.extend(signals)
                health[key]={'status':'links_only' if signals else 'accessible_empty',
                             'count':0,'signals':len(signals),
                             'checked_at':dt.datetime.now(TIMEZONE).isoformat(timespec='seconds'),'url':url}
                print(f'{name}: {health[key]["status"]} ({len(signals)} recent publication leads)')
                continue
            if key in ('quantsoc_site','finsoc_publications'):
                parse_society_coverage_page(raw,key)
                status='social_only' if key=='quantsoc_site' else 'publications_only'
                health[key]={'status':status,'count':0,
                             'checked_at':dt.datetime.now(TIMEZONE).isoformat(timespec='seconds'),'url':url,
                             'note':'Official page accessible; it does not expose a dated upcoming-event feed.'}
                print(f'{name}: {status} (no dated future events exposed)')
                continue
            if key in BIO_SOCIAL_NAMES:
                found,signals=parse_social_hub(raw,key,today,fetch_detail=fetcher)
                social_signals.extend(signals)
                health[key]={'status':'ok' if found else ('links_only' if signals else 'accessible_empty'),
                             'count':len(found),'signals':len(signals),
                             'checked_at':dt.datetime.now(TIMEZONE).isoformat(timespec='seconds'),'url':url}
                fresh.extend(found)
                print(f'{name}: {health[key]["status"]} ({len(found)} confirmed, {len(signals)} undated links)')
                continue
            structured=jsonld_events(raw,name,url,today)
            try:
                if key=='unit': found=parse_unit_home(raw,today)
                elif key=='unit_calendar': found=parse_unit_calendar(raw,today)
                elif key=='fmaa': found=parse_fmaa(raw,today,fetch_detail=fetcher)
                elif key=='finsoc':found=parse_finsoc(raw,today)
                elif key in ('capitalw','accsoc'):found=parse_squarespace_society(raw,key,today)
                elif key=='cma':found=parse_cma(raw,today)
                elif key=='bsoc_calendar':found=parse_bsoc_events(raw,today)
                elif key=='faic':found=parse_faic(raw,today)
                elif key=='mathsoc_quant':found=parse_mathsoc_quant(raw,today)
                elif key=='cfa':found=parse_cfa_australia(raw,today)
                elif key=='finma':found=parse_finma_student_events(raw,today)
                elif key=='cafba_sydney':found=parse_cafba_sydney_networking(raw,today)
                elif key=='rmia_sydney':found=parse_rmia_sydney_networking(raw,today)
                elif key=='step_emerging':found=parse_step_sydney_emerging_network(raw,today)
                elif key=='mymoney_expo':found=parse_mymoney_expo(raw,today,fetch_detail=fetcher)
                elif key=='unsw_public_events':found=parse_unsw_public_events(raw,today,fetch_detail=fetcher)
                elif key=='unsw_accounting_lecture':found=parse_unsw_accounting_lecture(raw,today)
                elif key=='finsoc_humanitix':found=parse_finsoc_humanitix(raw,today,fetch_detail=fetcher)
                elif key=='unsw':found=parse_unsw_with_registration_fallback(raw,today,fetch_detail=fetcher)
                else:found=parse_unsw(raw,today)
            except Exception:
                if not structured:raise
                found=[] # Valid Schema.org events are evidence even if card markup changed.
            found=unique(found+structured)
            found=[enrich_official_industry_listing(rec,key) for rec in found]
            health[key]={'status':'ok' if found else 'accessible_empty','count':len(found), 'checked_at':dt.datetime.now(TIMEZONE).isoformat(timespec='seconds'), 'url':url}
            fresh.extend(found)
        except Exception as exc:
            health[key]={'status':'error','count':0,'checked_at':dt.datetime.now(TIMEZONE).isoformat(timespec='seconds'), 'url':url, 'detail':str(exc)[:260]}
        print(f'{name}: {health[key]["status"]} ({health[key]["count"]} future events)')
    # Previous records without fresh confirmation are marked last-known. Keep for
    # at most 7 days after previous sighting; never email them as new discoveries.
    recently=[]
    for old in previous:
        if not old.get('starts_at') or old['starts_at'][:10]<today.isoformat():continue
        age=dt.date.fromisoformat(old.get('last_seen_on') or old.get('verified_on') or '2000-01-01')
        if (today-age).days>7:continue
        copy_old=copy.deepcopy(old)
        copy_old['collection_status']='last_known'
        recently.append(copy_old)
    # Preserve stable IDs when a previously saved listing gains better sources.
    for record in fresh:
        matches=[old for old in previous if similar(old,record)]
        if len(matches)==1 and matches[0].get('id'):
            record['id']=matches[0]['id']
    records=unique(fresh+recently)
    # Preserve the first discovery time across scheduled rechecks.
    historical={e.get('id'):e for e in previous}
    seen_clock=dt.datetime.now(TIMEZONE).isoformat(timespec='seconds')
    for rec in records:
        past=historical.get(rec.get('id'),{})
        first=past.get('first_seen_at') or rec.get('first_seen_at')
        if not first and past.get('verified_on'):
            try:
                day=dt.date.fromisoformat(past['verified_on'][:10])
                first=dt.datetime.combine(day,dt.time.min,TIMEZONE).isoformat(timespec='seconds')
            except ValueError:
                pass
        rec['first_seen_at']=first or seen_clock
    # Explicitly exclude the legacy seed from "new" notifications.
    previous_keys={e.get('id') for e in previous}
    newly=[e['id'] for e in records if old_path.exists() and e['id'] not in previous_keys and e.get('collection_status')=='current']
    sources=copy.deepcopy(baseline.get('sources',[]))
    by_id={s['id']:s for s in sources}
    if 'unit_calendar' not in by_id:
        sources.append({'id':'unit_calendar','name':'UNIT events archive','url':SOURCES['unit_calendar'][1],'method':'Public events calendar','coverage':'public','note':'A dated archive; historical events are never treated as upcoming.'})
    for key in BIO_SOCIAL_NAMES:
        if key not in by_id:
            sources.append({'id':key,'name':BIO_SOCIAL_NAMES[key]+' · social bio',
                'url':SOURCES[key][1],'method':'Public link-in-bio monitoring',
                'coverage':'limited','note':'Only public registration links are readable. No Facebook/Instagram posts, stories or private-group access.'})

    for key in ('bsoc_publications','unit_publications'):
        if key not in by_id:
            sources.append({'id':key,'name':SOURCES[key][0], 'url':SOURCES[key][1],
                            'method':'Public newsletters / articles', 'coverage':'limited',
                            'note':'Publication mentions are review-only leads, not verified calendar events.'})
    for key in ('capitalw','cma','accsoc','bsoc_calendar','faic'):
        if key not in by_id:
            sources.append({'id':key,'name':SOURCES[key][0],'url':SOURCES[key][1],
                'method':'Official public events page','coverage':'public' if key!='bsoc_calendar' else 'limited',
                'note':'Date-backed career events only; old recaps and unrelated social listings are excluded.'})
    for key in ('mathsoc_quant','quantsoc_site','finsoc_publications'):
        if key not in by_id:
            notes={
                'mathsoc_quant':'Only dated future QuantSoc collaborations; past trading competitions are ignored.',
                'quantsoc_site':'QuantSoc directs students to Discord/Facebook; this site has no publicly dated event feed.',
                'finsoc_publications':'Public FINSOC Weekly Wrap archives are published; these are not upcoming event listings.'
            }
            sources.append({'id':key,'name':SOURCES[key][0],'url':SOURCES[key][1],
                'method':'Official public website / cross-society listing',
                'coverage':'limited' if key!='mathsoc_quant' else 'public','note':notes[key]})
    for key in ('finsoc_humanitix',):
        if key not in by_id:
            sources.append({'id':key,'name':SOURCES[key][0],'url':SOURCES[key][1],
                'method':'Public Humanitix organiser host','coverage':'limited',
                'note':'Only official upcoming ticket pages with explicit dated event schema and FINSOC attribution; does not access private events.'})
    for key in ('unsw_public_events','unsw_accounting_lecture'):
        if key not in by_id:
            sources.append({'id':key,'name':SOURCES[key][0],'url':SOURCES[key][1],
                'method':'Official dated UNSW event listings','coverage':'public',
                'note':'UNSW public calendar scans only investment/finance-themed event pages with verified dates and registration links; professional lecture may have eligibility or cost restrictions.'})
    for key in ('cafba_sydney','rmia_sydney','step_emerging','mymoney_expo'):
        if key not in by_id:
            sources.append({'id':key,'name':SOURCES[key][0],'url':SOURCES[key][1],
                'method':'Official Sydney finance events listing','coverage':'public',
                'note':'Eligibility, ticket price, registration availability and dates remain controlled by organiser. Only individually verified public records are published.'})
    for key in ('cfa','finma'):
        if key not in by_id:
            sources.append({'id':key,'name':SOURCES[key][0],'url':SOURCES[key][1],
                'method':'Official dated event calendar','coverage':'public',
                'note':('Sydney and online investment sessions only; some events charge non-member fees or restrict attendance.' if key=='cfa' else
                        'Open student events are confirmed on the organiser site; registration availability is not guaranteed.')})
    for source in sources:
        if source['id'] in health:source['last_check']=health[source['id']]
    generated=dt.datetime.now(TIMEZONE).isoformat(timespec='seconds')
    payload={'schema':3,'generated_at':generated,'mode':'scheduled_sync',
             'notice':'Public event listings and society bio links only; Instagram and Facebook post feeds are not connected.',
             'sources':sources,'events':records,'signals':social_signals[:16]}
    report={'generated_at':generated,'sources':health,'event_count':len(records),
            'unverified_bio_links':len(social_signals),'new_event_ids':newly,
            'current_event_count':sum(e.get('collection_status')=='current' for e in records),
            'last_known_event_count':sum(e.get('collection_status')=='last_known' for e in records)}
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'feed.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n')
    (folder/'live.js').write_text('// Generated automatically: review organiser links before registering.\nwindow.RADAR_SYNC = '+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+';\n')
    (folder/'health.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    (folder/'new_events.json').write_text(json.dumps(newly,indent=2)+'\n')
    (folder/'signals.json').write_text(json.dumps(social_signals[:16],indent=2,ensure_ascii=False)+'\n')
    (folder/'events.ics').write_text(calendar_ics(records,today),encoding='utf-8',newline='')
    (folder/'events.xml').write_text(events_rss(records,today),encoding='utf-8')
    return payload,report


def main():
    args=argparse.ArgumentParser()
    args.add_argument('--date',help='simulate a local date; tests only')
    a=args.parse_args()
    today=dt.date.fromisoformat(a.date) if a.date else None
    _,report=collect(today=today)
    # A total source outage is a failing CI run; no need to fail merely because
    # the sources have no future events.
    return 2 if all(v['status']=='error' for v in report['sources'].values()) else 0


if __name__=='__main__':sys.exit(main())
