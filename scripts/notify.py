#!/usr/bin/env python3
"""Send opt-in email ONLY for truly new events on subsequent scheduled scans.

Configured via GitHub Actions secrets. Never send the initial import, or an
unconfirmed/previously-reviewed event. Persist notified ids after success.
"""
import html, json, os, hashlib
from pathlib import Path
import requests

DATA=Path(__file__).resolve().parents[1]/'data'

def notify(post=requests.post):
    api=os.getenv('RESEND_API_KEY','')
    recipient=os.getenv('RADAR_RECIPIENT_EMAIL','')
    sender=os.getenv('RADAR_FROM_EMAIL','')
    if not all((api,recipient,sender)):
        print('Email alerts disabled (no confirmed sender/recipient/API credentials).')
        return 0
    new_ids=set(json.loads((DATA/'new_events.json').read_text()))
    if not new_ids:
        print('No new event IDs; no email.')
        return 0
    sent_file=DATA/'notified.json'
    sent=set(json.loads(sent_file.read_text())) if sent_file.exists() else set()
    events=json.loads((DATA/'feed.json').read_text())['events']
    matched=[e for e in events if e['id'] in new_ids and e['id'] not in sent and e.get('fit')!='restricted' and e.get('collection_status')=='current' and e.get('confidence')=='source-backed']
    if not matched:return 0
    digest=matched[:20]
    blocks=[]
    for e in digest:
        label=html.escape(e['title']);date=html.escape(e['starts_at'][:10]);source=html.escape(e['organiser']);link=html.escape(e['source_urls'][0],quote=True)
        blocks.append(f'<div style="padding:14px 0;border-bottom:1px solid #dae0ea"><strong>{label}</strong><br>{date} · {source}<br><a href="{link}">View original organiser listing</a></div>')
    body='<h2>Finance Radar · new opportunities</h2><p>Automatically discovered public listings; confirm registration and eligibility with each organiser.</p>'+''.join(blocks)+'<p style="font-size:12px;color:#777">Personal alerts. To disable, remove the recipient address from the repository secret or disable the workflow.</p>'
    key=hashlib.sha256((recipient+'|'+','.join(sorted(e['id'] for e in digest))).encode()).hexdigest()
    response=post('https://api.resend.com/emails',headers={'Authorization':'Bearer '+api,'Content-Type':'application/json','Idempotency-Key':'radar-'+key[:32]},json={'from':sender,'to':[recipient],'subject':f'Finance Radar: {len(digest)} newly detected events','html':body},timeout=22)
    response.raise_for_status()
    sent.update(e['id'] for e in digest)
    sent_file.write_text(json.dumps(sorted(sent),indent=2)+'\n')
    print(f'Email delivered for {len(digest)} newly discovered events.')
    return len(digest)

if __name__=='__main__':notify()
