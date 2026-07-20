import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.storage import StorageError, StorageObject
from services.storage_config import load_storage_settings
from services.storage_factory import resolve_object_name


class StorageSettingsTests(unittest.TestCase):
    def test_defaults_to_oci(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {}, clear=True
        ):
            settings = load_storage_settings(temp_dir)
            self.assertEqual(settings.backend, "oci")

    def test_rejects_unknown_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"STORAGE_BACKEND": "desconocido"}, clear=True
        ):
            with self.assertRaises(StorageError):
                load_storage_settings(temp_dir)

    def test_oci_requires_bucket_and_namespace(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"STORAGE_BACKEND": "oci", "OCI_BUCKET_NAME": "", "OCI_NAMESPACE": ""},
            clear=True,
        ):
            with self.assertRaises(StorageError) as context:
                load_storage_settings(temp_dir)
            self.assertIn("OCI_BUCKET_NAME", str(context.exception))
            self.assertIn("OCI_NAMESPACE", str(context.exception))

    def test_cloud_mode_reads_complete_secret_set(self):
        cloud_env = {
            "STORAGE_BACKEND": "oci",
            "OCI_AUTH_MODE": "api_key",
            "OCI_USER_OCID": "ocid1.user.test",
            "OCI_TENANCY_OCID": "ocid1.tenancy.test",
            "OCI_FINGERPRINT": "fingerprint-test",
            "OCI_REGION": "sa-santiago-1",
            "OCI_PRIVATE_KEY_PEM": "private-key-test",
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, cloud_env, clear=True
        ):
            settings = load_storage_settings(temp_dir)
            self.assertEqual(settings.oci_auth_mode, "api_key")
            self.assertNotIn("private-key-test", repr(settings))

    def test_cloud_mode_rejects_incomplete_secret_set(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"OCI_AUTH_MODE": "api_key", "OCI_USER_OCID": "user-test"}, clear=True
        ):
            with self.assertRaisesRegex(StorageError, "OCI_PRIVATE_KEY_PEM"):
                load_storage_settings(temp_dir)


class StorageFactoryTests(unittest.TestCase):
    def test_resolves_oci_folder_format(self):
        storage = Mock()
        storage.list_objects.return_value = [
            StorageObject("data/administracion.xlsx", 10)
        ]
        result = resolve_object_name(storage, "data", "administracion.xlsx")
        self.assertEqual(result, "data/administracion.xlsx")

    def test_resolves_current_oci_prefix_without_slash(self):
        storage = Mock()
        storage.list_objects.return_value = [
            StorageObject("dataadministracion.xlsx", 10)
        ]
        result = resolve_object_name(storage, "data", "administracion.xlsx")
        self.assertEqual(result, "dataadministracion.xlsx")


if __name__ == "__main__":
    unittest.main()
