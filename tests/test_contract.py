"""Keep the campus's verified ePortal protocol unchanged without network access."""

import importlib.machinery
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs


loader = importlib.machinery.SourceFileLoader(
    "campus_network", str(Path(__file__).resolve().parents[1] / "src" / "campus-network")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
campus_network = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = campus_network
loader.exec_module(campus_network)


class PortalContractTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "portal": "http://10.28.200.56:8080",
            "test_url": "http://1.1.1.1",
            "probe_urls": [],
        }
        self.portal = campus_network.Portal(self.config)
        self.account = {
            "username": "Z09124129",
            "password": "pass +&=% 密码",
            "service": "移动",
        }
        self.query = "wlanuserip=10.1.2.3&wlanacname=AC&ssid=a%2Bb"

    def login(self, response):
        with patch.object(
            self.portal, "request", return_value=(200, json.dumps(response))
        ) as request:
            result = self.portal.login(self.account, self.query)
        return result, request

    def test_login_preserves_verified_endpoint_and_form(self):
        response = {"result": "success", "userIndex": "session-42"}
        result, request = self.login(response)
        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(
            args[0],
            self.config["portal"] + "/eportal/InterFace.do?method=login",
        )
        self.assertEqual(
            kwargs["fields"],
            {
                "userId": self.account["username"],
                "password": self.account["password"],
                "service": "移动",
                "queryString": self.query,
                "operatorPwd": "",
                "operatorUserId": "",
                "validcode": "",
                "passwordEncrypt": "false",
            },
        )
        self.assertEqual(result, response)

    def test_login_preserves_all_verified_headers(self):
        _, request = self.login({"result": "success", "userIndex": "42"})
        self.assertEqual(
            request.call_args.kwargs["headers"],
            {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": "Mozilla/5.0 (X11; Linux aarch64)",
                "Referer": self.config["portal"] + "/eportal/index.jsp?" + self.query,
                "Origin": self.config["portal"],
            },
        )

    def test_login_returns_failure_message_without_changing_it(self):
        response = {"result": "fail", "message": "用户名或密码错误", "code": 1}
        result, _ = self.login(response)
        self.assertEqual(result, response)

    def test_all_existing_service_names_are_passed_unchanged(self):
        for service in ("移动", "电信", "联通", "校园网"):
            with self.subTest(service=service):
                self.account["service"] = service
                _, request = self.login({"result": "fail", "message": "test"})
                self.assertEqual(request.call_args.kwargs["fields"]["service"], service)

    def test_logout_preserves_endpoint_and_session_field(self):
        response = {"result": "success", "message": "下线成功"}
        with patch.object(
            self.portal, "request", return_value=(200, json.dumps(response))
        ) as request:
            result = self.portal.logout("index+with/special=chars")
        request.assert_called_once()
        self.assertEqual(
            request.call_args.args[0],
            self.config["portal"] + "/eportal/InterFace.do?method=logout",
        )
        self.assertEqual(
            request.call_args.kwargs["fields"],
            {"userIndex": "index+with/special=chars"},
        )
        self.assertEqual(result, response)

    def test_logout_preserves_already_offline_response(self):
        response = {"result": "fail", "message": "用户已不在线"}
        with patch.object(
            self.portal, "request", return_value=(200, json.dumps(response))
        ):
            self.assertEqual(self.portal.logout("old-session"), response)

    def test_probe_extracts_query_from_existing_portal_redirect(self):
        for quote in ("'", '"'):
            with self.subTest(quote=quote):
                body = (
                    "<script>top.self.location.href="
                    + quote
                    + self.config["portal"]
                    + "/eportal/index.jsp?"
                    + self.query
                    + quote
                    + ";</script>"
                )
                with patch.object(
                    self.portal, "request", return_value=(200, body)
                ) as request:
                    result = self.portal.probe()
                self.assertEqual(result["kind"], "portal")
                self.assertEqual(result["query"], self.query)
                self.assertEqual(request.call_args_list[0].args[0], self.config["test_url"])

    def test_arbitrary_http_and_unexpected_https_bodies_are_not_online(self):
        self.portal.config["probe_urls"] = [
            {"url": "https://probe-a.invalid/", "status": 200, "contains": "EXPECTED-A"},
            {"url": "https://probe-b.invalid/", "status": 200, "contains": "EXPECTED-B"},
        ]
        with patch.object(
            self.portal,
            "request",
            side_effect=[(200, "ordinary HTML"), (200, "unrelated HTML"), (500, "EXPECTED-B")],
        ):
            self.assertEqual(self.portal.probe()["kind"], "unknown")

    def test_https_redirect_even_with_expected_body_is_not_online(self):
        self.portal.config["probe_urls"] = [
            {"url": "https://probe.invalid/", "status": 200, "contains": "EXPECTED"},
        ]
        with patch.object(
            self.portal, "request", side_effect=[(200, "ordinary HTML"), (302, "EXPECTED")]
        ):
            self.assertEqual(self.portal.probe()["kind"], "unknown")

    def test_one_verified_https_probe_is_enough(self):
        self.portal.config["probe_urls"] = [
            {"url": "https://probe-a.invalid/", "status": 200, "contains": "EXPECTED-A"},
            {"url": "https://probe-b.invalid/", "status": 200, "contains": "EXPECTED-B"},
        ]
        with patch.object(
            self.portal,
            "request",
            side_effect=[OSError("unreachable"), (500, "EXPECTED-A"), (200, "before EXPECTED-B after")],
        ):
            self.assertEqual(self.portal.probe()["kind"], "online")


@unittest.skipUnless(shutil.which("curl"), "curl is required for loopback protocol tests")
class CurlLoopbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.received.append({"path": self.path, "headers": dict(self.headers), "body": b""})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"loopback only\nsecond line")

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                self.server.received.append({"path": self.path, "headers": dict(self.headers), "body": body})
                response = json.dumps({"result": "success", "userIndex": "local-session"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *_):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.received = []
        self.executions = []

        def run(command, **kwargs):
            self.executions.append((command, kwargs))
            return subprocess.run(command, **kwargs)

        self.portal = campus_network.Portal({"portal": self.base_url}, runner=run)

    def test_actual_login_form_encoding_headers_and_private_stdin(self):
        account = {"username": "测试+&= user", "password": "private secret +&=% 密码", "service": "联通"}
        query = "wlanuserip=10.1.2.3&opaque=a%2Bb%26c%3Dd"
        self.assertEqual(self.portal.login(account, query)["userIndex"], "local-session")
        received = self.server.received[0]
        self.assertEqual(received["path"], "/eportal/InterFace.do?method=login")
        self.assertEqual(
            parse_qs(received["body"].decode("ascii"), keep_blank_values=True),
            {
                "userId": [account["username"]], "password": [account["password"]],
                "service": ["联通"], "queryString": [query], "operatorPwd": [""],
                "operatorUserId": [""], "validcode": [""], "passwordEncrypt": ["false"],
            },
        )
        self.assertEqual(received["headers"]["Content-Type"], "application/x-www-form-urlencoded; charset=UTF-8")
        self.assertEqual(received["headers"]["User-Agent"], "Mozilla/5.0 (X11; Linux aarch64)")
        self.assertEqual(received["headers"]["Referer"], self.base_url + "/eportal/index.jsp?" + query)
        self.assertEqual(received["headers"]["Origin"], self.base_url)
        command, kwargs = self.executions[0]
        self.assertNotIn(account["password"], " ".join(command))
        self.assertNotIn(account["username"], " ".join(command))
        self.assertEqual(kwargs["input"], received["body"])

    def test_actual_logout_preserves_special_session_and_form_content_type(self):
        index = "session +&=%/中文"
        self.assertEqual(self.portal.logout(index)["result"], "success")
        received = self.server.received[0]
        self.assertEqual(received["path"], "/eportal/InterFace.do?method=logout")
        self.assertEqual(parse_qs(received["body"].decode("ascii")), {"userIndex": [index]})
        self.assertEqual(received["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertNotIn(index, " ".join(self.executions[0][0]))

    def test_actual_get_keeps_encoded_url_and_multiline_body(self):
        suffix = "/probe?q=a%2Bb%26c%3Dd&text=%E4%B8%AD%E6%96%87"
        status, body = self.portal.request(self.base_url + suffix)
        self.assertEqual((status, body), (200, "loopback only\nsecond line"))
        self.assertEqual(self.server.received[0]["path"], suffix)


if __name__ == "__main__":
    unittest.main()
