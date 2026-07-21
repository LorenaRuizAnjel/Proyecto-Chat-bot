from pathlib import Path
import json
import logging
import re
import unicodedata
from time import perf_counter
from uuid import uuid4

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from modules.analizador_operacional import AnalizadorOperacional
from modules.chatbot_openrouter import (
    MODELO_OPENROUTER,
    ChatbotOpenRouter,
    ErrorModeloExterno,
)
from modules.lector_administracion import LectorAdministracion
from modules.lector_pdf import LectorPDF
from modules.lector_sql import LectorSQL
from modules.monitoreo_calidad import ESTADOS_MEJORA, MonitoreoCalidad
from modules.rag import (
    RAG,
    SemanticRAG,
    anexar_fuentes_documentales,
    contexto_documental_insuficiente,
)
from modules.catalogo_documentos import (
    CATEGORIAS_DOCUMENTALES,
    ESTADOS_DOCUMENTALES,
    CatalogoDocumentos,
)
from services import (
    StorageError,
    create_storage,
    load_storage_settings,
    materialize_files,
    object_version,
    resolve_object_name,
)
from services.audit_log import OciAuditLog


NOMBRE_SQL = "base_datos_chatbot_rag_transportes.sql"
NOMBRE_ADMINISTRACION = "administracion.xlsx"
RUTA_ESTADO_LOCAL = ".runtime"
RUTA_CATALOGO_DOCUMENTOS = f"{RUTA_ESTADO_LOCAL}/catalogo_documentos.db"
RUTA_MONITOREO_CALIDAD = f"{RUTA_ESTADO_LOCAL}/operacion_agente.db"
RUTA_INDICE_DOCUMENTAL = f"{RUTA_ESTADO_LOCAL}/indice_documental"


load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


st.set_page_config(
    page_title="Panel de gestión operacional",
    page_icon="📊",
    layout="wide",
)


@st.cache_resource(show_spinner=False)
def obtener_almacenamiento(configuracion):
    return create_storage(configuracion)


@st.cache_data(show_spinner=False)
def cargar_base(ruta_archivo, version_objeto):
    del version_objeto
    lector = LectorSQL(ruta_archivo)
    return lector.cargar_base()


@st.cache_data(show_spinner=False)
def cargar_administracion(ruta_archivo, version_objeto):
    del version_objeto
    lector = LectorAdministracion(ruta_archivo)
    return lector.cargar_datos()


@st.cache_data(show_spinner=False)
def cargar_documentos_pdf(archivos, version_objetos):
    del version_objetos
    return LectorPDF().cargar_archivos(archivos)


def _reiniciar_filtros(prefijo, campos):
    if st.button("Limpiar filtros", key=f"{prefijo}_limpiar"):
        for campo in campos:
            st.session_state.pop(f"{prefijo}_{campo}", None)
        st.rerun()


def _rango_fechas(datos, clave, etiqueta="Período"):
    fechas = pd.to_datetime(datos.get("Fecha"), errors="coerce").dropna()
    if fechas.empty:
        return None, None, False

    inicio = fechas.min().date()
    fin = fechas.max().date()
    seleccionado = st.date_input(etiqueta, value=(inicio, fin), key=clave)
    if not isinstance(seleccionado, (tuple, list)) or len(seleccionado) != 2:
        return inicio, fin, False

    desde, hasta = seleccionado
    activo = desde != inicio or hasta != fin
    return pd.Timestamp(desde), pd.Timestamp(hasta), activo


def _resumen_filtros(cantidad):
    texto = "Sin filtros activos" if not cantidad else f"{cantidad} filtro(s) activo(s)"
    st.caption(f"{texto}. Los indicadores, gráficos y tablas de esta vista respetan esta selección.")


def aplicar_filtros_viajes(viajes, prefijo="viajes"):
    if viajes.empty:
        return viajes, 0

    with st.expander("Filtros de viajes", expanded=True):
        _reiniciar_filtros(prefijo, ["periodo", "fuentes", "centros", "conductores", "tipos", "origenes", "destinos"])
        col_periodo, col_fuente, col_centro = st.columns(3)
        with col_periodo:
            desde, hasta, periodo_activo = _rango_fechas(viajes, f"{prefijo}_periodo")
        with col_fuente:
            fuentes = st.multiselect("Fuente", sorted(viajes["Fuente"].unique()), key=f"{prefijo}_fuentes")
        with col_centro:
            centros = st.multiselect("Centro", sorted(viajes["Centro"].unique()), key=f"{prefijo}_centros")

        col_conductor, col_camion, col_origen, col_destino = st.columns(4)
        with col_conductor:
            conductores = st.multiselect("Conductor", sorted(viajes["Conductor"].unique()), key=f"{prefijo}_conductores")
        with col_camion:
            tipos_camion = st.multiselect("Tipo de camión", sorted(viajes["Tipo Camion"].unique()), key=f"{prefijo}_tipos")
        with col_origen:
            origenes = st.multiselect("Origen", sorted(viajes["Desde"].unique()), key=f"{prefijo}_origenes")
        with col_destino:
            destinos = st.multiselect("Destino", sorted(viajes["Hasta"].unique()), key=f"{prefijo}_destinos")

    filtrados = viajes.copy()
    if desde is not None:
        filtrados = filtrados[filtrados["Fecha"].between(desde, hasta)]
    for columna, seleccion in [
        ("Fuente", fuentes),
        ("Centro", centros),
        ("Conductor", conductores),
        ("Tipo Camion", tipos_camion),
        ("Desde", origenes),
        ("Hasta", destinos),
    ]:
        if seleccion:
            filtrados = filtrados[filtrados[columna].isin(seleccion)]

    activos = sum(bool(valor) for valor in [periodo_activo, fuentes, centros, conductores, tipos_camion, origenes, destinos])
    return filtrados, activos


def aplicar_filtros_mantenciones(mantenciones, prefijo="mantenciones"):
    if mantenciones.empty:
        st.info("No hay mantenciones disponibles para filtrar.")
        return mantenciones, 0

    with st.expander("Filtros de mantenciones", expanded=True):
        _reiniciar_filtros(prefijo, ["periodo", "patentes", "tipos"])
        col_periodo, col_patente, col_tipo = st.columns(3)
        with col_periodo:
            desde, hasta, periodo_activo = _rango_fechas(mantenciones, f"{prefijo}_periodo")
        with col_patente:
            patentes = st.multiselect("Patente", sorted(mantenciones["Patente"].unique()), key=f"{prefijo}_patentes")
        with col_tipo:
            tipos = st.multiselect("Tipo de mantención", sorted(mantenciones["Tipo Mantencion"].unique()), key=f"{prefijo}_tipos")

    filtradas = mantenciones.copy()
    if desde is not None:
        filtradas = filtradas[filtradas["Fecha"].between(desde, hasta)]
    if patentes:
        filtradas = filtradas[filtradas["Patente"].isin(patentes)]
    if tipos:
        filtradas = filtradas[filtradas["Tipo Mantencion"].isin(tipos)]

    activos = sum(bool(valor) for valor in [periodo_activo, patentes, tipos])
    return filtradas, activos


def calcular_kpis_viajes(viajes):
    viajes_vacios = viajes is None or viajes.empty
    ingreso_neto = 0 if viajes_vacios else float(viajes["Ingreso Neto"].sum())

    return {
        "viajes": 0 if viajes_vacios else int(len(viajes)),
        "ingreso_neto": ingreso_neto,
        "guias": 0 if viajes_vacios else int(viajes["Cantidad Guias"].sum()),
        "fuentes_viajes": 0 if viajes_vacios else int(viajes["Fuente"].nunique()),
    }


def calcular_kpis_flota(mantenciones):
    mantenciones_vacias = mantenciones is None or mantenciones.empty
    cantidad = 0 if mantenciones_vacias else int(len(mantenciones))
    costo_total = 0 if mantenciones_vacias else float(mantenciones["Costo Total"].sum())
    costo_promedio = costo_total / cantidad if cantidad else 0
    vehiculos = 0 if mantenciones_vacias else int(mantenciones["Patente"].nunique())

    return {
        "mantenciones": cantidad,
        "costo_mantenciones": costo_total,
        "costo_promedio_mantencion": costo_promedio,
        "vehiculos_con_mantencion": vehiculos,
    }


def mostrar_kpis(kpis_viajes, kpis_flota, filtros_mantenciones_activos=False):
    resultado_neto_estimado = kpis_viajes["ingreso_neto"] - kpis_flota["costo_mantenciones"]

    st.subheader("Indicadores según filtros de viajes")
    st.caption("Estos indicadores cambian según los filtros de viajes seleccionados.")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Viajes", f"{kpis_viajes['viajes']:.0f}")
    col2.metric("Ingreso neto", f"${kpis_viajes['ingreso_neto']:,.0f}")
    col3.metric("Resultado neto estimado", f"${resultado_neto_estimado:,.0f}")
    col4.metric("Guias", f"{kpis_viajes['guias']:,.0f}")
    col5.metric("Fuentes viajes", f"{kpis_viajes['fuentes_viajes']:.0f}")

    st.caption("Resultado neto estimado: ingreso neto menos costo de mantenciones visibles.")

    st.subheader("Indicadores generales de flota")
    if filtros_mantenciones_activos:
        st.caption(
            "Estos indicadores corresponden a mantenciones de la flota filtradas por patente o tipo de mantencion; "
            "no se atribuyen directamente al conductor seleccionado."
        )
    else:
        st.caption(
            "Estos indicadores corresponden a mantenciones de la flota y no se atribuyen directamente al conductor seleccionado."
        )

    col6, col7, col8, col9 = st.columns(4)
    col6.metric("Mantenciones totales", f"{kpis_flota['mantenciones']:.0f}")
    col7.metric("Costo mantenciones flota", f"${kpis_flota['costo_mantenciones']:,.0f}")
    col8.metric("Costo promedio por mantencion", f"${kpis_flota['costo_promedio_mantencion']:,.0f}")
    col9.metric("Vehiculos/patentes con mantencion", f"{kpis_flota['vehiculos_con_mantencion']:.0f}")


def texto_periodo(datos):
    fechas = pd.to_datetime(datos.get("Fecha"), errors="coerce").dropna()
    if fechas.empty:
        return "Sin fechas disponibles"
    return f"{fechas.min():%d-%m-%Y} al {fechas.max():%d-%m-%Y}"


def evolucion_operacional(viajes, mantenciones):
    ingresos = pd.DataFrame(columns=["Mes", "Ingresos operacionales"])
    costos = pd.DataFrame(columns=["Mes", "Costos de mantención"])
    if not viajes.empty:
        ingresos = viajes.assign(Mes=viajes["Fecha"].dt.to_period("M").astype(str)).groupby("Mes", as_index=False)["Ingreso Neto"].sum()
        ingresos = ingresos.rename(columns={"Ingreso Neto": "Ingresos operacionales"})
    if not mantenciones.empty:
        costos = mantenciones.assign(Mes=mantenciones["Fecha"].dt.to_period("M").astype(str)).groupby("Mes", as_index=False)["Costo Total"].sum()
        costos = costos.rename(columns={"Costo Total": "Costos de mantención"})

    mensual = pd.merge(ingresos, costos, on="Mes", how="outer").fillna(0)
    if mensual.empty:
        return mensual
    return mensual.sort_values("Mes")


def grafico_evolucion_operacional(datos, alto=340):
    datos_largos = datos.melt("Mes", var_name="Indicador", value_name="Monto")
    return (
        alt.Chart(datos_largos)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=70), strokeWidth=3)
        .encode(
            x=alt.X("Mes:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Monto:Q", title="Monto (CLP)", axis=alt.Axis(format="~s", grid=True)),
            color=alt.Color(
                "Indicador:N",
                scale=alt.Scale(
                    domain=["Ingresos operacionales", "Costos de mantención"],
                    range=["#287271", "#e76f51"],
                ),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("Mes:N", title="Mes"),
                alt.Tooltip("Indicador:N", title="Indicador"),
                alt.Tooltip("Monto:Q", title="Monto", format=",.0f"),
            ],
        )
        .properties(height=alto)
        .configure_view(strokeWidth=0)
    )


def obtener_alertas(facturas, catalogo_documentos, mantenciones, monitoreo_calidad):
    alertas = []
    if not facturas.empty:
        pendientes = facturas[facturas["Estado"].str.lower() == "pendiente"]
        if not pendientes.empty:
            monto = float(pendientes["Monto_Total"].sum())
            alertas.append(("Facturas pendientes", f"{len(pendientes)} factura(s) pendiente(s) por {formato_pesos(monto)}."))

    if not catalogo_documentos.empty:
        pendientes_revision = int((catalogo_documentos["estado"] == "Pendiente de revision").sum())
        if pendientes_revision:
            alertas.append(("Curaduría documental", f"{pendientes_revision} documento(s) pendiente(s) de revisión."))

    if monitoreo_calidad is not None:
        negativos = monitoreo_calidad.feedback_negativo(limite=1000)
        if not negativos.empty:
            alertas.append(("Calidad del asistente", f"{len(negativos)} respuesta(s) con feedback negativo requieren revisión."))

    if not mantenciones.empty:
        costos = mantenciones.groupby("Patente", dropna=False)["Costo Total"].sum().sort_values(ascending=False)
        if len(costos) >= 2:
            umbral = costos.quantile(0.75)
            criticos = costos[costos >= umbral]
            if not criticos.empty:
                patentes = ", ".join(criticos.head(3).index.astype(str))
                alertas.append(("Costos de mantención", f"Patentes sobre el percentil 75 de costo acumulado: {patentes}."))
    return alertas


def mostrar_resumen(viajes, mantenciones, facturas, catalogo_documentos, monitoreo_calidad):
    st.title("Panel de gestión operacional")
    col_titulo, col_accion = st.columns([5, 1])
    with col_titulo:
        st.caption(f"Período operativo analizado: {texto_periodo(viajes)} · Vista sin filtros")
        st.caption(f"Última actualización de la vista: {pd.Timestamp.now():%d-%m-%Y %H:%M}")
    with col_accion:
        if st.button("Actualizar datos", key="resumen_actualizar"):
            cargar_base.clear()
            cargar_administracion.clear()
            cargar_documentos_pdf.clear()
            st.rerun()

    kpis_viajes = calcular_kpis_viajes(viajes)
    kpis_flota = calcular_kpis_flota(mantenciones)
    ingreso = kpis_viajes["ingreso_neto"]
    costos = kpis_flota["costo_mantenciones"]
    resultado = ingreso - costos
    margen = (resultado / ingreso * 100) if ingreso else 0

    kpi_viajes, kpi_ingreso, kpi_costos, kpi_resultado, kpi_margen = st.columns(5)
    kpi_viajes.metric("Viajes realizados", f"{kpis_viajes['viajes']:,}", help="Dato real de viajes registrados.")
    kpi_ingreso.metric("Ingresos operacionales", formato_pesos(ingreso), help="Ingreso neto proveniente de viajes registrados.")
    kpi_costos.metric("Costos de mantención", formato_pesos(costos), help="Costo total de mantenciones registradas.")
    kpi_resultado.metric("Resultado operacional estimado", formato_pesos(resultado), help="Ingresos operacionales menos costos de mantención.")
    kpi_margen.metric("Margen operacional", formato_porcentaje(margen), help="Resultado operacional estimado dividido por ingresos operacionales.")
    st.caption(
        "Valores en CLP · datos sin filtros. El resultado y margen son estimaciones operacionales: no representan utilidad contable ni incorporan gastos administrativos, impuestos o devengos."
    )

    col_evolucion, col_alertas = st.columns([3, 2])
    with col_evolucion:
        st.subheader("Evolución operacional")
        mensual = evolucion_operacional(viajes, mantenciones)
        if mensual.empty:
            st.info("No hay información mensual suficiente para mostrar la evolución.")
        else:
            st.altair_chart(grafico_evolucion_operacional(mensual), width="stretch")
        st.caption("Ingresos de viajes y costos de mantención se presentan como componentes operacionales, no como cifras contables equivalentes.")
    with col_alertas:
        st.subheader("Situaciones que requieren atención")
        alertas = obtener_alertas(facturas, catalogo_documentos, mantenciones, monitoreo_calidad)
        if not alertas:
            st.success("No hay alertas relevantes con la información disponible.")
        else:
            for titulo, detalle in alertas[:4]:
                st.warning(f"{titulo}: {detalle}")

    col_actividad, col_flota = st.columns(2)
    with col_actividad:
        st.subheader("Actividad operacional reciente")
        if viajes.empty:
            st.info("No hay viajes recientes disponibles.")
        else:
            columnas = ["Fecha", "Centro", "Conductor", "Ruta", "Ingreso Neto"]
            st.dataframe(viajes.sort_values("Fecha", ascending=False).head(5)[columnas], hide_index=True, width="stretch")
            if st.button("Ver detalle de viajes", key="resumen_ver_viajes"):
                st.session_state.seccion_principal = "Operaciones"
                st.session_state.operaciones_seccion = "Viajes"
                st.rerun()
    with col_flota:
        st.subheader("Estado resumido de la flota")
        if mantenciones.empty:
            st.info("No hay mantenciones disponibles.")
        else:
            flota = mantenciones.groupby("Patente", as_index=False).agg(Mantenciones=("ID Mantencion", "count"), Costo_Total=("Costo Total", "sum"))
            flota = flota.sort_values("Costo_Total", ascending=False).head(5).rename(columns={"Costo_Total": "Costo total"})
            st.dataframe(flota, hide_index=True, width="stretch")
            if st.button("Ver detalle de mantenciones", key="resumen_ver_mantenciones"):
                st.session_state.seccion_principal = "Operaciones"
                st.session_state.operaciones_seccion = "Mantenciones"
                st.rerun()


def formato_pesos(valor):
    return f"${valor:,.0f}"


def formato_porcentaje(valor):
    return f"{valor:.1f}%"


def grafico_barras_horizontales(datos, categoria, valor, titulo_valor, esquema="tealblues", alto=340):
    base = alt.Chart(datos).encode(
        y=alt.Y(
            f"{categoria}:N",
            sort="-x",
            title=None,
            axis=alt.Axis(labelLimit=220),
        ),
        x=alt.X(
            f"{valor}:Q",
            title=titulo_valor,
            axis=alt.Axis(format="~s", grid=True),
        ),
    )

    barras = base.mark_bar(cornerRadiusEnd=8, height={"band": 0.62}).encode(
        color=alt.Color(
            f"{valor}:Q",
            scale=alt.Scale(scheme=esquema),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip(f"{categoria}:N", title=categoria),
            alt.Tooltip(f"{valor}:Q", title=titulo_valor, format=",.0f"),
        ],
    )

    etiquetas = base.mark_text(
        align="left",
        baseline="middle",
        dx=6,
        color="#263238",
        fontSize=12,
    ).encode(
        text=alt.Text(f"{valor}:Q", format=",.0f"),
    )

    return (barras + etiquetas).properties(height=alto).configure_view(strokeWidth=0)


def grafico_linea(datos, x, y, titulo_y, color="#2a9d8f", alto=320):
    linea = (
        alt.Chart(datos)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=80), strokeWidth=3, color=color)
        .encode(
            x=alt.X(f"{x}:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{y}:Q", title=titulo_y, axis=alt.Axis(format="~s", grid=True)),
            tooltip=[
                alt.Tooltip(f"{x}:N", title=x),
                alt.Tooltip(f"{y}:Q", title=titulo_y, format=",.0f"),
            ],
        )
        .properties(height=alto)
        .configure_view(strokeWidth=0)
    )
    return linea


def grafico_donut(datos, categoria, valor, esquema="tableau20", alto=320, titulo_valor="Ingreso neto"):
    return (
        alt.Chart(datos)
        .mark_arc(innerRadius=70, outerRadius=120, stroke="white", strokeWidth=2)
        .encode(
            theta=alt.Theta(f"{valor}:Q"),
            color=alt.Color(f"{categoria}:N", scale=alt.Scale(scheme=esquema), legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip(f"{categoria}:N", title=categoria),
                alt.Tooltip(f"{valor}:Q", title=titulo_valor, format=",.0f"),
            ],
        )
        .properties(height=alto)
        .configure_view(strokeWidth=0)
    )


def grafico_lineas_financieras(datos, alto=340):
    datos_largos = datos.melt(
        id_vars="Mes",
        value_vars=["Facturacion", "Gastos", "Utilidad"],
        var_name="Indicador",
        value_name="Monto",
    )

    return (
        alt.Chart(datos_largos)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=70), strokeWidth=3)
        .encode(
            x=alt.X("Mes:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Monto:Q", title="Monto", axis=alt.Axis(format="~s", grid=True)),
            color=alt.Color(
                "Indicador:N",
                scale=alt.Scale(
                    domain=["Facturacion", "Gastos", "Utilidad"],
                    range=["#287271", "#e76f51", "#2a9d8f"],
                ),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("Mes:N", title="Mes"),
                alt.Tooltip("Indicador:N", title="Indicador"),
                alt.Tooltip("Monto:Q", title="Monto", format=",.0f"),
            ],
        )
        .properties(height=alto)
        .configure_view(strokeWidth=0)
    )


def filtrar_administracion(facturas, gastos, prefijo="finanzas"):
    if facturas.empty and gastos.empty:
        return facturas, gastos, 0

    datos_periodo = pd.concat(
        [datos[["Fecha"]] for datos in [facturas, gastos] if not datos.empty],
        ignore_index=True,
    )

    with st.expander("Filtros de finanzas", expanded=True):
        _reiniciar_filtros(
            prefijo,
            ["periodo", "clientes", "estados", "categorias", "servicios", "centros", "proveedores"],
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            desde, hasta, periodo_activo = _rango_fechas(datos_periodo, f"{prefijo}_periodo")
        with col2:
            clientes = st.multiselect("Cliente", sorted(facturas["Cliente"].unique()), key=f"{prefijo}_clientes")
        with col3:
            estados = st.multiselect("Estado de factura", sorted(facturas["Estado"].unique()), key=f"{prefijo}_estados")

        col4, col5, col6, col7 = st.columns(4)
        with col4:
            categorias = st.multiselect("Categoría de gasto", sorted(gastos["Categoria"].unique()), key=f"{prefijo}_categorias")
        with col5:
            servicios = st.multiselect("Servicio", sorted(facturas["Servicio"].unique()), key=f"{prefijo}_servicios")
        with col6:
            centros = st.multiselect("Centro de costo", sorted(gastos["Centro_Costo"].unique()), key=f"{prefijo}_centros")
        with col7:
            proveedores = st.multiselect("Proveedor", sorted(gastos["Proveedor"].unique()), key=f"{prefijo}_proveedores")

    facturas_filtradas = facturas.copy()
    gastos_filtrados = gastos.copy()

    if desde is not None:
        facturas_filtradas = facturas_filtradas[facturas_filtradas["Fecha"].between(desde, hasta)]
        gastos_filtrados = gastos_filtrados[gastos_filtrados["Fecha"].between(desde, hasta)]

    if clientes:
        facturas_filtradas = facturas_filtradas[facturas_filtradas["Cliente"].isin(clientes)]

    if estados:
        facturas_filtradas = facturas_filtradas[facturas_filtradas["Estado"].isin(estados)]

    if servicios:
        facturas_filtradas = facturas_filtradas[facturas_filtradas["Servicio"].isin(servicios)]

    if categorias:
        gastos_filtrados = gastos_filtrados[gastos_filtrados["Categoria"].isin(categorias)]

    if centros:
        gastos_filtrados = gastos_filtrados[gastos_filtrados["Centro_Costo"].isin(centros)]

    if proveedores:
        gastos_filtrados = gastos_filtrados[gastos_filtrados["Proveedor"].isin(proveedores)]

    activos = sum(bool(valor) for valor in [periodo_activo, clientes, estados, categorias, servicios, centros, proveedores])
    return facturas_filtradas, gastos_filtrados, activos


def mostrar_administracion(facturas, gastos, kpis_excel):
    if facturas.empty and gastos.empty:
        st.info("No hay datos administrativos disponibles.")
        return

    facturas_filtradas, gastos_filtrados, filtros_activos = filtrar_administracion(facturas, gastos)
    _resumen_filtros(filtros_activos)

    ingresos = float(facturas_filtradas["Monto_Neto"].sum()) if not facturas_filtradas.empty else 0
    gastos_total = float(gastos_filtrados["Monto"].sum()) if not gastos_filtrados.empty else 0
    utilidad = ingresos - gastos_total
    margen = (utilidad / ingresos * 100) if ingresos else 0
    pendiente = (
        float(facturas_filtradas.loc[facturas_filtradas["Estado"].str.lower() == "pendiente", "Monto_Total"].sum())
        if not facturas_filtradas.empty
        else 0
    )
    pagado = (
        float(facturas_filtradas.loc[facturas_filtradas["Estado"].str.lower() == "pagada", "Monto_Total"].sum())
        if not facturas_filtradas.empty
        else 0
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Facturación neta", formato_pesos(ingresos), help="Dato administrativo proveniente de facturas.")
    col2.metric("Gastos", formato_pesos(gastos_total))
    col3.metric("Resultado administrativo", formato_pesos(utilidad), help="Facturación neta menos gastos registrados en esta vista.")
    col4.metric("Margen", formato_porcentaje(margen))

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Facturas", f"{len(facturas_filtradas):,.0f}")
    col6.metric("Pendiente de cobro", formato_pesos(pendiente))
    col7.metric("Cobrado total", formato_pesos(pagado))
    col8.metric("Gastos registrados", f"{len(gastos_filtrados):,.0f}")

    if not kpis_excel.empty:
        st.caption("KPIs consolidados del archivo administracion.xlsx")
        columnas = st.columns(min(len(kpis_excel), 6))
        for indice, fila in kpis_excel.head(6).iterrows():
            columnas[indice % len(columnas)].metric(str(fila["Indicador"]), f"{fila['Valor']:,.0f}")

    st.divider()

    facturacion_mes = (
        facturas_filtradas.groupby("Mes", dropna=False)["Monto_Neto"].sum().reset_index(name="Facturacion")
        if not facturas_filtradas.empty
        else None
    )
    gastos_mes = (
        gastos_filtrados.groupby("Mes", dropna=False)["Monto"].sum().reset_index(name="Gastos")
        if not gastos_filtrados.empty
        else None
    )

    if facturacion_mes is not None or gastos_mes is not None:
        meses = sorted(
            set([] if facturacion_mes is None else facturacion_mes["Mes"])
            | set([] if gastos_mes is None else gastos_mes["Mes"])
        )
        mensual = pd.DataFrame({"Mes": meses})

        if facturacion_mes is not None:
            mensual = mensual.merge(facturacion_mes, on="Mes", how="left")
        else:
            mensual["Facturacion"] = 0

        if gastos_mes is not None:
            mensual = mensual.merge(gastos_mes, on="Mes", how="left")
        else:
            mensual["Gastos"] = 0

        mensual[["Facturacion", "Gastos"]] = mensual[["Facturacion", "Gastos"]].fillna(0)
        mensual["Utilidad"] = mensual["Facturacion"] - mensual["Gastos"]

        st.subheader("Evolucion financiera mensual")
        st.altair_chart(grafico_lineas_financieras(mensual), width="stretch")

    col9, col10 = st.columns(2)
    with col9:
        st.subheader("Facturacion por cliente")
        if facturas_filtradas.empty:
            st.info("No hay facturas para los filtros seleccionados.")
        else:
            clientes = (
                facturas_filtradas.groupby("Cliente", dropna=False)["Monto_Neto"]
                .sum()
                .sort_values(ascending=False)
                .head(10)
                .reset_index(name="Monto_Neto")
            )
            st.altair_chart(
                grafico_barras_horizontales(clientes, "Cliente", "Monto_Neto", "Facturacion neta", "greens"),
                width="stretch",
            )

    with col10:
        st.subheader("Gastos por categoria")
        if gastos_filtrados.empty:
            st.info("No hay gastos para los filtros seleccionados.")
        else:
            categorias = (
                gastos_filtrados.groupby("Categoria", dropna=False)["Monto"]
                .sum()
                .sort_values(ascending=False)
                .reset_index(name="Monto")
            )
            st.altair_chart(
                grafico_barras_horizontales(categorias, "Categoria", "Monto", "Gastos", "orangered"),
                width="stretch",
            )

    col11, col12 = st.columns(2)
    with col11:
        st.subheader("Facturas por estado")
        if facturas_filtradas.empty:
            st.info("No hay estados para graficar.")
        else:
            estados = (
                facturas_filtradas.groupby("Estado", dropna=False)["Monto_Total"]
                .sum()
                .reset_index(name="Monto_Total")
            )
            st.altair_chart(
                grafico_donut(estados, "Estado", "Monto_Total", alto=320, titulo_valor="Monto total"),
                width="stretch",
            )

    with col12:
        st.subheader("Gastos por centro de costo")
        if gastos_filtrados.empty:
            st.info("No hay centros de costo para graficar.")
        else:
            centros = (
                gastos_filtrados.groupby("Centro_Costo", dropna=False)["Monto"]
                .sum()
                .sort_values(ascending=False)
                .reset_index(name="Monto")
            )
            st.altair_chart(
                grafico_barras_horizontales(centros, "Centro_Costo", "Monto", "Gastos", "goldorange", alto=320),
                width="stretch",
            )

    st.subheader("Facturas pendientes")
    pendientes = facturas_filtradas[facturas_filtradas["Estado"].str.lower() == "pendiente"]
    columnas_facturas = ["Factura", "Fecha", "Cliente", "Servicio", "Monto_Neto", "IVA", "Monto_Total", "Estado"]
    st.dataframe(
        pendientes.sort_values("Monto_Total", ascending=False)[columnas_facturas],
        width="stretch",
    )

    st.subheader("Detalle de gastos")
    columnas_gastos = ["ID_Gasto", "Fecha", "Categoria", "Proveedor", "Descripcion", "Monto", "Centro_Costo"]
    st.dataframe(
        gastos_filtrados.sort_values("Monto", ascending=False)[columnas_gastos],
        width="stretch",
    )


def mostrar_graficos_mantencion(mantenciones):
    if mantenciones.empty:
        st.info("No hay mantenciones para graficar con los filtros seleccionados.")
        return

    top_n = st.slider("Top de camiones/patentes", min_value=5, max_value=20, value=10)

    resumen_patentes = (
        mantenciones.groupby("Patente", dropna=False)
        .agg(
            Mantenciones=("ID Mantencion", "count"),
            Costo_Total=("Costo Total", "sum"),
            Costo_Promedio=("Costo Total", "mean"),
        )
        .sort_values("Mantenciones", ascending=False)
        .head(top_n)
        .reset_index()
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Camiones con mas mantenciones")
        st.altair_chart(
            grafico_barras_horizontales(
                resumen_patentes,
                "Patente",
                "Mantenciones",
                "Mantenciones",
                esquema="blues",
                alto=360,
            ),
                width="stretch",
        )

    with col2:
        st.subheader("Costo total por camion")
        costos_patentes = resumen_patentes.sort_values("Costo_Total", ascending=False)
        st.altair_chart(
            grafico_barras_horizontales(
                costos_patentes,
                "Patente",
                "Costo_Total",
                "Costo total",
                esquema="orangered",
                alto=360,
            ),
            width="stretch",
        )

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Costo por tipo de mantencion")
        costos_tipo = (
            mantenciones.groupby("Tipo Mantencion", dropna=False)["Costo Total"]
            .sum()
            .sort_values(ascending=False)
            .reset_index(name="Costo_Total")
        )
        st.altair_chart(
            grafico_barras_horizontales(
                costos_tipo,
                "Tipo Mantencion",
                "Costo_Total",
                "Costo total",
                esquema="goldorange",
                alto=320,
            ),
            width="stretch",
        )

    with col4:
        st.subheader("Costo mensual de mantenciones")
        costos_mes = mantenciones.copy()
        costos_mes["Mes"] = costos_mes["Fecha"].dt.to_period("M").astype(str)
        costos_mes = (
            costos_mes.groupby("Mes", dropna=False)["Costo Total"]
            .sum()
            .reset_index(name="Costo_Total")
        )
        st.altair_chart(
            grafico_linea(costos_mes, "Mes", "Costo_Total", "Costo total", color="#e76f51", alto=320),
            width="stretch",
        )

    st.subheader("Resumen por camion")
    tabla_resumen = resumen_patentes.rename(
        columns={
            "Costo_Total": "Costo Total",
            "Costo_Promedio": "Costo Promedio",
        }
    )
    st.dataframe(tabla_resumen, width="stretch")


def mostrar_graficos_ingresos(viajes):
    if viajes.empty:
        st.info("No hay viajes para graficar con los filtros seleccionados.")
        return

    top_n = st.slider("Top de ingresos", min_value=5, max_value=20, value=10)

    def ranking_ingresos(grupo):
        return (
            viajes.groupby(grupo, dropna=False)["Ingreso Neto"]
            .sum()
            .sort_values(ascending=False)
            .head(top_n)
            .reset_index(name="Ingreso_Neto")
        )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Ingresos por conductor")
        st.altair_chart(
            grafico_barras_horizontales(
                ranking_ingresos("Conductor"),
                "Conductor",
                "Ingreso_Neto",
                "Ingreso neto",
                esquema="greens",
                alto=360,
            ),
            width="stretch",
        )

    with col2:
        st.subheader("Ingresos por tracto")
        st.altair_chart(
            grafico_barras_horizontales(
                ranking_ingresos("Patente Tracto"),
                "Patente Tracto",
                "Ingreso_Neto",
                "Ingreso neto",
                esquema="tealblues",
                alto=360,
            ),
            width="stretch",
        )

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Ingresos por rampla")
        st.altair_chart(
            grafico_barras_horizontales(
                ranking_ingresos("Patente Rampla"),
                "Patente Rampla",
                "Ingreso_Neto",
                "Ingreso neto",
                esquema="purples",
                alto=360,
            ),
            width="stretch",
        )

    with col4:
        st.subheader("Ingresos por ruta")
        st.altair_chart(
            grafico_barras_horizontales(
                ranking_ingresos("Ruta"),
                "Ruta",
                "Ingreso_Neto",
                "Ingreso neto",
                esquema="bluegreen",
                alto=360,
            ),
            width="stretch",
        )

    col5, col6 = st.columns(2)
    with col5:
        st.subheader("Ingresos por centro")
        st.altair_chart(
            grafico_barras_horizontales(
                ranking_ingresos("Centro"),
                "Centro",
                "Ingreso_Neto",
                "Ingreso neto",
                esquema="viridis",
                alto=320,
            ),
            width="stretch",
        )

    with col6:
        st.subheader("Ingresos por fuente")
        ingresos_fuente = (
            viajes.groupby("Fuente", dropna=False)["Ingreso Neto"]
            .sum()
            .sort_values(ascending=False)
            .reset_index(name="Ingreso_Neto")
        )
        st.altair_chart(
            grafico_donut(ingresos_fuente, "Fuente", "Ingreso_Neto", alto=320),
            width="stretch",
        )

    st.subheader("Ingresos mensuales")
    ingresos_mes = viajes.copy()
    ingresos_mes["Mes"] = ingresos_mes["Fecha"].dt.to_period("M").astype(str)
    ingresos_mes = (
        ingresos_mes.groupby("Mes", dropna=False)["Ingreso Neto"]
        .sum()
        .reset_index(name="Ingreso_Neto")
    )
    st.altair_chart(
        grafico_linea(ingresos_mes, "Mes", "Ingreso_Neto", "Ingreso neto", color="#2a9d8f", alto=320),
        width="stretch",
    )

    st.subheader("Detalle de ingresos por conductor")
    detalle_conductor = (
        viajes.groupby("Conductor", dropna=False)
        .agg(
            Viajes=("ID", "count"),
            Ingreso_Neto=("Ingreso Neto", "sum"),
            Ingreso_Promedio=("Ingreso Neto", "mean"),
        )
        .sort_values("Ingreso_Neto", ascending=False)
        .head(top_n)
        .reset_index()
        .rename(
            columns={
                "Ingreso_Neto": "Ingreso Neto",
                "Ingreso_Promedio": "Ingreso Promedio",
            }
        )
    )
    st.dataframe(detalle_conductor, width="stretch")


def normalizar_texto_intencion(texto):
    texto = str(texto).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return texto.strip()


def clasificar_intencion(pregunta):
    pregunta_normalizada = normalizar_texto_intencion(pregunta)

    if not pregunta_normalizada:
        return "documental"

    patrones_documentales = [
        "plan",
        "manual",
        "politica",
        "procedimiento",
        "procedimientos",
        "protocolo",
        "protocolos",
        "definicion",
        "definir",
        "regla",
        "reglas",
        "instruccion",
        "instrucciones",
        "explicacion",
        "explica",
        "explique",
        "que dice",
        "como se debe",
        "cada cuanto",
        "que debe",
        "que deben",
        "que se revisa",
        "que revisar",
        "antes de salir",
        "emergencia",
    ]
    patrones_analiticos = [
        "ranking",
        "rank",
        "total",
        "totales",
        "monto",
        "montos",
        "costo",
        "costos",
        "ingreso",
        "ingresos",
        "mayor",
        "mayores",
        "menor",
        "menores",
        "promedio",
        "suma",
        "cuanto",
        "cuantos",
        "cuantas",
        "gastado",
        "gasto",
        "gastos",
        "factura",
        "facturas",
        "conductor",
        "conductores",
        "chofer",
        "choferes",
        "operador",
        "operadores",
        "patente",
        "patentes",
        "vehiculo",
        "vehiculos",
        "camion",
        "camiones",
        "tracto",
        "rampla",
        "comparacion",
        "compara",
    ]

    if any(patron in pregunta_normalizada for patron in patrones_documentales):
        return "documental"

    if any(patron in pregunta_normalizada for patron in patrones_analiticos):
        return "analitica"

    return "documental"


def responder_pregunta(pregunta, viajes, mantenciones, documentos, facturas=None, gastos=None, historial=None, traza=None):
    traza = traza if traza is not None else {}
    respuesta_cantidad_pdf = responder_cantidad_pdf(pregunta, documentos)
    if respuesta_cantidad_pdf:
        traza.update(tipo_consulta="inventario_documental", metodo_respuesta="calculo_local")
        st.caption("Intención detectada localmente: inventario de documentos PDF")
        return respuesta_cantidad_pdf

    intencion_semantica = clasificar_intencion_semantica(pregunta)

    if intencion_semantica:
        logger.info("Intencion detectada por Gemini: %s", intencion_semantica)
        st.caption(
            "Intención detectada: "
            f"{intencion_semantica['tipo']} / {intencion_semantica['accion']} / "
            f"{intencion_semantica['metrica']} / {intencion_semantica['entidad']}"
        )

        if intencion_semantica["tipo"] == "analitica":
            traza["tipo_consulta"] = "analitica"
            return responder_analitica(pregunta, viajes, mantenciones, facturas, gastos, intencion_semantica, historial, traza)

        if intencion_semantica["tipo"] == "documental":
            traza["tipo_consulta"] = "documental"
            return responder_documental(pregunta, documentos, historial, traza)

    intencion = clasificar_intencion(pregunta)

    if intencion == "analitica":
        traza["tipo_consulta"] = "analitica"
        return responder_analitica(pregunta, viajes, mantenciones, facturas, gastos, historial=historial, traza=traza)

    traza["tipo_consulta"] = "documental"
    return responder_documental(pregunta, documentos, historial, traza)


def clasificar_intencion_semantica(pregunta):
    try:
        chatbot = ChatbotOpenRouter()
        return chatbot.clasificar_intencion(pregunta)
    except Exception as error:
        logger.warning("No se pudo clasificar semanticamente la pregunta. Se usara fallback local: %s", error)
        return None


def mostrar_error_modelo_externo(error):
    causa = error.__cause__
    tipo_error = type(causa).__name__ if causa is not None else type(error).__name__

    st.error(error.mensaje_usuario)
    with st.expander("Detalle técnico de OpenRouter", expanded=True):
        st.code(
            "\n".join(
                [
                    "Proveedor: OpenRouter",
                    f"Modelo: {MODELO_OPENROUTER}",
                    f"Tipo de error: {tipo_error}",
                    f"Detalle: {error.detalle}",
                ]
            ),
            language="text",
        )


def responder_documental(pregunta, documentos=None, historial=None, traza=None):
    traza = traza if traza is not None else {}
    if documentos is None:
        documentos = globals().get("documentos", pd.DataFrame())

    documentos_pdf = filtrar_documentos_pdf(documentos)

    @st.cache_resource(show_spinner=False)
    def construir_rag_documental(documentos_indexados):
        return SemanticRAG(None, None, documentos_indexados, ruta_indice=RUTA_INDICE_DOCUMENTAL)

    try:
        rag_documental = construir_rag_documental(documentos_pdf)
    except ModuleNotFoundError as error:
        st.warning(f"{error}. Se usara el RAG simple para esta sesion.")
        rag_documental = RAG(None, None, documentos_pdf)

    contexto = rag_documental.obtener_contexto(pregunta)
    traza["contexto_recuperado"] = contexto
    traza["metodo_respuesta"] = "rag_documental"

    if contexto_documental_insuficiente(contexto):
        return (
            "No encontré esta información en los documentos disponibles. "
            "Consulta con el área responsable si necesitas una confirmación oficial."
        )

    try:
        chatbot = ChatbotOpenRouter()
        respuesta = chatbot.preguntar(pregunta, contexto, historial)
        if not chatbot.verificar_respaldo_documental(respuesta, contexto):
            return (
                "No puedo entregar una respuesta porque no fue posible respaldarla "
                "de forma suficiente con los documentos recuperados."
            )
        return anexar_fuentes_documentales(respuesta, contexto)

    except ErrorModeloExterno as error:
        logger.exception("Error al conectar con el modelo externo: %s", error.detalle)
        mostrar_error_modelo_externo(error)
        respuesta_documentos = responder_con_documentos_locales(pregunta, documentos_pdf)
        if respuesta_documentos:
            return (
                "No fue posible conectar con el modelo externo. "
                "Se muestran los fragmentos más relevantes encontrados en los documentos.\n\n"
                f"{respuesta_documentos}"
            )

        return (
            "No fue posible conectar con el modelo externo. "
            "Se muestran los fragmentos más relevantes encontrados en los documentos.\n\n"
            "No encontré información relevante en los documentos cargados."
        )


def responder_analitica(pregunta, viajes=None, mantenciones=None, facturas=None, gastos=None, intencion=None, historial=None, traza=None):
    traza = traza if traza is not None else {}
    if viajes is None:
        viajes = globals().get("viajes_filtrados", pd.DataFrame())
    if mantenciones is None:
        mantenciones = globals().get("mantenciones_filtradas", pd.DataFrame())
    if facturas is None:
        facturas = globals().get("facturas", pd.DataFrame())
    if gastos is None:
        gastos = globals().get("gastos", pd.DataFrame())

    analizador = AnalizadorOperacional(viajes, mantenciones)
    respuesta_calculada = analizador.generar_respuesta_calculada(pregunta, intencion)

    if respuesta_calculada:
        traza["metodo_respuesta"] = "calculo_local"
        return respuesta_calculada

    respuesta_administrativa = responder_analitica_administrativa(pregunta, facturas, gastos)
    if respuesta_administrativa:
        traza["metodo_respuesta"] = "calculo_local_administrativo"
        return respuesta_administrativa

    @st.cache_resource(show_spinner=False)
    def construir_rag(viajes, mantenciones):
        try:
            return SemanticRAG(viajes, mantenciones, None)
        except ModuleNotFoundError as error:
            st.warning(f"{error}. Se usara el RAG simple para esta sesion.")
            return RAG(viajes, mantenciones, None)

    contexto = construir_rag(viajes, mantenciones).obtener_contexto(pregunta)
    traza["contexto_recuperado"] = contexto
    traza["metodo_respuesta"] = "rag_analitico"

    try:
        chatbot = ChatbotOpenRouter()
        return chatbot.preguntar(pregunta, contexto, historial)
    except ErrorModeloExterno as error:
        logger.exception("Error al conectar con el modelo externo: %s", error.detalle)
        mostrar_error_modelo_externo(error)
        return (
            "La consulta fue clasificada como analitica, pero no encontre un calculo directo "
            "para responderla con los DataFrames disponibles. Ademas, no pude conectar con "
            "el modelo externo para interpretar el contexto tabular."
        )


def responder_analitica_administrativa(pregunta, facturas=None, gastos=None):
    pregunta_normalizada = normalizar_texto_intencion(pregunta)

    if facturas is not None and not facturas.empty and "factura" in pregunta_normalizada:
        facturas_datos = facturas.copy()
        facturas_datos["Estado"] = facturas_datos["Estado"].fillna("").astype(str)

        if "pendiente" in pregunta_normalizada:
            pendientes = facturas_datos[facturas_datos["Estado"].str.lower() == "pendiente"]
            monto = float(pendientes["Monto_Total"].sum()) if "Monto_Total" in pendientes.columns else 0
            return (
                "Facturas pendientes:\n"
                f"- Cantidad: {len(pendientes):,.0f}\n"
                f"- Monto total pendiente: ${monto:,.0f}"
            )

        return f"Facturas registradas: {len(facturas_datos):,.0f}"

    if gastos is not None and not gastos.empty and any(palabra in pregunta_normalizada for palabra in ["gasto", "gastos", "combustible"]):
        gastos_datos = gastos.copy()
        gastos_datos["Categoria"] = gastos_datos["Categoria"].fillna("").astype(str)
        gastos_datos["Descripcion"] = gastos_datos["Descripcion"].fillna("").astype(str)

        if "combustible" in pregunta_normalizada:
            mascara = (
                gastos_datos["Categoria"].str.lower().str.contains("combustible", na=False)
                | gastos_datos["Descripcion"].str.lower().str.contains("combustible", na=False)
            )
            gastos_datos = gastos_datos[mascara]

        monto = float(gastos_datos["Monto"].sum()) if "Monto" in gastos_datos.columns else 0
        return (
            "Gastos registrados:\n"
            f"- Cantidad: {len(gastos_datos):,.0f}\n"
            f"- Monto total: ${monto:,.0f}"
        )

    return None


def responder_cantidad_pdf(pregunta, documentos):
    pregunta_normalizada = normalizar_texto_intencion(pregunta)
    consulta_cantidad = any(
        termino in pregunta_normalizada
        for termino in ["cuanto", "cuantos", "cantidad", "numero", "total"]
    )
    menciona_pdf = "pdf" in pregunta_normalizada

    if not consulta_cantidad or not menciona_pdf:
        return None

    if documentos is None or documentos.empty:
        documentos_pdf = pd.DataFrame()
    elif "Tipo Documento" in documentos.columns:
        mascara_pdf = documentos["Tipo Documento"].fillna("").astype(str).str.upper() == "PDF"
        documentos_pdf = documentos[mascara_pdf].copy()
    else:
        documentos_pdf = filtrar_documentos_pdf(documentos)
    if documentos_pdf.empty:
        return "No hay archivos PDF cargados."

    if "Archivo" in documentos_pdf.columns:
        archivos = documentos_pdf["Archivo"].fillna("").astype(str).str.strip()
        archivos = archivos[archivos != ""].drop_duplicates()
    else:
        archivos = pd.Series(dtype="object")

    if archivos.empty and "Referencia Tabla" in documentos_pdf.columns:
        archivos = (
            documentos_pdf["Referencia Tabla"]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        archivos = archivos[archivos != ""].drop_duplicates()

    cantidad = len(archivos)
    sustantivo = "archivo PDF" if cantidad == 1 else "archivos PDF"
    return f"Hay {cantidad} {sustantivo} cargados."


def filtrar_documentos_pdf(documentos):
    if documentos is None or documentos.empty:
        return pd.DataFrame(columns=["Tipo Documento", "Referencia Tabla", "Referencia ID", "Contenido"])

    if "Tipo Documento" not in documentos.columns:
        return documentos

    documentos_pdf = documentos[documentos["Tipo Documento"].fillna("").astype(str).str.upper() == "PDF"].copy()

    if documentos_pdf.empty:
        return documentos

    return documentos_pdf


def responder_con_documentos_locales(pregunta, documentos):
    if documentos is None or documentos.empty:
        return None

    palabras = [palabra for palabra in normalizar_texto_intencion(pregunta).split() if len(palabra) > 3]
    if not palabras:
        return None

    datos = documentos.copy()
    datos["Referencia Tabla"] = datos["Referencia Tabla"].fillna("").astype(str)
    datos["Referencia ID"] = datos["Referencia ID"].fillna("").astype(str)
    datos["Contenido"] = datos["Contenido"].fillna("").astype(str)
    datos["_titulo_busqueda"] = datos.apply(texto_titulo_documento, axis=1)
    datos["_contenido_busqueda"] = datos["Contenido"].apply(normalizar_texto_intencion)
    datos["_puntaje"] = datos.apply(lambda fila: puntuar_documento(palabras, fila), axis=1)
    datos["_referencia_id_orden"] = datos["Referencia ID"].fillna("").astype(str)
    datos = (
        datos[datos["_puntaje"] > 0]
        .sort_values(["_puntaje", "_referencia_id_orden"], ascending=[False, True])
        .drop(columns="_referencia_id_orden")
    )

    if datos.empty:
        return None

    mejor_documento = datos.iloc[0]["Referencia Tabla"]
    mejor_puntaje = datos.iloc[0]["_puntaje"]
    datos_mejor_documento = datos[datos["Referencia Tabla"] == mejor_documento]

    if mejor_puntaje >= 8:
        datos = datos_mejor_documento

    lineas = []
    for _, fila in datos.head(3).iterrows():
        referencia = str(fila["Referencia Tabla"]).replace("_", " ").title()
        contenido = str(fila["Contenido"]).strip()
        if len(contenido) > 500:
            contenido = contenido[:500].rsplit(" ", 1)[0].rstrip() + "..."

        archivo = str(fila.get("Archivo", "") or "").strip()
        pagina = fila.get("Pagina", "")
        if archivo and pd.notna(pagina) and str(pagina).strip():
            fuente = f"{archivo}, pagina {pagina}"
        elif archivo:
            fuente = archivo
        else:
            fuente = f"seccion {fila['Referencia ID']}"

        lineas.append(f"- {referencia} [{fuente}]: {contenido}")

    return "\n".join(lineas)


def texto_titulo_documento(fila):
    partes = []
    for columna in ["Referencia Tabla", "Referencia ID", "Archivo"]:
        if columna in fila.index:
            partes.append(str(fila.get(columna, "")))

    return normalizar_texto_intencion(" ".join(partes).replace("_", " "))


def puntuar_documento(palabras, fila):
    titulo = fila["_titulo_busqueda"]
    contenido = fila["_contenido_busqueda"]
    puntaje = 0

    for palabra in palabras:
        if palabra in titulo:
            puntaje += 6
        if palabra in contenido:
            puntaje += 1

    frases = construir_frases_busqueda(palabras)
    for frase in frases:
        if frase in titulo:
            puntaje += 18
        if frase in contenido:
            puntaje += 4

    if all(palabra in titulo for palabra in palabras):
        puntaje += 25

    return puntaje


def construir_frases_busqueda(palabras):
    frases = []
    for largo in range(min(4, len(palabras)), 1, -1):
        for indice in range(0, len(palabras) - largo + 1):
            frases.append(" ".join(palabras[indice : indice + largo]))

    return frases


def mostrar_documentos(documentos):
    st.subheader("Documentos disponibles")

    if documentos.empty:
        st.info("No hay documentos disponibles.")
        return

    documentos_vista = documentos.copy()
    documentos_vista["Referencia Tabla"] = documentos_vista["Referencia Tabla"].fillna("Sin referencia").astype(str)
    documentos_vista["Contenido"] = documentos_vista["Contenido"].fillna("").astype(str)

    busqueda = st.text_input("Buscar en documentos", placeholder="Ej: plan mantenimiento preventivo")
    opciones = sorted(documentos_vista["Referencia Tabla"].unique())
    seleccion = st.selectbox("Documento", ["Todos"] + opciones)

    filtrados = documentos_vista.copy()

    if seleccion != "Todos":
        filtrados = filtrados[filtrados["Referencia Tabla"] == seleccion]

    if busqueda.strip():
        palabras = [palabra.lower() for palabra in busqueda.split() if len(palabra) > 2]
        texto_busqueda = (
            filtrados["Referencia Tabla"].str.lower()
            + " "
            + filtrados["Referencia ID"].fillna("").astype(str).str.lower()
            + " "
            + filtrados["Contenido"].str.lower()
        )
        mascara = texto_busqueda.apply(lambda texto: all(palabra in texto for palabra in palabras))
        filtrados = filtrados[mascara]

    if "Referencia ID" in filtrados.columns:
        filtrados = (
            filtrados.assign(_referencia_id_orden=filtrados["Referencia ID"].fillna("").astype(str))
            .sort_values("_referencia_id_orden")
            .drop(columns="_referencia_id_orden")
        )

    columnas = ["Tipo Documento", "Referencia Tabla", "Referencia ID", "Contenido"]
    columnas = [columna for columna in columnas if columna in filtrados.columns]

    st.dataframe(filtrados[columnas], width="stretch")

    if filtrados.empty:
        st.info("No hay documentos para la busqueda seleccionada.")
        return

    documento_actual = filtrados.iloc[0]
    st.subheader(str(documento_actual["Referencia Tabla"]).replace("_", " ").title())
    st.text_area("Contenido", documento_actual["Contenido"], height=280)

    archivo = documento_actual.get("Archivo")
    if isinstance(archivo, str) and archivo:
        ruta_pdf = Path(str(documento_actual.get("Ruta Local", "")))
        if ruta_pdf.exists():
            st.download_button(
                "Descargar PDF",
                data=ruta_pdf.read_bytes(),
                file_name=archivo,
                mime="application/pdf",
            )


def registrar_auditoria_segura(
    auditoria,
    *,
    execution_id,
    session_id,
    pregunta,
    respuesta,
    tiempo_respuesta_ms,
    traza,
    versiones_datos,
    estado="exitoso",
    error=None,
):
    if auditoria is None:
        st.warning("La auditoría OCI no está disponible; esta ejecución no quedó registrada en la nube.")
        return
    try:
        auditoria.register(
            execution_id=execution_id,
            question=pregunta,
            response=respuesta,
            session_id=session_id,
            latency_ms=tiempo_respuesta_ms,
            model=MODELO_OPENROUTER,
            trace=traza,
            status=estado,
            error=error,
            data_versions=versiones_datos,
        )
    except Exception:
        logger.exception("No fue posible registrar la ejecución en OCI Object Storage")
        st.warning("La respuesta se procesó, pero no fue posible registrar su auditoría en OCI.")


@st.cache_data(ttl=60, show_spinner=False)
def cargar_registros_auditoria(_auditoria, limite):
    return _auditoria.list_records(limite)


def mostrar_auditoria_ejecuciones(auditoria):
    st.subheader("Auditoría de ejecuciones")
    st.caption(
        "Consulta los registros persistentes del agente almacenados en OCI Object Storage. "
        "Esta vista contiene preguntas, respuestas y contexto recuperado; su acceso debe restringirse a administradores."
    )

    if auditoria is None:
        st.error("La auditoría OCI no está disponible con la configuración actual.")
        return

    col_limite, col_actualizar = st.columns([3, 1])
    with col_limite:
        limite = st.slider("Registros recientes a consultar", 25, 500, 100, 25, key="auditoria_limite")
    with col_actualizar:
        st.write("")
        if st.button("Actualizar", key="auditoria_actualizar", width="stretch"):
            cargar_registros_auditoria.clear()
            st.rerun()

    with st.spinner("Leyendo registros desde OCI..."):
        registros, fallidos = cargar_registros_auditoria(auditoria, limite)

    if fallidos:
        st.warning(f"No fue posible interpretar {len(fallidos)} objeto(s) de auditoría.")
    if not registros:
        st.info("Aún no hay ejecuciones registradas en el prefijo de auditoría.")
        return

    filas = []
    for registro in registros:
        filas.append(
            {
                "Fecha UTC": registro.get("timestamp_utc"),
                "Estado": registro.get("estado", ""),
                "Tipo": registro.get("tipo_consulta", ""),
                "Método": registro.get("metodo_respuesta", ""),
                "Latencia ms": registro.get("latencia_ms", 0),
                "Fuentes": len(registro.get("fuentes") or []),
                "Pregunta": registro.get("pregunta", ""),
                "ID ejecución": registro.get("execution_id", ""),
            }
        )
    resumen = pd.DataFrame(filas)
    resumen["Fecha UTC"] = pd.to_datetime(resumen["Fecha UTC"], errors="coerce", utc=True)

    col_busqueda, col_estado = st.columns([3, 1])
    with col_busqueda:
        busqueda = st.text_input("Buscar en pregunta o ID", key="auditoria_busqueda").strip().lower()
    with col_estado:
        estados_disponibles = sorted(valor for valor in resumen["Estado"].dropna().unique() if valor)
        estados = st.multiselect("Estado", estados_disponibles, key="auditoria_estados")

    filtrado = resumen.copy()
    if busqueda:
        mascara = (
            filtrado["Pregunta"].fillna("").astype(str).str.lower().str.contains(busqueda, regex=False)
            | filtrado["ID ejecución"].fillna("").astype(str).str.lower().str.contains(busqueda, regex=False)
        )
        filtrado = filtrado[mascara]
    if estados:
        filtrado = filtrado[filtrado["Estado"].isin(estados)]

    total = len(filtrado)
    errores = int((filtrado["Estado"] == "error").sum()) if total else 0
    latencia = pd.to_numeric(filtrado["Latencia ms"], errors="coerce").mean() if total else 0
    latencia = float(latencia) if pd.notna(latencia) else 0.0
    con_fuentes = int((pd.to_numeric(filtrado["Fuentes"], errors="coerce") > 0).sum()) if total else 0
    col_total, col_errores, col_latencia, col_fuentes = st.columns(4)
    col_total.metric("Ejecuciones", total)
    col_errores.metric("Errores", errores)
    col_latencia.metric("Latencia promedio", f"{latencia / 1000:.2f} s")
    col_fuentes.metric("Con fuentes", con_fuentes)

    if filtrado.empty:
        st.info("No hay registros que coincidan con los filtros.")
        return

    st.dataframe(filtrado, hide_index=True, width="stretch")

    ids_visibles = filtrado["ID ejecución"].dropna().astype(str).tolist()
    preguntas_por_id = dict(zip(filtrado["ID ejecución"].astype(str), filtrado["Pregunta"].astype(str)))
    execution_id = st.selectbox(
        "Ver detalle de una ejecución",
        ids_visibles,
        format_func=lambda value: f"{value[:8]} — {preguntas_por_id.get(value, '')[:90]}",
        key="auditoria_detalle_id",
    )
    registro = next(item for item in registros if str(item.get("execution_id", "")) == execution_id)

    st.caption(f"Objeto OCI: {registro.get('_objeto_oci', '')}")
    tab_respuesta, tab_contexto, tab_metadatos = st.tabs(["Respuesta", "Contexto y fuentes", "Metadatos"])
    with tab_respuesta:
        st.markdown("**Pregunta**")
        st.write(registro.get("pregunta") or "Sin pregunta registrada.")
        st.markdown("**Respuesta**")
        st.write(registro.get("respuesta") or "Sin respuesta registrada.")
        if registro.get("error"):
            st.error(registro["error"])
    with tab_contexto:
        fuentes = registro.get("fuentes") or []
        if fuentes:
            st.dataframe(pd.DataFrame(fuentes), hide_index=True, width="stretch")
        else:
            st.info("La ejecución no registró fuentes documentales.")
        st.text_area(
            "Contexto recuperado",
            value=str(registro.get("contexto_recuperado") or ""),
            height=320,
            disabled=True,
            key=f"auditoria_contexto_{execution_id}",
        )
    with tab_metadatos:
        metadatos = {
            clave: valor
            for clave, valor in registro.items()
            if clave not in {"pregunta", "respuesta", "contexto_recuperado", "fuentes"}
        }
        st.json(metadatos)

    registro_descarga = {clave: valor for clave, valor in registro.items() if not clave.startswith("_")}
    st.download_button(
        "Descargar registro JSON",
        data=json.dumps(registro_descarga, ensure_ascii=False, indent=2),
        file_name=f"ejecucion-{execution_id}.json",
        mime="application/json",
        key=f"auditoria_descargar_{execution_id}",
    )


def mostrar_chat(viajes, mantenciones, documentos, facturas, gastos, monitoreo_calidad, auditoria, versiones_datos):
    st.title("Consultar a la IA")
    st.info("Estás conversando con un agente de IA. Verifica las fuentes documentales antes de tomar decisiones.")
    st.caption("La consulta utiliza la base disponible completa; los filtros de Operaciones y Finanzas no afectan esta conversación.")

    if "historial" not in st.session_state:
        st.session_state.historial = []
    if "audit_session_id" not in st.session_state:
        st.session_state.audit_session_id = str(uuid4())

    st.subheader("Nueva consulta")
    ejemplos = [
        "Dame un resumen general",
        "Qué centros tienen mayor ingreso neto",
        "Qué conductores concentran mayor ingreso neto",
        "Qué rutas tienen mayor ingreso neto",
        "Compara ingresos por fuente de viaje",
        "Qué patentes tienen mayor costo de mantención",
        "Qué tipos de mantención tienen mayor costo",
        "Qué centros tienen más guías",
    ]
    pregunta = st.selectbox("Pregunta rápida", [""] + ejemplos, key="chat_pregunta_rapida", placeholder="Selecciona una pregunta")
    pregunta_manual = st.text_input("O escribe tu pregunta", key="chat_pregunta_manual")
    consulta = pregunta_manual.strip() or pregunta

    if st.button("Consultar", key="chat_consultar", type="primary"):
        if not consulta:
            st.warning("Debes escribir o seleccionar una pregunta.")
        else:
            with st.spinner("Analizando datos y documentos..."):
                execution_id = str(uuid4())
                traza = {}
                inicio_consulta = perf_counter()
                try:
                    respuesta = responder_pregunta(
                        consulta,
                        viajes,
                        mantenciones,
                        documentos,
                        facturas,
                        gastos,
                        st.session_state.historial,
                        traza,
                    )
                    tiempo_respuesta_ms = (perf_counter() - inicio_consulta) * 1000
                    consulta_id = None
                    if monitoreo_calidad is not None:
                        consulta_id = monitoreo_calidad.registrar_consulta(consulta, respuesta, tiempo_respuesta_ms, MODELO_OPENROUTER)
                    registrar_auditoria_segura(
                        auditoria,
                        execution_id=execution_id,
                        session_id=st.session_state.audit_session_id,
                        pregunta=consulta,
                        respuesta=respuesta,
                        tiempo_respuesta_ms=tiempo_respuesta_ms,
                        traza=traza,
                        versiones_datos=versiones_datos,
                    )
                    st.session_state.historial.append(
                        {
                            "pregunta": consulta,
                            "respuesta": respuesta,
                            "feedback": None,
                            "consulta_id": consulta_id,
                            "execution_id": execution_id,
                        }
                    )
                    st.rerun()
                except Exception as error:
                    tiempo_respuesta_ms = (perf_counter() - inicio_consulta) * 1000
                    registrar_auditoria_segura(
                        auditoria,
                        execution_id=execution_id,
                        session_id=st.session_state.audit_session_id,
                        pregunta=consulta,
                        respuesta=None,
                        tiempo_respuesta_ms=tiempo_respuesta_ms,
                        traza=traza,
                        versiones_datos=versiones_datos,
                        estado="error",
                        error={"tipo": type(error).__name__, "mensaje": str(error)[:500]},
                    )
                    logger.exception("Error inesperado al generar la respuesta")
                    st.error(f"No se pudo generar la respuesta. Detalle: {error}")
                    with st.expander("Detalle técnico del error", expanded=True):
                        st.exception(error)

    col_titulo, col_limpiar = st.columns([5, 1])
    with col_titulo:
        st.subheader("Conversación")
    with col_limpiar:
        if st.button("Limpiar historial", key="chat_limpiar_historial"):
            st.session_state.historial = []
            st.rerun()

    for indice in range(len(st.session_state.historial) - 1, -1, -1):
        item = st.session_state.historial[indice]
        with st.chat_message("user"):
            st.write(item["pregunta"])
        with st.chat_message("assistant"):
            st.write(item["respuesta"])
            if item.get("execution_id"):
                st.caption(f"ID de ejecución: {item['execution_id']}")
            feedback = item.get("feedback")
            columna_positivo, columna_negativo, columna_estado = st.columns([1, 1, 4])
            if columna_positivo.button("👍 Útil", key=f"feedback_positivo_{indice}", disabled=feedback is not None):
                item["feedback"] = "positivo"
                if monitoreo_calidad is not None and item.get("consulta_id"):
                    monitoreo_calidad.registrar_feedback(item["consulta_id"], "positivo")
                st.toast("Gracias por tu retroalimentación.")
            if columna_negativo.button("👎 No útil", key=f"feedback_negativo_{indice}", disabled=feedback is not None):
                item["feedback"] = "negativo"
                if monitoreo_calidad is not None and item.get("consulta_id"):
                    monitoreo_calidad.registrar_feedback(item["consulta_id"], "negativo")
                st.toast("Gracias. Usaremos esta señal para mejorar el agente.")
            if feedback:
                columna_estado.caption(f"Evaluación registrada: {'Útil' if feedback == 'positivo' else 'No útil'}")


try:
    configuracion_almacenamiento = load_storage_settings()
    almacenamiento = obtener_almacenamiento(configuracion_almacenamiento)
    prefijo_datos = configuracion_almacenamiento.oci_data_prefix
    objeto_sql = resolve_object_name(
        almacenamiento,
        prefijo_datos,
        NOMBRE_SQL,
    )
    ruta_sql = almacenamiento.materialize(objeto_sql)
    version_sql = object_version(almacenamiento, objeto_sql)
    base = cargar_base(str(ruta_sql), version_sql)
except StorageError as error:
    st.error(f"No fue posible obtener la base SQL desde el almacenamiento configurado. Detalle: {error}")
    st.stop()
except Exception as error:
    st.error(f"No fue posible cargar la base SQL. Detalle: {error}")
    st.stop()

version_administracion = None
try:
    objeto_administracion = resolve_object_name(
        almacenamiento,
        prefijo_datos,
        NOMBRE_ADMINISTRACION,
    )
    ruta_administracion = almacenamiento.materialize(objeto_administracion)
    version_administracion = object_version(almacenamiento, objeto_administracion)
    administracion = cargar_administracion(
        str(ruta_administracion),
        version_administracion,
    )
except StorageError as error:
    administracion = {"facturas": pd.DataFrame(), "gastos": pd.DataFrame(), "kpis": pd.DataFrame()}
    st.warning(
        "No fue posible obtener administracion.xlsx desde el almacenamiento configurado. "
        f"Detalle: {error}"
    )
except Exception as error:
    administracion = {"facturas": pd.DataFrame(), "gastos": pd.DataFrame(), "kpis": pd.DataFrame()}
    st.warning(f"No fue posible cargar administracion.xlsx. Detalle: {error}")

version_pdfs = ""
try:
    archivos_pdf, version_pdfs = materialize_files(
        almacenamiento,
        configuracion_almacenamiento.oci_rag_prefix,
        ".pdf",
    )
    documentos_pdf = cargar_documentos_pdf(tuple(archivos_pdf), version_pdfs)
    carga_documentos_pdf_exitosa = True
except StorageError as error:
    documentos_pdf = pd.DataFrame()
    carga_documentos_pdf_exitosa = False
    st.warning(f"No fue posible obtener los PDF desde OCI Object Storage. Detalle: {error}")
except Exception as error:
    documentos_pdf = pd.DataFrame()
    carga_documentos_pdf_exitosa = False
    st.warning(f"No fue posible procesar los PDF descargados desde OCI. Detalle: {error}")

try:
    auditoria_oci = OciAuditLog(
        almacenamiento,
        prefix=configuracion_almacenamiento.oci_audit_prefix,
    )
except Exception as error:
    auditoria_oci = None
    st.warning(f"No fue posible configurar la auditoría en OCI. Detalle: {error}")

versiones_datos = {
    "sql": version_sql,
    "administracion": version_administracion,
    "pdfs": version_pdfs,
}

Path(RUTA_ESTADO_LOCAL).mkdir(parents=True, exist_ok=True)
try:
    catalogo_repo = CatalogoDocumentos(RUTA_CATALOGO_DOCUMENTOS)
    if carga_documentos_pdf_exitosa:
        catalogo_repo.sincronizar(documentos_pdf)
    catalogo_documentos = catalogo_repo.obtener()
except Exception as error:
    catalogo_repo = None
    catalogo_documentos = pd.DataFrame()
    st.warning(f"No fue posible actualizar el catálogo documental. Detalle: {error}")

try:
    monitoreo_calidad = MonitoreoCalidad(RUTA_MONITOREO_CALIDAD)
except Exception as error:
    monitoreo_calidad = None
    st.warning(f"No fue posible iniciar el monitoreo de calidad. Detalle: {error}")

viajes = base["viajes"]
mantenciones = base["mantenciones"]
documentos = pd.concat([base["documentos"], documentos_pdf], ignore_index=True)
if "Referencia ID" in documentos.columns:
    documentos["Referencia ID"] = documentos["Referencia ID"].fillna("").astype(str)
facturas = administracion["facturas"]
gastos = administracion["gastos"]
kpis_administracion = administracion["kpis"]
st.sidebar.caption(f"Datos estructurados: {configuracion_almacenamiento.backend.upper()}")

if st.session_state.pop("aviso_documentos_actualizados", False):
    st.toast("Los documentos PDF cambiaron y el índice fue actualizado.")

with st.sidebar:
    st.title("Panel de gestión")
    st.caption("Navegación principal")
    seccion = st.radio(
        "Sección",
        ["Resumen", "Consultar a la IA", "Operaciones", "Finanzas", "Gestión del asistente"],
        key="seccion_principal",
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("La gestión del asistente está separada para habilitar control por roles cuando exista autenticación. Actualmente no se restringe el acceso porque el proyecto no tiene usuarios ni roles.")

if seccion == "Resumen":
    mostrar_resumen(viajes, mantenciones, facturas, catalogo_documentos, monitoreo_calidad)

elif seccion == "Consultar a la IA":
    mostrar_chat(
        viajes,
        mantenciones,
        documentos,
        facturas,
        gastos,
        monitoreo_calidad,
        auditoria_oci,
        versiones_datos,
    )

elif seccion == "Operaciones":
    st.title("Operaciones")
    st.caption("Analiza viajes y mantenciones por separado para conservar su alcance operacional.")
    subseccion = st.radio("Vista", ["Viajes", "Mantenciones"], horizontal=True, key="operaciones_seccion")

    if subseccion == "Viajes":
        viajes_filtrados, filtros_activos = aplicar_filtros_viajes(viajes)
        _resumen_filtros(filtros_activos)
        if viajes_filtrados.empty:
            st.info("No hay viajes para los filtros seleccionados.")
        else:
            kpis_viajes = calcular_kpis_viajes(viajes_filtrados)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Viajes", f"{kpis_viajes['viajes']:,}")
            col2.metric("Ingresos de viajes", formato_pesos(kpis_viajes["ingreso_neto"]))
            col3.metric("Guías", f"{kpis_viajes['guias']:,}")
            col4.metric("Fuentes", f"{kpis_viajes['fuentes_viajes']:,}")
            st.caption("Datos reales de viajes. Los ingresos no corresponden a la facturación administrativa.")
            mostrar_graficos_ingresos(viajes_filtrados)
            with st.expander("Ver tabla de viajes", expanded=False):
                st.dataframe(viajes_filtrados, width="stretch")

    else:
        mantenciones_filtradas, filtros_activos = aplicar_filtros_mantenciones(mantenciones)
        _resumen_filtros(filtros_activos)
        if mantenciones_filtradas.empty:
            st.info("No hay mantenciones para los filtros seleccionados.")
        else:
            kpis_flota = calcular_kpis_flota(mantenciones_filtradas)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Mantenciones", f"{kpis_flota['mantenciones']:,}")
            col2.metric("Costo total", formato_pesos(kpis_flota["costo_mantenciones"]))
            col3.metric("Costo promedio", formato_pesos(kpis_flota["costo_promedio_mantencion"]))
            col4.metric("Patentes", f"{kpis_flota['vehiculos_con_mantencion']:,}")
            st.caption("Costos reales de mantenciones registradas; no se atribuyen automáticamente a un viaje o conductor.")
            mostrar_graficos_mantencion(mantenciones_filtradas)
            with st.expander("Ver tabla de mantenciones", expanded=False):
                st.dataframe(mantenciones_filtradas, width="stretch")

elif seccion == "Finanzas":
    st.title("Finanzas")
    st.caption("Facturación y gastos administrativos. Estas cifras se muestran separadas de los ingresos operacionales por viajes.")
    mostrar_administracion(facturas, gastos, kpis_administracion)

else:
    st.title("Gestión del asistente")
    st.caption("Área preparada para restringirse a administradores cuando el proyecto incorpore autenticación y roles.")
    gestion = st.radio(
        "Herramienta de gestión",
        ["Documentos RAG", "Curaduría documental", "Monitoreo de calidad", "Auditoría de ejecuciones", "Ciclo de mejora"],
        horizontal=True,
        key="gestion_seccion",
    )

    if gestion == "Documentos RAG":
        if st.button("Actualizar documentos PDF", key="gestion_actualizar_pdf", help="Vuelve a leer los PDF y reconstruye el índice al consultar."):
            cargar_documentos_pdf.clear()
            st.session_state.aviso_documentos_actualizados = True
            st.rerun()
        mostrar_documentos(documentos)

    elif gestion == "Curaduría documental":
        st.subheader("Curaduría documental")
        st.caption("Los PDF nuevos quedan pendientes de revisión. Completa responsable, versión, estado y fechas antes de declararlos oficiales. Esta etapa aún no excluye documentos de la recuperación.")
        if catalogo_repo is None or catalogo_documentos.empty:
            st.info("No hay documentos PDF disponibles para catalogar.")
        else:
            pendientes = int((catalogo_documentos["estado"] == "Pendiente de revision").sum())
            no_disponibles = int((catalogo_documentos["disponible"] == 0).sum())
            col_pendientes, col_no_disponibles = st.columns(2)
            col_pendientes.metric("Pendientes de revisión", pendientes)
            col_no_disponibles.metric("Archivos no disponibles", no_disponibles)
            catalogo_editado = st.data_editor(
                catalogo_documentos,
                hide_index=True,
                width="stretch",
                disabled=["archivo", "ultima_modificacion", "disponible"],
                column_config={
                    "categoria": st.column_config.SelectboxColumn("Categoría", options=CATEGORIAS_DOCUMENTALES),
                    "estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS_DOCUMENTALES),
                    "responsable": st.column_config.TextColumn("Responsable"),
                    "version": st.column_config.TextColumn("Versión"),
                    "fecha_vigencia": st.column_config.TextColumn("Fecha de vigencia"),
                    "proxima_revision": st.column_config.TextColumn("Próxima revisión"),
                    "ultima_modificacion": st.column_config.TextColumn("Última modificación"),
                    "disponible": st.column_config.CheckboxColumn("Disponible"),
                },
                key="editor_catalogo_documentos",
            )
            if st.button("Guardar curaduría documental", key="guardar_curaduria", type="primary"):
                catalogo_repo.guardar(catalogo_editado)
                st.success("Curaduría documental guardada.")
                st.rerun()

    elif gestion == "Monitoreo de calidad":
        st.subheader("Monitoreo de calidad")
        st.caption("Las métricas se guardan localmente en este equipo para identificar vacíos de conocimiento.")
        if monitoreo_calidad is None:
            st.info("El monitoreo de calidad no está disponible.")
        else:
            resumen_calidad = monitoreo_calidad.resumen()
            col_total, col_sin_respuesta, col_tiempo, col_feedback = st.columns(4)
            col_total.metric("Consultas registradas", resumen_calidad["total_consultas"])
            col_sin_respuesta.metric("Sin respuesta", f"{resumen_calidad['tasa_sin_respuesta']:.1%}")
            col_tiempo.metric("Tiempo promedio", f"{resumen_calidad['tiempo_promedio_ms'] / 1000:.2f} s")
            col_feedback.metric("Feedback negativo", f"{resumen_calidad['tasa_feedback_negativo']:.1%}")
            st.subheader("Preguntas recurrentes sin respuesta")
            preguntas_sin_respuesta = monitoreo_calidad.preguntas_sin_respuesta()
            if preguntas_sin_respuesta.empty:
                st.info("Aún no hay preguntas sin respuesta registradas.")
            else:
                st.dataframe(preguntas_sin_respuesta, hide_index=True, width="stretch")
            st.subheader("Respuestas con feedback negativo")
            feedback_negativo = monitoreo_calidad.feedback_negativo()
            if feedback_negativo.empty:
                st.info("Aún no hay feedback negativo registrado.")
            else:
                st.dataframe(feedback_negativo, hide_index=True, width="stretch")

    elif gestion == "Auditoría de ejecuciones":
        mostrar_auditoria_ejecuciones(auditoria_oci)

    else:
        st.subheader("Ciclo de mejora")
        st.caption("Esta cola prioriza mejoras a partir de preguntas sin respuesta y feedback negativo. Asigna un responsable y actualiza el estado cuando la acción sea atendida.")
        if monitoreo_calidad is None:
            st.info("El ciclo de mejora no está disponible porque el monitoreo no pudo iniciarse.")
        else:
            acciones_mejora = monitoreo_calidad.acciones_mejora()
            if acciones_mejora.empty:
                st.info("Aún no hay acciones de mejora generadas.")
            else:
                acciones_editadas = st.data_editor(
                    acciones_mejora,
                    hide_index=True,
                    width="stretch",
                    disabled=["id", "tipo", "pregunta", "ocurrencias", "recomendacion", "ultima_detectada"],
                    column_config={
                        "estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS_MEJORA),
                        "responsable": st.column_config.TextColumn("Responsable"),
                    },
                    key="editor_acciones_mejora",
                )
                if st.button("Guardar acciones de mejora", key="guardar_acciones_mejora", type="primary"):
                    monitoreo_calidad.guardar_acciones_mejora(acciones_editadas)
                    st.success("Acciones de mejora guardadas.")
                    st.rerun()
