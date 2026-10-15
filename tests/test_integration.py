"""Exercise persistent intent and daemon coordination without a campus network."""

import copy
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader(
    "campus_network_integration", str(ROOT / "src" / "campus-network")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
campus_network = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = campus_network
loader.exec_module(campus_network)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds=1000):
        self.now += seconds


class Portal:
    def __init__(self):
        self.calls = []
        self.probe_result = {"kind": "portal", "query": "wlanuserip=10.0.0.1"}
        self.login_result = {"result": "success", "userIndex": "private-session-42"}
        self.logout_result = {"result": "success"}
        self.probe_started = None
        self.probe_continue = None
        self.login_started = None
        self.login_continue = None
        self.login_error = None
        self.logout_error = None

    def probe(self):
        self.calls.append(("probe",))
        if self.probe_started is not None:
            self.probe_started.set()
            if not self.probe_continue.wait(5):
                raise TimeoutError("test probe was not released")
        return dict(self.probe_result)

    def login(self, account, query):
        self.calls.append(("login", dict(account), query))
        if self.login_started is not None:
            self.login_started.set()
            if not self.login_continue.wait(5):
                raise TimeoutError("test login was not released")
        if self.login_error is not None:
            raise self.login_error
        if self.login_result.get("result") == "success":
            self.probe_result = {"kind": "online", "reason": "external probe passed"}
        return dict(self.login_result)

    def logout(self, session):
        self.calls.append(("logout", session))
        if self.logout_error is not None:
            raise self.logout_error
        return dict(self.logout_result)

    def count(self, command):
        return sum(call[0] == command for call in self.calls)


class ControllerTests(unittest.TestCase):
    account = {
        "username": "office-account",
        "password": "private-password-42",
        "service": "移动",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="campus-network-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state_dir = self.root / "state"
        self.account_path = self.root / "account.json"
        self.clock = Clock()
        self.portal = Portal()
        self.config = copy.deepcopy(campus_network.DEFAULT_CONFIG)
        self.config.update(initial_jitter=0, retry_base=2, retry_max=120)
        self.link = True

    def controller(self):
        return campus_network.Controller(
            self.config,
            self.state_dir,
            self.account_path,
            portal=self.portal,
            network=lambda: self.network(),
            clock=self.clock,
            rng=lambda low, high: low,
        )

    def network(self):
        return {
            "ready": self.link,
            "interface": "eth-test",
            "link": self.link,
            "signature": ("eth-test", self.link, "10.1.2.3", "default-route"),
            "reason": "网线未连接" if not self.link else "网络就绪",
        }

    def turn_on(self, controller):
        return controller.command({"command": "on", "account": dict(self.account)})

    def connect(self, controller):
        self.turn_on(controller)
        self.clock.advance()
        controller.step()
        self.assertEqual(controller.state["session"], "private-session-42")

    def test_default_mode_never_attempts_authentication(self):
        controller = self.controller()
        for _ in range(3):
            self.clock.advance()
            controller.step()
        self.assertEqual(controller.state["mode"], "off")
        self.assertEqual(self.portal.count("login"), 0)

    def test_enabled_mode_and_account_survive_restart(self):
        controller = self.controller()
        self.turn_on(controller)
        restarted = self.controller()
        self.assertEqual(restarted.state["mode"], "on")
        restarted.step()
        self.assertEqual(self.portal.count("login"), 1)

    def test_disabled_mode_survives_restart(self):
        controller = self.controller()
        self.turn_on(controller)
        controller.command({"command": "off"})
        restarted = self.controller()
        self.clock.advance()
        restarted.step()
        self.assertEqual(restarted.state["mode"], "off")
        self.assertEqual(self.portal.count("login"), 0)

    def test_session_survives_restart_and_can_be_released(self):
        controller = self.controller()
        self.connect(controller)
        restarted = self.controller()
        self.assertEqual(restarted.state["session"], "private-session-42")
        restarted.command({"command": "off"})
        restarted.step()
        self.assertEqual(self.portal.count("logout"), 1)
        self.assertEqual(restarted.state["session"], "")

    def test_failed_logout_preserves_session_and_disabled_intent(self):
        controller = self.controller()
        self.connect(controller)
        self.portal.logout_result = {"result": "fail", "message": "temporary failure"}
        controller.command({"command": "off"})
        controller.step()
        self.assertEqual(controller.state["mode"], "off")
        self.assertEqual(controller.state["session"], "private-session-42")
        restarted = self.controller()
        self.assertEqual(restarted.state["mode"], "off")
        self.assertEqual(restarted.state["session"], "private-session-42")

    def test_already_offline_response_completes_release(self):
        controller = self.controller()
        self.connect(controller)
        self.portal.logout_result = {"result": "fail", "message": "用户已不在线"}
        controller.command({"command": "off"})
        controller.step()
        self.assertEqual(controller.state["session"], "")

    def test_no_link_prevents_authentication(self):
        controller = self.controller()
        self.link = False
        self.turn_on(controller)
        self.clock.advance()
        controller.step()
        self.assertEqual(self.portal.count("login"), 0)
        self.link = True
        self.clock.advance()
        controller.step()
        self.assertEqual(self.portal.count("login"), 1)

    def test_external_network_failure_does_not_destroy_existing_session(self):
        controller = self.controller()
        self.connect(controller)
        self.portal.probe_result = {"kind": "unknown", "reason": "upstream unavailable"}
        self.clock.advance()
        controller.step()
        self.assertEqual(self.portal.count("login"), 1)
        self.assertEqual(self.portal.count("logout"), 0)
        self.assertEqual(controller.state["session"], "private-session-42")

    def test_off_while_login_is_in_flight_remains_durable(self):
        controller = self.controller()
        self.portal.login_started = threading.Event()
        self.portal.login_continue = threading.Event()
        self.turn_on(controller)
        self.clock.advance()
        worker_errors = []

        def step():
            try:
                controller.step()
            except BaseException as error:
                worker_errors.append(error)

        worker = threading.Thread(target=step, daemon=True)
        worker.start()
        try:
            self.assertTrue(self.portal.login_started.wait(2), "login did not start")
            command_started = time.monotonic()
            controller.command({"command": "off"})
            self.assertLess(time.monotonic() - command_started, 0.5)
            self.assertEqual(self.controller().state["mode"], "off")
        finally:
            self.portal.login_continue.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])
        self.clock.advance()
        controller.step()
        self.assertEqual(controller.state["mode"], "off")
        self.assertEqual(controller.state["session"], "")
        self.assertEqual(self.portal.count("login"), 1)
        self.assertEqual(self.portal.count("logout"), 1)

    def test_public_status_omits_credentials_and_session_token(self):
        controller = self.controller()
        self.connect(controller)
        for result in (controller.snapshot(), controller.command({"command": "status"})):
            public = json.dumps(result, ensure_ascii=False)
            self.assertNotIn(self.account["password"], public)
            self.assertNotIn("private-session-42", public)

    def test_off_during_probe_prevents_starting_login(self):
        controller = self.controller()
        self.portal.probe_started = threading.Event()
        self.portal.probe_continue = threading.Event()
        self.turn_on(controller)
        self.clock.advance()
        worker_errors = []

        def step():
            try:
                controller.step()
            except BaseException as error:
                worker_errors.append(error)

        worker = threading.Thread(target=step, daemon=True)
        worker.start()
        try:
            self.assertTrue(self.portal.probe_started.wait(2), "probe did not start")
            controller.command({"command": "off"})
        finally:
            self.portal.probe_continue.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])
        self.assertEqual(controller.state["mode"], "off")
        self.assertEqual(self.portal.count("login"), 0)

    def test_retries_have_bounded_exponential_jitter(self):
        controller = self.controller()
        self.portal.login_result = {"result": "fail", "message": "authentication unavailable"}
        self.turn_on(controller)
        for failure in range(12):
            with self.subTest(failure=failure):
                self.clock.advance()
                # Exercise both ends of the injected random range through real failures.
                controller.rng = (lambda low, high: low) if failure % 2 == 0 else (lambda low, high: high)
                controller.step()
                delay = controller.next_action - self.clock()
                ceiling = min(self.config["retry_max"], self.config["retry_base"] * 2 ** failure)
                self.assertGreaterEqual(delay, ceiling / 2)
                self.assertLessEqual(delay, ceiling)
                self.assertEqual(controller.failures, failure + 1)
        self.assertEqual(self.portal.count("login"), 12)

    def test_repeated_on_cannot_bypass_authentication_backoff(self):
        controller = self.controller()
        self.portal.login_result = {"result": "fail", "message": "busy"}
        self.turn_on(controller)
        controller.step()
        deadline, failures = controller.next_action, controller.failures
        for _ in range(10):
            controller.command({"command": "on"})
            controller.step()
        self.assertEqual(controller.next_action, deadline)
        self.assertEqual(controller.failures, failures)
        self.assertEqual(self.portal.count("login"), 1)

    def test_online_checks_do_not_reauthenticate(self):
        controller = self.controller()
        self.connect(controller)
        for _ in range(5):
            self.clock.advance()
            controller.step()
            self.assertEqual(controller.snapshot()["state"], "online")
        self.assertEqual(self.portal.count("login"), 1)
        self.assertEqual(self.portal.count("logout"), 0)

    def test_restart_does_not_claim_persisted_session_is_online(self):
        controller = self.controller()
        self.connect(controller)
        self.clock.advance()
        controller.step()
        self.assertEqual(controller.snapshot()["state"], "online")
        restarted = self.controller()
        self.assertNotEqual(restarted.snapshot()["state"], "online")
        self.assertIsNone(restarted.snapshot()["last_online"])
        restarted.step()
        self.assertEqual(restarted.snapshot()["state"], "online")
        self.assertEqual(self.portal.count("login"), 1)

    def test_logout_transport_failure_retains_pending_release(self):
        controller = self.controller()
        self.connect(controller)
        self.portal.logout_error = OSError("connection reset")
        controller.command({"command": "off"})
        controller.step()
        self.assertEqual(controller.state["mode"], "off")
        self.assertEqual(controller.state["session"], "private-session-42")
        self.assertTrue(controller.snapshot()["pending_release"])
        self.assertGreater(controller.next_action, self.clock())

    def test_login_failure_reason_redacts_password_and_control_characters(self):
        controller = self.controller()
        self.portal.login_result = {
            "result": "fail",
            "message": self.account["password"] + "\x1b[31m\ninvalid",
        }
        self.turn_on(controller)
        controller.step()
        reason = controller.snapshot()["reason"]
        self.assertNotIn(self.account["password"], reason)
        self.assertNotIn("\x1b", reason)
        self.assertNotIn("\n", reason)

    def test_corrupt_account_cannot_prevent_off_or_releasing_session(self):
        controller = self.controller()
        self.connect(controller)
        self.account_path.write_text("{corrupt", encoding="utf-8")
        controller.command({"command": "off"})
        controller.step()
        self.assertEqual(controller.state["mode"], "off")
        self.assertEqual(controller.state["session"], "")
        self.assertFalse(controller.snapshot()["configured"])

    def test_lost_login_response_remains_unconfirmed_across_restart(self):
        controller = self.controller()
        self.portal.login_error = subprocess.TimeoutExpired("curl", 5)
        self.turn_on(controller)
        controller.step()
        self.assertTrue(controller.state["uncertain"])
        restarted = self.controller()
        restarted.command({"command": "off"})
        restarted.step()
        self.assertEqual(restarted.snapshot()["state"], "release-unconfirmed")
        self.assertTrue(restarted.snapshot()["pending_release"])
        self.assertEqual(self.portal.count("login"), 1)
        self.assertEqual(self.portal.count("logout"), 0)

    def test_login_success_without_session_is_not_reported_as_released(self):
        controller = self.controller()
        self.portal.login_result = {"result": "success"}
        self.turn_on(controller)
        controller.step()
        controller.command({"command": "off"})
        controller.step()
        self.assertEqual(controller.snapshot()["state"], "release-unconfirmed")
        self.assertTrue(controller.snapshot()["pending_release"])

    def test_latest_on_intent_keeps_successful_inflight_session(self):
        controller = self.controller()
        self.portal.login_started = threading.Event()
        self.portal.login_continue = threading.Event()
        self.turn_on(controller)
        worker_errors = []

        def step():
            try:
                controller.step()
            except BaseException as error:
                worker_errors.append(error)

        worker = threading.Thread(target=step, daemon=True)
        worker.start()
        try:
            self.assertTrue(self.portal.login_started.wait(2))
            controller.command({"command": "off"})
            controller.command({"command": "on"})
        finally:
            self.portal.login_continue.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])
        self.clock.advance()
        controller.step()
        self.assertEqual(controller.state["mode"], "on")
        self.assertEqual(controller.state["session"], "private-session-42")
        self.assertFalse(controller.state["uncertain"])
        self.assertEqual(controller.snapshot()["state"], "online")
        self.assertEqual(self.portal.count("login"), 1)
        self.assertEqual(self.portal.count("logout"), 0)

    def test_numeric_failure_message_does_not_crash_worker(self):
        controller = self.controller()
        self.portal.login_result = {"result": "fail", "message": 1234}
        self.turn_on(controller)
        controller.step()
        self.assertEqual(controller.snapshot()["state"], "retrying")
        self.assertEqual(controller.snapshot()["reason"], "1234")

    def test_status_reads_do_not_forge_worker_heartbeat(self):
        controller = self.controller()
        before = controller.heartbeat
        self.clock.advance()
        self.assertEqual(controller.command({"command": "status"})["heartbeat"], before)

    def test_releasing_older_session_cannot_claim_unknown_new_session_released(self):
        controller = self.controller()
        self.connect(controller)
        self.portal.probe_result = {"kind": "portal", "query": "re-authentication"}
        self.portal.login_error = subprocess.TimeoutExpired("curl", 5)
        self.clock.advance()
        controller.step()
        self.assertTrue(controller.state["uncertain"])
        controller.command({"command": "off"})
        controller.step()
        self.assertEqual(controller.state["session"], "")
        self.assertTrue(controller.state["uncertain"])
        self.assertEqual(controller.snapshot()["state"], "release-unconfirmed")

    def test_later_explicit_login_failure_cannot_clear_older_uncertainty(self):
        controller = self.controller()
        self.portal.login_error = subprocess.TimeoutExpired("curl", 5)
        self.turn_on(controller)
        controller.step()
        self.assertTrue(controller.state["uncertain"])
        self.portal.login_error = None
        self.portal.login_result = {"result": "fail", "message": "busy"}
        self.clock.advance()
        controller.step()
        self.assertTrue(controller.state["uncertain"])

    def test_account_replacement_is_rejected_while_remote_result_is_unknown(self):
        controller = self.controller()
        self.portal.login_error = subprocess.TimeoutExpired("curl", 5)
        self.turn_on(controller)
        controller.step()
        controller.command({"command": "off"})
        with self.assertRaises(ValueError):
            controller.command({"command": "on", "account": dict(self.account, username="replacement")})


class ValidationTests(unittest.TestCase):
    def test_nonobject_portal_responses_are_rejected(self):
        portal = campus_network.Portal({})
        for payload in ([], None, True, "unexpected"):
            for action in (lambda: portal.login(ControllerTests.account, "query"), lambda: portal.logout("session")):
                with self.subTest(payload=payload):
                    with patch.object(portal, "request", return_value=(200, json.dumps(payload))):
                        with self.assertRaises(ValueError):
                            action()

    def test_unsafe_or_unbounded_timeouts_are_rejected(self):
        changes = (
            {"request_timeout": 9}, {"connect_timeout": 6}, {"initial_jitter": 31},
            {"retry_base": 121}, {"retry_max": 0}, {"check_interval": True},
            {"check_interval": float("inf")}, {"retry_base": -1},
            {"interface": "interface-name-too-long"},
            {"probe_urls": [{"url": "http://example.com", "status": 204}]},
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            for values in changes:
                with self.subTest(values=values):
                    path.write_text(json.dumps(values), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        campus_network.load_config(path)

    def test_zero_initial_jitter_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text('{"initial_jitter":0}', encoding="utf-8")
            self.assertEqual(campus_network.load_config(path)["initial_jitter"], 0)

    def test_legacy_migration_preserves_special_password_and_stays_off(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            account = root / "account.json"
            (root / "account").write_text(
                "USER=office-account\nPASS=$'first\\nsecond\\t\\\\last'\nSERVICE=移动\n",
                encoding="utf-8",
            )
            (root / "userindex").write_text("legacy-session\n", encoding="utf-8")
            campus_network.migrate_legacy(account, root)
            self.assertEqual(campus_network.read_json(account)["password"], "first\nsecond\t\\last")
            state = campus_network.read_json(root / "state.json")
            self.assertEqual(state["mode"], "off")
            self.assertEqual(state["session"], "legacy-session")
            self.assertFalse((root / "userindex").exists())

    def test_legacy_shell_values_are_never_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "must-not-exist"
            path = root / "account"
            path.write_text("PASS='$(touch " + str(marker) + ")'\n", encoding="utf-8")
            values = campus_network.shell_values(path, ("PASS",))
            self.assertIn("$(touch ", values["PASS"])
            self.assertFalse(marker.exists())


class MessageTests(unittest.TestCase):
    def test_json_object_with_newline_is_accepted(self):
        self.assertEqual(campus_network.read_message(io.BytesIO(b'{"command":"status"}\n')), {"command": "status"})

    def test_messages_require_complete_bounded_objects(self):
        for data in (b'{"command":"status"}', b'[]\n', b'null\n', b'x\n', b'{}' + b' ' * 8191 + b'\n'):
            with self.subTest(data=data[:40]):
                with self.assertRaises(ValueError):
                    campus_network.read_message(io.BytesIO(data))

    def test_maximum_length_message_is_accepted(self):
        data = b'{"x":"' + b'a' * 8183 + b'"}\n'
        self.assertEqual(len(data), 8192)
        self.assertEqual(len(campus_network.read_message(io.BytesIO(data))["x"]), 8183)


DAEMON_HARNESS = """
import os, runpy, sys
from pathlib import Path
values = runpy.run_path(sys.argv[1], run_name='campus_test_daemon')
scope = values['daemon'].__globals__
base = Path(sys.argv[2])
scope['CONFIG_DIR'] = base / 'etc'
scope['STATE_DIR'] = base / 'state'
scope['RUNTIME_DIR'] = base / 'run'
scope['os'].geteuid = lambda: 0
scope['inspect_network'] = lambda interface='': {
    'ready': False, 'link': False, 'interface': 'eth-test',
    'signature': ('eth-test', False), 'reason': 'test cable disconnected',
}
values['daemon']()
"""


@unittest.skipUnless(sys.platform == "linux", "daemon uses Linux fcntl and Unix sockets")
class DaemonSocketTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="campus-socket-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "etc").mkdir()
        (self.root / "etc/config.json").write_text("{}", encoding="utf-8")
        self.process = None
        self.addCleanup(self.stop)
        self.start()

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, "-c", DAEMON_HARNESS, str(ROOT / "src/campus-network"), str(self.root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output, errors = self.process.communicate()
                self.fail("daemon exited: " + (output + errors).decode(errors="replace"))
            try:
                self.request({"command": "status"})
                return
            except OSError:
                time.sleep(.02)
        self.fail("daemon did not open its control socket")

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(5)
            self.process.communicate()
            self.process = None

    def request(self, value):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(1)
            connection.connect(str(self.root / "run/control.sock"))
            connection.sendall((json.dumps(value, ensure_ascii=False) + "\n").encode())
            with connection.makefile("rb") as stream:
                return campus_network.read_message(stream)

    def test_control_socket_is_public_but_persistent_secrets_are_private(self):
        self.assertEqual(stat.S_IMODE((self.root / "run/control.sock").stat().st_mode), 0o666)
        result = self.request({"command": "on", "account": ControllerTests.account})
        self.assertEqual(result["mode"], "on")
        self.assertNotIn(ControllerTests.account["password"], json.dumps(result))
        for path in (self.root / "etc/account.json", self.root / "state/state.json"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_idle_socket_client_cannot_block_status_or_off(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as idle:
            idle.connect(str(self.root / "run/control.sock"))
            started = time.monotonic()
            self.assertEqual(self.request({"command": "status"})["mode"], "off")
            self.assertEqual(self.request({"command": "off"})["mode"], "off")
            self.assertLess(time.monotonic() - started, 1)

    def test_restart_retains_on_and_off_modes(self):
        self.request({"command": "on", "account": ControllerTests.account})
        self.stop()
        self.start()
        self.assertEqual(self.request({"command": "status"})["mode"], "on")
        self.request({"command": "off"})
        self.stop()
        self.start()
        self.assertEqual(self.request({"command": "status"})["mode"], "off")

    def test_corrupt_request_does_not_break_following_requests(self):
        self.assertIn("error", self.request({"command": "invalid"}))
        self.assertEqual(self.request({"command": "status"})["mode"], "off")


if __name__ == "__main__":
    unittest.main()
