"""No Azure calls: verify creation, reuse and refusal to overwrite another agent."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from azure.core.exceptions import ResourceNotFoundError
from azure.ai.projects.models import PromptAgentDefinition

path = Path(__file__).resolve().parents[2] / 'scripts/create_foundry_agent.py'
spec = importlib.util.spec_from_file_location('creator', path)
creator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creator)


class CreatorTests(unittest.TestCase):
    def setUp(self):
        self.body = creator.definition('synthetic-model')
        self.version = SimpleNamespace(
            name=creator.AGENT_NAME, version='1', id='synthetic-id',
            metadata={'soloai_definition_sha256': creator.fingerprint(self.body)},
            definition=PromptAgentDefinition(model=self.body['model'], instructions=self.body['instructions'], tools=[]))
        self.project = MagicMock()

    def test_create_and_read_back(self):
        self.project.agents.get.side_effect = ResourceNotFoundError()
        self.project.agents.create_version.return_value = self.version
        self.project.agents.get_version.return_value = self.version
        self.assertEqual(creator.ensure_agent(self.project, self.body)['status'], 'created')
        self.assertEqual(self.project.agents.create_version.call_args.kwargs['definition'].tools, [])

    def test_reuse_identical_version(self):
        self.project.agents.list_versions.return_value = [self.version]
        self.assertEqual(creator.ensure_agent(self.project, self.body)['status'], 'existing')
        self.project.agents.create_version.assert_not_called()

    def test_refuse_unreviewed_change(self):
        self.project.agents.list_versions.return_value = []
        with self.assertRaises(ValueError):
            creator.ensure_agent(self.project, self.body)
        self.project.agents.create_version.assert_not_called()

    def test_detect_unexpected_tools(self):
        self.assertFalse(creator.same_definition(self.body | {'tools': [{'type': 'web_search'}]}, self.body))


if __name__ == '__main__':
    unittest.main()
