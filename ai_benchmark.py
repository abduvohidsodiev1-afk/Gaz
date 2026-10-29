"""Real local Ollama evaluation. Does not access Telegram or the bot database."""
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time
import urllib.error
import urllib.request
from datetime import date
from ai_cases import DATA

PROMPT = '''You extract structured facts from Uzbek Latin/Cyrillic Telegram propane station conversations.
Analyze the LAST message using earlier messages as context. Return only JSON matching the supplied schema.
Use only station IDs in stations. IBR is station 19, never station 6. Bridge 8 and 9 are distinct from numbered catalog IDs.
Typos such as qnaqa mean qanaqa; qancha/kancha/qanaqa/qanday/aytvorila without ? can be questions.
A price report can be just a known station name plus number, no currency label.
A question mentioning a price is not a factual report. Set price_uzs=null for questions.
A bare numeric reply or mention can report a price ONLY if it unambiguously answers one station question.
If one person asks about two stations and is tagged with a bare number, do not guess.
Sergeli has two separate stations; unqualified Sassu/Sassiq bridge names mean bridge8; explicitly after the bridge means bridge9.
Do not treat phone numbers, car models or unrelated questions as prices.
Unknown stations and unbound numbers require review. An explicitly old price requires review.
For greetings/unrelated text use other. For a phone-only statement at a known station use other with its station_id.
Set needs_review=false when all relevant information is unambiguous; true for unknown/ambiguous claims or station questions.
Return reply_to as the target question ID only for an actual answer; otherwise null.
Set observed_date only if explicitly stated, otherwise null. Never invent a date or price.
'''
FIELDS = ('intent','station_id','price_uzs','status','needs_review','reply_to','observed_date')
INTENTS = ['price_question','status_question','price_report','status_report','master_report','other','uncertain']
BASE = 'http://127.0.0.1:11434'
MODEL = 'qwen2.5:3b'


def schema():
    return {'type':'object','additionalProperties':False,'required':list(FIELDS),'properties':{
        'intent':{'type':'string','enum':INTENTS},'station_id':{'enum':[None]+[s['id'] for s in DATA['stations']]},
        'price_uzs':{'type':['integer','null'],'minimum':500,'maximum':100000},
        'status':{'enum':[None,'open','closed']},'needs_review':{'type':'boolean'},
        'reply_to':{'type':['integer','null']},'observed_date':{'type':['string','null']}}}


def validate(value):
    if not isinstance(value,dict) or set(value)!=set(FIELDS):
        raise ValueError('Invalid fields')
    if value['intent'] not in INTENTS or value['station_id'] not in [None]+[s['id'] for s in DATA['stations']]:
        raise ValueError('Invalid station/intent')
    if value['price_uzs'] is not None and (type(value['price_uzs']) is not int or not 500<=value['price_uzs']<=100000):
        raise ValueError('Invalid price')
    if value['status'] not in (None,'open','closed') or type(value['needs_review']) is not bool:
        raise ValueError('Invalid status/review')
    if value['reply_to'] is not None and type(value['reply_to']) is not int:
        raise ValueError('Invalid reply ID')
    if value['observed_date'] is not None:
        date.fromisoformat(value['observed_date'])
    return value


def request(path, data=None):
    # Only the local model receives these synthetic/public test examples.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    payload=None if data is None else json.dumps(data).encode('utf-8')
    req=urllib.request.Request(BASE+path,data=payload,headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=180) as response:
        return json.load(response)


def model_payload(case):
    return {'model':MODEL,'stream':False,'format':schema(),
            'messages':[{'role':'system','content':PROMPT},
                        {'role':'user','content':json.dumps({'stations':DATA['stations'],'messages':case['messages']},ensure_ascii=False)}],
            'options':{'temperature':0,'num_ctx':4096,'num_predict':256,'num_thread':4}}


def judge(actual,expected):
    unsafe = (actual['price_uzs'] is not None and
              (actual['price_uzs']!=expected['price_uzs'] or actual['station_id']!=expected['station_id']))
    unsafe = unsafe or (actual['status'] is not None and
                       (actual['status']!=expected['status'] or actual['station_id']!=expected['station_id']))
    return {'passed':actual==expected,'unsafe':bool(unsafe),
            'different_fields':[key for key in FIELDS if actual[key]!=expected[key]]}


def save(folder, report):
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'AI_TEST_RESULTS.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=report['cases']
    summary=['Mahalliy AI sinovi', 'Holat: '+report['status'],
             'Model: '+MODEL, 'Bajarilgan: '+str(len(rows))+'/'+str(len(DATA['cases'])),
             'Toliq togri: '+str(sum(r.get('passed',False) for r in rows)),
             'Xavfli narx/holat xatosi: '+str(sum(r.get('unsafe',False) for r in rows))]
    if report['status']!='completed':
        summary.append('Bu yakuniy AI sifati natijasi emas. '+report.get('error',''))
    else:
        times=[row['seconds'] for row in rows]
        summary+=['Median vaqt: '+str(round(statistics.median(times),2))+' s',
                  'Bu sinovdan otish botga avtomatik ulanish yoki mukammal aniqlik kafolati emas.']
    for row in rows:
        if not row.get('passed'):
            summary.append('FAIL '+row['id']+': '+', '.join(row.get('different_fields',[]))+' '+row.get('error',''))
    (folder/'AI_TEST_RESULTS.txt').write_text('\n'.join(summary),encoding='utf-8-sig')
    return path


def run(base):
    folder=Path(base)/'ai-test-results'
    report={'status':'checking','model_executed':False,'model':MODEL,'cases':[],
            'system':{'os':platform.platform(),'processor':platform.processor()},
            'cases_sha256':hashlib.sha256(json.dumps(DATA,sort_keys=True).encode()).hexdigest(),
            'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest()}
    for case in DATA['cases']:
        validate(case['expected'])
    try:
        report['ollama_version']=request('/api/version')
        details=request('/api/show',{'model':MODEL})
        report['model_details']=details.get('details')
        report['status']='running'
        save(folder,report)
        print('Model: '+MODEL+'. '+str(len(DATA['cases']))+' ta sinov. Bu bir necha daqiqa olishi mumkin.',flush=True)
        for index,case in enumerate(DATA['cases'],1):
            start=time.perf_counter()
            row={'id':case['id'],'messages':case['messages'],'expected':case['expected']}
            try:
                raw=request('/api/chat',model_payload(case))
                report['model_executed']=True
                row['raw_output']=raw['message']['content']
                actual=validate(json.loads(row['raw_output']))
                row.update(actual=actual,**judge(actual,case['expected']))
                row['eval_count']=raw.get('eval_count')
                row['eval_duration']=raw.get('eval_duration')
                row['load_duration']=raw.get('load_duration')
                row['prompt_eval_count']=raw.get('prompt_eval_count')
            except (OSError,ValueError,KeyError,urllib.error.URLError) as error:
                row.update(passed=False,unsafe=False,error=type(error).__name__)
            row['seconds']=round(time.perf_counter()-start,3)
            report['cases'].append(row)
            save(folder,report)
            print(str(index)+'/'+str(len(DATA['cases']))+' '+case['id']+' '+('PASS' if row['passed'] else 'FAIL')+' '+str(row['seconds'])+'s',flush=True)
        try:
            report['runtime_after_test']=request('/api/ps')
        except (OSError,ValueError,KeyError,urllib.error.URLError):
            pass
        report['status']='completed' if report['model_executed'] else 'unavailable'
        if not report['model_executed']:
            report['error']='Hech bir haqiqiy model javobi olinmadi.'
        path=save(folder,report)
        print('Natija: '+str(path),flush=True)
        print('Toliq togri: '+str(sum(r['passed'] for r in report['cases']))+'/'+str(len(DATA['cases'])),flush=True)
        print('AI_TEST_RESULTS.json faylini chatga yuboring. Token va baza yuborilmadi.',flush=True)
        return 0 if report['model_executed'] else 1
    except KeyboardInterrupt:
        report.update(status='interrupted',error='Sinov foydalanuvchi tomonidan toxtatildi.')
    except (OSError,ValueError,KeyError,urllib.error.URLError):
        report.update(status='unavailable',error='Ollama yoki qwen2.5:3b modeli mavjud emas. Ollama ishlayotganini tekshiring.')
    save(folder,report)
    print(report['error'],flush=True)
    print('Natija: '+str(folder/'AI_TEST_RESULTS.json'),flush=True)
    return 1
