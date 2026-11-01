"""Test the actual browser calendar exporter with Node."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest

SITE=(Path(__file__).resolve().parents[1]/'index.html').read_text()
NODE=shutil.which('node')
pytestmark=pytest.mark.skipif(not NODE,reason='Node unavailable')

def exported_ics(event):
    logic='function escapeICS('+SITE.split('function escapeICS(',1)[1].split('function renderCalendar(',1)[0]
    setup="""
const events=__EVENTS__;
let data='',alert='';
function notify(s){alert=s;}
class BlobMock{constructor(parts){data=parts.join('');}}
const Blob=BlobMock;
const URL={createObjectURL:()=> 'blob:mock',revokeObjectURL:()=>{}};
const document={body:{appendChild:()=>{}},createElement:()=>({href:'',download:'',click:()=>{},remove:()=>{}})};
function setTimeout(){}
""".replace('__EVENTS__',json.dumps([event]))
    script=setup+logic+'\naddICS('+json.dumps(event['id'])+');console.log(JSON.stringify({data,alert}));'
    result=subprocess.run([NODE,'-e',script],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)

def example(**updates):
    rec={'id':'example-1','title':'Careers: banking, markets & finance','starts_at':'2026-11-05T18:00:00+11:00',
       'ends_at':'2026-11-05T20:00:00+11:00','registration_url':'https://www.unit.org.au/events',
       'source_urls':['https://www.unit.org.au/events'],'subtitle':'Campus finance careers',
       'location':'Sydney CBD','collection_status':'current'}
    rec.update(updates)
    return rec

def test_timed_export_has_exact_start_and_end():
    result=exported_ics(example())['data']
    assert 'DTSTART:20261105T070000Z' in result
    assert 'DTEND:20261105T090000Z' in result
    assert result.startswith('BEGIN:VCALENDAR\r\n')
    assert result.endswith('END:VCALENDAR\r\n')

def test_no_end_does_not_invent_an_hour():
    result=exported_ics(example(ends_at=None))['data']
    assert 'DTSTART:20261105T070000Z' in result
    assert 'DTEND:' not in result

def test_date_only_uses_all_day_placeholder():
    result=exported_ics(example(starts_at='2027-06-15',ends_at=None))
    assert 'DTSTART;VALUE=DATE:20270615' in result['data']
    assert 'DTEND;VALUE=DATE:20270616' in result['data']
    assert 'confirm event time' in result['alert']

def test_unconfirmed_cannot_be_exported():
    result=exported_ics(example(collection_status='last_known'))
    assert result['data']==''
    assert 'not confirmed' in result['alert'].lower()

def test_multibyte_line_folding_and_special_characters():
    data=exported_ics(example(title=('Markets, trading; 🌏 and university partners ')*4))['data']
    assert r'\,' in data and r'\;' in data
    assert all(len(line.encode('utf-8'))<=75 for line in data.split('\r\n') if line)

def test_dst_conversion_uses_actual_offset():
    result=exported_ics(example(starts_at='2027-06-15T18:00:00+10:00',ends_at='2027-06-15T19:30:00+10:00'))['data']
    assert 'DTSTART:20270615T080000Z' in result
    assert 'DTEND:20270615T093000Z' in result
