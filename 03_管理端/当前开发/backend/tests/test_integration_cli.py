import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integration_cli import Service, sync_questions, coverage_handoff


def test_service_rejects_credentials_and_remote_http():
    for url in ['http://example.com','https://user:pass@example.com','https://example.com?token=secret','file:///tmp/data']:
        with pytest.raises(ValueError): Service(url)


def test_redirect_not_followed_and_errors_do_not_leak_body():
    def response(request):
        return httpx.Response(302,headers={'location':'https://elsewhere.example'},text='secret')
    service=Service('https://example.com','fixture',httpx.MockTransport(response))
    with pytest.raises(RuntimeError,match='HTTP 302') as error:
        service.request('GET','/api/questions')
    assert 'secret' not in str(error.value)
    service.close()


@pytest.mark.parametrize('payload',[{'total':1,'items':[]}, {'total':0,'other':[]},
    {'total':1,'items':[{'id':'Q-1','text':'我','level':1,'tokens':[{'c':'我','py':'wo3'}],'status':'ready'}]}])
def test_incomplete_or_unpublished_questions_do_not_import(payload):
    upstream=Service('http://testserver',transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload)))
    class NeverWrite:
        def request(self,*args,**kwargs): raise AssertionError('不得写入不完整列表')
    with pytest.raises(ValueError): sync_questions(NeverWrite(),upstream,1)
    upstream.close()


def test_changed_coverage_receipt_is_not_success(tmp_path):
    snapshot={'snapshot_version':'fixture:1','generated_at':'2026-11-23T00:00:00Z','items':[]}
    saved=tmp_path/'snapshot.json';saved.write_text(json.dumps(snapshot))
    upstream=Service('http://testserver',transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
        'ok':True,'applied':False,'snapshot':{**snapshot,'items':[{'question_id':'unexpected'}]}})))
    with pytest.raises(RuntimeError,match='回执'):
        coverage_handoff(None,upstream,saved)
    upstream.close()
