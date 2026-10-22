// Deploy in the customer's Supabase project. SoloAI receives only a scoped token,
// never SUPABASE_SERVICE_ROLE_KEY. Keep this function limited to read-only fields.
const headers = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' };
const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), {status, headers});
Deno.serve(async (req: Request) => {
  if (req.method !== 'POST') return reply(405, {error: 'method_not_allowed'});
  const expected = Deno.env.get('SOLOAI_BOOKING_TOKEN_SHA256');
  const token = (req.headers.get('Authorization') || '').replace(/^Bearer /, '');
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token))))
    .map(x => x.toString(16).padStart(2, '0')).join('');
  // Fixed-length comparison, with no secrets in error responses or application logs.
  let difference = expected?.length === 64 ? 0 : 1;
  for (let i = 0; i < 64; i++) difference |= hash.charCodeAt(i) ^ (expected || '').charCodeAt(i);
  if (!expected || difference !== 0) return reply(401, {error: 'unauthorized'});
  try {
    const raw = await req.text();
    if (raw.length > 1024) return reply(413, {error: 'too_large'});
    const body = JSON.parse(raw);
    if (Object.keys(body).sort().join(',') !== 'booking_id,customer_id' ||
        !/^[A-Za-z0-9_-]{1,80}$/.test(body.booking_id) || !/^[A-Za-z0-9_-]{1,100}$/.test(body.customer_id))
      return reply(400, {error: 'invalid_request'});
    const url = new URL('/rest/v1/soloai_test_bookings', Deno.env.get('SUPABASE_URL'));
    url.search = new URLSearchParams({select:'booking_id,status,change_allowed',
      booking_id:'eq.'+body.booking_id, customer_id:'eq.'+body.customer_id, limit:'1'}).toString();
    const key = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
    const result = await fetch(url, {headers:{apikey:key, Authorization:'Bearer '+key}, signal:AbortSignal.timeout(2500)});
    if (!result.ok) return reply(503, {error:'lookup_unavailable'});
    const rows = await result.json();
    return reply(200, {customer_id:body.customer_id, booking_id:body.booking_id, found:rows.length===1,
      status:rows[0]?.status ?? null, change_allowed:rows[0]?.change_allowed ?? null});
  } catch { return reply(503, {error:'lookup_unavailable'}); }
});
