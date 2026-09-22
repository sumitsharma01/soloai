"""Curated MCP adapter. Configuration is operator-owned, never model supplied."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from app.email_tools import BookingInput, BookingResult, EmailFailure

MAX_BYTES = 65536


def connection(tenant):
    path = os.getenv('SOLOAI_MCP_CONFIG_FILE')
    if not path:
        return None
    try:
        config = json.loads(Path(path).read_text())
        entry = config['tenants'].get(tenant)
        if entry is None:
            return None
        url = entry['url']
        parsed = urlsplit(url)
        local = os.getenv('SOLOAI_ENV') == 'development' and parsed.hostname == '127.0.0.1'
        if (url not in config['allowed_urls'] or parsed.username or parsed.password
                or parsed.query or parsed.fragment or not parsed.hostname
                or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http'))):
            raise ValueError()
        token = entry['token']
        tokens = [value['token'] for value in config['tenants'].values()]
        if len(set(tokens)) != len(tokens): raise ValueError()
        if not isinstance(token, str) or not token.isascii() or len(token) < 32 or any(c.isspace() for c in token):
            raise ValueError()
        return {'url': url, 'token': token}
    except Exception:
        raise EmailFailure('mcp_configuration_invalid') from None


class LimitedStream(httpx.AsyncByteStream):
    def __init__(self, stream): self.stream = stream
    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_BYTES:
                raise EmailFailure('mcp_response_too_large')
            yield chunk
    async def aclose(self): await self.stream.aclose()


class LimitedTransport(httpx.AsyncBaseTransport):
    def __init__(self): self.inner = httpx.AsyncHTTPTransport(retries=0)
    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        response.stream = LimitedStream(response.stream)
        return response
    async def aclose(self): await self.inner.aclose()


class MCPBookingSource:
    async def get_booking(self, tenant, booking_id):
        entry = connection(tenant)
        if entry is None: raise EmailFailure('mcp_not_configured')
        args = BookingInput(booking_id=booking_id)
        try:
            # Short-lived per-call clients prevent cross-workspace session reuse.
            async with asyncio.timeout(4):
                async with httpx.AsyncClient(
                    headers={'Authorization':'Bearer '+entry['token'], 'Accept-Encoding':'identity'},
                    transport=LimitedTransport(), follow_redirects=False,
                    trust_env=False, timeout=3) as http:
                    async with streamable_http_client(entry['url'], http_client=http) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool('get_booking', args.model_dump())
                            if result.isError: raise EmailFailure('mcp_tool_failed')
                            data = result.structuredContent
                            if data is None:
                                if len(result.content) != 1 or result.content[0].type != 'text':
                                    raise EmailFailure('invalid_tool_result')
                                data = json.loads(result.content[0].text)
                            validated = BookingResult.model_validate(data)
                            if validated.booking_id != booking_id or (validated.status and len(validated.status)>100):
                                raise EmailFailure('invalid_tool_result')
                            return validated.model_dump()
        except TimeoutError:
            raise EmailFailure('tool_timeout') from None
        except Exception:
            # Includes SDK exception groups. Never expose remote text or credentials.
            raise EmailFailure('mcp_unavailable_or_invalid') from None


def booking_source(engine, tenant):
    from app.email_tools import DatabaseBookingSource
    return MCPBookingSource() if connection(tenant) else DatabaseBookingSource(engine)
