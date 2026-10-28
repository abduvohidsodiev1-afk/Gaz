"""Small local-model diagnostics: separate tasks and compare output grammars."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time
import urllib.error
from ai_benchmark import request, MODEL

CASES = [
    ('intent-typo','intent','mayorskida narx qnaqa','price_question'),
    ('intent-fact','intent','майорский 8200','price_report'),
    ('intent-status','intent','Майорский очиқми','status_question'),
    ('intent-other','intent','Ассалому алайкум','other'),
    ('price-bare','price','майорский 8200',8200),
    ('price-spaced','price','Майорский: 8 200',8200),
    ('price-question','price','ИБРда пропан қанча',None),
    ('price-confirm-question','price','майорский 8200данми',None),
    ('status-greeting','status','Ассалому алайкум',None),
    ('status-price','status','майорский 8200',None),
    ('status-open','status','Майорский очиқ', 'open'),
    ('status-closed','status','Майорский ёпиқ','closed'),
]
INTENTS = ['price_question','price_report','status_question','status_report','other','uncertain']
FIELDS = {'intent':'intent','price':'price_uzs','status':'status'}
PROMPTS = {
 'intent': 'Classify this Uzbek Latin/Cyrillic message. Return only JSON with one key intent. Allowed: price_question, price_report, status_question, status_report, other, uncertain. Questions include qancha, kancha, qanaqa, qnaqa, qanday even without ?. A known station name plus a number is a price report. A greeting is other.',
 'price': 'Extract a propane price ONLY if this Uzbek message states it as a fact. Return only JSON with one key price_uzs: integer or null. Currency words are optional. Join spaced thousands. A question asking or checking a price is NOT a factual report: return null. Never invent, estimate or use outside knowledge.',
 'status': 'Extract the operational status explicitly STATED as a fact in this Uzbek message. Return only JSON with one key status: open, closed, or null. ochiq means open; yopiq means closed. If no operational state is stated, return null. A price does NOT imply open or closed. Never guess.',
}


def modes(task):
    return ['json','enum_nullable','typed_nullable','explicit_unknown'] if task=='status' else ['json','typed_schema']


def jobs():
    return [(case,mode) for case in CASES for mode in modes(case[1])]


def payload(case,mode):
    _,task,text,_ = case
    field=FIELDS[task]
    prompt=PROMPTS[task]
    if task=='intent':
        prop={'type':'string','enum':INTENTS}
    elif task=='price':
        prop={'type':['integer','null'],'minimum':500,'maximum':100000}
    elif mode=='enum_nullable':
        prop={'enum':[None,'open','closed']}
    elif mode=='explicit_unknown':
        prop={'type':'string','enum':['unknown','open','closed']}
        prompt=prompt.replace('or null','or unknown').replace('return null','return unknown')
    else:
        prop={'type':['string','null'],'enum':[None,'open','closed']}
    fmt='json' if mode=='json' else {'type':'object','additionalProperties':False,'required':[field],'properties':{field:prop}}
    return {'model':MODEL,'stream':False,'format':fmt,
            'messages':[{'role':'system','content':prompt},{'role':'user','content':text}],
            'options':{'temperature':0,'num_ctx':2048,'num_predict':96,'num_thread':4}}


def normalize(task,mode,output):
    field=FIELDS[task]
    if not isinstance(output,dict) or set(output)!={field}:
        raise ValueError('Invalid output fields')
    value=output[field]
    if task=='intent' and value not in INTENTS:
        raise ValueError('Invalid intent')
    if task=='price' and value is not None and (type(value) is not int or not 500<=value<=100000):
        raise ValueError('Invalid price')
    if task=='status':
        if mode=='explicit_unknown':
            if value not in ['unknown','open','closed']:
                raise ValueError('Invalid status sentinel')
            return None if value=='unknown' else value
        if value not in [None,'open','closed']:
            raise ValueError('Invalid status')
    return value


def save(folder,report):
    folder.mkdir(parents=True,exist_ok=True)
    counts=defaultdict(lambda:{'passed':0,'total':0})
    for row in report['results']:
        group=row['task']+'/'+row['mode']
        counts[group]['total']+=1
        counts[group]['passed']+=int(row.get('passed',False))
    report['by_task_format']=dict(counts)
    (folder/'AI_DIAG_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['AI diagnostika v2','Holat: '+report['status'], 'Bajarilgan: '+str(len(report['results']))+'/'+str(len(jobs()))]
    for key,value in sorted(counts.items()):
        lines.append(key+': '+str(value['passed'])+'/'+str(value['total']))
    if report.get('error'): lines.append(report['error'])
    lines.append('Bu 12 ta kichik holatdagi format taqqoslashi. Botga ulash uchun yakuniy sifat kafolati emas.')
    (folder/'AI_DIAG_RESULTS.txt').write_text('\n'.join(lines),encoding='utf-8-sig')


def run(base):
    folder=Path(base)/'ai-test-results'
    fingerprint=json.dumps({'cases':CASES,'prompts':PROMPTS},ensure_ascii=False,sort_keys=True)
    report={'version':'diag-v2','status':'checking','model':MODEL,'model_executed':False,
            'cases_prompt_sha256':hashlib.sha256(fingerprint.encode()).hexdigest(),'results':[]}
    try:
        report['ollama_version']=request('/api/version')
        report['model_details']=request('/api/show',{'model':MODEL}).get('details')
        report['status']='running'
        save(folder,report)
        print('12 ta holat, 32 ta model sorovi. Token/baza kerak emas. Natija alohida faylga yoziladi.',flush=True)
        for index,(case,mode) in enumerate(jobs(),1):
            cid,task,text,expected=case
            start=time.perf_counter()
            row={'case_id':cid,'task':task,'mode':mode,'input':text,'expected':expected}
            try:
                response=request('/api/chat',payload(case,mode))
                report['model_executed']=True
                row['raw_output']=response['message']['content']
                actual=normalize(task,mode,json.loads(row['raw_output']))
                row.update(actual=actual,passed=actual==expected)
                row['unsafe']=task in ('price','status') and actual is not None and actual!=expected
                row['prompt_eval_count']=response.get('prompt_eval_count')
                row['eval_count']=response.get('eval_count')
            except (OSError,ValueError,KeyError,urllib.error.URLError) as error:
                row.update(passed=False,error=type(error).__name__)
            row['seconds']=round(time.perf_counter()-start,3)
            report['results'].append(row)
            save(folder,report)
            print(str(index)+'/32 '+cid+' '+mode+' '+('PASS' if row['passed'] else 'FAIL'),flush=True)
        report['status']='completed' if report['model_executed'] else 'unavailable'
        if not report['model_executed']: report['error']='Haqiqiy model javobi olinmadi.'
    except KeyboardInterrupt:
        report.update(status='interrupted',error='Sinov toxtatildi; natija toliq emas.')
    except (OSError,ValueError,KeyError,urllib.error.URLError):
        report.update(status='unavailable',error='Ollama yoki qwen2.5:3b mavjud emas.')
    save(folder,report)
    print('Natija: '+str(folder/'AI_DIAG_RESULTS.json'),flush=True)
    print('AI_DIAG_RESULTS.json faylini chatga yuboring. Eski AI_TEST_RESULTS.json saqlandi.',flush=True)
    return 0 if report['status']=='completed' else 1
