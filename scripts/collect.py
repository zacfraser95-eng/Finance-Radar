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
}
MONTHS = ('January February March April May June July August September October November December').split()
MONTH_RX = '|'.join(MONTHS+[m[:3] for m in MONTHS])
DATE_DAY_MONTH = re.compile(rf'\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{MONTH_RX})\b(?:,?\s+(?P<year>20\d{{2}}))?', re.I)
DATE_MONTH_DAY = re.compile(rf'\b(?P<month>{MONTH_RX})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>20\d{{2}})\b', re.I)
RANGE_RX = re.compile(r'\b(?P<start>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|–|—|to)\s*(?P<end>\d{1,2}(?::\d{2})?\s*(?:am|pm))\b',re.I)
CLOCK_RX = re.compile(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b', re.I)
ELIGIBILITY_RX = re.compile(r'penultimate[\s-]*year|final[\s-]*year\s+(?:undergrad|students)|postgraduate\s+only|master.s\s+students\s+only',re.I)
CAREER_RX = re.compile(r'finance|bank|capital|trading|asset management|markets?|invest|portfolio|equity|recruit|intern|network|linkedin|job search|interview|consult|mckinsey|bain|careers?|corporate strategy|accounting',re.I)


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
    elif re.search(r'finance|invest|bank|strategy',t): category='Finance & strategy'
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
        if trusted_host(link,LINK_EVENT_HOSTS):
            try:
                content=fetch_detail(link)
                confirmed=jsonld_events(content,BIO_SOCIAL_NAMES[source_key],link,today)
            except (requests.RequestException,ValueError,RuntimeError):pass
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
                        'status':'date_unverified','note':'Public bio link only; date, availability and eligibility not confirmed.',
                        'checked_on':today.isoformat()})
    return unique(results),signals


def similar(a:dict,b:dict) -> bool:
    if a['starts_at'][:10]!=b['starts_at'][:10]:return False
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
                else:found=parse_unsw(raw,today)
            except Exception:
                if not structured:raise
                found=[] # Valid Schema.org events are evidence even if card markup changed.
            found=unique(found+structured)
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
    records=unique(fresh+recently)
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
