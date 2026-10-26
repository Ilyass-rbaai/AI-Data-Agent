"""Offline regression tests for AI Data Agent; no API or database traffic."""
import ast
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(os.environ.get('AGENT_PROJECT', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(ROOT))
os.environ.setdefault('OPENAI_API_KEY', 'offline-test-key')

# Replacing the model factory prevents model construction from using credentials.
fake_factory = types.ModuleType('utils.llm_pick')
fake_factory.pick_llm = MagicMock(return_value=MagicMock())
sys.modules['utils.llm_pick'] = fake_factory

from langchain_core.messages import AIMessage, HumanMessage
from Models.schema import AgentSchema, JudgeSchema, RouterSchema
from utils.etl_tools import Etl_tools
from utils.database import DatabaseUtil

# Fail closed if an unmocked dependency attempts an external connection.
network_guard = patch('socket.socket.connect', side_effect=AssertionError('Network disabled in offline tests'))
network_guard.start()
data = importlib.import_module('agents.data_agent')
etl = importlib.import_module('agents.etl_analyst')
sql_agent = importlib.import_module('agents.sql_analyst')


class SchemaTests(unittest.TestCase):
    def test_initial_state_accepts_pending_review(self):
        state = AgentSchema(messages=[], user_question='List users', curated_question='',
            prompt_query_context='', generated_sql_query='', sql_query_execution_result='', final_answer='')
        self.assertIsNone(state.is_safe)

    def test_judge_rejects_unknown_verdict(self):
        with self.assertRaises(ValueError):
            JudgeSchema(answer='maybe', comments='uncertain')

    def test_router_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            RouterSchema(answer='delete', comments='invalid')


class RoutingTests(unittest.TestCase):
    def run_route(self, route):
        router = MagicMock()
        router.invoke.return_value = RouterSchema(answer=route, comments='fixture')
        sql = MagicMock()
        sql.invoke.return_value = {'final_answer': 'SQL result'}
        etl_graph = MagicMock()
        etl_graph.invoke.return_value = {'messages': [AIMessage(content='ETL result')]}
        with patch.object(data, 'llm_router', router), patch.object(data, 'sql_analyst', sql), patch.object(data, 'etl_analyst', etl_graph):
            result = data.data_agent.invoke({'messages':[HumanMessage(content='fixture')], 'route_response':''})
        return result, sql, etl_graph

    def test_sql_route_calls_only_sql(self):
        result, sql, etl_graph = self.run_route('sql')
        sql.invoke.assert_called_once()
        etl_graph.invoke.assert_not_called()
        self.assertEqual(result['messages'][-1].content, 'SQL result')
        self.assertEqual(len(result['messages']), 2)

    def test_etl_route_calls_only_etl(self):
        result, sql, etl_graph = self.run_route('etl')
        etl_graph.invoke.assert_called_once()
        sql.invoke.assert_not_called()
        self.assertEqual(result['messages'][-1].content, 'ETL result')

    def test_router_failure_stops_before_execution(self):
        with patch.object(data.llm_router, 'invoke', side_effect=RuntimeError('offline')), patch.object(data.sql_analyst, 'invoke') as execute:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                data.data_agent.invoke({'messages':[HumanMessage(content='fixture')], 'route_response':''})
            execute.assert_not_called()


class EtlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.tool = Etl_tools()
        self.response = MagicMock()
        self.response.json.return_value = {'results':[{'name':'venusaur','url':'/3'},{'name':'bulbasaur','url':'/1'}]}

    def extract(self, fmt='csv'):
        with patch('utils.etl_tools.requests.get', return_value=self.response) as request:
            result = self.tool.extract_load('https://example.test/items', str(self.folder), fmt)
        return result, request

    def test_csv_contains_expected_records(self):
        import pandas as pd
        self.extract()
        frame = pd.read_csv(self.folder / 'extracted_data.csv')
        self.assertEqual(frame['name'].tolist(), ['venusaur', 'bulbasaur'])

    def test_extraction_returns_success_message(self):
        result, _ = self.extract()
        self.assertIsInstance(result, str)
        self.assertIn('extracted_data.csv', result)

    def test_http_request_has_finite_timeout(self):
        _, request = self.extract()
        timeout = request.call_args.kwargs.get('timeout')
        self.assertIsNotNone(timeout, 'HTTP calls can currently wait forever')
        self.assertGreater(timeout, 0)

    def test_unsupported_format_is_rejected(self):
        with self.assertRaises(ValueError):
            self.extract('exe')

    def test_json_extraction_can_be_read_by_context_tool(self):
        self.extract('json')
        context = self.tool.transform_load_context(str(self.folder / 'extracted_data.json'))
        self.assertIn('venusaur', context)
        self.assertIn('bulbasaur', context)

    def test_missing_input_file_reports_error(self):
        with self.assertRaises(FileNotFoundError):
            self.tool.transform_load_context(str(self.folder / 'missing.csv'))

    def test_http_failure_is_not_reported_as_success(self):
        import requests
        with patch('utils.etl_tools.requests.get', side_effect=requests.Timeout('fixture timeout')):
            try:
                result = self.tool.extract_load('https://example.test', str(self.folder), 'csv')
            except requests.RequestException:
                return
        self.assertIn('Failed', result)
        self.assertFalse((self.folder / 'extracted_data.csv').exists())

    def test_graph_tool_roundtrip_preserves_each_message_once(self):
        first = AIMessage(content='', tool_calls=[{'name':'extract_load_tool','args':{'url':'https://example.test','output_folder':str(self.folder),'format':'csv'},'id':'call_fixture'}])
        model = MagicMock()
        model.invoke.side_effect = [first, AIMessage(content='Saved successfully')]
        with patch.object(etl, 'llm_bind', model), patch('utils.etl_tools.requests.get', return_value=self.response):
            result = etl.etl_analyst.invoke({'messages':[HumanMessage(content='extract fixture')]})
        messages = result['messages']
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[2].tool_call_id, 'call_fixture')
        self.assertNotEqual(messages[2].content, 'None')
        self.assertEqual(messages[-1].content, 'Saved successfully')

    def test_failed_transform_does_not_claim_saved(self):
        tools = MagicMock()
        tools.transform_load_context.return_value = 'name: fixture'
        tools.execute_code.return_value = 'Failed to execute code fixture failure'
        model = MagicMock()
        model.invoke.return_value = AIMessage(content='raise ValueError("fixture failure")')
        with patch.object(etl, 'Etl_tools', return_value=tools), patch.object(etl, 'pick_llm', return_value=model):
            try:
                result = etl.tranform_load_tool.invoke({'input_file_path':'fixture.csv','output_folder':str(self.folder),'output_format':'csv','user_question':'filter'})
            except RuntimeError:
                return
        self.assertNotIn('The data is transformed and saved', result)


class SqlGraphTests(unittest.TestCase):
    def invoke_graph(self, verdict):
        factory = MagicMock()
        factory.schema_details.return_value = 'users(user_id integer, first_name text)'
        factory.execute_query.return_value = "[(1, 'Ada')]"
        model = MagicMock()
        model.invoke.side_effect = [AIMessage(content='List users'), AIMessage(content='SELECT user_id, first_name FROM users LIMIT 10'), AIMessage(content='Ada')]
        model.with_structured_output.return_value.invoke.return_value = JudgeSchema(answer=verdict, comments='fixture review')
        env = {'host':'offline', 'port':'5434','database':'fixture','user':'fixture','password':'fixture'}
        with patch.dict(os.environ, env), patch.object(sql_agent, 'DatabaseUtil', return_value=factory), patch.object(sql_agent, 'pick_llm', return_value=model):
            result = sql_agent.sql_analyst.invoke({'messages':[], 'user_question':'List users','curated_question':'','prompt_query_context':'','generated_sql_query':'','is_safe':None,'comment':'','sql_query_execution_result':'','final_answer':''})
        return result, factory

    def test_approved_sql_executes_exactly_once(self):
        result, database = self.invoke_graph('yes')
        database.execute_query.assert_called_once()
        self.assertEqual(result['final_answer'], 'Ada')

    def test_rejected_sql_never_executes(self):
        result, database = self.invoke_graph('no')
        database.execute_query.assert_not_called()
        self.assertIn('unsafe', result['final_answer'])

    def test_sql_history_does_not_duplicate_messages(self):
        result, _ = self.invoke_graph('yes')
        self.assertEqual(len(result['messages']), 3, 'Expected curated question, result and final answer only')


class DatabaseTests(unittest.TestCase):
    def test_connection_failure_is_not_silently_swallowed(self):
        import psycopg2
        with patch('utils.database.psycopg2.connect', side_effect=psycopg2.OperationalError('fixture')):
            with self.assertRaises(psycopg2.OperationalError):
                DatabaseUtil({'host':'offline'})

    def test_queries_use_read_only_transaction(self):
        connection = MagicMock()
        connection.cursor.return_value.fetchall.return_value = [(1,)]
        with patch('utils.database.psycopg2.connect', return_value=connection):
            database = DatabaseUtil({})
            database.execute_query('SELECT 1')
        self.assertTrue(any(call.kwargs.get('readonly') is True for call in connection.set_session.call_args_list), 'No database-enforced read-only transaction')
        connection.close.assert_called_once()

    def test_query_failure_is_not_returned_as_none(self):
        import psycopg2
        connection = MagicMock()
        connection.cursor.return_value.execute.side_effect = psycopg2.ProgrammingError('fixture')
        with patch('utils.database.psycopg2.connect', return_value=connection):
            database = DatabaseUtil({})
            with self.assertRaises(psycopg2.ProgrammingError):
                database.execute_query('SELECT missing')
        connection.close.assert_called_once()


class SourceChecks(unittest.TestCase):
    def test_python_sources_parse(self):
        for folder in ['agents','utils','Models']:
            for path in (ROOT / folder).glob('*.py'):
                ast.parse(path.read_text(encoding='utf-8'))

    def test_env_file_is_gitignored(self):
        patterns = (ROOT / '.gitignore').read_text().splitlines()
        self.assertTrue(any(p.strip() in ('.env', '.env*', '/.env') for p in patterns), 'Credentials file is not explicitly ignored')


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records=[]
    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({'test':test.id(), 'status':'pass'})
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({'test':test.id(), 'status':'fail', 'detail':self._exc_info_to_string(err,test)})
    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({'test':test.id(), 'status':'error', 'detail':self._exc_info_to_string(err,test)})


if __name__ == '__main__':
    started=time.monotonic()
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    out=Path(os.environ.get('RELIABILITY_REPORT_DIR', str(ROOT / 'reports')))
    out.mkdir(parents=True, exist_ok=True)
    report={'suite':'offline regression', 'network':'blocked', 'api_calls':0, 'live_database_calls':0,
            'duration_seconds':round(time.monotonic()-started,3), 'total':result.testsRun,
            'passed':sum(r['status']=='pass' for r in result.records), 'failures':len(result.failures),
            'errors':len(result.errors), 'results':result.records}
    (out/'reliability-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
