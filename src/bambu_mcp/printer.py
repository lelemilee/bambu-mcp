"""LAN connection to the printer: MQTT for status and commands, FTPS for files.

Everything here talks only to the printer's local IP. Nothing goes to the
Bambu cloud and nothing listens on a network port.
"""

from __future__ import annotations

import copy
import ftplib
import hashlib
import json
import ssl
import threading
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from .config import Settings
from .parsing import deep_merge

MQTT_PORT = 8883
FTPS_PORT = 990
USERNAME = "bblp"


def _printer_tls_context() -> ssl.SSLContext:
    # The printer's certificate isn't signed by a public CA, so normal
    # verification can't work. Instead we pin its fingerprint (see CertPins).
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class CertPins:
    """Trust-on-first-use pinning of the printer's TLS certificate.

    The first connection saves the cert's SHA-256 fingerprint per port. After
    that, a different cert (for example someone on the Wi-Fi pretending to be
    the printer) is refused before the access code is sent. If you replace the
    printer or its firmware changes the cert, delete the pin file.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def check(self, port: int, der_cert: bytes | None) -> None:
        if not der_cert:
            raise ConnectionError("Printer sent no TLS certificate; refusing to connect.")
        fingerprint = hashlib.sha256(der_cert).hexdigest()
        pins = self._load()
        pinned = pins.get(str(port))
        if pinned is None:
            pins[str(port)] = fingerprint
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(pins, indent=2), encoding="utf-8")
        elif pinned != fingerprint:
            raise ConnectionError(
                f"Printer TLS certificate on port {port} changed. Refusing to send the "
                f"access code. If this is expected, delete {self.path} and retry."
            )


class _PinnedMqttClient(mqtt.Client):
    """paho client that checks the cert pin right after the TLS handshake,
    before the MQTT CONNECT packet (which carries the access code) is sent."""

    pins: CertPins

    def _ssl_wrap_socket(self, tcp_sock):  # paho 2.x internal hook
        ssl_sock = super()._ssl_wrap_socket(tcp_sock)
        try:
            self.pins.check(MQTT_PORT, ssl_sock.getpeercert(binary_form=True))
        except ConnectionError:
            ssl_sock.close()
            raise
        return ssl_sock


class PrinterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._state: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._got_report = threading.Event()
        self._connected = threading.Event()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self.pins = CertPins(settings.work_dir / "printer_cert_pins.json")
        self._client = _PinnedMqttClient(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"bambu-mcp-{int(time.time())}"
        )
        self._client.pins = self.pins
        self._client.username_pw_set(USERNAME, settings.access_code)
        self._client.tls_set_context(_printer_tls_context())
        # Hostname check is replaced by the cert pin (the printer has no DNS name).
        self._client.tls_insecure_set(True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = lambda *a, **k: self._connected.clear()

    @property
    def _report_topic(self) -> str:
        return f"device/{self.settings.serial}/report"

    @property
    def _request_topic(self) -> str:
        return f"device/{self.settings.serial}/request"

    # ---- connection -------------------------------------------------------

    def connect(self, timeout: float = 10) -> None:
        if self._connected.is_set():
            return
        self._client.connect(self.settings.host, MQTT_PORT, keepalive=60)
        self._client.loop_start()
        if not self._connected.wait(timeout):
            raise ConnectionError(
                "Couldn't reach the printer over MQTT. Check the IP, access code, "
                "and that LAN Only Mode / Developer Mode are on."
            )

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(self._report_topic)
            self._connected.set()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        with self._lock:
            deep_merge(self._state, payload)
        self._got_report.set()

    # ---- requests ---------------------------------------------------------

    def _publish(self, body: dict[str, Any]) -> None:
        self.connect()
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        section = next(iter(body))
        body[section]["sequence_id"] = str(seq)
        self._client.publish(self._request_topic, json.dumps(body))

    def refresh(self, timeout: float = 8) -> dict[str, Any]:
        """Ask for a full report and return the merged state."""
        self._got_report.clear()
        self._publish({"pushing": {"command": "pushall"}})
        if not self._got_report.wait(timeout):
            raise TimeoutError("Printer didn't send a report in time.")
        time.sleep(0.5)  # let the rest of the burst arrive
        with self._lock:
            return copy.deepcopy(self._state)

    def pause(self) -> None:
        self._publish({"print": {"command": "pause"}})

    def resume(self) -> None:
        self._publish({"print": {"command": "resume"}})

    def stop(self) -> None:
        self._publish({"print": {"command": "stop"}})

    def start_project(
        self, remote_name: str, plate: int, use_ams: bool, ams_mapping: list[int] | None
    ) -> None:
        """Start a sliced .gcode.3mf that is already on the printer's storage."""
        body: dict[str, Any] = {
            "print": {
                "command": "project_file",
                "param": f"Metadata/plate_{plate}.gcode",
                "url": f"ftp:///{remote_name}",
                "subtask_name": Path(remote_name).stem,
                "project_id": "0",
                "profile_id": "0",
                "task_id": "0",
                "subtask_id": "0",
                "md5": "",
                "timelapse": False,
                "bed_leveling": True,
                "flow_cali": False,
                "vibration_cali": False,
                "layer_inspect": False,
                "use_ams": use_ams,
            }
        }
        if ams_mapping is not None:
            body["print"]["ams_mapping"] = ams_mapping
        self._publish(body)

    # ---- files ------------------------------------------------------------

    def upload(self, local_path: Path, remote_name: str | None = None) -> str:
        remote_name = remote_name or local_path.name
        ftp = _ImplicitFTPS(context=_printer_tls_context())
        ftp.connect(self.settings.host, FTPS_PORT, timeout=30)
        try:
            self.pins.check(FTPS_PORT, ftp.sock.getpeercert(binary_form=True))
            ftp.login(USERNAME, self.settings.access_code)
            ftp.prot_p()
            with local_path.open("rb") as fh:
                ftp.storbinary(f"STOR {remote_name}", fh)
        finally:
            try:
                ftp.quit()
            except (ftplib.Error, OSError):
                ftp.close()
        return remote_name


class _ImplicitFTPS(ftplib.FTP_TLS):
    """FTP_TLS for servers that expect TLS straight away (port 990)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        # Reuse the control session for the data channel; Bambu's server needs it.
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, session=self.sock.session)
        return conn, size


__all__ = ["PrinterClient"]
