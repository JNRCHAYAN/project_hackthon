"""Make the project root importable regardless of pytest's invocation mode."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """The real app, wired to an engine that cannot reach the network.

    The dashboard's engine narrates through the LLM layer by default, and this
    environment has a token set: without this fixture a suite run would make
    live HTTP calls, one narrative at a time. The stub here is the engine's own
    ``use_llm=False`` switch plus an unset token, which leaves the deterministic
    template narratives — the same text the app falls back to in production.

    ``db_path`` points at a scratch directory rather than ``data/audit.sqlite``,
    so a test run can neither read the case statuses a demo left behind nor
    leave any of its own. It lives here rather than in one test module because
    more than one module now drives the real app, and a second copy of this
    fixture would be a second place to forget the same two protections.
    """
    patch = MonkeyPatch()
    patch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    from app import main
    from app.engine import Engine

    scratch = tmp_path_factory.mktemp("api")
    previous = main._engine
    main._engine = Engine(seed=42, outlets=12, use_llm=False,
                          db_path=scratch / "audit.sqlite")
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main._engine = previous
        patch.undo()
