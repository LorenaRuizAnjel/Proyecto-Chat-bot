from pathlib import Path
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import oci

from services.oci_storage import OciObjectStorage
from services.storage import StorageError


class RawDownload:
    def __init__(self, content: bytes):
        self.content = content

    def stream(self, _chunk_size, decode_content=False):
        del decode_content
        yield self.content


def response_with(content: bytes):
    return SimpleNamespace(data=SimpleNamespace(raw=RawDownload(content)))


class OciObjectStorageTests(unittest.TestCase):
    def build_storage(self, root: str, client: Mock) -> OciObjectStorage:
        return OciObjectStorage(
            namespace="namespace-test",
            bucket_name="bucket-test",
            cache_dir=root,
            client=client,
        )

    def test_downloads_object_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = Mock()
            client.head_object.return_value = SimpleNamespace(
                headers={"content-length": "4", "etag": "etag-test"}
            )
            client.get_object.return_value = response_with(b"data")
            storage = self.build_storage(temp_dir, client)

            first = storage.materialize("data/sample.csv")
            second = storage.materialize("data/sample.csv")

            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), b"data")
            self.assertEqual(client.get_object.call_count, 1)

    def test_rejects_unsafe_object_name_before_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = Mock()
            storage = self.build_storage(temp_dir, client)
            with self.assertRaises(StorageError):
                storage.materialize("../private-key.pem")
            client.head_object.assert_not_called()

    def test_rejects_empty_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = Mock()
            client.head_object.return_value = SimpleNamespace(
                headers={"content-length": "0", "etag": "empty"}
            )
            storage = self.build_storage(temp_dir, client)
            with self.assertRaisesRegex(StorageError, "vacio"):
                storage.materialize("data/empty.pdf")
            client.get_object.assert_not_called()

    def test_translates_missing_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = Mock()
            client.head_object.side_effect = oci.exceptions.ServiceError(
                404, "ObjectNotFound", {}, "missing"
            )
            storage = self.build_storage(temp_dir, client)
            with self.assertRaisesRegex(StorageError, "no existe"):
                storage.get_object_info("data/missing.pdf")

    def test_translates_authentication_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = Mock()
            client.get_bucket.side_effect = oci.exceptions.ServiceError(
                401, "NotAuthenticated", {}, "rejected"
            )
            storage = self.build_storage(temp_dir, client)
            with self.assertRaisesRegex(StorageError, "autenticacion"):
                storage.check_access()

    def test_put_json_uploads_utf8_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = Mock()
            storage = self.build_storage(temp_dir, client)

            storage.put_json("auditoria/2026/registro.json", {"pregunta": "¿Cuántos viajes?"})

            args, kwargs = client.put_object.call_args
            self.assertEqual(args[:3], ("namespace-test", "bucket-test", "auditoria/2026/registro.json"))
            self.assertEqual(json.loads(args[3].decode("utf-8"))["pregunta"], "¿Cuántos viajes?")
            self.assertEqual(kwargs["content_type"], "application/json; charset=utf-8")

    def test_put_json_rejects_unsafe_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = Mock()
            storage = self.build_storage(temp_dir, client)
            with self.assertRaises(StorageError):
                storage.put_json("../registro.json", {})
            client.put_object.assert_not_called()

    def test_missing_config_is_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-config"
            with self.assertRaisesRegex(StorageError, "configuracion"):
                OciObjectStorage(
                    namespace="namespace-test",
                    bucket_name="bucket-test",
                    config_file=missing,
                    cache_dir=Path(temp_dir) / "cache",
                )

    def test_cloud_signer_uses_private_key_content_without_config_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "services.oci_storage.oci.signer.Signer"
        ) as signer_class, patch(
            "services.oci_storage.oci.object_storage.ObjectStorageClient"
        ) as client_class:
            signer = signer_class.return_value
            storage = OciObjectStorage(
                namespace="namespace-test",
                bucket_name="bucket-test",
                auth_mode="api_key",
                region="sa-santiago-1",
                user_ocid="user-test",
                tenancy_ocid="tenancy-test",
                fingerprint="fingerprint-test",
                private_key_content="line-1\\nline-2",
                config_file=Path(temp_dir) / "does-not-exist",
                cache_dir=Path(temp_dir) / "cache",
            )

            signer_class.assert_called_once_with(
                tenancy="tenancy-test",
                user="user-test",
                fingerprint="fingerprint-test",
                private_key_file_location=None,
                private_key_content="line-1\nline-2",
            )
            client_class.assert_called_once_with(
                {
                    "region": "sa-santiago-1",
                    "tenancy": "tenancy-test",
                    "user": "user-test",
                    "fingerprint": "fingerprint-test",
                    "key_content": "line-1\nline-2",
                },
                signer=signer,
            )
            self.assertIs(storage.client, client_class.return_value)


if __name__ == "__main__":
    unittest.main()
