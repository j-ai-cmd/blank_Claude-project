import pytest

from workforce import harness as harness_mod
from workforce.agents import FakeRunner
from workforce.config import Config
from workforce.db import make_sessionmaker
from workforce.dispatcher import Dispatcher
from workforce.slack import SlackClient


@pytest.fixture(scope="session")
def cfg():
    return Config()


@pytest.fixture
def Session(tmp_path):
    return make_sessionmaker(f"sqlite:///{tmp_path}/t.db")


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(harness_mod, "WORKSPACE_ROOT", tmp_path / "ws")
    return tmp_path / "ws"


@pytest.fixture
def make_dispatcher(cfg, Session):
    runners = []

    def _make(scripts):
        runner = FakeRunner(scripts)
        runners.append(runner)
        slack = SlackClient(token="")
        return Dispatcher(cfg, Session, runner, slack), runner, slack
    yield _make
    for r in runners:  # a failing assertion inside a scripted agent must fail the test
        assert not r.script_errors, "\n".join(r.script_errors)
