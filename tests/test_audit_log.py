import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.audit_log import OciAuditLog, extract_sources
from services.storage import StorageObject


class AuditLogTests(unittest.TestCase):
    def test_extracts_unique_document_sources(self):
        context = (
            "archivo=manual.pdf, pagina=4, texto=uno\n"
            "archivo=manual.pdf, pagina=4, texto=dos\n"
            "Documento: politica.pdf\nSeccion: politica-p7-control"
        )
        self.assertEqual(
            extract_sources(context),
            [
                {"archivo": "manual.pdf", "pagina": "4"},
                {"archivo": "politica.pdf", "pagina": "7", "seccion": "politica-p7-control"},
            ],
        )

    @patch("services.audit_log.datetime")
    def test_registers_complete_record_under_date_prefix(self, datetime_mock):
        datetime_mock.now.return_value = __import__("datetime").datetime(
            2026, 7, 21, 14, 30, tzinfo=__import__("datetime").timezone.utc
        )
        storage = Mock()
        audit = OciAuditLog(storage, "auditoria/ejecuciones")

        execution_id, object_name = audit.register(
            execution_id="execution-test",
            question="Pregunta",
            response="Respuesta",
            session_id="session-test",
            latency_ms=123.4567,
            model="model-test",
            trace={"contexto_recuperado": "archivo=manual.pdf, pagina=2"},
            data_versions={"sql": "etag-test"},
        )

        self.assertEqual(execution_id, "execution-test")
        self.assertTrue(object_name.startswith("auditoria/ejecuciones/2026/07/21/"))
        payload = storage.put_json.call_args.args[1]
        self.assertEqual(payload["pregunta"], "Pregunta")
        self.assertEqual(payload["fuentes"], [{"archivo": "manual.pdf", "pagina": "2"}])
        self.assertEqual(payload["versiones_datos"]["sql"], "etag-test")
        self.assertEqual(payload["estado"], "exitoso")

    def test_lists_recent_records_and_reports_invalid_objects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            newest = root / "newest.json"
            oldest = root / "oldest.json"
            invalid = root / "invalid.json"
            newest.write_text(json.dumps({"execution_id": "newest"}), encoding="utf-8")
            oldest.write_text(json.dumps({"execution_id": "oldest"}), encoding="utf-8")
            invalid.write_text("not-json", encoding="utf-8")

            storage = Mock()
            storage.list_objects.return_value = [
                StorageObject("auditoria/ejecuciones/2026/07/20/oldest.json", 1),
                StorageObject("auditoria/ejecuciones/2026/07/21/newest.json", 1),
                StorageObject("auditoria/ejecuciones/2026/07/19/invalid.json", 1),
                StorageObject("auditoria/otro.json", 1),
            ]
            paths = {
                "auditoria/ejecuciones/2026/07/21/newest.json": newest,
                "auditoria/ejecuciones/2026/07/20/oldest.json": oldest,
                "auditoria/ejecuciones/2026/07/19/invalid.json": invalid,
            }
            storage.materialize.side_effect = lambda name: paths[name]

            records, failures = OciAuditLog(storage).list_records(10)

            self.assertEqual([record["execution_id"] for record in records], ["newest", "oldest"])
            self.assertEqual(failures, ["auditoria/ejecuciones/2026/07/19/invalid.json"])


if __name__ == "__main__":
    unittest.main()
