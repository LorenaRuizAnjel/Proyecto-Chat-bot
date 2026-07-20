"""Seleccion centralizada del origen y resolucion de archivos de negocio."""

from pathlib import Path

from services.oci_storage import OciObjectStorage
from services.storage import StorageBackend, StorageError
from services.storage_config import StorageSettings


def create_storage(
    settings: StorageSettings,
    *,
    cache_dir: str | Path | None = None,
    client=None,
) -> StorageBackend:
    if settings.backend == "oci":
        return OciObjectStorage(
            namespace=settings.oci_namespace,
            bucket_name=settings.oci_bucket_name,
            auth_mode=settings.oci_auth_mode,
            profile=settings.oci_config_profile,
            region=settings.oci_region,
            user_ocid=settings.oci_user_ocid,
            tenancy_ocid=settings.oci_tenancy_ocid,
            fingerprint=settings.oci_fingerprint,
            private_key_content=settings.oci_private_key_pem,
            cache_dir=cache_dir,
            client=client,
        )
    raise StorageError(f"Backend de almacenamiento no soportado: {settings.backend}")


def materialize_files(
    storage: StorageBackend,
    prefix: str,
    extension: str,
) -> tuple[list[tuple[str, str, str | None]], str]:
    """Materializa una coleccion y conserva nombres/metadatos del bucket."""
    clean_prefix = prefix.strip().replace("\\", "/").strip("/")
    normalized_extension = extension.lower()
    objects = [
        item
        for item in storage.list_objects(clean_prefix)
        if item.name.lower().endswith(normalized_extension) and item.size > 0
    ]
    if not objects:
        raise StorageError(
            f"No hay archivos {normalized_extension} bajo el prefijo OCI '{clean_prefix}'."
        )

    files = []
    version_parts = []
    for item in sorted(objects, key=lambda value: value.name):
        local_path = storage.materialize(item.name)
        display_name = item.name
        if clean_prefix and display_name.startswith(clean_prefix):
            display_name = display_name[len(clean_prefix) :].lstrip("/")
        display_name = Path(display_name).name or Path(item.name).name
        modified = item.last_modified.isoformat() if item.last_modified else None
        files.append((str(local_path), display_name, modified))
        version_parts.append(f"{item.name}:{item.size}:{item.etag or ''}:{modified or ''}")
    return files, "|".join(version_parts)


def resolve_object_name(storage: StorageBackend, prefix: str, filename: str) -> str:
    """Resuelve carpetas normales y el prefijo sin '/' usado por el bucket actual."""
    clean_prefix = prefix.strip().replace("\\", "/").strip("/")
    candidates = [filename] if not clean_prefix else [
        f"{clean_prefix}/{filename}",
        f"{clean_prefix}{filename}",
    ]
    available = {item.name for item in storage.list_objects(clean_prefix)}
    matches = [candidate for candidate in candidates if candidate in available]
    if not matches:
        raise StorageError(
            f"No se encontro {filename} bajo el prefijo configurado '{clean_prefix}'."
        )
    if len(matches) > 1:
        raise StorageError(
            f"Hay mas de un objeto posible para {filename}; configura un prefijo no ambiguo."
        )
    return matches[0]


def object_version(storage: StorageBackend, object_name: str) -> str:
    info = storage.get_object_info(object_name)
    return ":".join(
        [
            info.name,
            str(info.size),
            info.etag or "sin-etag",
            info.last_modified.isoformat() if info.last_modified else "sin-fecha",
        ]
    )
