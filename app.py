from pathlib import Path
import logging
import re
import unicodedata

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
from modules.rag import (
    RAG,
    SemanticRAG,
    anexar_fuentes_documentales,
    contexto_documental_insuficiente,
)


RUTA_SQL = "data/base_datos_chatbot_rag_transportes.sql"
RUTA_ADMINISTRACION = "data/administracion.xlsx"
RUTA_PDFS = "data"


load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


st.set_page_config(
    page_title="Chatbot Gerencial",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def cargar_base(_ultima_modificacion):
    lector = LectorSQL(RUTA_SQL)
    return lector.cargar_base()


@st.cache_data(show_spinner=False)
def cargar_administracion(_ultima_modificacion):
    lector = LectorAdministracion(RUTA_ADMINISTRACION)
    return lector.cargar_datos()


@st.cache_data(show_spinner=False)
def cargar_documentos_pdf(_ultima_modificacion):
    lector = LectorPDF(RUTA_PDFS)
    return lector.cargar_datos()


def obtener_marca_modificacion_pdfs():
    carpeta = Path(RUTA_PDFS)
    if not carpeta.exists():
        return "sin-carpeta"

    marcas = [
        f"{archivo.name}:{archivo.stat().st_size}:{archivo.stat().st_mtime}"
        for archivo in sorted(carpeta.glob("*.pdf"))
    ]
    return "|".join(marcas) if marcas else "sin-pdf"


def aplicar_filtros_viajes(viajes):
    st.sidebar.header("Filtros de viajes")

    fuentes = st.sidebar.multiselect(
        "Fuente",
        options=sorted(viajes["Fuente"].unique()),
        default=[],
        placeholder="Selecciona una o mas fuentes",
    )
    centros = st.sidebar.multiselect(
        "Centro",
        options=sorted(viajes["Centro"].unique()),
        default=[],
        placeholder="Selecciona uno o mas centros",
    )
    conductores = st.sidebar.multiselect(
        "Conductor",
        options=sorted(viajes["Conductor"].unique()),
        default=[],
        placeholder="Selecciona uno o mas conductores",
    )
    tipos_camion = st.sidebar.multiselect(
        "Tipo camion",
        options=sorted(viajes["Tipo Camion"].unique()),
        default=[],
        placeholder="Selecciona uno o mas tipos",
    )
    origenes = st.sidebar.multiselect(
        "Desde",
        options=sorted(viajes["Desde"].unique()),
        default=[],
        placeholder="Selecciona uno o mas origenes",
    )
    destinos = st.sidebar.multiselect(
        "Hasta",
        options=sorted(viajes["Hasta"].unique()),
        default=[],
        placeholder="Selecciona uno o mas destinos",
    )

    filtrados = viajes.copy()

    if fuentes:
        filtrados = filtrados[filtrados["Fuente"].isin(fuentes)]

    if centros:
        filtrados = filtrados[filtrados["Centro"].isin(centros)]

    if conductores:
        filtrados = filtrados[filtrados["Conductor"].isin(conductores)]

    if tipos_camion:
        filtrados = filtrados[filtrados["Tipo Camion"].isin(tipos_camion)]

    if origenes:
        filtrados = filtrados[filtrados["Desde"].isin(origenes)]

    if destinos:
        filtrados = filtrados[filtrados["Hasta"].isin(destinos)]

    return filtrados


def aplicar_filtros_mantenciones(mantenciones):
    if mantenciones.empty:
        return mantenciones

    st.sidebar.header("Filtros de mantenciones")

    patentes = st.sidebar.multiselect(
        "Patente mantencion",
        options=sorted(mantenciones["Patente"].unique()),
        default=[],
        placeholder="Selecciona una o mas patentes",
    )
    tipos = st.sidebar.multiselect(
        "Tipo mantencion",
        options=sorted(mantenciones["Tipo Mantencion"].unique()),
        default=[],
        placeholder="Selecciona uno o mas tipos",
    )

    filtradas = mantenciones.copy()

    if patentes:
        filtradas = filtradas[filtradas["Patente"].isin(patentes)]

    if tipos:
        filtradas = filtradas[filtradas["Tipo Mantencion"].isin(tipos)]

    filtradas.attrs["filtros_mantenciones_activos"] = bool(patentes or tipos)
    return filtradas


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


def filtrar_administracion(facturas, gastos):
    st.subheader("Filtros administrativos")

    col1, col2, col3 = st.columns(3)
    with col1:
        clientes = st.multiselect(
            "Cliente",
            options=sorted(facturas["Cliente"].unique()),
            default=[],
            placeholder="Selecciona uno o mas clientes",
        )
    with col2:
        estados = st.multiselect(
            "Estado factura",
            options=sorted(facturas["Estado"].unique()),
            default=[],
            placeholder="Selecciona uno o mas estados",
        )
    with col3:
        categorias = st.multiselect(
            "Categoria gasto",
            options=sorted(gastos["Categoria"].unique()),
            default=[],
            placeholder="Selecciona una o mas categorias",
        )

    col4, col5, col6 = st.columns(3)
    with col4:
        servicios = st.multiselect(
            "Servicio",
            options=sorted(facturas["Servicio"].unique()),
            default=[],
            placeholder="Selecciona uno o mas servicios",
        )
    with col5:
        centros = st.multiselect(
            "Centro de costo",
            options=sorted(gastos["Centro_Costo"].unique()),
            default=[],
            placeholder="Selecciona uno o mas centros",
        )
    with col6:
        proveedores = st.multiselect(
            "Proveedor",
            options=sorted(gastos["Proveedor"].unique()),
            default=[],
            placeholder="Selecciona uno o mas proveedores",
        )

    facturas_filtradas = facturas.copy()
    gastos_filtrados = gastos.copy()

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

    return facturas_filtradas, gastos_filtrados


def mostrar_administracion(facturas, gastos, kpis_excel):
    if facturas.empty and gastos.empty:
        st.info("No hay datos administrativos disponibles.")
        return

    facturas_filtradas, gastos_filtrados = filtrar_administracion(facturas, gastos)

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
    col1.metric("Facturacion neta", formato_pesos(ingresos))
    col2.metric("Gastos", formato_pesos(gastos_total))
    col3.metric("Utilidad estimada", formato_pesos(utilidad))
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
        st.altair_chart(grafico_lineas_financieras(mensual), use_container_width=True)

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
                use_container_width=True,
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
                use_container_width=True,
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
                use_container_width=True,
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
                use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
            use_container_width=True,
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
        use_container_width=True,
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


def responder_pregunta(pregunta, viajes, mantenciones, documentos, facturas=None, gastos=None):
    respuesta_cantidad_pdf = responder_cantidad_pdf(pregunta, documentos)
    if respuesta_cantidad_pdf:
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
            return responder_analitica(pregunta, viajes, mantenciones, facturas, gastos, intencion_semantica)

        if intencion_semantica["tipo"] == "documental":
            return responder_documental(pregunta, documentos)

    intencion = clasificar_intencion(pregunta)

    if intencion == "analitica":
        return responder_analitica(pregunta, viajes, mantenciones, facturas, gastos)

    return responder_documental(pregunta, documentos)


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


def responder_documental(pregunta, documentos=None):
    if documentos is None:
        documentos = globals().get("documentos", pd.DataFrame())

    documentos_pdf = filtrar_documentos_pdf(documentos)

    @st.cache_resource(show_spinner=False)
    def construir_rag_documental(documentos_indexados):
        return SemanticRAG(None, None, documentos_indexados)

    try:
        rag_documental = construir_rag_documental(documentos_pdf)
    except ModuleNotFoundError as error:
        st.warning(f"{error}. Se usara el RAG simple para esta sesion.")
        rag_documental = RAG(None, None, documentos_pdf)

    contexto = rag_documental.obtener_contexto(pregunta)

    if contexto_documental_insuficiente(contexto):
        return (
            "No encontré esta información en los documentos disponibles. "
            "Consulta con el área responsable si necesitas una confirmación oficial."
        )

    try:
        chatbot = ChatbotOpenRouter()
        respuesta = chatbot.preguntar(pregunta, contexto)
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


def responder_analitica(pregunta, viajes=None, mantenciones=None, facturas=None, gastos=None, intencion=None):
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
        return respuesta_calculada

    respuesta_administrativa = responder_analitica_administrativa(pregunta, facturas, gastos)
    if respuesta_administrativa:
        return respuesta_administrativa

    @st.cache_resource(show_spinner=False)
    def construir_rag(viajes, mantenciones):
        try:
            return SemanticRAG(viajes, mantenciones, None)
        except ModuleNotFoundError as error:
            st.warning(f"{error}. Se usara el RAG simple para esta sesion.")
            return RAG(viajes, mantenciones, None)

    contexto = construir_rag(viajes, mantenciones).obtener_contexto(pregunta)

    try:
        chatbot = ChatbotOpenRouter()
        return chatbot.preguntar(pregunta, contexto)
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
        ruta_pdf = Path(RUTA_PDFS) / archivo
        if ruta_pdf.exists():
            st.download_button(
                "Descargar PDF",
                data=ruta_pdf.read_bytes(),
                file_name=archivo,
                mime="application/pdf",
            )


st.title("Chatbot Gerencial")
st.caption("Consultas sobre viajes de materiales/redes, cosecha, mantenciones, equipos e ingresos netos.")

try:
    base = cargar_base(str(Path(RUTA_SQL).stat().st_mtime))
except Exception as error:
    st.error(f"No fue posible cargar la base SQL. Detalle: {error}")
    st.stop()

try:
    administracion = cargar_administracion(str(Path(RUTA_ADMINISTRACION).stat().st_mtime))
except Exception as error:
    administracion = {"facturas": pd.DataFrame(), "gastos": pd.DataFrame(), "kpis": pd.DataFrame()}
    st.warning(f"No fue posible cargar administracion.xlsx. Detalle: {error}")

try:
    documentos_pdf = cargar_documentos_pdf(obtener_marca_modificacion_pdfs())
except Exception as error:
    documentos_pdf = pd.DataFrame()
    st.warning(f"No fue posible cargar los PDF de data/. Detalle: {error}")

viajes = base["viajes"]
mantenciones = base["mantenciones"]
documentos = pd.concat([base["documentos"], documentos_pdf], ignore_index=True)
facturas = administracion["facturas"]
gastos = administracion["gastos"]
kpis_administracion = administracion["kpis"]

if viajes.empty:
    st.warning("No hay viajes disponibles en la base cargada.")
    st.stop()

viajes_filtrados = aplicar_filtros_viajes(viajes)
mantenciones_filtradas = aplicar_filtros_mantenciones(mantenciones)

if viajes_filtrados.empty:
    st.warning("No hay viajes para los filtros seleccionados.")
    st.stop()

analizador = AnalizadorOperacional(viajes_filtrados, mantenciones_filtradas)
kpis_viajes = calcular_kpis_viajes(viajes_filtrados)
kpis_flota = calcular_kpis_flota(mantenciones_filtradas)
mostrar_kpis(
    kpis_viajes,
    kpis_flota,
    mantenciones_filtradas.attrs.get("filtros_mantenciones_activos", False),
)

st.divider()

tab_chat, tab_graficos_mantencion, tab_graficos_ingresos, tab_administracion, tab_viajes, tab_mantenciones, tab_documentos = st.tabs(
    [
        "Chat",
        "Graficos mantencion",
        "Graficos ingresos",
        "Administracion",
        "Viajes",
        "Mantenciones",
        "Documentos RAG",
    ]
)

with tab_chat:
    st.subheader("Consulta gerencial")

    ejemplos = [
        "Dame un resumen general",
        "Que centros tienen mayor ingreso neto",
        "Que conductores concentran mayor ingreso neto",
        "Que rutas tienen mayor ingreso neto",
        "Compara ingresos por fuente de viaje",
        "Que patentes tienen mayor costo de mantencion",
        "Que tipos de mantencion tienen mayor costo",
        "Que centros tienen mas guias",
    ]

    pregunta = st.selectbox(
        "Pregunta rapida",
        [""] + ejemplos,
        placeholder="Selecciona una pregunta",
    )
    pregunta_manual = st.text_input("O escribe tu pregunta")
    consulta = pregunta_manual.strip() or pregunta

    if "historial" not in st.session_state:
        st.session_state.historial = []

    if st.button("Consultar", type="primary"):
        if not consulta:
            st.warning("Debes escribir o seleccionar una pregunta.")
        else:
            with st.spinner("Analizando datos..."):
                try:
                    respuesta = responder_pregunta(
                        consulta,
                        viajes_filtrados,
                        mantenciones_filtradas,
                        documentos,
                        facturas,
                        gastos,
                    )
                    st.session_state.historial.append(
                        {"pregunta": consulta, "respuesta": respuesta}
                    )
                except Exception as error:
                    logger.exception("Error inesperado al generar la respuesta")
                    st.error(f"No se pudo generar la respuesta. Detalle: {error}")
                    with st.expander("Detalle técnico del error", expanded=True):
                        st.exception(error)

    for item in reversed(st.session_state.historial):
        with st.chat_message("user"):
            st.write(item["pregunta"])
        with st.chat_message("assistant"):
            st.write(item["respuesta"])

with tab_graficos_mantencion:
    mostrar_graficos_mantencion(mantenciones_filtradas)

with tab_graficos_ingresos:
    mostrar_graficos_ingresos(viajes_filtrados)

with tab_administracion:
    mostrar_administracion(facturas, gastos, kpis_administracion)

with tab_viajes:
    st.subheader("Viajes disponibles")
    st.dataframe(viajes_filtrados, width="stretch")

with tab_mantenciones:
    st.subheader("Mantenciones disponibles")
    st.dataframe(mantenciones_filtradas, width="stretch")

with tab_documentos:
    mostrar_documentos(documentos)
