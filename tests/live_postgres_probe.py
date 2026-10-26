import json
from pathlib import Path
import psycopg2
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent.parent
config=dotenv_values(ROOT/'.env')
report={'connectivity':'unverified','safety':{},'tables':[]}
conn=None
try:
    conn=psycopg2.connect(host=config.get('host','127.0.0.1'),port=int(config.get('port','5434')),dbname=config.get('database','postgres'),user=config.get('user','postgres'),password=config.get('password'),connect_timeout=5)
    conn.set_session(readonly=True,autocommit=False)
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='5s'")
        cur.execute('SELECT 1')
        assert cur.fetchone()==(1,)
        report['connectivity']='pass'
        cur.execute('SHOW transaction_read_only')
        report['safety']['transaction_read_only']=cur.fetchone()[0]
        cur.execute('SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=current_user')
        report['safety']['role_flags']=dict(zip(['superuser','create_role','create_database'],cur.fetchone()))
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
        report['tables']=[r[0] for r in cur.fetchall()]
        if 'users' in report['tables']:
            cur.execute("SELECT has_table_privilege(current_user, 'public.users', 'UPDATE'),has_table_privilege(current_user, 'public.users', 'DELETE'),has_table_privilege(current_user, 'public.users', 'INSERT')")
            report['safety']['users_write_privileges']=dict(zip(['update','delete','insert'],cur.fetchone()))
    conn.rollback()
    if 'users' in report['tables']:
        try:
            with conn.cursor() as cur:
                cur.execute('UPDATE public.users SET user_id=user_id WHERE FALSE')
            report['safety']['write_in_readonly']='unexpectedly_allowed'
        except psycopg2.Error as exc:
            report['safety']['write_in_readonly_sqlstate']=exc.pgcode
            report['safety']['write_in_readonly']='blocked' if exc.pgcode=='25006' else 'other_error'
        finally:
            conn.rollback()
        try:
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION READ WRITE')
                cur.execute('SET LOCAL ROLE pg_read_all_data')
                cur.execute("SET LOCAL statement_timeout='5s'")
                cur.execute('UPDATE public.users SET user_id=user_id WHERE FALSE')
            report['safety']['restricted_role_write']='unexpectedly_allowed'
        except psycopg2.Error as exc:
            report['safety']['restricted_role_write']='blocked' if exc.pgcode=='42501' else 'other_error'
            report['safety']['restricted_role_sqlstate']=exc.pgcode
        finally:
            conn.rollback()
        # Zero matching rows; probes whether client transaction protection can be disabled.
        try:
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION READ WRITE')
                cur.execute("SET LOCAL statement_timeout='5s'")
                cur.execute('UPDATE public.users SET user_id=user_id WHERE FALSE')
            report['safety']['after_readwrite_override']='write_permission_available'
        except psycopg2.Error as exc:
            report['safety']['after_readwrite_override']='blocked'
            report['safety']['override_sqlstate']=exc.pgcode
        finally:
            conn.rollback()
except Exception as exc:
    error=str(exc)
    for key,value in config.items():
        if value and any(part in key.lower() for part in ['password','key','secret','token']):
            error=error.replace(value,'[hidden]')
    report['error_type']=type(exc).__name__
    report['error']=error
finally:
    if conn is not None:
        conn.close()
(ROOT/'reports/live-probe-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
