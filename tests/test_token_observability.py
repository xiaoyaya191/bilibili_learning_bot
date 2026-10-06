import asyncio
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import httpx
import pytest
from flask import Flask
from services.token_observability import TokenStore, observed_post, observed_urlopen, period, report, usage, validate_settings
from services.token_routes import blueprint


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


def record(store, **kwargs):
    value = dict(started=stamp('2026-10-07T08:00:00+08:00'), latency_ms=123.456,
                 source='brain', model='requested', url='https://user:secret@api.example/v1?key=secret',
                 data={'model':'actual', 'usage':{'prompt_tokens':100, 'completion_tokens':20, 'total_tokens':120,
                       'prompt_tokens_details':{'cached_tokens':30}, 'completion_tokens_details':{'reasoning_tokens':5}}})
    value.update(kwargs)
    store.record(**value)


def args(**kwargs):
    return dict(start='2026-10-07', end='2026-10-07', timezone='Asia/Shanghai', **kwargs)


@pytest.mark.parametrize('data,expected', [
    ({}, (None,None,None,None,None)),
    ({'usage':{'prompt_tokens':0,'completion_tokens':0}}, (0,0,0,None,None)),
    ({'usage':{'input_tokens':10,'output_tokens':3,'input_tokens_details':{'cached_tokens':4},'output_tokens_details':{'reasoning_tokens':2}}}, (10,3,13,4,2)),
    ({'usage':{'total_tokens':12}}, (None,None,12,None,None)),
    ({'usage':{'prompt_tokens':True,'completion_tokens':-1,'total_tokens':'8'}}, (None,None,None,None,None)),
    ({'usage':{'prompt_tokens':10,'completion_tokens':3,'prompt_tokens_details':{'cached_tokens':11},'completion_tokens_details':{'reasoning_tokens':4}}}, (10,3,13,None,None)),
    ({'usage':[]}, (None,None,None,None,None)),
])
def test_usage_variants(data, expected):
    assert usage(data) == expected


def test_exact_totals_missing_usage_price_and_redaction(tmp_path):
    store = TokenStore(tmp_path)
    record(store)
    record(store, data=None, outcome='http_error', status=429)
    store.save_settings({'prices':{'actual':{'input':2,'output':8,'cached':.5}}})
    result = report(store, args())
    assert result['summary']['total_tokens'] == 120
    assert result['summary']['input_tokens'] == 100
    assert result['summary']['cached_tokens'] == 30
    assert result['summary']['reasoning_tokens'] == 5
    assert result['summary']['known'] == 1 and result['summary']['unknown'] == 1
    assert result['summary']['coverage_percent'] == 50
    assert result['summary']['estimated_cny'] == pytest.approx((70*2+30*.5+20*8)/1e6)
    assert result['summary']['priced_requests'] == 1
    assert 'secret' not in json.dumps(result)
    assert result['records'][0]['provider'] == 'api.example'
    assert result['records'][0]['timestamp'].endswith('+08:00')


def test_cache_unknown_prevents_false_estimates(tmp_path):
    store = TokenStore(tmp_path)
    record(store, data={'model':'actual','usage':{'input_tokens':100,'output_tokens':20}})
    store.save_settings({'prices':{'actual':{'input':2,'output':8,'cached':.5}}})
    assert report(store,args())['records'][0]['estimated_cny'] is None
    store.save_settings({'prices':{'actual':{'input':2,'output':8,'cached':2}}})
    assert report(store,args())['records'][0]['estimated_cny'] == pytest.approx(.00036)


def test_period_includes_end_and_excludes_next_day(tmp_path):
    store = TokenStore(tmp_path)
    for value in ['2026-10-06T23:59:59+08:00','2026-10-07T00:00:00+08:00','2026-10-07T23:59:59+08:00','2026-10-08T00:00:00+08:00']:
        record(store, started=stamp(value))
    assert report(store,args())['summary']['requests'] == 2
    result = report(store,dict(start='2026-10-06',end='2026-10-07',timezone='UTC'))
    assert result['summary']['requests'] == 4
    spring = period(dict(start='2026-03-08',end='2026-03-08',timezone='America/New_York'))
    autumn = period(dict(start='2026-11-01',end='2026-11-01',timezone='America/New_York'))
    assert spring[4]-spring[3] == 23*3600
    assert autumn[4]-autumn[3] == 25*3600


@pytest.mark.parametrize('value', [dict(start='bad'),dict(start='2026-10-08',end='2026-10-07'),dict(start='2020-01-01',end='2026-10-07'),dict(timezone='invalid')])
def test_invalid_ranges(value):
    with pytest.raises(ValueError):
        period(value)


@pytest.mark.parametrize('value', [None,{'retention_days':0},{'retention_days':True},{'monthly_token_budget':-1},{'prices':[]},{'prices':{'model':{'input':1,'output':2,'cached':float('inf')}}},{'extra':True}])
def test_invalid_settings(value):
    with pytest.raises(ValueError):
        validate_settings(value)


def test_concurrent_account_isolation_and_filters(tmp_path):
    first = TokenStore(tmp_path/'first')
    second = TokenStore(tmp_path/'second')
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: record(first,source='chat' if index%2 else 'brain'),range(50)))
    result = report(first,args(source='brain',page='2',limit='10'))
    assert result['summary']['requests'] == 25
    assert len(result['records']) == 10 and result['pages'] == 3
    assert report(second,args())['summary']['requests'] == 0
    assert report(first,args(model="' OR 1=1 --"))['summary']['requests'] == 0


def test_observed_physical_attempts_and_network_errors(tmp_path):
    attempts = []
    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(429,json={'error':'secret'})
        if len(attempts) == 2:
            return httpx.Response(200,json={'usage':{'prompt_tokens':10,'completion_tokens':2},'model':'actual'})
        raise httpx.ConnectError('secret',request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for unused in range(2):
                await observed_post(client,'https://api.example/chat',source='api-pool',model='requested',data_dir=tmp_path,json={})
            with pytest.raises(httpx.ConnectError):
                await observed_post(client,'https://api.example/chat',source='api-pool',model='requested',data_dir=tmp_path,json={})
    asyncio.run(run())
    with TokenStore(tmp_path).connect() as connection:
        rows = connection.execute('SELECT * FROM requests ORDER BY id').fetchall()
    assert len(rows) == 3
    assert [row['outcome'] for row in rows] == ['http_error','success','network_error']
    assert rows[1]['total_tokens'] == 12 and rows[0]['total_tokens'] is None


def test_write_failure_never_breaks_ai(tmp_path,monkeypatch):
    monkeypatch.setattr(TokenStore,'record',lambda *args,**kwargs: (_ for unused in []).throw(OSError('secret')))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'usage':{'total_tokens':4}}))) as client:
            response = await observed_post(client,'https://api.example/chat',source='test',model='model',data_dir=tmp_path)
            assert response.status_code == 200
    asyncio.run(run())


def test_api_export_settings_prune(tmp_path):
    app = Flask(__name__)
    app.config['TOKEN_DATA_DIRECTORY'] = lambda:tmp_path
    app.register_blueprint(blueprint)
    client = app.test_client()
    store = TokenStore(tmp_path)
    record(store,model='=HYPERLINK("bad")',data={'usage':{'total_tokens':10}})
    result = client.get('/api/tokens/report',query_string=args()).get_json()
    assert result['ok'] and '_export' not in result
    response = client.get('/api/tokens/export',query_string=args())
    parsed = list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
    assert parsed[1][3].startswith("'=") and parsed[1][7] == 'success'
    assert client.post('/api/tokens/settings',json={'retention_days':0}).status_code == 400
    assert client.post('/api/tokens/settings',json={'monthly_token_budget':100}).get_json()['ok']
    assert client.post('/api/tokens/prune',json={}).status_code == 400
    record(store,started=0)
    assert client.post('/api/tokens/prune',json={'confirmed':True}).get_json()['removed'] >= 1
    assert client.get('/api/tokens/report?start=bad').status_code == 400
    assert client.get('/api/tokens/report?page=0').status_code == 400


def test_panel_auth_and_route_registration(tmp_path,monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel,'DATA_DIR',tmp_path)
    monkeypatch.setattr(web_panel.app,'testing',True)
    client = web_panel.app.test_client()
    assert client.get('/api/tokens/report').get_json()['ok']
    monkeypatch.setattr(web_panel.app,'testing',False)
    response = client.get('/api/tokens/report')
    assert response.status_code != 200 or response.get_json().get('ok') is not True


def test_sync_model_test_transport_preserves_usage(tmp_path):
    from urllib.request import Request
    class Reply:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *arguments):
            pass
        def read(self):
            return b'{"usage":{"prompt_tokens":8,"completion_tokens":2},"choices":[]}'
    result = observed_urlopen(lambda *arguments,**keywords:Reply(),Request('https://provider.example/v1'),model='tested',data_dir=tmp_path)
    assert result['choices'] == []
    with TokenStore(tmp_path).connect() as connection:
        row = connection.execute('SELECT * FROM requests').fetchone()
    assert row['total_tokens'] == 10 and row['source'] == 'model-test'


@pytest.mark.parametrize('response,outcome',[(httpx.Response(200,text='bad json'),'invalid_response'),(httpx.Response(200,json=[]),'invalid_response')])
def test_invalid_json_observed_without_masking_response(tmp_path,response,outcome):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:response)) as client:
            assert (await observed_post(client,'https://api.example/chat',source='test',model='model',data_dir=tmp_path)).status_code == 200
    asyncio.run(run())
    with TokenStore(tmp_path).connect() as connection:
        row = connection.execute('SELECT * FROM requests').fetchone()
    assert row['outcome'] == outcome and row['total_tokens'] is None


def test_cancelled_request_has_own_outcome(tmp_path):
    async def handler(request):
        raise asyncio.CancelledError()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(asyncio.CancelledError):
                await observed_post(client,'https://api.example/chat',source='test',model='model',data_dir=tmp_path)
    asyncio.run(run())
    with TokenStore(tmp_path).connect() as connection:
        assert connection.execute('SELECT outcome FROM requests').fetchone()[0] == 'cancelled'


def test_response_compatibility_preserves_usage():
    from services._services_ai import _compat_resp
    original={'model':'actual','usage':{'total_tokens':3},'choices':[{'message':{'content':'ok'}}]}
    result=_compat_resp(original)
    assert result.usage['total_tokens'] == 3 and result.model == 'actual'
    assert result.model_dump() == original and result.choices[0].message.content == 'ok'
