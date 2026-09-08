import threading
import queue
import time
import os
import sys
import logging
from typing import Dict, Any, Optional

# Configura log básico para avisar se a telemetria falhar
logger = logging.getLogger("telemetry")
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

class TelemetryClient:
    def __init__(self, disabled: bool = False):
        self.disabled = disabled or os.getenv("TELEMETRY_DISABLED", "false").lower() == "true"
        self._queue = queue.Queue()
        self._worker_thread = None
        self._stop_event = threading.Event()

        # Palavras-chave que indicam dados sensíveis (PII) que devem ser bloqueados
        self._pii_keywords = ["placa", "latitude", "longitude", "lat", "lon", "endereco", "cpf", "cliente"]

        if not self.disabled:
            self._start_worker()

    def _start_worker(self):
        """Inicia a thread em background para não bloquear as rotas do Flask."""
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()
        logger.info("[Telemetria] Worker de background iniciado.")

    def _process_queue(self):
        """Processa os eventos da fila e envia para o servidor (simulado)."""
        while not self._stop_event.is_set():
            try:
                # Tenta pegar um evento, aguarda no máximo 1 segundo
                event = self._queue.get(timeout=1.0)
                
                # --- AQUI VOCÊ INTEGRARIA COM POSTHOG, MIXPANEL OU DATADOG ---
                # Exemplo: requests.post("https://sua-api...", json=event)
                logger.info(f"[Telemetria Emitida]: {event['event_name']} | Properties: {event['properties']}")
                
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[Telemetria Erro] Falha ao enviar evento: {e}")

    def _sanitize_properties(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Remove dados restritos (PII) antes de enviar."""
        if not properties:
            return {}
        
        sanitized = {}
        for key, value in properties.items():
            key_lower = key.lower()
            is_sensitive = any(pii in key_lower for pii in self._pii_keywords)
            
            if is_sensitive:
                sanitized[key] = "[BLOQUEADO POR POLITICA DE PII]"
            else:
                sanitized[key] = value
        return sanitized

    def track(self, event_name: str, properties: Optional[Dict[str, Any]] = None):
        """Enfileira um evento para ser enviado em background."""
        if self.disabled:
            return

        safe_properties = self._sanitize_properties(properties or {})
        
        event_payload = {
            "event_name": event_name,
            "properties": safe_properties,
            "timestamp": time.time()
        }

        try:
            # Coloca na fila sem bloquear. Se a fila estiver cheia, descarta silenciosamente
            self._queue.put_nowait(event_payload)
        except queue.Full:
            logger.warning("[Telemetria] Fila cheia. Evento descartado.")

    def stop(self):
        """Para o worker graciosamente."""
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            self._worker_thread.join(timeout=2.0)

# Instância global (Singleton) para ser importada por toda a aplicação
telemetry_client = TelemetryClient()

# Função auxiliar para importar direto
def track_event(event_name: str, properties: Optional[Dict[str, Any]] = None):
    telemetry_client.track(event_name, properties)