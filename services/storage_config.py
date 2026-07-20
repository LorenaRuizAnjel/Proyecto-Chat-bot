"""Configuracion centralizada y no secreta del almacenamiento."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv

from services.storage import StorageError


VALID_BACKENDS = {"oci"}


@dataclass(frozen=True)
class StorageSettings:
    backend: str
    oci_auth_mode: str
    oci_config_profile: str
    oci_bucket_name: str
    oci_namespace: str
    oci_rag_prefix: str
    oci_data_prefix: str
    oci_region: str
    oci_user_ocid: str
    oci_tenancy_ocid: str
    oci_fingerprint: str
    oci_private_key_pem: str = field(repr=False)


def load_storage_settings(project_root: str | Path | None = None) -> StorageSettings:
    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    load_dotenv(root / ".env")

    backend = os.getenv("STORAGE_BACKEND", "oci").strip().lower()
    if backend not in VALID_BACKENDS:
        raise StorageError("Este proyecto requiere STORAGE_BACKEND=oci; no existe fallback local.")

    private_key = os.getenv("OCI_PRIVATE_KEY_PEM", "")
    cloud_fields = {
        "OCI_USER_OCID": os.getenv("OCI_USER_OCID", "").strip(),
        "OCI_TENANCY_OCID": os.getenv("OCI_TENANCY_OCID", "").strip(),
        "OCI_FINGERPRINT": os.getenv("OCI_FINGERPRINT", "").strip(),
        "OCI_REGION": os.getenv("OCI_REGION", "sa-santiago-1").strip(),
        "OCI_PRIVATE_KEY_PEM": private_key.strip(),
    }
    auth_mode = os.getenv("OCI_AUTH_MODE", "auto").strip().lower()
    if auth_mode == "auto":
        auth_mode = "api_key" if all(cloud_fields.values()) else "config"
    if auth_mode not in {"config", "api_key"}:
        raise StorageError("OCI_AUTH_MODE debe ser 'auto', 'config' o 'api_key'.")

    settings = StorageSettings(
        backend=backend,
        oci_auth_mode=auth_mode,
        oci_config_profile=os.getenv("OCI_CONFIG_PROFILE", "DEFAULT").strip(),
        oci_bucket_name=os.getenv("OCI_BUCKET_NAME", "bucket-20260720-1446").strip(),
        oci_namespace=os.getenv("OCI_NAMESPACE", "axbguiv0hwl2").strip(),
        oci_rag_prefix=os.getenv("OCI_RAG_PREFIX", "data").strip(),
        oci_data_prefix=os.getenv("OCI_DATA_PREFIX", "data").strip(),
        oci_region=cloud_fields["OCI_REGION"],
        oci_user_ocid=cloud_fields["OCI_USER_OCID"],
        oci_tenancy_ocid=cloud_fields["OCI_TENANCY_OCID"],
        oci_fingerprint=cloud_fields["OCI_FINGERPRINT"],
        oci_private_key_pem=private_key,
    )
    missing = [
        name
        for name, value in (
            ("OCI_CONFIG_PROFILE", settings.oci_config_profile),
            ("OCI_BUCKET_NAME", settings.oci_bucket_name),
            ("OCI_NAMESPACE", settings.oci_namespace),
        )
        if not value
    ]
    if missing:
        raise StorageError("Falta configuracion obligatoria para OCI: " + ", ".join(missing))
    if auth_mode == "api_key":
        missing_cloud = [name for name, value in cloud_fields.items() if not value]
        if missing_cloud:
            raise StorageError(
                "Faltan secretos obligatorios para autenticar OCI en Cloud: "
                + ", ".join(missing_cloud)
            )
    return settings
