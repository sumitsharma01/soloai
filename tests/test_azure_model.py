from types import SimpleNamespace
import pytest
from app.azure_model import messages, ToolCall, DirectEmailProvider
from app.email_tools import EmailFailure


def test_tool_results_keep_call_identity():
    history=[{'role':'user','content':'booking question'},
        {'type':'function_call','call_id':'one','name':'get_booking','arguments':'{}'},
        {'type':'function_call_output','call_id':'one','output':'{"found":false}'}]
    result=messages(history,'Draft only')
    assert result[0]=={'role':'system','content':'Draft only'}
    assert result[2]['tool_calls'][0]['id']=='one'
    assert result[3]=={'role':'tool','tool_call_id':'one','content':'{"found":false}'}


def test_call_serialization_has_no_provider_extra_fields():
    call=ToolCall(SimpleNamespace(id='one',function=SimpleNamespace(name='get_booking',arguments='{}')))
    assert call.model_dump()=={'type':'function_call','call_id':'one','name':'get_booking','arguments':'{}'}


def test_direct_provider_rejects_jobs_for_old_configuration(monkeypatch):
    monkeypatch.setenv('AZURE_OPENAI_DEPLOYMENT','gpt-4.1-mini')
    with pytest.raises(EmailFailure):
        import asyncio
        asyncio.run(DirectEmailProvider().verify({'model':'old-model','agent_version':'1'}))
