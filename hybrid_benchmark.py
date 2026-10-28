"""Evaluate short AI tasks plus independent guards. Not connected to bot writes."""
from pathlib import Path
import json
import time
import urllib.error
from ai_cases import DATA
from ai_benchmark import request, MODEL, validate, judge
import ai_diagnostics
import catalog
import hybrid_core


def payload(case,task):
    simple=('case',task,case['messages'][-1]['text'],None)
    mode='explicit_unknown' if task=='status' else 'typed_schema'
    result=ai_diagnostics.payload(simple,mode)
    extra={
        'intent':' Uzbek -mi/-danmi suffix marks a question. ochiqmi asks whether open, not the price. If the author is tagged after asking two different station questions, return uncertain. A bare number without any answer context is uncertain.',
        'price':' Uzbek mi/danmi is a question suffix, even without ?. A checking question is not a factual price. If a tagged author asked two station questions, return null. If a price is explicitly old/eski, return null.',
        'status':' Uzbek ёпиқ/yopiq, ёпилди/yopildi and ишламаяпти/ishlamayapti explicitly mean closed. очиқ/ochiq and ишга тушди/ishga tushdi explicitly mean open. -mi marks a question, not a fact.'}
    result['messages'][0]['content']+=extra[task]
    # Only source messages and mechanical transliteration, not answers/candidate labels.
    source=[dict(message,latin_text=catalog.normalize(message['text'])) for message in case['messages']]
    result['messages'][1]['content']=json.dumps({'messages':source},ensure_ascii=False)
    return result


def save(folder,report):
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'AI_HYBRID_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=report['cases']
    raw={task:sum(r.get('ai_fields',{}).get(task,{}).get('passed',False) for r in rows) for task in ('intent','price','status')}
    summary=['Hybrid evaluation v3','Status: '+report['status'],'Cases: '+str(len(rows))+'/'+str(len(DATA['cases'])),
             'Guard-only baseline correct: '+str(sum(r['baseline_grade']['passed'] for r in rows)),
             'Guarded + AI correct: '+str(sum(r['guarded_grade']['passed'] for r in rows)),
             'Guarded risky errors: '+str(sum(r['guarded_grade']['unsafe'] for r in rows)),
             'AI field-only results: '+json.dumps(raw),
             'This compares known test cases. Guard-only results are NOT AI accuracy. AI is not connected to bot writes.']
    if report.get('error'):summary.append(report['error'])
    (folder/'AI_HYBRID_RESULTS.txt').write_text('\n'.join(summary),encoding='utf-8-sig')


def run(base):
    folder=Path(base)/'ai-test-results'
    report={'version':'hybrid-v3','status':'checking','model':MODEL,'model_executed':False,'cases':[],
            'note':'AI raw fields, code-only baseline and guarded outputs are measured separately; no production DB writes.'}
    try:
        report['ollama_version']=request('/api/version')
        report['model_details']=request('/api/show',{'model':MODEL}).get('details')
        report['status']='running'
        save(folder,report)
        print('59 holat x 3 qisqa vazifa = 177 model sorovi. Natija eski fayllarni almashtirmaydi.',flush=True)
        for index,case in enumerate(DATA['cases'],1):
            started=time.perf_counter()
            row={'id':case['id'],'messages':case['messages'],'expected':case['expected'],'ai_fields':{}}
            hints={}
            for task,field in [('intent','intent'),('price','price_uzs'),('status','status')]:
                field_row={'expected':case['expected'][field]}
                try:
                    response=request('/api/chat',payload(case,task))
                    report['model_executed']=True
                    field_row['raw_output']=response['message']['content']
                    mode='explicit_unknown' if task=='status' else 'typed_schema'
                    actual=ai_diagnostics.normalize(task,mode,json.loads(field_row['raw_output']))
                    hints[field]=actual
                    field_row.update(actual=actual,passed=actual==case['expected'][field],prompt_eval_count=response.get('prompt_eval_count'))
                except (OSError,ValueError,KeyError,urllib.error.URLError) as error:
                    field_row.update(passed=False,error=type(error).__name__)
                row['ai_fields'][task]=field_row
            baseline=validate(hybrid_core.apply(case['messages']))
            guarded=validate(hybrid_core.apply(case['messages'],hints))
            row.update(baseline=baseline,baseline_grade=judge(baseline,case['expected']),
                       guarded=guarded,guarded_grade=judge(guarded,case['expected']),
                       ai_changed_baseline=baseline!=guarded,seconds=round(time.perf_counter()-started,3))
            report['cases'].append(row)
            save(folder,report)
            print(str(index)+'/59 '+case['id']+' guarded '+('PASS' if row['guarded_grade']['passed'] else 'FAIL'),flush=True)
        report['status']='completed' if report['model_executed'] else 'unavailable'
    except KeyboardInterrupt:
        report.update(status='interrupted',error='Sinov toxtatildi; natija toliq emas.')
    except (OSError,ValueError,KeyError,urllib.error.URLError):
        report.update(status='unavailable',error='Ollama yoki qwen2.5:3b mavjud emas.')
    save(folder,report)
    print('Natija: '+str(folder/'AI_HYBRID_RESULTS.json'),flush=True)
    print('AI_HYBRID_RESULTS.json faylini chatga yuboring.',flush=True)
    return 0 if report['status']=='completed' else 1
