"""Experimental AI interpretation with independent, evidence-based write guards.
No database writes or network calls. Used by the evaluation harness first.
"""
import re
import catalog
import conversation
import price_parse
import question_intent
import station_directory


def question(text):
    norm=catalog.normalize(text)
    return question_intent.is_question(text) or bool(re.search(r'\d\s*(?:s[ou]m)?\s*(?:danmi|mi)\b',norm)) or bool(re.search(r'\b[a-z]+mi\b[.! ]*$',norm))


def station_ids(text):
    if conversation.landmark_place(text)=='ambiguous-bridge':
        return []
    return station_directory.find(text)


def apply(messages, hints=None):
    model_used = hints is not None
    hints=hints or {}
    last=messages[-1]
    text=last.get('text','')
    norm=catalog.normalize(text).replace('ы','i')
    ids=station_ids(text)
    raw_price=price_parse.amount(text)
    old=bool(re.search(r'\b(?:eski|oldingi|taxminan)\b',norm))
    is_question=question(text)
    target=None
    parent_id=last.get('reply_to')
    if parent_id is not None:
        parents=[m for m in messages[:-1] if m.get('id')==parent_id and question(m.get('text',''))]
    elif last.get('mentions'):
        parents=[m for m in messages[:-1] if m.get('author_id') in last['mentions'] and question(m.get('text',''))]
    else:
        parents=[]
    parent_ambiguous=False
    if len(parents)==1:
        pids=station_ids(parents[0].get('text',''))
        if len(pids)==1:
            if ids and ids!=pids:
                parent_ambiguous=True
            else:
                ids=pids
                target=parents[0]['id']
        else:
            parent_ambiguous=True
    elif len(parents)>1:
        parent_ambiguous=True
    shared_bridge=conversation.landmark_place(text)=='ambiguous-bridge'
    sid=ids[0] if len(ids)==1 and not parent_ambiguous else None
    status=None
    if not is_question:
        if re.search(r'\b(?:yopiq|yopildi|zakrito|ishlamayapti|ochiq emas|gaz yoq)\b',norm):
            status='closed'
        elif re.search(r'\b(?:ochiq|ochildi|otkrito|ishlayapti|ishga tushdi|gaz bor)\b',norm):
            status='open'
    result={'intent':'other','station_id':sid,'price_uzs':None,'status':None,
            'needs_review':False,'reply_to':None,'observed_date':None}
    has_price_text=bool(re.search(r'(?<!\d)\d{4,5}(?!\d)',norm))
    phone=bool(re.search(r'(?:\+?998[ -]*)\d{2}[ -]*\d{3}[ -]*\d{2}[ -]*\d{2}',norm))
    if old:
        result.update(intent='uncertain',needs_review=True)
    elif parent_ambiguous or shared_bridge:
        result.update(intent='uncertain',station_id=None,needs_review=True)
    elif is_question and (ids or re.search(r'propan|narx',norm)):
        status_question=bool(re.search(r'ochiqmi|yopiqmi|ishlayaptimi|ishlaydimi|ochiq yoki yopiq',norm))
        result.update(intent='status_question' if status_question else 'price_question',needs_review=sid is None)
    elif sid and hints.get('intent') in ('price_question','status_question'):
        result['intent']=hints['intent']
    elif model_used and (raw_price is not None or status is not None) and hints.get('intent') not in ('price_report','status_report'):
        result.update(intent='uncertain',needs_review=True)
    elif raw_price is not None:
        if sid is None:
            result.update(intent='uncertain',needs_review=True)
        else:
            result.update(intent='price_report',price_uzs=raw_price,status=status,reply_to=target)
    elif status is not None:
        if sid is None:
            result.update(intent='uncertain',needs_review=True)
        else:
            result.update(intent='status_report',status=status,reply_to=target)
    elif phone:
        pass  # A phone is not a gas price.
    elif sid and hints.get('intent') in ('price_question','status_question'):
        # AI may recognize a new question form, but cannot provide a price or state.
        result['intent']=hints['intent']
    elif sid and hints.get('intent') in ('price_report','status_report'):
        result.update(intent='uncertain',needs_review=True)
    elif has_price_text and not phone:
        result.update(intent='uncertain',needs_review=True)
    return result
