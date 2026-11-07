import socket
import ssl
import subprocess
import threading

import paho.mqtt.client as mqtt
import pytest

from bambu_mcp.printer import CertPins, _PinnedMqttClient, _printer_tls_context


def test_first_use_saves_then_mismatch_refused(tmp_path):
    pins = CertPins(tmp_path / "pins.json")
    pins.check(8883, b"cert-a")
    pins.check(8883, b"cert-a")
    with pytest.raises(ConnectionError, match="changed"):
        pins.check(8883, b"cert-b")
    pins.check(990, b"cert-b")  # each port pinned separately


def test_missing_cert_refused(tmp_path):
    with pytest.raises(ConnectionError):
        CertPins(tmp_path / "p.json").check(8883, None)


@pytest.fixture
def tls_server(tmp_path):
    """Local TLS server that records any bytes the client sends after the handshake."""
    key, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key,
         "-out", crt, "-days", "1", "-subj", "/CN=printer"],
        check=True, capture_output=True,
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    received = bytearray()

    def serve():
        conn, _ = srv.accept()
        try:
            with ctx.wrap_socket(conn, server_side=True) as tls:
                tls.settimeout(2)
                while chunk := tls.recv(1024):
                    received.extend(chunk)
        except (OSError, ssl.SSLError):
            pass

    threading.Thread(target=serve, daemon=True).start()
    yield srv.getsockname()[1], received
    srv.close()


def test_access_code_not_sent_when_pin_mismatches(tmp_path, tls_server):
    port, received = tls_server
    pins = CertPins(tmp_path / "pins.json")
    pins.path.write_text('{"8883": "' + "0" * 64 + '"}')
    client = _PinnedMqttClient(mqtt.CallbackAPIVersion.VERSION2)
    client.pins = pins
    client.username_pw_set("bblp", "SECRET-CODE")
    client.tls_set_context(_printer_tls_context())
    client.tls_insecure_set(True)
    with pytest.raises(ConnectionError, match="changed"):
        client.connect("127.0.0.1", port)
    threading.Event().wait(0.5)
    assert b"SECRET-CODE" not in received
