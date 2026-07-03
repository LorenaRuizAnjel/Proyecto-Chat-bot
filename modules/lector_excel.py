from pathlib import Path

import pandas as pd


COLUMNAS_REQUERIDAS = {
    "ID",
    "Fecha",
    "Conductor",
    "Patente",
    "Tipo Camión",
    "Ruta",
    "Cliente",
    "Carga (kg)",
    "Kilómetros",
    "Combustible (L)",
    "Entregas",
    "Incidentes",
    "Estado",
}


class LectorExcel:
    def __init__(self, ruta_archivo):
        self.ruta_archivo = Path(ruta_archivo)

    def cargar_datos(self):
        if not self.ruta_archivo.exists():
            raise FileNotFoundError(f"No se encontró el archivo: {self.ruta_archivo}")

        datos = pd.read_excel(self.ruta_archivo)
        datos.columns = [str(columna).strip() for columna in datos.columns]
        self._validar_columnas(datos)
        return self._normalizar_datos(datos)

    def _validar_columnas(self, datos):
        faltantes = sorted(COLUMNAS_REQUERIDAS - set(datos.columns))

        if faltantes:
            columnas = ", ".join(faltantes)
            raise ValueError(f"El Excel no tiene las columnas requeridas: {columnas}")

    def _normalizar_datos(self, datos):
        datos = datos.copy()
        datos["Fecha"] = pd.to_datetime(datos["Fecha"], errors="coerce")

        columnas_numericas = [
            "Carga (kg)",
            "Kilómetros",
            "Combustible (L)",
            "Entregas",
            "Incidentes",
        ]

        for columna in columnas_numericas:
            datos[columna] = pd.to_numeric(datos[columna], errors="coerce").fillna(0)

        columnas_texto = ["Conductor", "Patente", "Tipo Camión", "Ruta", "Cliente", "Estado"]

        for columna in columnas_texto:
            datos[columna] = datos[columna].fillna("Sin dato").astype(str).str.strip()

        return datos


if __name__ == "__main__":
    lector = LectorExcel("data/datos_operacionales.xlsx")
    print(lector.cargar_datos())
