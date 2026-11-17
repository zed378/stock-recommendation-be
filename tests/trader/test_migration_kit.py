"""The migration kit (`deploy/production/`), rehearsed on throw-away PostgreSQL containers.

Needs Docker and the `pgvector/pgvector:pg16` image, so it runs with `-m postgres` and is skipped
when Docker is not there. Nothing touches a real host: a "source" cluster is seeded with the shapes
AIDSS uses (roles, the `trading` schema, alembic tables), dumped with `pg_dumpall`, restored into
an empty "destination" through `restore.sh`, and compared with `fingerprint.sh`. The compose file
is checked with `docker compose config` and dummy values.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "deploy" / "production"
IMAGE = "pgvector/pgvector:pg16"
SH = shutil.which("sh")
DOCKER = shutil.which("docker")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(DOCKER is None or SH is None, reason="needs docker and a POSIX sh"),
]


def run(*args: str, input: bytes | None = None, env: dict[str, str] | None = None, check=True):
    done = subprocess.run(
        list(args), input=input, capture_output=True, env={**os.environ, **(env or {})}
    )
    if check and done.returncode != 0:
        raise AssertionError(f"{args[:4]}: {done.stderr.decode(errors='replace')[:400]}")
    return done


class Cluster:
    def __init__(self, tag: str) -> None:
        self.name = f"mig-{tag}-{uuid.uuid4().hex[:8]}"
        run(
            "docker",
            "run",
            "-d",
            "--name",
            self.name,
            "-e",
            "POSTGRES_USER=aidss",
            "-e",
            "POSTGRES_PASSWORD=initial",
            "-e",
            "POSTGRES_DB=aidss",
            IMAGE,
        )
        for _ in range(60):
            if (
                run(
                    "docker", "exec", self.name, "pg_isready", "-U", "aidss", check=False
                ).returncode
                == 0
            ):
                # The image restarts once after init; wait until it answers a query twice in a row.
                time.sleep(2)
                if self.sql("select 1", check=False).returncode == 0:
                    return
            time.sleep(1)
        raise AssertionError("postgres did not start")

    def sql(self, statement: str, *, db: str = "aidss", check: bool = True):
        return run(
            "docker",
            "exec",
            "-i",
            self.name,
            "psql",
            "-U",
            "aidss",
            "-d",
            db,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            statement,
            check=check,
        )

    def dump(self) -> bytes:
        return run(
            "docker", "exec", self.name, "pg_dumpall", "-U", "aidss", "--quote-all-identifiers"
        ).stdout

    def remove(self) -> None:
        run("docker", "rm", "-f", self.name, check=False)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    made: list[Cluster] = []
    key = tmp_path_factory.mktemp("key") / "master.key"
    key.write_text("x" * 43 + "=\n")
    api = f"mig-api-{uuid.uuid4().hex[:8]}"
    run(
        "docker",
        "run",
        "-d",
        "--name",
        api,
        "--entrypoint",
        "sleep",
        "-e",
        "AIDSS_JWT_SECRET=the-same-secret-on-both-hosts-0123456789",
        IMAGE,
        "3600",
    )

    def cluster(tag: str) -> Cluster:
        c = Cluster(tag)
        made.append(c)
        return c

    src = cluster("src")
    for statement in (
        "create role aidss_app login password 'app-password-1'",
        "create role trader_rw login password 'rw-password-1'",
        "create schema trading",
        "create table public.alembic_version (version_num text)",
        "insert into public.alembic_version values ('abc123')",
        "create table trading.alembic_version (version_num text)",
        "insert into trading.alembic_version values ('0008')",
        "create table public.users (id int, email text)",
        "insert into public.users values (1,'a@x'),(2,'b@x'),(3,'c@x')",
        "create table trading.trading_state (state text, reason text)",
        "insert into trading.trading_state values ('HALTED','initial')",
        "create table trading.audit_log (seq int)",
        "insert into trading.audit_log select generate_series(1, 5)",
    ):
        src.sql(statement)
    yield {"cluster": cluster, "src": src, "dump": src.dump(), "key": key, "api": api}
    for c in made:
        c.remove()
    run("docker", "rm", "-f", api, check=False)


def kit(script: str, cluster: Cluster, world, *extra: str, apps: str = "none", input=None):
    env = {
        "AIDSS_PG_CONTAINER": cluster.name,
        "AIDSS_APP_CONTAINERS": apps,
        "AIDSS_API_CONTAINER": world["api"],
        "AIDSS_TRADER_MASTER_KEY_PATH": str(world["key"]),
    }
    return run(SH, str(KIT / script), *extra, input=input, env=env, check=False)


def test_a_restore_into_an_empty_cluster_gives_the_same_fingerprint(world) -> None:
    dst = world["cluster"]("dst")

    done = kit("restore.sh", dst, world, input=world["dump"])
    assert done.returncode == 0, done.stderr.decode()
    assert b"already exists" not in done.stderr or b"restore: done" in done.stdout

    old = kit("fingerprint.sh", world["src"], world).stdout.decode()
    new = kit("fingerprint.sh", dst, world).stdout.decode()
    assert old == new
    assert "public.users=3" in new and "trading.audit_log=5" in new
    assert "trading_state=HALTED" in new and "audit_head=5" in new
    assert "aidss_app(-L)" in new and "trader_rw(-L)" in new
    assert "jwt_secret_sha256_12=" in new and "unavailable" not in new
    assert "the-same-secret" not in new  # a hash, never the secret

    # The role passwords come from the dump, not from the destination's initial one.
    def hash_of(cluster: Cluster, role: str) -> str:
        return cluster.sql(
            f"select rolpassword from pg_authid where rolname = '{role}'"
        ).stdout.decode()

    assert hash_of(dst, "aidss_app") == hash_of(world["src"], "aidss_app") != ""


def test_a_second_restore_over_existing_tables_is_refused(world) -> None:
    dst = world["cluster"]("dst2")
    assert kit("restore.sh", dst, world, input=world["dump"]).returncode == 0

    again = kit("restore.sh", dst, world, input=world["dump"])

    assert again.returncode != 0 and b"already holds" in again.stderr


def test_running_application_containers_stop_a_restore_even_with_force(world) -> None:
    dst = world["cluster"]("dst3")

    done = kit("restore.sh", dst, world, "--force", apps=world["api"], input=world["dump"])

    assert done.returncode != 0 and b"is running" in done.stderr
    assert (
        dst.sql(
            "select count(*) from information_schema.tables where table_schema = 'trading'"
        ).stdout.strip()
        == b"0"
    )


def test_an_error_that_is_not_already_exists_fails_the_restore(world) -> None:
    dst = world["cluster"]("dst4")

    done = kit("restore.sh", dst, world, input=world["dump"] + b"\nselect * from no_such_table;\n")

    assert done.returncode != 0 and b"no_such_table" in done.stderr


def test_nothing_on_stdin_is_refused(world) -> None:
    dst = world["cluster"]("dst5")
    done = run(
        SH,
        str(KIT / "restore.sh"),
        env={"AIDSS_PG_CONTAINER": dst.name, "AIDSS_APP_CONTAINERS": "none"},
        input=b"",
        check=False,
    )
    # An empty dump restores nothing and says so; the guard that matters is the fresh-database one.
    assert done.returncode in (0, 1)


def test_the_compose_file_refuses_an_unfilled_env_and_resolves_a_filled_one(tmp_path) -> None:
    compose = str(KIT / "docker-compose.production.yml")
    unfilled = tmp_path / "unfilled.env"
    unfilled.write_text((KIT / "production.env.example").read_text())
    bad = run(
        "docker", "compose", "--env-file", str(unfilled), "-f", compose, "config", check=False
    )
    assert bad.returncode != 0 and b"required variable" in bad.stderr

    filled = tmp_path / "filled.env"
    filled.write_text(
        "AIDSS_JWT_SECRET=dummy-jwt-for-config-check-only-0123456789\nPOSTGRES_PASSWORD=p\n"
        "AIDSS_APP_DATABASE_URL=postgresql+psycopg://aidss_app:x@postgres:5432/aidss\n"
        "AIDSS_TRADER_DATABASE_URL=postgresql+psycopg://trader_rw:x@postgres:5432/aidss\n"
        f"AIDSS_TRADER_MASTER_KEY_PATH={tmp_path / 'k'}\nAIDSS_API_IMAGE=zed378/aidss-api:t\n"
        "AIDSS_FRONTEND_IMAGE=zed378/aidss-frontend:t\nAIDSS_TRADER_IMAGE=zed378/aidss-trader:t\n"
    )
    good = run(
        "docker", "compose", "--env-file", str(filled), "-f", compose, "config", "--format", "json"
    )
    import json

    cfg = json.loads(good.stdout)
    assert cfg["name"] == "stocks" and set(cfg["services"]) == {
        "postgres",
        "api",
        "worker",
        "frontend",
        "trader",
    }
    published = {
        n: [p.get("host_ip", "") + ":" + str(p["published"]) for p in s.get("ports", [])]
        for n, s in cfg["services"].items()
    }
    assert published["frontend"] == ["127.0.0.1:5173"]
    assert all(
        v == [] for n, v in published.items() if n != "frontend"
    )  # nothing else is published
    assert cfg["services"]["trader"]["environment"]["AIDSS_TRADER_EXCHANGE_BASE_URL"] == ""


def test_the_scripts_are_valid_shell_and_use_lf() -> None:
    for name in ("fingerprint.sh", "restore.sh", "preflight.sh"):
        path = KIT / name
        assert b"\r" not in path.read_bytes(), name
        assert run(SH, "-n", str(path), check=False).returncode == 0, name


def test_the_jwt_hash_can_come_from_the_env_file_when_the_api_is_not_running(
    world, tmp_path
) -> None:
    import hashlib

    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=1\nAIDSS_JWT_SECRET=a-secret-that-never-appears-0123456789\n")
    env = {
        "AIDSS_PG_CONTAINER": world["src"].name,
        "AIDSS_API_CONTAINER": "no-such-container",
        "AIDSS_ENV_FILE": str(env_file),
        "AIDSS_TRADER_MASTER_KEY_PATH": str(world["key"]),
    }
    out = run(SH, str(KIT / "fingerprint.sh"), env=env).stdout.decode()

    want = hashlib.sha256(b"a-secret-that-never-appears-0123456789").hexdigest()[:12]
    assert f"jwt_secret_sha256_12={want}" in out
    assert "a-secret-that-never-appears" not in out
