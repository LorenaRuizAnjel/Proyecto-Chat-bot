from pathlib import Path

import pandas as pd


HOJAS_REQUERIDAS = {"Facturas", "Gastos", "KPIs"}

COLUMNAS_FACTURAS = {
    "Factura",
    "Fecha",
    "Cliente",
    "Servicio",
    "Monto_Neto",
    "IVA",
    "Monto_Total",
    "Estado",
    "Fecha_Pago",
}

COLUMNAS_GASTOS = {
    "ID_Gasto",
    "Fecha",
    "Categoria",
    "Proveedor",
    "Descripcion",
    "Monto",
    "Centro_Costo",
}


class LectorAdministracion:
    def __init__(self, ruta_archivo):
        self.ruta_archivo = Path(ruta_archivo)

    def cargar_datos(self):
        if not self.ruta_archivo.exists():
            raise FileNotFoundError(f"No se encontro el archivo: {self.ruta_archivo}")

        libro = pd.ExcelFile(self.ruta_archivo)
        hojas_faltantes = sorted(HOJAS_REQUERIDAS - set(libro.sheet_names))

        if hojas_faltantes:
            hojas = ", ".join(hojas_faltantes)
            raise ValueError(f"El Excel no tiene las hojas requeridas: {hojas}")

        facturas = pd.read_excel(libro, sheet_name="Facturas")
        gastos = pd.read_excel(libro, sheet_name="Gastos")
        kpis = pd.read_excel(libro, sheet_name="KPIs")

        facturas.columns = [str(columna).strip() for columna in facturas.columns]
        gastos.columns = [str(columna).strip() for columna in gastos.columns]
        kpis.columns = [str(columna).strip() for columna in kpis.columns]

        self._validar_columnas(facturas, COLUMNAS_FACTURAS, "Facturas")
        self._validar_columnas(gastos, COLUMNAS_GASTOS, "Gastos")

        return {
            "facturas": self._normalizar_facturas(facturas),
            "gastos": self._normalizar_gastos(gastos),
            "kpis": self._normalizar_kpis(kpis),
        }

    def _validar_columnas(self, datos, requeridas, hoja):
        faltantes = sorted(requeridas - set(datos.columns))

        if faltantes:
            columnas = ", ".join(faltantes)
            raise ValueError(f"La hoja {hoja} no tiene las columnas requeridas: {columnas}")

    def _normalizar_facturas(self, facturas):
        facturas = facturas.copy()
        facturas["Fecha"] = pd.to_datetime(facturas["Fecha"], errors="coerce")
        facturas["Fecha_Pago"] = pd.to_datetime(facturas["Fecha_Pago"], errors="coerce")

        for columna in ["Monto_Neto", "IVA", "Monto_Total"]:
            facturas[columna] = pd.to_numeric(facturas[columna], errors="coerce").fillna(0)

        for columna in ["Factura", "Cliente", "Servicio", "Estado"]:
            facturas[columna] = facturas[columna].fillna("Sin dato").astype(str).str.strip()

        facturas["Mes"] = facturas["Fecha"].dt.to_period("M").astype(str)
        facturas["Dias_Cobro"] = (facturas["Fecha_Pago"] - facturas["Fecha"]).dt.days
        facturas.loc[facturas["Fecha_Pago"].isna(), "Dias_Cobro"] = None

        return facturas

    def _normalizar_gastos(self, gastos):
        gastos = gastos.copy()
        gastos["Fecha"] = pd.to_datetime(gastos["Fecha"], errors="coerce")
        gastos["Monto"] = pd.to_numeric(gastos["Monto"], errors="coerce").fillna(0)

        columnas_texto = ["ID_Gasto", "Categoria", "Proveedor", "Descripcion", "Centro_Costo"]

        for columna in columnas_texto:
            gastos[columna] = gastos[columna].fillna("Sin dato").astype(str).str.strip()

        gastos["Mes"] = gastos["Fecha"].dt.to_period("M").astype(str)

        return gastos

    def _normalizar_kpis(self, kpis):
        if kpis.empty:
            return kpis

        kpis = kpis.copy()
        kpis["Indicador"] = kpis["Indicador"].fillna("Sin dato").astype(str).str.strip()
        kpis["Valor"] = pd.to_numeric(kpis["Valor"], errors="coerce").fillna(0)
        return kpis
