import re
import sqlite3
from pathlib import Path

import pandas as pd


TIPOS_CAMION = {
    "CB": "Cama Baja",
    "CC": "Camion Carro",
    "C/C": "Camion Carro",
    "CHA": "Chasis",
    "CS": "Camion simple",
    "CSP": "Camion simple pluma",
    "RA": "Rampla",
}


class LectorSQL:
    def __init__(self, ruta_archivo):
        self.ruta_archivo = Path(ruta_archivo)

    def cargar_base(self):
        tablas = self._cargar_tablas()
        viajes = self._normalizar_viajes(tablas)
        mantenciones = self._normalizar_mantenciones(tablas.get("mantenciones"))
        documentos = self._normalizar_documentos(tablas.get("documentos_rag"))

        return {
            "viajes": viajes,
            "mantenciones": mantenciones,
            "documentos": documentos,
            "conductores": tablas.get("conductores", pd.DataFrame()),
            "equipos": tablas.get("equipos", pd.DataFrame()),
        }

    def cargar_datos(self):
        return self.cargar_base()["viajes"]

    def _cargar_tablas(self):
        if not self.ruta_archivo.exists():
            raise FileNotFoundError(f"No se encontro el archivo: {self.ruta_archivo}")

        sql = self._leer_sql_compatible()

        with sqlite3.connect(":memory:") as conexion:
            conexion.executescript(sql)
            nombres = pd.read_sql_query(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
                conexion,
            )["name"].tolist()

            return {nombre: pd.read_sql_query(f'SELECT * FROM "{nombre}"', conexion) for nombre in nombres}

    def _leer_sql_compatible(self):
        sql = self.ruta_archivo.read_text(encoding="utf-8-sig")
        sql = re.sub(r"(?im)^\s*DROP\s+DATABASE\s+IF\s+EXISTS\s+[^;]+;\s*", "", sql)
        sql = re.sub(r"(?im)^\s*CREATE\s+DATABASE\s+[^;]+;\s*", "", sql)
        sql = re.sub(r"(?im)^\s*USE\s+[^;]+;\s*", "", sql)
        sql = re.sub(r"(?im)^\s*SET\s+[^;]+;\s*", "", sql)
        sql = re.sub(
            r"\bINT\s+AUTO_INCREMENT\s+PRIMARY\s+KEY\b",
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(
            r"\bINT\s+PRIMARY\s+KEY\s+AUTO_INCREMENT\b",
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(r"\)\s*ENGINE\s*=\s*[^;]+;", ");", sql, flags=re.IGNORECASE)
        sql = re.sub(r"(?is)-- Consultas de verificaci[oÃ³]n.*$", "", sql)
        return sql

    def _normalizar_viajes(self, tablas):
        frames = []

        if "viajes_materiales_redes" in tablas:
            frames.append(self._normalizar_tabla_viajes(tablas["viajes_materiales_redes"], "Materiales/redes"))

        if "viajes_cosecha" in tablas:
            frames.append(self._normalizar_tabla_viajes(tablas["viajes_cosecha"], "Cosecha"))

        if "transporte_materiales_redes" in tablas:
            frames.append(self._normalizar_tabla_legacy(tablas["transporte_materiales_redes"]))

        if not frames:
            return pd.DataFrame()

        viajes = pd.concat(frames, ignore_index=True)
        viajes["Fecha"] = pd.to_datetime(viajes["Fecha"], errors="coerce")

        columnas_texto = [
            "Fuente",
            "Centro",
            "Tipo Camion",
            "Desde",
            "Hasta",
            "Conductor",
            "Patente Tracto",
            "Patente Rampla",
            "Tipo Carga",
            "Guias",
        ]

        for columna in columnas_texto:
            viajes[columna] = viajes[columna].fillna("Sin dato").astype(str).str.strip()

        viajes["Tipo Camion"] = viajes["Tipo Camion"].replace(TIPOS_CAMION)
        viajes["Tarifa Flete"] = pd.to_numeric(viajes["Tarifa Flete"], errors="coerce").fillna(0)
        viajes["Ingreso Neto"] = viajes["Tarifa Flete"]
        viajes["Ruta"] = viajes["Desde"] + " -> " + viajes["Hasta"]
        viajes["Cantidad Guias"] = viajes["Guias"].apply(self._contar_guias)
        viajes["Costo Total"] = 0.0
        viajes["Costos Extra"] = 0.0
        viajes["Tiene Extras"] = False

        return viajes

    def _normalizar_tabla_viajes(self, datos, etiqueta_fuente):
        datos = datos.copy()

        return pd.DataFrame(
            {
                "ID": datos["id_viaje"],
                "Fuente": etiqueta_fuente,
                "Orden Control": datos["orden_control_int"],
                "Fecha": datos["fecha_salida"],
                "Centro": datos["centro"],
                "Tipo Camion": datos["tipo_camion"],
                "Desde": datos["origen"],
                "Hasta": datos["destino"],
                "Conductor": datos["conductor"],
                "Patente Tracto": datos["patente_tracto"],
                "Patente Rampla": datos["patente_rampla"],
                "Tipo Carga": etiqueta_fuente,
                "Guias": datos["guias"],
                "Tarifa Flete": datos["tarifa_flete"],
            }
        )

    def _normalizar_tabla_legacy(self, datos):
        datos = datos.copy()
        datos.columns = [self._normalizar_nombre_columna(columna) for columna in datos.columns]

        return pd.DataFrame(
            {
                "ID": datos.get("id", range(1, len(datos) + 1)),
                "Fuente": "Materiales/redes",
                "Orden Control": datos["orden_control_int"],
                "Fecha": datos.get("salida"),
                "Centro": datos["centro"],
                "Tipo Camion": datos["tipo_camion"],
                "Desde": datos["desde"],
                "Hasta": datos["hasta"],
                "Conductor": datos["conductor"],
                "Patente Tracto": datos["patente_tracto"],
                "Patente Rampla": datos["patente_rampla"],
                "Tipo Carga": datos.get("tipo_carga", "Sin dato"),
                "Guias": datos["guias"],
                "Tarifa Flete": datos["tarifa_flete"],
            }
        )

    def _normalizar_mantenciones(self, datos):
        if datos is None or datos.empty:
            return pd.DataFrame(
                columns=[
                    "ID Mantencion",
                    "ID Equipo",
                    "Patente",
                    "Fecha",
                    "Tipo Mantencion",
                    "Motivo",
                    "Costo Repuestos",
                    "Costo Mano Obra",
                    "Costo Total",
                    "Fuente",
                ]
            )

        mantenciones = datos.rename(
            columns={
                "id_mantencion": "ID Mantencion",
                "id_equipo": "ID Equipo",
                "patente": "Patente",
                "fecha": "Fecha",
                "tipo_mantencion": "Tipo Mantencion",
                "motivo": "Motivo",
                "costo_repuestos": "Costo Repuestos",
                "costo_mano_obra": "Costo Mano Obra",
                "costo_total": "Costo Total",
                "fuente": "Fuente",
            }
        ).copy()

        mantenciones["Fecha"] = pd.to_datetime(mantenciones["Fecha"], errors="coerce")
        for columna in ["Costo Repuestos", "Costo Mano Obra", "Costo Total"]:
            mantenciones[columna] = pd.to_numeric(mantenciones[columna], errors="coerce").fillna(0)

        for columna in ["Patente", "Tipo Mantencion", "Motivo", "Fuente"]:
            mantenciones[columna] = mantenciones[columna].fillna("Sin dato").astype(str).str.strip()

        return mantenciones

    def _normalizar_documentos(self, datos):
        if datos is None:
            return pd.DataFrame(columns=["Tipo Documento", "Referencia Tabla", "Referencia ID", "Contenido"])

        return datos.rename(
            columns={
                "tipo_documento": "Tipo Documento",
                "referencia_tabla": "Referencia Tabla",
                "referencia_id": "Referencia ID",
                "contenido": "Contenido",
            }
        )

    def _normalizar_nombre_columna(self, columna):
        nombre = str(columna).strip().lower()
        nombre = nombre.replace("á", "a").replace("é", "e").replace("í", "i")
        nombre = nombre.replace("ó", "o").replace("ú", "u").replace("ñ", "n")
        nombre = re.sub(r"[^a-z0-9]+", "_", nombre)
        return nombre.strip("_")

    def _contar_guias(self, guias):
        if not guias or str(guias).strip().lower() in ["sin dato", "sg"]:
            return 0

        return len([guia for guia in str(guias).replace(" - ", "-").split("-") if guia.strip()])


if __name__ == "__main__":
    base = LectorSQL("data/base_datos_chatbot_rag_transportes.sql").cargar_base()
    print(base["viajes"].head())
    print(base["mantenciones"].head())
