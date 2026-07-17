from pathlib import Path
import sqlite3

import pandas as pd


CATEGORIAS_DOCUMENTALES = [
    "Sin clasificar",
    "Operaciones",
    "Mantencion",
    "Financiero",
    "Recursos Humanos",
    "Legal",
    "Seguridad",
    "Otro",
]

ESTADOS_DOCUMENTALES = [
    "Pendiente de revision",
    "Oficial",
    "Obsoleto",
]


class CatalogoDocumentos:
    """Catalogo persistente para la curaduria de documentos PDF."""

    def __init__(self, ruta="data/catalogo_documentos.db"):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    def _conexion(self):
        return sqlite3.connect(self.ruta)

    def _inicializar(self):
        with self._conexion() as conexion:
            conexion.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogo_documentos (
                    archivo TEXT PRIMARY KEY,
                    categoria TEXT NOT NULL DEFAULT 'Sin clasificar',
                    responsable TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '',
                    estado TEXT NOT NULL DEFAULT 'Pendiente de revision',
                    fecha_vigencia TEXT NOT NULL DEFAULT '',
                    proxima_revision TEXT NOT NULL DEFAULT '',
                    ultima_modificacion TEXT NOT NULL DEFAULT '',
                    disponible INTEGER NOT NULL DEFAULT 1,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def sincronizar(self, documentos_pdf):
        """Registra altas, cambios y bajas sin sobrescribir la curaduria manual."""
        if documentos_pdf is None or documentos_pdf.empty or "Archivo" not in documentos_pdf.columns:
            documentos = pd.DataFrame(columns=["Archivo", "Fecha Modificacion"])
        else:
            columnas = ["Archivo"] + (["Fecha Modificacion"] if "Fecha Modificacion" in documentos_pdf.columns else [])
            documentos = documentos_pdf[columnas].copy()
            documentos["Archivo"] = documentos["Archivo"].fillna("").astype(str).str.strip()
            documentos = documentos[documentos["Archivo"] != ""].drop_duplicates(subset="Archivo")

        with self._conexion() as conexion:
            conexion.execute("UPDATE catalogo_documentos SET disponible = 0")

            for _, documento in documentos.iterrows():
                fecha = documento.get("Fecha Modificacion", "")
                fecha = "" if pd.isna(fecha) else str(fecha)
                conexion.execute(
                    """
                    INSERT INTO catalogo_documentos (archivo, ultima_modificacion, disponible)
                    VALUES (?, ?, 1)
                    ON CONFLICT(archivo) DO UPDATE SET
                        ultima_modificacion = excluded.ultima_modificacion,
                        disponible = 1,
                        actualizado_en = CURRENT_TIMESTAMP
                    """,
                    (documento["Archivo"], fecha),
                )

    def obtener(self):
        columnas = [
            "archivo",
            "categoria",
            "responsable",
            "version",
            "estado",
            "fecha_vigencia",
            "proxima_revision",
            "ultima_modificacion",
            "disponible",
        ]
        with self._conexion() as conexion:
            return pd.read_sql_query(
                f"SELECT {', '.join(columnas)} FROM catalogo_documentos ORDER BY archivo",
                conexion,
            )

    def guardar(self, catalogo):
        columnas_editables = [
            "categoria",
            "responsable",
            "version",
            "estado",
            "fecha_vigencia",
            "proxima_revision",
        ]
        with self._conexion() as conexion:
            for _, fila in catalogo.iterrows():
                valores = ["" if pd.isna(fila.get(columna)) else str(fila.get(columna)).strip() for columna in columnas_editables]
                conexion.execute(
                    """
                    UPDATE catalogo_documentos
                    SET categoria = ?, responsable = ?, version = ?, estado = ?,
                        fecha_vigencia = ?, proxima_revision = ?, actualizado_en = CURRENT_TIMESTAMP
                    WHERE archivo = ?
                    """,
                    (*valores, str(fila["archivo"])),
                )
