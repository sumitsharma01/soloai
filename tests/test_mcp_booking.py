import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import httpx
import pytest
from app.mcp_booking import connection, MCPBookingSource
from app.email_tools import EmailFailure


def test_configuration_fails_closed(tmp_path, monkeypatch):
    p=tmp_path/'client.json'
    monkeypatch.setenv('SOLOAI_MCP_CONFIG_FILE',str(p))
    p.write_text(json.dumps({'allowed_urls':['http://evil.example/mcp'],
        'tenants':{'a':{'url':'http://evil.example/mcp','token':'x'*32}}}))
    assert connection('b') is None
    with pytest.raises(EmailFailure): connection('a')
    p.write_text('invalid')
    with pytest.raises(EmailFailure): connection('b')


def test_real_mcp_tenant_isolation(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}/mcp'
    server=tmp_path/'server.json'
    server.write_text(json.dumps({'tenants':{
        'a':{'token':'a'*40,'bookings':{'BK-1':{'status':'confirmed','change_allowed':True}}},
        'b':{'token':'b'*40,'bookings':{}}}}))
    client=tmp_path/'client.json'
    config={'allowed_urls':[url], 'tenants':{
        'a':{'url':url,'token':'a'*40}, 'b':{'url':url,'token':'b'*40},
        'bad':{'url':url,'token':'c'*40}}}
    client.write_text(json.dumps(config))
    monkeypatch.setenv('SOLOAI_ENV','development')
    monkeypatch.setenv('SOLOAI_MCP_CONFIG_FILE',str(client))
    process=subprocess.Popen([sys.executable,'-m','uvicorn','examples.booking_mcp_server:app',
        '--host','127.0.0.1','--port',str(port),'--no-access-log'],
        env={**os.environ,'BOOKING_MCP_SERVER_FILE':str(server)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if httpx.get(url,timeout=.2).status_code==401: break
            except httpx.HTTPError: pass
            time.sleep(.05)
        else: pytest.fail('MCP demo server did not start')
        source=MCPBookingSource()
        assert asyncio.run(source.get_booking('a','BK-1'))['found'] is True
        assert asyncio.run(source.get_booking('b','BK-1'))['found'] is False
        with pytest.raises(EmailFailure): asyncio.run(source.get_booking('bad','BK-1'))
    finally:
        process.terminate(); process.wait(timeout=5)


def test_response_stream_is_bounded():
    from app.mcp_booking import LimitedStream
    class Large(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'x'*40000
            yield b'x'*40000
    async def consume():
        async for _ in LimitedStream(Large()): pass
    with pytest.raises(EmailFailure): asyncio.run(consume())


def test_duplicate_credentials_rejected(tmp_path, monkeypatch):
    p=tmp_path/'client.json'
    entry={'url':'https://booking.example.com/mcp','token':'x'*40}
    p.write_text(json.dumps({'allowed_urls':[entry['url']],'tenants':{'a':entry,'b':entry}}))
    monkeypatch.setenv('SOLOAI_MCP_CONFIG_FILE',str(p))
    with pytest.raises(EmailFailure): connection('a')
