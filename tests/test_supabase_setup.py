from fastapi.testclient import TestClient
from app.main import app
from tests.test_security import create


def test_setup_is_private_validated_and_not_a_connection():
    body = dict(project_url='https://example.supabase.co', table_name='bookings',
                reference_column='reference', customer_column='customer_id',
                allowed_fields=['status'], ownership_rule='Dedicated business project',
                verification_rule='Verified customer session required')
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as anonymous:
        create(a,'supabase-a@example.com'); create(b,'supabase-b@example.com')
        assert anonymous.post('/api/integrations/supabase/setup',json=body).status_code==401
        assert a.post('/api/integrations/supabase/setup',json={**body,'project_url':'http://127.0.0.1'}).status_code==422
        assert a.post('/api/integrations/supabase/setup',json={**body,'secret':'do-not-store'}).status_code==422
        assert a.post('/api/integrations/supabase/setup',json=body).json()['connected'] is False
        saved=a.get('/api/integrations/supabase').json()
        assert saved['configuration']==body and saved['status']=='setup_requested'
        assert b.get('/api/integrations/supabase').json()['configuration'] is None
        body['allowed_fields']=['status','arrival_date']
        assert a.post('/api/integrations/supabase/setup',json=body).status_code==200
        assert a.get('/api/integrations/supabase').json()['configuration']==body
