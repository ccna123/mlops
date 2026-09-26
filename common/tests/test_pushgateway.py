import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from ml_common import pushgateway


def test_format_declares_each_metric_once_and_escapes_labels():
    text = pushgateway.format_metrics([
        ("m_level", {"part": "feature"}, 1),
        ("m_level", {"part": 'we"ird'}, 2),
    ])
    assert text.count("# TYPE m_level gauge") == 1
    assert 'm_level{part="feature"} 1' in text
    assert 'm_level{part="we\\"ird"} 2' in text


def test_insufficient_data_is_minus_one_so_no_alert_rule_matches():
    summary = {"model_name": "m", "model_version": "4",
               "parts": {"feature": "insufficient_data", "performance": "high"},
               "consecutive_warnings": {"feature": 0, "performance": 0},
               "current_metrics": {"rmse": 150.0}, "reference_metrics": {"rmse": 100.0},
               "n_predictions": 300, "n_ground_truth": 300}
    samples = {(n, labels.get("part")): v for n, labels, v in
               pushgateway.monitoring_samples(summary)}
    assert samples[("ml_monitoring_level", "feature")] == -1
    assert samples[("ml_monitoring_level", "performance")] == 2
    assert samples[("ml_monitoring_rmse_ratio", None)] == 1.5


def test_push_without_a_url_does_nothing(monkeypatch):
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    assert pushgateway.push([("x", {}, 1)], "job", {}) is False


def test_push_puts_the_group_path_and_body():
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):  # noqa: N802
            received["path"] = self.path
            received["body"] = self.rfile.read(int(self.headers["Content-Length"])).decode()
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    ok = pushgateway.push([("x", {"a": "b"}, 3)], "monitoring", {"model_name": "m/1"},
                          url=f"http://127.0.0.1:{server.server_port}")
    thread.join()
    server.server_close()
    assert ok is True
    assert received["path"] == "/metrics/job/monitoring/model_name/m%2F1"
    assert 'x{a="b"} 3' in received["body"]


def test_an_unreachable_pushgateway_never_raises():
    assert pushgateway.push([("x", {}, 1)], "j", {}, url="http://127.0.0.1:9") is False
