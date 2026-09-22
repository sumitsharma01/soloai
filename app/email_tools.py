"""Two read-only tools. Identity is supplied by the worker, never by model arguments."""
import asyncio
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Protocol
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, or_
from app.email_schema import bookings, policies, tool_calls
from app.packages import PACKAGES
from app.telemetry import emit


class EmailFailure(Exception):
    def __init__(self, code, transient=False):
        self.code, self.transient = code, transient
        super().__init__(code)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class BookingInput(StrictModel):
    booking_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


class BookingResult(StrictModel):
    found: bool
    booking_id: str
    status: str | None
    change_allowed: bool | None


class PolicyInput(StrictModel):
    query: str = Field(min_length=1, max_length=300)


class PolicyItem(StrictModel):
    title: str = Field(max_length=200)
    content: str = Field(max_length=600)


class PolicyResult(StrictModel):
    found: bool
    policies: list[PolicyItem] = Field(max_length=2)


class BookingSource(Protocol):
    async def get_booking(self, tenant: str, booking_id: str) -> dict: ...


class DatabaseBookingSource:
    """Minimal imported support snapshot, not a connection to a live booking vendor."""
    def __init__(self, engine): self.engine = engine

    async def get_booking(self, tenant, booking_id):
        return await asyncio.to_thread(self._lookup, tenant, booking_id)

    def _lookup(self, tenant, booking_id):
        with self.engine.connect() as c:
            row = c.execute(select(bookings).where(
                bookings.c.tenant == tenant, bookings.c.booking_id == booking_id)).mappings().first()
        return {'found': row is not None, 'booking_id': booking_id,
                'status': row['status'] if row else None,
                'change_allowed': row['change_allowed'] if row else None}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    required_permission: str

    def definition(self):
        return {'type': 'function', 'name': self.name, 'description': self.description,
                'parameters': self.input_schema.model_json_schema(), 'strict': True}


TOOLS = {
    'get_booking': Tool('get_booking', 'Read a booking support snapshot. Missing means unknown.',
                        BookingInput, BookingResult, 'get_booking'),
    'search_policy': Tool('search_policy', 'Find short policy excerpts using a few relevant keywords.',
                          PolicyInput, PolicyResult, 'search_policy'),
}


class ToolGateway:
    def __init__(self, store, context, booking_source=None, timeout=5):
        self.store, self.context = store, context
        self.booking_source = booking_source
        self.timeout = timeout
        self.seen = set()
        self.count = 0
        self.missing_information = False

    async def call(self, name, arguments):
        start = time.monotonic()
        status = 'failed'
        safe_name = name if name in TOOLS else 'unknown'
        try:
            self.store.check_active(self.context)
            if name not in TOOLS: raise EmailFailure('unknown_tool')
            tool = TOOLS[name]
            if tool.required_permission not in PACKAGES[self.context['agent']]['permissions']:
                raise EmailFailure('unauthorized_tool')
            if self.count >= 3: raise EmailFailure('tool_limit')
            if not isinstance(arguments, str) or len(arguments) > 2000:
                raise EmailFailure('invalid_tool_arguments')
            try:
                args = tool.input_schema.model_validate_json(arguments)
            except (ValidationError, ValueError):
                raise EmailFailure('invalid_tool_arguments') from None
            signature = (name, args.model_dump_json())
            if signature in self.seen: raise EmailFailure('repeated_tool_call')
            self.seen.add(signature)
            self.count += 1
            try:
                result = await asyncio.wait_for(self.execute(name, args), self.timeout)
                result = tool.output_schema.model_validate(result)
            except TimeoutError:
                raise EmailFailure('tool_timeout') from None
            except ValidationError:
                raise EmailFailure('invalid_tool_result') from None
            self.store.check_active(self.context)
            self.missing_information |= not result.found
            status = 'ok' if result.found else 'not_found'
            return result.model_dump_json()
        except EmailFailure:
            raise
        except Exception:
            raise EmailFailure('tool_unavailable') from None
        finally:
            duration = round((time.monotonic() - start) * 1000)
            # Do not persist arguments, results, raw tool names, or customer identifiers.
            with self.store.transaction(self.context['tenant']) as c:
                c.execute(tool_calls.insert().values(id=secrets.token_hex(16),
                    tenant=self.context['tenant'], execution_id=self.context['execution_id'],
                    tool_name=safe_name, status=status, duration=duration, created_at=int(time.time())))
                self.store.audit(c, self.context['tenant'], 'email.tool.' + safe_name + '.' + status)
            emit('agent.tool', tool_name=safe_name, status=status, duration_ms=duration)

    async def execute(self, name, args):
        tenant = self.context['tenant']
        if name == 'get_booking':
            from app.mcp_booking import booking_source
            source = self.booking_source or booking_source(self.store.engine, tenant)
            return await source.get_booking(tenant, args.booking_id)
        return await asyncio.to_thread(self._search_policy, tenant, args.query)

    def _search_policy(self, tenant, query):
        terms = list(dict.fromkeys(re.findall(r'\w{3,}', query.lower())))[:8]
        if not terms: return {'found': False, 'policies': []}
        # Bound the result at the database. SQL parameters and autoescape prevent
        # wildcard/SQL injection. No vector database or model-generated SQL.
        with self.store.engine.connect() as c:
            rows = c.execute(select(policies.c.title, policies.c.content).where(
                policies.c.tenant == tenant,
                or_(*(policies.c.content.ilike('%' + term.replace('_', r'\_') + '%', escape='\\')
                      for term in terms))).order_by(policies.c.id).limit(2)).mappings().all()
        return {'found': bool(rows), 'policies': [
            {'title': r['title'], 'content': r['content'][:600]} for r in rows]}
