"""Registro persistente y auditable de las ejecuciones del agente en OCI."""

from datetime import datetime, timezone
import json
import os
import re
from uuid import uuid4

from services.storage import StorageError


PROMPT_VERSION = "v1"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def extract_sources(context: str) -> list[dict]:
    """Extrae referencias documentales sin almacenar duplicados."""
    sources = []
    seen = set()

    semantic_pattern = re.compile(
        r"\barchivo=([^,\n|]+).*?\bpagina=([^,\n|]+)",
        flags=re.IGNORECASE,
    )
    for filename, page in semantic_pattern.findall(str(context or "")):
        source = {"archivo": filename.strip(), "pagina": page.strip()}
        key = (source["archivo"], source["pagina"])
        if key not in seen:
            seen.add(key)
            sources.append(source)

    simple_pattern = re.compile(
        r"Documento:\s*([^\n]+)\nSecci[oó]n:\s*([^\n]+)",
        flags=re.IGNORECASE,
    )
    for document, section in simple_pattern.findall(str(context or "")):
        page = re.search(r"-p(\d+)(?:-|$)", section, flags=re.IGNORECASE)
        source = {
            "archivo": document.strip(),
            "pagina": page.group(1) if page else None,
            "seccion": section.strip(),
        }
        key = (source["archivo"], source["pagina"] or source["seccion"])
        if key not in seen:
            seen.add(key)
            sources.append(source)

    return sources


class OciAuditLog:
    def __init__(self, storage, prefix="auditoria/ejecuciones"):
        clean_prefix = str(prefix).strip().replace("\\", "/").strip("/")
        if not clean_prefix:
            raise StorageError("OCI_AUDIT_PREFIX no puede estar vacio.")
        self.storage = storage
        self.prefix = clean_prefix

    def register(
        self,
        *,
        question,
        response,
        session_id,
        latency_ms,
        model,
        trace=None,
        status="exitoso",
        error=None,
        data_versions=None,
        execution_id=None,
    ) -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        execution_id = execution_id or str(uuid4())
        trace = trace or {}
        context = str(trace.get("contexto_recuperado", ""))
        record = {
            "schema_version": 1,
            "execution_id": execution_id,
            "timestamp_utc": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "session_id": str(session_id),
            "pregunta": str(question).strip(),
            "contexto_recuperado": context,
            "fuentes": extract_sources(context),
            "respuesta": None if response is None else str(response),
            "tipo_consulta": trace.get("tipo_consulta"),
            "metodo_respuesta": trace.get("metodo_respuesta"),
            "modelo": str(model),
            "modelo_embeddings": EMBEDDING_MODEL,
            "prompt_version": PROMPT_VERSION,
            "app_version": os.getenv("APP_VERSION", "no-configurada").strip(),
            "versiones_datos": data_versions or {},
            "latencia_ms": round(float(latency_ms), 3),
            "tokens_entrada": trace.get("tokens_entrada"),
            "tokens_salida": trace.get("tokens_salida"),
            "estado": str(status),
            "error": error,
        }
        object_name = (
            f"{self.prefix}/{now:%Y/%m/%d}/"
            f"{now:%H%M%S_%f}-{execution_id}.json"
        )
        self.storage.put_json(object_name, record)
        return execution_id, object_name

    def list_records(self, limit=100) -> tuple[list[dict], list[str]]:
        """Lee los registros mas recientes y reporta objetos que no pudo interpretar."""
        limit = max(1, min(int(limit), 500))
        prefix = f"{self.prefix}/"
        objects = [
            item
            for item in self.storage.list_objects(prefix)
            if item.name.startswith(prefix) and item.name.lower().endswith(".json")
        ]
        records = []
        failures = []
        for item in sorted(objects, key=lambda value: value.name, reverse=True)[:limit]:
            try:
                local_path = self.storage.materialize(item.name)
                record = json.loads(local_path.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("El registro no es un objeto JSON.")
                if not record.get("execution_id"):
                    raise ValueError("El registro no contiene execution_id.")
                record["_objeto_oci"] = item.name
                records.append(record)
            except Exception:
                failures.append(item.name)
        return records, failures
