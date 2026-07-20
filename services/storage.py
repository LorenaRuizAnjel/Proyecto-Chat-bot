"""Contrato comun para obtener archivos sin acoplarse a su origen."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable


class StorageError(RuntimeError):
    """Error comprensible al acceder al almacenamiento configurado."""


@dataclass(frozen=True)
class StorageObject:
    name: str
    size: int
    etag: str | None = None
    last_modified: datetime | None = None


class StorageBackend(ABC):
    @abstractmethod
    def list_objects(self, prefix: str = "") -> list[StorageObject]:
        """Lista objetos disponibles bajo un prefijo logico."""

    @abstractmethod
    def materialize(self, object_name: str) -> Path:
        """Entrega una ruta local segura y legible para un objeto."""

    @abstractmethod
    def get_object_info(self, object_name: str) -> StorageObject:
        """Obtiene metadatos de un objeto sin descargar su contenido."""

    def materialize_many(self, object_names: Iterable[str]) -> list[Path]:
        return [self.materialize(name) for name in object_names]


def validate_object_name(object_name: str) -> PurePosixPath:
    """Valida un nombre logico usando '/' como separador en todos los sistemas."""
    if not object_name or "\x00" in object_name:
        raise StorageError("El nombre del objeto esta vacio o no es valido.")

    normalized = object_name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise StorageError("El nombre del objeto contiene una ruta insegura.")
    if len(path.parts) > 0 and ":" in path.parts[0]:
        raise StorageError("El nombre del objeto contiene una ruta insegura.")
    return path
