from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from modules.analizador_operacional import AnalizadorOperacional
from modules.chatbot_openrouter import ChatbotOpenRouter
from modules.lector_administracion import LectorAdministracion
from modules.lector_sql import LectorSQL
from modules.rag import RAG, SemanticRAG


RUTA_SQL = "data/base_datos_chatbot_rag_transportes.sql"
RUTA_ADMINISTRACION = "data/administracion.xlsx"


load_dotenv()


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

    return filtradas


def mostrar_kpis(kpis):
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Viajes", f"{kpis['viajes']:.0f}")
    col2.metric("Ingreso neto", f"${kpis['ingreso_neto']:,.0f}")
    col3.metric("Mantenciones", f"{kpis['mantenciones']:.0f}")
    col4.metric("Costo mantenciones", f"${kpis['costo_mantenciones']:,.0f}")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Resultado neto", f"${kpis['resultado_neto']:,.0f}")
    col6.metric("Guias", f"{kpis['guias']:,.0f}")
    col7.metric("Fuentes viajes", f"{kpis['fuentes_viajes']:.0f}")
    col8.metric("Costo total", f"${kpis['costo_total']:,.0f}")


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


def responder_pregunta(pregunta, viajes, mantenciones, documentos):
    analizador = AnalizadorOperacional(viajes, mantenciones)
    respuesta_calculada = analizador.generar_respuesta_calculada(pregunta)

    if respuesta_calculada:
        return respuesta_calculada

    @st.cache_resource(show_spinner=False)
    def construir_rag(viajes, mantenciones, documentos):
        try:
            return SemanticRAG(viajes, mantenciones, documentos)
        except ModuleNotFoundError as error:
            st.warning(
                f"{error}. Se usara el RAG simple para esta sesion."
            )
            return RAG(viajes, mantenciones, documentos)

    rag = construir_rag(viajes, mantenciones, documentos)
    contexto = rag.obtener_contexto(pregunta)
    chatbot = ChatbotOpenRouter()
    return chatbot.preguntar(pregunta, contexto)


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

viajes = base["viajes"]
mantenciones = base["mantenciones"]
documentos = base["documentos"]
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
mostrar_kpis(analizador.obtener_kpis())

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
                    )
                    st.session_state.historial.append(
                        {"pregunta": consulta, "respuesta": respuesta}
                    )
                except Exception as error:
                    st.error(f"No se pudo generar la respuesta. Detalle: {error}")

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
    st.subheader("Documentos RAG disponibles")
    st.dataframe(documentos, width="stretch")
