"""Contract and SDK boundary tests; no Azure calls or credentials needed."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from app import foundry

@pytest.mark.parametrize('mutation', [ {'channel':'email_draft'}, {'subject':'unexpected'}, {'needs_human':'false'}, {'extra':'value'} ])
def test_rejects_wrong_contract(monkeypatch, mutation):
    with mocked_provider(monkeypatch) as client:
        body={'channel':'website_chat','subject':'','reply':'Hello','needs_human':False}|mutation
        client.responses.create.return_value.output_text=json.dumps(body)
        with pytest.raises(ValueError): foundry.invoke(foundry.envelope('website-chat','Policy A','Hello'))

from contextlib import contextmanager
@contextmanager
def mocked_provider(monkeypatch):
    for key,value in {'PROJECT_ENDPOINT':'https://example.services.ai.azure.com/api/projects/test','AGENT_NAME':'soloai-support','AGENT_VERSION':'1','MODEL':'gpt-5.4'}.items():
        monkeypatch.setenv('AZURE_FOUNDRY_'+key,value)
    with patch('azure.ai.projects.AIProjectClient') as factory, patch('azure.identity.DefaultAzureCredential'):
        project=factory.return_value.__enter__.return_value
        project.agents.get_version.return_value.definition.as_dict.return_value={'kind':'prompt','model':'gpt-5.4','instructions':foundry.INSTRUCTIONS,'tools':[]}
        client=project.get_openai_client.return_value.__enter__.return_value
        client.responses.create.return_value=SimpleNamespace(status='completed',output=[SimpleNamespace(type='message')],output_text=json.dumps({'channel':'website_chat','subject':'','reply':'Hello','needs_human':False}),usage=SimpleNamespace(total_tokens=100))
        yield client

def test_stateless_pinned_call(monkeypatch):
    with mocked_provider(monkeypatch) as client:
        answer,tokens=foundry.invoke(foundry.envelope('website-chat','Only this workspace','Hello'))
        kwargs=client.responses.create.call_args.kwargs
        assert kwargs['store'] is False
        assert 'conversation' not in kwargs and 'previous_response_id' not in kwargs
        assert kwargs['extra_body']['agent_reference']['version']=='1'
        assert tokens==100 and answer.reply=='Hello'
