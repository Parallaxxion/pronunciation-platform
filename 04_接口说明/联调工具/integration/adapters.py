"""Pure, strict adapters; no upstream writes or database access."""
import hashlib
import json
import re
import unicodedata

class ContractError(ValueError):
    pass


def pinyin_numbered(value):
    """One syllable -> lowercase numbered pinyin; ü/v/u: -> v, neutral -> 5."""
    if not isinstance(value, str) or not value.strip():
        raise ContractError('拼音必须是一个非空音节')
    raw = value.strip().lower().replace('u:', 'ü').replace('v', 'ü')
    number = None
    if raw[-1:].isdigit():
        number = '5' if raw[-1] == '0' else raw[-1]
        if number not in '12345':
            raise ContractError('声调必须为0至5')
        raw = raw[:-1]
    result, mark = [], None
    for c in unicodedata.normalize('NFD', raw):
        if c == '\u0308':
            if not result or result[-1] != 'u':
                raise ContractError('无效的ü')
            result[-1] = 'v'
        elif c in '\u0304\u0301\u030c\u0300':
            tone = {'\u0304':'1','\u0301':'2','\u030c':'3','\u0300':'4'}[c]
            if mark is not None:
                raise ContractError('一个音节不能有多个声调符号')
            mark = tone
        elif 'a' <= c <= 'z':
            result.append(c)
        else:
            raise ContractError('不接受拼接音节或标点，请提供逐字tokens')
    if not result or (mark and number and mark != number):
        raise ContractError('拼音或声调冲突')
    return ''.join(result) + (number or mark or '5')


def _is_han(c):
    return '\u3400' <= c <= '\u9fff' or '\U00020000' <= c <= '\U000323af'


def normalize_question(item, source='proposition'):
    if not isinstance(item, dict):
        raise ContractError('题目必须为对象')
    qid = item.get('question_id', item.get('id'))
    text = item.get('display_text', item.get('text'))
    level = item.get('level')
    if not isinstance(qid, str) or not qid or not isinstance(text, str) or not text:
        raise ContractError('题目编号和文本必填')
    if type(level) is not int or not 1 <= level <= 9:
        raise ContractError('level必须是1至9整数')
    tokens = item.get('tokens')
    if tokens is None:
        py = item.get('pinyin')
        chars = [c for c in text if _is_han(c)]
        if not isinstance(py, list) or len(py) != len(chars):
            raise ContractError('缺少逐字tokens，整句拼音字符串不能自动猜分词')
        tokens = [dict(c=c, py=p) for c,p in zip(chars,py)]
    if not isinstance(tokens,list) or not tokens:
        raise ContractError('tokens不能为空')
    normalized, cursor = [], 0
    for token in tokens:
        if not isinstance(token, dict):
            raise ContractError('token必须为对象')
        c = token.get('c', token.get('char'))
        py = token.get('py', token.get('pinyin'))
        if not isinstance(c,str) or len(c) != 1 or not _is_han(c):
            raise ContractError('token必须为单个汉字')
        pos = text.find(c,cursor)
        if pos < 0 or any(_is_han(x) for x in text[cursor:pos]):
            raise ContractError('tokens与题文顺序不一致或有汉字遗漏')
        normalized.append({'c':c,'py':pinyin_numbered(py),'display_py':token.get('display_py',py),'display_start':pos})
        cursor = pos+1
    if any(_is_han(x) for x in text[cursor:]):
        raise ContractError('tokens遗漏题文末尾汉字')
    payload={'text':text,'tokens':[{k:t[k] for k in ('c','py')} for t in normalized]}
    revision=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result = {'question_id':qid,'question_version':item.get('question_version'),
            'content_revision':revision,'level':level,'display_text':text,'tokens':normalized,
            'grammar':item.get('grammar',[]),'status':item.get('status','unknown'),'source':source}
    upstream_revision = item.get('source_content_revision') or item.get('content_revision')
    if upstream_revision is not None:
        result['source_content_revision'] = upstream_revision
    return result


def question_list(payload):
    if isinstance(payload,list): items=payload
    elif isinstance(payload,dict) and isinstance(payload.get('items'),list): items=payload['items']
    elif isinstance(payload,dict) and isinstance(payload.get('questions'),list): items=payload['questions']
    else: raise ContractError('题目列表需要items数组；不把未知结构当空题库')
    return [normalize_question(q) for q in items]


def normalize_diagnosis(data, question):
    if not isinstance(data, dict): raise ContractError('诊断必须为对象')
    n=len(question['tokens'])
    if not isinstance(data.get('status'),str): raise ContractError('诊断状态必须为字符串')
    status={'done':'completed','pending':'pending','processing':'processing','failed':'failed','completed':'completed'}.get(data.get('status'))
    if status is None: raise ContractError('未知诊断状态')
    rid=data.get('recording_id')
    if not isinstance(rid,str) or not rid: raise ContractError('诊断必须关联recording_id')
    out={'recording_id':rid,'status':status,'model_version':data.get('model_version'),
         'error_message':data.get('error_message'),'errors':[]}
    if status != 'completed': return out
    if isinstance(data.get('errors'),list):
        errors=data['errors']
    elif isinstance(data.get('tokens'),list):
        if len(data['tokens']) != n: raise ContractError('诊断tokens长度与题目不同')
        errors=[]
        for i,t in enumerate(data['tokens']):
            if not isinstance(t,dict): raise ContractError('诊断token必须为对象')
            if t.get('c') != question['tokens'][i]['c']: raise ContractError('诊断tokens字序不同')
            err=t.get('err')
            if err:
                if not isinstance(err,dict): raise ContractError('偏误必须为对象')
                if not isinstance(err.get('t'),str): raise ContractError('偏误类型必须为字符串')
                kind={'tone':'tone','sf':'substitution','del':'omission'}.get(err.get('t'))
                if not kind: raise ContractError('未知字符偏误类型')
                errors.append({'type':kind,'char_index':i,'actual':err.get('py')})
        gaps=data.get('gap_errors',{})
        if not isinstance(gaps,dict): raise ContractError('gap_errors应为对象')
        for k,e in gaps.items():
            if not isinstance(k,str) or not isinstance(e,dict) or not re.fullmatch(r'0|[1-9][0-9]*',k) or e.get('t') != 'ins':
                raise ContractError('无效的字间偏误')
            errors.append({'type':'insertion','boundary_index':int(k),'actual':e.get('py')})
    else: raise ContractError('已完成诊断缺少errors或tokens，不能判为无偏误')
    for e in errors:
        if not isinstance(e,dict): raise ContractError('偏误必须为对象')
        kind=e.get('type')
        if kind not in ('tone','substitution','omission','insertion'): raise ContractError('未知偏误类型')
        key='boundary_index' if kind=='insertion' else 'char_index'
        index=e.get(key)
        if type(index) is not int or not 0 <= index <= (n if kind=='insertion' else n-1):
            raise ContractError('偏误索引越界')
        actual=e.get('actual')
        if kind != 'omission':
            if not isinstance(actual,str) or not actual.strip(): raise ContractError('偏误缺少实际读音')
            actual=' '.join(pinyin_numbered(p) for p in actual.split())
        else: actual=None
        out['errors'].append({'type':kind,key:index,'expected':None if kind=='insertion' else question['tokens'][index]['py'],'actual':actual})
    return out


def coverage(questions, recordings, targets=None):
    """Count recordings by stable ID, not upload attempts. Fail on conflicting duplicates."""
    targets=targets or {}
    known={q['question_id'] for q in questions}
    seen={}
    for r in recordings:
        rid=r.get('recording_id')
        if not isinstance(rid,str) or not rid: raise ContractError('缺少录音唯一ID')
        if r.get('question_id') not in known: raise ContractError('录音关联未知题号')
        if not isinstance(r.get('speaker_id'),str) or not r['speaker_id']: raise ContractError('缺少匿名说话人编号')
        if rid in seen and seen[rid] != r: raise ContractError('同一录音ID存在冲突快照')
        seen[rid]=r
    items=[]
    for q in questions:
        rows=[r for r in seen.values() if r['question_id']==q['question_id'] and r.get('upload_status')=='uploaded' and not r.get('deleted',False)]
        target=targets.get(q['question_id'])
        if target is not None and (type(target) is not int or target<0): raise ContractError('目标必须为非负整数或null')
        items.append({'question_id':q['question_id'],'recording_count':len(rows),
                      'unique_speaker_count':len({r['speaker_id'] for r in rows}),
                      'target_recordings':target,'gap':None if target is None else max(0,target-len(rows))})
    return {'counting_policy':'uploaded_not_deleted_distinct_recording_id','items':items}
