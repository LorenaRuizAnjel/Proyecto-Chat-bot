"""Prueba de solo lectura para el bucket privado de OCI Object Storage."""

from pathlib import Path
import tempfile

import oci


CONFIG_PATH = Path.home() / ".oci" / "config"
PROFILE = "DEFAULT"
NAMESPACE = "axbguiv0hwl2"
BUCKET_NAME = "bucket-20260720-1446"


def main():
    config = oci.config.from_file(str(CONFIG_PATH), PROFILE)
    oci.config.validate_config(config)
    client = oci.object_storage.ObjectStorageClient(config)

    # Confirma autenticacion y acceso al bucket sin modificarlo.
    client.get_bucket(NAMESPACE, BUCKET_NAME)
    response = oci.pagination.list_call_get_all_results(
        client.list_objects,
        NAMESPACE,
        BUCKET_NAME,
        fields="name,size,etag,timeModified",
    )
    objects = response.data.objects

    print("Autenticacion OCI: correcta")
    print("Acceso de lectura al bucket: correcto")
    print(f"Objetos encontrados: {len(objects)}")
    for item in objects:
        print(item.name)

    candidate = next(
        (item for item in objects if item.name and not item.name.endswith("/") and (item.size or 0) > 0),
        None,
    )
    if candidate is None:
        raise RuntimeError("El bucket no contiene un objeto no vacio que pueda probarse.")

    temporary_path = None
    with tempfile.TemporaryDirectory(prefix="oci-read-test-") as temporary_dir:
        safe_name = Path(candidate.name.replace("\\", "/")).name
        if not safe_name or safe_name in {".", ".."}:
            raise RuntimeError("El objeto seleccionado no tiene un nombre de archivo seguro.")
        temporary_path = Path(temporary_dir) / safe_name

        object_response = client.get_object(NAMESPACE, BUCKET_NAME, candidate.name)
        with temporary_path.open("wb") as output:
            for chunk in object_response.data.raw.stream(1024 * 1024, decode_content=False):
                output.write(chunk)

        downloaded_size = temporary_path.stat().st_size
        if downloaded_size <= 0:
            raise RuntimeError("El objeto descargado esta vacio.")
        print(f"Descarga temporal: correcta ({downloaded_size} bytes)")

    print(f"Copia temporal eliminada: {not temporary_path.exists()}")


if __name__ == "__main__":
    main()
