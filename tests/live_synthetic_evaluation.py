"""Bounded, real-model evaluation; no production records are modified."""
import ast
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from unittest.mock import patch
import psycopg2
from dotenv import dotenv_values, load_dotenv

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'reports'
sys.path.insert(0,str(ROOT))
load_dotenv(ROOT/'.env')
config=dotenv_values(ROOT/'.env')
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage
from utils.llm_pick import pick_llm as original_factory
from Models.schema import RouterSchema


class Meter(BaseCallbackHandler):
    raise_error=True
    def __init__(self):
        self.calls=0
        self.input_tokens=0
        self.output_tokens=0
    def on_llm_start(self, serialized, prompts, **kwargs):
        if self.calls>=24:
            raise RuntimeError('Evaluation limit of 24 model calls reached')
        self.calls+=1
    def on_llm_end(self,response,**kwargs):
        for batch in response.generations:
            for generation in batch:
                usage=getattr(getattr(generation,'message',None),'usage_metadata',None) or {}
                self.input_tokens+=usage.get('input_tokens',0)
                self.output_tokens+=usage.get('output_tokens',0)

FIXTURE='reliability_fixture_'+uuid.uuid4().hex[:10]
meter=Meter()
def model(level):
    llm=original_factory(level)
    llm.callbacks=[meter]
    llm.request_timeout=40
    llm.max_retries=0
    return llm

def connect():
    return psycopg2.connect(host=config.get('host','127.0.0.1'),port=int(config.get('port','5434')),dbname=config.get('database','postgres'),user=config.get('user','postgres'),password=config.get('password'),connect_timeout=5)

def read_query(query):
    # Deliberately restricted benchmark grammar: plain SELECT only. No multi-statement,
    # comments, CTEs, dollar-quoted bodies, SELECT INTO or transaction commands.
    query=query.strip()
    if query.endswith(';'):
        query=query[:-1]
    if not re.match(r'^SELECT\b',query,re.I):
        raise ValueError('Benchmark accepts plain SELECT only')
    if any(token in query for token in [';','--','/*','*/','$$']):
        raise ValueError('Multi-statement or commented query rejected')
    if re.search(r'\b(INTO|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|COPY|CALL|DO|SET|RESET)\b',query,re.I):
        raise ValueError('Disallowed benchmark SQL token')
    allowed_tables={"users","rides","payments"}
    for reference in re.findall(r'\b(?:FROM|JOIN)\s+([\w.\"]+)',query,re.I):
        parts=reference.replace('"','').split('.')
        if parts[-1].lower() not in allowed_tables or (len(parts)>1 and parts[-2]!=FIXTURE):
            raise ValueError('Query references a table outside synthetic fixtures')
    allowed_functions={'count','sum','round','avg','min','max','coalesce','abs','in','as'}
    for function in re.findall(r'([a-zA-Z_][\w.]*)\s*\(',query):
        if function.lower() not in allowed_functions:
            raise ValueError('Function outside benchmark allowlist')
    conn=connect()
    try:
        conn.set_session(readonly=True,autocommit=False)
        with conn.cursor() as cur:
            cur.execute('SET LOCAL ROLE pg_read_all_data')
            cur.execute('SET LOCAL search_path TO '+FIXTURE)
            cur.execute("SET LOCAL statement_timeout='5s'")
            cur.execute(query)
            rows=cur.fetchmany(101)
            if len(rows)>100:
                raise ValueError('Benchmark result exceeds 100 rows')
            return rows
    finally:
        conn.rollback()
        conn.close()

def records(name):
    with (ROOT/'data'/f'{name}.csv').open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

users=[
    {'user_id':'1','first_name':'Alice','last_name':'Example','is_active':'true'},
    {'user_id':'2','first_name':'Bob','last_name':'Example','is_active':'false'},
    {'user_id':'3','first_name':'Carla','last_name':'Example','is_active':'true'},
    {'user_id':'4','first_name':'David','last_name':'Example','is_active':'true'},
    {'user_id':'5','first_name':'Eve','last_name':'Example','is_active':'false'},
    {'user_id':'6','first_name':'Farah','last_name':'Example','is_active':'true'},
]
payments=[{'amount':'10.50'},{'amount':'20.00'},{'amount':'7.25'},{'amount':'12.25'}]
rides=[{'rider_id':str(x)} for x in [1,1,1,2,2,3,4,5,6]]

# Create only synthetic fixtures in a unique schema; no production rows are read.
fixture_connection=connect()
try:
    with fixture_connection.cursor() as cur:
        cur.execute('CREATE SCHEMA '+FIXTURE)
        cur.execute('CREATE TABLE '+FIXTURE+'.users (user_id integer PRIMARY KEY, first_name text, last_name text, is_active boolean)')
        cur.execute('CREATE TABLE '+FIXTURE+'.rides (ride_id integer PRIMARY KEY, rider_id integer)')
        cur.execute('CREATE TABLE '+FIXTURE+'.payments (payment_id integer PRIMARY KEY, amount numeric(10,2))')
        cur.executemany('INSERT INTO '+FIXTURE+'.users VALUES (%s,%s,%s,%s)', [(int(r['user_id']),r['first_name'],r['last_name'],r['is_active']=='true') for r in users])
        cur.executemany('INSERT INTO '+FIXTURE+'.rides VALUES (%s,%s)', [(i+1,int(r['rider_id'])) for i,r in enumerate(rides)])
        cur.executemany('INSERT INTO '+FIXTURE+'.payments VALUES (%s,%s)', [(i+1,r['amount']) for i,r in enumerate(payments)])
    fixture_connection.commit()
except BaseException:
    fixture_connection.rollback()
    fixture_connection.close()
    raise

counts=Counter(int(row['rider_id']) for row in rides)
by_id={int(row['user_id']):row for row in users}
top=sorted(counts,key=lambda key:(-counts[key],key))[:5]
cases=[
    {'id':'user_count','question':'How many users are in users? Return exactly one column, the count.',
     'reference_sql':'SELECT count(*) FROM users','expected':[(len(users),)]},
    {'id':'first_five_users','question':'Return exactly user_id, first_name, last_name for the first 5 users ordered by user_id ascending.',
     'reference_sql':'SELECT user_id, first_name, last_name FROM users ORDER BY user_id LIMIT 5',
     'expected':[(int(r['user_id']),r['first_name'],r['last_name']) for r in sorted(users,key=lambda r:int(r['user_id']))[:5]]},
    {'id':'active_users','question':'How many users have is_active equal to true? Return exactly one column, the count.',
     'reference_sql':'SELECT count(*) FROM users WHERE is_active IS TRUE',
     'expected':[(sum(r['is_active'].lower() in ('true','t','1') for r in users),)]},
    {'id':'payment_total','question':'What is the sum of amount across all payments? Return exactly one numeric column rounded to 2 decimal places, without a currency symbol.',
     'reference_sql':'SELECT round(sum(amount),2) FROM payments',
     'expected':[(sum((Decimal(r['amount']) for r in payments if r['amount']),Decimal('0')).quantize(Decimal('.01')),)]},
    {'id':'top_riders_join','question':'Join users to rides on users.user_id = rides.rider_id. Return exactly user_id, first_name, count of rides for the 5 riders with the most rides. Include only users with rides. Sort by ride count descending, then user_id ascending.',
     'reference_sql':'SELECT u.user_id,u.first_name,count(*) FROM users u JOIN rides r ON u.user_id=r.rider_id GROUP BY u.user_id,u.first_name ORDER BY count(*) DESC,u.user_id ASC LIMIT 5',
     'expected':[(key,by_id[key]['first_name'],counts[key]) for key in top]},
]

def canonical(rows):
    def value(v):
        if v is None: return None
        if isinstance(v,(int,float,Decimal)):
            return str(Decimal(str(v)).normalize())
        return str(v)
    return [[value(v) for v in row] for row in rows]

schema = f"""Only use these synthetic benchmark tables. Qualify all table names with {FIXTURE}.
{FIXTURE}.users(user_id integer, first_name text, last_name text, is_active boolean)
{FIXTURE}.rides(ride_id integer, rider_id integer)
{FIXTURE}.payments(payment_id integer, amount numeric(10,2))
"""

class EvaluationDatabase:
    def __init__(self,config): pass
    def schema_details(self,name): return schema
    def execute_query(self,query): return repr(read_query(query))

report={'scope':'Live SQL graph with real models; restricted read-only executor; synthetic ground truth',
        'cases':[],'routing':[],'limits':{'max_model_calls':24,'model_timeout_seconds':40,'max_retries':0},
        'excluded':['ETL generated Python execution','adversarial prompt suite','load testing','repeat-run stability'],
        'context':'Only synthetic fixture schema and synthetic query results sent to model; no production schema or rows exported.'}
started=time.monotonic()

try:
    # Patch before importing graphs so no default unbounded clients are used.
    with patch('utils.llm_pick.pick_llm',side_effect=model):
        from agents import sql_analyst as agent
        with patch.object(agent,'DatabaseUtil',EvaluationDatabase),patch.object(agent,'pick_llm',side_effect=model):
            for case in cases:
                entry={'id':case['id'],'question':case['question']}
                tick=time.monotonic()
                try:
                    expected=canonical(case['expected'])
                    baseline=canonical(read_query(case['reference_sql']))
                    entry['fixture_database_match']=baseline==expected
                    if baseline!=expected:
                        entry['status']='skip_ground_truth_mismatch'
                    else:
                        state={'messages':[],'user_question':case['question'],'curated_question':'','prompt_query_context':'','generated_sql_query':'','is_safe':None,'comment':'','sql_query_execution_result':'','final_answer':''}
                        result=agent.sql_analyst.invoke(state,config={'recursion_limit':12})
                        entry['generated_sql']=result['generated_sql_query']
                        entry['judge_verdict']=result['is_safe']
                        if result['is_safe']!='yes':
                            entry['status']='fail_judge_rejected_read_query'
                        else:
                            # The exact SQL executed by the graph, not the final prose answer.
                            actual=canonical(read_query(result['generated_sql_query']))
                            entry['status']='pass' if actual==expected else 'fail_result_mismatch'
                            entry['expected_rows']=len(expected)
                            entry['actual_rows']=len(actual)
                            entry['expected_hash']=hashlib.sha256(json.dumps(expected).encode()).hexdigest()
                            entry['actual_hash']=hashlib.sha256(json.dumps(actual).encode()).hexdigest()
                            entry['final_answer_nonempty']=bool(result['final_answer'].strip())
                except Exception as exc:
                    entry['status']='error'
                    entry['error_type']=type(exc).__name__
                    # Do not persist exception request bodies or private result rows.
                entry['seconds']=round(time.monotonic()-tick,2)
                report['cases'].append(entry)
                print(case['id'],entry['status'],entry['seconds'],flush=True)
                (OUT/'synthetic-evaluation-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                if entry.get('error_type') in ('AuthenticationError','PermissionDeniedError','RateLimitError','OpenAIInvalidRequestError'):
                    break
        for question,expected in [('List the first ten users in the PostgreSQL database.','sql'),('Extract an API into a CSV file and filter that file.','etl')]:
            try:
                result=model('medium').with_structured_output(RouterSchema).invoke(question)
                report['routing'].append({'question':question,'expected':expected,'actual':result.answer,'status':'pass' if result.answer==expected else 'fail'})
            except Exception as exc:
                report['routing'].append({'question':question,'expected':expected,'status':'error','error_type':type(exc).__name__})
finally:
    fixture_connection.rollback()
    try:
        with fixture_connection.cursor() as cur:
            cur.execute('DROP SCHEMA '+FIXTURE+' CASCADE')
        fixture_connection.commit()
        report['fixture_cleanup']='pass'
    except Exception as exc:
        report['fixture_cleanup']='failed: '+type(exc).__name__
    finally:
        fixture_connection.close()
    report['model_calls']=meter.calls
    report['input_tokens']=meter.input_tokens
    report['output_tokens']=meter.output_tokens
    report['seconds']=round(time.monotonic()-started,2)
    report['sql_passed']=sum(c['status']=='pass' for c in report['cases'])
    report['sql_attempted']=len(report['cases'])
    (OUT/'synthetic-evaluation-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['sql_passed','sql_attempted','model_calls','input_tokens','output_tokens','seconds']},indent=2),flush=True)
