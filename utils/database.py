"""PostgreSQL reads with explicit failures, finite timeouts and transaction cleanup."""
from pathlib import Path
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")


class DatabaseUtil:
    def __init__(self, db_config):
        config = dict(db_config)
        config.setdefault("connect_timeout", 10)
        self.connection = psycopg2.connect(**config)
        try:
            self.connection.set_session(readonly=True, autocommit=False)
        except Exception:
            self.connection.close()
            raise

    def schema_details(self, schema_name):
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
                (schema_name,),
            )
            tables = cursor.fetchall()
            lines = [f"Database Schema: {schema_name}"]
            for (table,) in tables:
                lines.append(f"Table Name: {table}")
                cursor.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                    (schema_name, table),
                )
                for name, dtype in cursor.fetchall():
                    lines.append(f"Column Name: {name}, Data Type: {dtype}")
                cursor.execute(sql.SQL("SELECT * FROM {}.{} LIMIT 5").format(
                    sql.Identifier(schema_name), sql.Identifier(table)))
                lines.append(f"Sample Data from {table}:")
                lines.extend(str(row) for row in cursor.fetchall())
            return "\n".join(lines)
        finally:
            try:
                if cursor is not None:
                    cursor.close()
                self.connection.rollback()
            finally:
                self.connection.close()

    def execute_query(self, query):
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute(query)
            return str(cursor.fetchall())
        finally:
            try:
                if cursor is not None:
                    cursor.close()
                self.connection.rollback()
            finally:
                self.connection.close()
