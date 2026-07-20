"""Acceso de solo lectura a un bucket privado de OCI Object Storage."""

from datetime import datetime
import hashlib
from pathlib import Path
import tempfile

import oci

from services.storage import StorageBackend, StorageError, StorageObject, validate_object_name


class OciObjectStorage(StorageBackend):
    """Materializa objetos OCI en una cache temporal sin modificar el bucket."""

    def __init__(
        self,
        namespace: str,
        bucket_name: str,
        auth_mode: str = "config",
        profile: str = "DEFAULT",
        region: str = "",
        user_ocid: str = "",
        tenancy_ocid: str = "",
        fingerprint: str = "",
        private_key_content: str = "",
        config_file: str | Path | None = None,
        cache_dir: str | Path | None = None,
        client=None,
    ):
        if not namespace or not bucket_name:
            raise StorageError("OCI_NAMESPACE y OCI_BUCKET_NAME son obligatorios.")
        self.namespace = namespace
        self.bucket_name = bucket_name
        self.auth_mode = auth_mode
        self.profile = profile or "DEFAULT"
        self.region = region
        self.user_ocid = user_ocid
        self.tenancy_ocid = tenancy_ocid
        self.fingerprint = fingerprint
        self.private_key_content = private_key_content
        self.config_file = Path(config_file or Path.home() / ".oci" / "config").expanduser()
        self._temporary_cache = None
        if cache_dir is None:
            self._temporary_cache = tempfile.TemporaryDirectory(prefix="project-oci-cache-")
            self.cache_dir = Path(self._temporary_cache.name).resolve()
        else:
            self.cache_dir = Path(cache_dir).expanduser().resolve()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or self._create_client()

    def _create_client(self):
        if self.auth_mode == "api_key":
            return self._create_cloud_client()
        if self.auth_mode != "config":
            raise StorageError("El modo de autenticacion OCI configurado no es valido.")
        if not self.config_file.is_file():
            raise StorageError("No existe el archivo local de configuracion de OCI.")
        try:
            config = oci.config.from_file(str(self.config_file), self.profile)
            oci.config.validate_config(config)
            key_file = Path(config["key_file"]).expanduser()
            if not key_file.is_file():
                raise StorageError("La clave privada referenciada por OCI no existe.")
            return oci.object_storage.ObjectStorageClient(config)
        except StorageError:
            raise
        except oci.exceptions.InvalidConfig as error:
            raise StorageError("La configuracion local de OCI esta incompleta o no es valida.") from error
        except KeyError as error:
            raise StorageError("El perfil configurado de OCI no existe o esta incompleto.") from error
        except Exception as error:
            raise StorageError("No fue posible cargar de forma segura la configuracion local de OCI.") from error

    def _create_cloud_client(self):
        required = {
            "OCI_REGION": self.region,
            "OCI_USER_OCID": self.user_ocid,
            "OCI_TENANCY_OCID": self.tenancy_ocid,
            "OCI_FINGERPRINT": self.fingerprint,
            "OCI_PRIVATE_KEY_PEM": self.private_key_content,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise StorageError(
                "Faltan secretos obligatorios para autenticar OCI en Cloud: " + ", ".join(missing)
            )
        private_key = self.private_key_content.replace("\\n", "\n").strip()
        try:
            signer = oci.signer.Signer(
                tenancy=self.tenancy_ocid,
                user=self.user_ocid,
                fingerprint=self.fingerprint,
                private_key_file_location=None,
                private_key_content=private_key,
            )
            return oci.object_storage.ObjectStorageClient(
                {
                    "region": self.region,
                    "tenancy": self.tenancy_ocid,
                    "user": self.user_ocid,
                    "fingerprint": self.fingerprint,
                    "key_content": private_key,
                },
                signer=signer,
            )
        except Exception as error:
            raise StorageError(
                "No fue posible crear el cliente OCI con los secretos de Streamlit Cloud."
            ) from error

    def check_access(self) -> None:
        try:
            self.client.get_bucket(self.namespace, self.bucket_name)
        except Exception as error:
            raise self._translate_error(error, resource="bucket") from error

    def list_objects(self, prefix: str = "") -> list[StorageObject]:
        try:
            response = oci.pagination.list_call_get_all_results(
                self.client.list_objects,
                self.namespace,
                self.bucket_name,
                prefix=prefix or None,
                fields="name,size,etag,timeModified",
            )
        except Exception as error:
            raise self._translate_error(error, resource="bucket") from error
        return [self._to_storage_object(item) for item in response.data.objects]

    def get_object_info(self, object_name: str) -> StorageObject:
        validate_object_name(object_name)
        try:
            response = self.client.head_object(self.namespace, self.bucket_name, object_name)
        except Exception as error:
            raise self._translate_error(error, resource="object") from error
        headers = response.headers
        size = int(headers.get("content-length", 0))
        modified = headers.get("last-modified")
        return StorageObject(
            name=object_name,
            size=size,
            etag=headers.get("etag"),
            last_modified=modified if isinstance(modified, datetime) else None,
        )

    def materialize(self, object_name: str) -> Path:
        logical_path = validate_object_name(object_name)
        info = self.get_object_info(object_name)
        if info.size <= 0:
            raise StorageError(f"El objeto solicitado esta vacio: {object_name}")

        cache_key = hashlib.sha256(
            f"{object_name}\0{info.etag or info.size}".encode("utf-8")
        ).hexdigest()[:16]
        safe_name = logical_path.name
        destination = (self.cache_dir / f"{cache_key}-{safe_name}").resolve()
        try:
            destination.relative_to(self.cache_dir)
        except ValueError as error:
            raise StorageError("El objeto intenta escribirse fuera de la cache permitida.") from error
        if destination.is_file() and destination.stat().st_size == info.size:
            return destination

        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            response = self.client.get_object(self.namespace, self.bucket_name, object_name)
            with temporary.open("wb") as output:
                for chunk in response.data.raw.stream(1024 * 1024, decode_content=False):
                    output.write(chunk)
            downloaded_size = temporary.stat().st_size
            if downloaded_size <= 0:
                raise StorageError(f"El objeto descargado esta vacio: {object_name}")
            if info.size and downloaded_size != info.size:
                raise StorageError(
                    f"La descarga de {object_name} esta incompleta; se esperaban {info.size} bytes."
                )
            temporary.replace(destination)
            return destination
        except StorageError:
            if temporary.exists():
                temporary.unlink()
            raise
        except Exception as error:
            if temporary.exists():
                temporary.unlink()
            raise self._translate_error(error, resource="object") from error

    def close(self) -> None:
        if self._temporary_cache is not None:
            self._temporary_cache.cleanup()
            self._temporary_cache = None

    def _to_storage_object(self, item) -> StorageObject:
        return StorageObject(
            name=item.name,
            size=item.size or 0,
            etag=getattr(item, "etag", None),
            last_modified=getattr(item, "time_modified", None),
        )

    def _translate_error(self, error: Exception, resource: str) -> StorageError:
        if isinstance(error, oci.exceptions.ServiceError):
            status = error.status
            code = error.code or ""
            if status == 401 or code in {"NotAuthenticated", "InvalidAuthenticationInfo"}:
                return StorageError("OCI rechazo la autenticacion local. Revisa el perfil y la clave API.")
            if status == 403 or code in {"NotAuthorized", "NotAuthorizedOrNotFound"}:
                return StorageError("La identidad OCI no tiene permisos suficientes para leer el recurso.")
            if status == 404:
                if resource == "bucket":
                    return StorageError("El bucket configurado no existe o no es visible para esta identidad.")
                return StorageError("El objeto solicitado no existe en el bucket.")
            if status >= 500:
                return StorageError("OCI Object Storage no esta disponible temporalmente.")
        if isinstance(error, (TimeoutError, ConnectionError)):
            return StorageError("No fue posible conectar temporalmente con OCI Object Storage.")
        return StorageError("No fue posible leer el recurso desde OCI Object Storage.")
