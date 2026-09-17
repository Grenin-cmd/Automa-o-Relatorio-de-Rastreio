import threading
import queue
import time
import os
import sys
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("telemetry")
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

class TelemetryClient:
    def __init__(self, disabled: bool = False):
        self.disabled = disabled or os.getenv("TELEMETRY_DISABLED", "false").lower() == "true"
        self._queue = queue.Queue(maxsize=1000)
        self._worker_thread = None
        self._stop_event = threading.Event()
        self._pii_keywords = ["placa", "latitude", "longitude", "lat", "lon", "endereco", "cpf", "cliente", "email", "telefone"]
        if not self.disabled:
            self._start_worker()

    def _start_worker(self):
        try:
            self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._worker_thread.start()
            logger.info("[Telemetria] Worker de background iniciado.")
        except Exception as e:
            logger.error(f"[Telemetria] Erro ao iniciar worker: {e}")

    def _process_queue(self):
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=1.0)
                logger.info(f"[Telemetria Emitida]: {event['event_name']} | Properties: {event.get('properties', {})}")
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[Telemetria] Erro ao enviar evento: {e}")

    def _sanitize_properties(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        if not properties:
            return {}
        sanitized = {}
        for key, value in properties.items():
            key_lower = str(key).lower()
            is_sensitive = any(pii in key_lower for pii in self._pii_keywords)
            if is_sensitive:
                sanitized[key] = "[BLOQUEADO POR POLITICA DE PII]"
            else:
                sanitized[key] = value
        return sanitized

    def track(self, event_name: str, properties: Optional[Dict[str, Any]] = None):
        if self.disabled:
            return
        try:
            safe_properties = self._sanitize_properties(properties or {})
            event_payload = {
                "event_name": event_name,
                "properties": safe_properties,
                "timestamp": time.time()
            }
            self._queue.put_nowait(event_payload)
        except queue.Full:
            logger.warning("[Telemetria] Fila cheia. Evento descartado.")
        except Exception as e:
            logger.error(f"[Telemetria] Erro ao enfileirar evento: {e}")

    def stop(self):
        try:
            if self._worker_thread and self._worker_thread.is_alive():
                self._stop_event.set()
                self._worker_thread.join(timeout=2.0)
                logger.info("[Telemetria] Worker parado.")
        except Exception as e:
            logger.error(f"[Telemetria] Erro ao parar worker: {e}")

telemetry_client = TelemetryClient()

def track_event(event_name: str, properties: Optional[Dict[str, Any]] = None):
    if telemetry_client:
        telemetry_client.track(event_name, properties)