import procrastinate

from app.config import settings

# Keyword arguments go to psycopg_pool.AsyncConnectionPool; conninfo is the plain postgresql:// DSN.
task_queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=settings.procrastinate_dsn),
    import_paths=["app.jobs.tasks"],  # so `procrastinate worker` registers every task
)
