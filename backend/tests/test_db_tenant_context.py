from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.auth import CurrentUser
from app.database.session import (
    TenantAwareSession,
    _set_transaction_tenant,
    get_db,
)
from app.database import session as session_module


class FakeConnection:
    def __init__(self, dialect_name: str):
        self.dialect = SimpleNamespace(name=dialect_name)
        self.statements = []

    def execute(self, statement, parameters):
        self.statements.append((statement, parameters))


def test_postgres_transaction_sets_local_tenant_context_each_time():
    session = SimpleNamespace(info={"tenant_id": "verified-tenant"})
    connection = FakeConnection("postgresql")

    _set_transaction_tenant(session, None, connection)
    _set_transaction_tenant(session, None, connection)

    assert len(connection.statements) == 2
    for statement, parameters in connection.statements:
        assert str(statement) == "SELECT set_config('app.current_user_id', :tenant_id, true)"
        assert parameters == {"tenant_id": "verified-tenant"}


def test_missing_identity_does_not_set_postgres_tenant_context():
    session = SimpleNamespace(info={})
    connection = FakeConnection("postgresql")

    _set_transaction_tenant(session, None, connection)

    assert connection.statements == []


def test_non_postgres_transactions_do_not_execute_postgres_settings():
    session = SimpleNamespace(info={"tenant_id": "verified-tenant"})
    connection = FakeConnection("sqlite")

    _set_transaction_tenant(session, None, connection)

    assert connection.statements == []


@pytest.mark.asyncio
async def test_request_database_dependency_binds_verified_identity_to_session():
    dependency = get_db(user=CurrentUser(id="verified-tenant"))
    session = await anext(dependency)

    try:
        assert isinstance(session.sync_session, TenantAwareSession)
        assert session.sync_session.info["tenant_id"] == "verified-tenant"
        await session.execute(text("SELECT 1"))
    finally:
        await dependency.aclose()


class FakeResult:
    def __init__(self, *, row=None, rows=(), scalar=None):
        self._row = row
        self._rows = rows
        self._scalar = scalar

    def one_or_none(self):
        return self._row

    def scalar_one_or_none(self):
        return self._scalar

    def __iter__(self):
        return iter(self._rows)


class FakePostgresConnection:
    def __init__(self, *, role, policies, revision="003_durable_ingestion"):
        self.role = role
        self.policies = policies
        self.revision = revision

    async def execute(self, statement, _parameters=None):
        sql = str(statement)
        if "alembic_version" in sql:
            return FakeResult(scalar=self.revision)
        if "FROM pg_roles" in sql:
            return FakeResult(row=self.role)
        if "FROM pg_class" in sql:
            return FakeResult(rows=self.policies)
        raise AssertionError(f"Unexpected startup validation query: {sql}")


class FakeConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class FakeEngine:
    def __init__(self, connection, dialect_name="postgresql"):
        self._connection = connection
        self.dialect = SimpleNamespace(name=dialect_name)

    def connect(self):
        return FakeConnectionContext(self._connection)


def _valid_policy_rows():
    return [
        SimpleNamespace(
            relname=table_name,
            relrowsecurity=True,
            relforcerowsecurity=True,
            permissive="PERMISSIVE",
            qual="(owner_id = current_setting('app.current_user_id'))",
            with_check="(owner_id = current_setting('app.current_user_id'))",
        )
        for table_name in session_module.TENANT_RLS_TABLES
    ]


@pytest.mark.asyncio
async def test_production_rls_startup_check_accepts_current_secure_schema(monkeypatch):
    connection = FakePostgresConnection(
        role=SimpleNamespace(
            rolsuper=False,
            rolbypassrls=False,
            has_privileged_membership=False,
        ),
        policies=_valid_policy_rows(),
    )
    monkeypatch.setattr(session_module, "engine", FakeEngine(connection))

    await session_module.verify_postgres_rls()


@pytest.mark.asyncio
async def test_production_rls_startup_check_rejects_superuser_role(monkeypatch):
    connection = FakePostgresConnection(
        role=SimpleNamespace(
            rolsuper=True,
            rolbypassrls=False,
            has_privileged_membership=False,
        ),
        policies=_valid_policy_rows(),
    )
    monkeypatch.setattr(session_module, "engine", FakeEngine(connection))

    with pytest.raises(RuntimeError, match="non-superuser without BYPASSRLS"):
        await session_module.verify_postgres_rls()


@pytest.mark.asyncio
async def test_production_rls_startup_check_rejects_unapplied_migrations(monkeypatch):
    connection = FakePostgresConnection(
        role=SimpleNamespace(
            rolsuper=False,
            rolbypassrls=False,
            has_privileged_membership=False,
        ),
        policies=_valid_policy_rows(),
        revision="001_initial_schema",
    )
    monkeypatch.setattr(session_module, "engine", FakeEngine(connection))

    with pytest.raises(RuntimeError, match="not at revision 003_durable_ingestion"):
        await session_module.verify_postgres_rls()


@pytest.mark.asyncio
async def test_production_rls_startup_check_rejects_privileged_role_membership(monkeypatch):
    connection = FakePostgresConnection(
        role=SimpleNamespace(
            rolsuper=False,
            rolbypassrls=False,
            has_privileged_membership=True,
        ),
        policies=_valid_policy_rows(),
    )
    monkeypatch.setattr(session_module, "engine", FakeEngine(connection))

    with pytest.raises(RuntimeError, match="non-superuser without BYPASSRLS"):
        await session_module.verify_postgres_rls()


@pytest.mark.asyncio
async def test_production_rls_startup_check_rejects_unforced_table_policy(monkeypatch):
    policies = _valid_policy_rows()
    policies[0].relforcerowsecurity = False
    connection = FakePostgresConnection(
        role=SimpleNamespace(
            rolsuper=False,
            rolbypassrls=False,
            has_privileged_membership=False,
        ),
        policies=policies,
    )
    monkeypatch.setattr(session_module, "engine", FakeEngine(connection))

    with pytest.raises(RuntimeError, match="RLS is missing, not forced, or has an invalid policy"):
        await session_module.verify_postgres_rls()


@pytest.mark.asyncio
async def test_production_init_requires_migrations_instead_of_creating_schema(monkeypatch):
    monkeypatch.setattr(session_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(session_module, "validate_runtime_config", lambda: None)
    monkeypatch.setattr(
        session_module,
        "engine",
        FakeEngine(connection=None),
    )
    verified = False

    async def verify():
        nonlocal verified
        verified = True

    monkeypatch.setattr(session_module, "verify_postgres_rls", verify)
    await session_module.init_db()

    assert verified
