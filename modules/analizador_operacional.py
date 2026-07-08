import re
import unicodedata


class AnalizadorOperacional:
    SINONIMOS = {
        "choferes": "conductores",
        "chofer": "conductor",
        "operarios": "conductores",
        "operario": "conductor",
        "operadores": "conductores",
        "operador": "conductor",
        "trabajadores": "conductores",
        "trabajador": "conductor",
        "pilotos": "conductores",
        "piloto": "conductor",
        "camioneros": "conductores",
        "camionero": "conductor",
        "conductora": "conductor",
        "conductoras": "conductores",
    }

    def __init__(self, viajes, mantenciones=None):
        self.viajes = viajes
        self.mantenciones = mantenciones

    def obtener_kpis(self):
        viajes_vacios = self.viajes is None or self.viajes.empty
        mantenciones_vacias = self.mantenciones is None or self.mantenciones.empty

        ingreso_neto = 0 if viajes_vacios else float(self.viajes["Ingreso Neto"].sum())
        costo_mantenciones = 0 if mantenciones_vacias else float(self.mantenciones["Costo Total"].sum())

        return {
            "viajes": 0 if viajes_vacios else int(len(self.viajes)),
            "ingreso_neto": ingreso_neto,
            "tarifa_flete": ingreso_neto,
            "mantenciones": 0 if mantenciones_vacias else int(len(self.mantenciones)),
            "costo_mantenciones": costo_mantenciones,
            "costo_total": costo_mantenciones,
            "resultado_neto": ingreso_neto - costo_mantenciones,
            "guias": 0 if viajes_vacios else int(self.viajes["Cantidad Guias"].sum()),
            "fuentes_viajes": 0 if viajes_vacios else int(self.viajes["Fuente"].nunique()),
        }

    def generar_respuesta_calculada(self, pregunta, intencion=None):
        pregunta_normalizada = self._normalizar_pregunta(pregunta)

        if not pregunta_normalizada:
            return None

        if self._es_resultado_por_vehiculo(pregunta_normalizada):
            return self._resultado_neto_por_vehiculo(pregunta_normalizada)

        respuesta_intencion = self._respuesta_desde_intencion(intencion)
        if respuesta_intencion:
            return respuesta_intencion

        if self._menciona(pregunta_normalizada, ["kpi", "indicador", "resumen", "general"]):
            return self._resumen_general()

        if self._es_monto_mantencion_por_vehiculo(pregunta_normalizada):
            return self._ranking_mantenciones_por_patente()

        if self._es_pregunta_calculada_mantenciones(pregunta_normalizada):
            return self._respuesta_mantenciones(pregunta_normalizada)

        if self._menciona(pregunta_normalizada, ["ingreso", "ingresos", "venta", "ventas", "flete", "tarifa"]):
            return self._respuesta_ingresos(pregunta_normalizada)

        if self._menciona(pregunta_normalizada, ["cosecha", "materiales", "redes", "fuente", "informe"]):
            return self._ranking_viajes("Fuente", "Ingreso Neto", "ingreso neto")

        if self._menciona(pregunta_normalizada, ["centro", "centros"]):
            return self._ranking_viajes("Centro", "Ingreso Neto", "ingreso neto")

        if self._menciona(pregunta_normalizada, ["conductor", "conductores"]):
            return self._ranking_viajes("Conductor", "Ingreso Neto", "ingreso neto")

        if self._menciona(pregunta_normalizada, ["ruta", "rutas", "origen", "destino"]):
            return self._ranking_viajes("Ruta", "Ingreso Neto", "ingreso neto")

        if self._menciona(pregunta_normalizada, ["guia", "guias"]):
            return self._ranking_viajes("Centro", "Cantidad Guias", "guias")

        return None

    def _respuesta_desde_intencion(self, intencion):
        if not intencion or intencion.get("tipo") != "analitica":
            return None

        metrica = intencion.get("metrica")
        entidad = intencion.get("entidad")

        if metrica == "ingreso_neto":
            if entidad == "conductor":
                return self._ranking_ingresos_por_columna("Conductor", "Ranking de ingresos por conductor:")

            if entidad == "patente_tracto":
                return self._ranking_ingresos_por_columna("Patente Tracto", "Ranking de ingresos por tracto:")

            if entidad == "patente_rampla":
                return self._ranking_ingresos_por_columna("Patente Rampla", "Ranking de ingresos por rampla:")

            if entidad == "vehiculo":
                return self._ranking_vehiculos_por_ingreso()

            if entidad == "centro":
                return self._ranking_ingresos_por_columna("Centro", "Ranking de ingresos por centro:")

            if entidad == "ruta":
                return self._ranking_ingresos_por_columna("Ruta", "Ranking de ingresos por ruta:")

        if metrica == "costo_mantencion" and entidad == "vehiculo":
            return self._ranking_mantenciones_por_patente()

        return None

    def _resumen_general(self):
        kpis = self.obtener_kpis()

        return (
            "Resumen operacional:\n"
            f"- Viajes registrados: {kpis['viajes']:.0f}\n"
            f"- Fuentes de viajes: {kpis['fuentes_viajes']:.0f}\n"
            f"- Ingreso neto por tarifa flete: ${kpis['ingreso_neto']:,.0f}\n"
            f"- Mantenciones registradas: {kpis['mantenciones']:.0f}\n"
            f"- Costo de mantenciones: ${kpis['costo_mantenciones']:,.0f}\n"
            f"- Resultado neto estimado: ${kpis['resultado_neto']:,.0f}\n"
            f"- Guias transportadas: {kpis['guias']:,.0f}"
        )

    def _respuesta_mantenciones(self, pregunta):
        if self.mantenciones is None or self.mantenciones.empty:
            return "No hay mantenciones disponibles en los datos cargados."

        if self._menciona(pregunta, ["tipo", "preventiva", "evento"]):
            return self._ranking_mantenciones("Tipo Mantencion", "Costo Total", "costo total")

        return self._ranking_mantenciones("Patente", "Costo Total", "costo total")

    def _ranking_viajes(self, grupo, columna, etiqueta):
        if self.viajes is None or self.viajes.empty:
            return f"No hay viajes suficientes para calcular {etiqueta}."

        error_columnas = self._validar_columnas(self.viajes, [grupo, columna], "viajes")
        if error_columnas:
            return error_columnas

        ranking = (
            self.viajes.groupby(grupo, dropna=False)[columna]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )

        if ranking.empty:
            return f"No hay viajes suficientes para calcular {etiqueta}."

        if columna in ["Ingreso Neto", "Tarifa Flete", "Costo Total"]:
            lineas = "\n".join(f"- {nombre}: ${valor:,.0f}" for nombre, valor in ranking.items())
        else:
            lineas = "\n".join(f"- {nombre}: {valor:,.0f} {etiqueta}" for nombre, valor in ranking.items())

        return f"Ranking por {grupo.lower()} segun {etiqueta}:\n{lineas}"

    def _ranking_mantenciones(self, grupo, columna, etiqueta):
        error_columnas = self._validar_columnas(self.mantenciones, [grupo, columna], "mantenciones")
        if error_columnas:
            return error_columnas

        ranking = (
            self.mantenciones.groupby(grupo, dropna=False)[columna]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )

        if ranking.empty:
            return f"No hay mantenciones suficientes para calcular {etiqueta}."

        lineas = "\n".join(f"- {nombre}: ${valor:,.0f}" for nombre, valor in ranking.items())
        return f"Ranking de mantenciones por {grupo.lower()} segun {etiqueta}:\n{lineas}"

    def _respuesta_ingresos(self, pregunta):
        if self._menciona(pregunta, ["tracto", "tractos"]):
            return self._ranking_ingresos_por_columna("Patente Tracto", "Ranking de ingresos por tracto:")

        if self._menciona(pregunta, ["rampla", "ramplas"]):
            return self._ranking_ingresos_por_columna("Patente Rampla", "Ranking de ingresos por rampla:")

        if self._menciona(pregunta, self._palabras_vehiculo()):
            return self._ranking_vehiculos_por_ingreso()

        grupo = self._grupo_viajes_mencionado(pregunta)
        return self._ranking_viajes(grupo, "Ingreso Neto", "ingreso neto")

    def _ranking_ingresos_por_columna(self, grupo, titulo):
        if self.viajes is None or self.viajes.empty:
            return "No hay viajes suficientes para calcular el ranking de ingresos."

        error_columnas = self._validar_columnas(self.viajes, [grupo, "Ingreso Neto"], "viajes")
        if error_columnas:
            return error_columnas

        ranking = self._sumar_por_columna(self.viajes, grupo, "Ingreso Neto", 10)

        if ranking.empty:
            return "No hay viajes suficientes para calcular el ranking de ingresos."

        return f"{titulo}\n\n{self._formatear_ranking_montos(ranking)}"

    def _ranking_vehiculos_por_ingreso(self):
        if self.viajes is None or self.viajes.empty:
            return "No hay viajes suficientes para calcular el ranking de ingresos por vehículo/equipo."

        columnas = ["Patente Tracto", "Patente Rampla", "Ingreso Neto"]
        error_columnas = self._validar_columnas(self.viajes, columnas, "viajes")
        if error_columnas:
            return error_columnas

        tractos = self._sumar_por_columna(self.viajes, "Patente Tracto", "Ingreso Neto", 10)
        ramplas = self._sumar_por_columna(self.viajes, "Patente Rampla", "Ingreso Neto", 10)

        if tractos.empty and ramplas.empty:
            return "No hay datos suficientes para calcular el ranking de ingresos por vehículo/equipo."

        return (
            "Ranking de ingresos por vehículo/equipo:\n\n"
            "Tractos:\n"
            f"{self._formatear_ranking_montos(tractos)}\n\n"
            "Ramplas:\n"
            f"{self._formatear_ranking_montos(ramplas)}"
        )

    def _ranking_mantenciones_por_patente(self):
        if self.mantenciones is None or self.mantenciones.empty:
            return "No hay mantenciones disponibles en los datos cargados."

        columnas = ["Patente", "Costo Total"]
        error_columnas = self._validar_columnas(self.mantenciones, columnas, "mantenciones")
        if error_columnas:
            return error_columnas

        ranking = self._sumar_por_columna(self.mantenciones, "Patente", "Costo Total", 10)

        if ranking.empty:
            return "No hay mantenciones suficientes para calcular el monto por vehiculo/patente."

        return (
            "Monto de mantencion por vehiculo/patente:\n\n"
            f"{self._formatear_ranking_montos(ranking)}"
        )

    def _resultado_neto_por_vehiculo(self, pregunta):
        if self.viajes is None or self.viajes.empty:
            return "No hay viajes suficientes para calcular el resultado neto por vehiculo."

        error_viajes = self._validar_columnas(
            self.viajes,
            ["Patente Tracto", "Patente Rampla", "Ingreso Neto"],
            "viajes",
        )
        if error_viajes:
            return error_viajes

        if self.mantenciones is not None and not self.mantenciones.empty:
            error_mantenciones = self._validar_columnas(self.mantenciones, ["Patente", "Costo Total"], "mantenciones")
            if error_mantenciones:
                return error_mantenciones

        solo_tractos = self._menciona(pregunta, ["tracto", "tractos"])
        solo_ramplas = self._menciona(pregunta, ["rampla", "ramplas"])
        incluir_flota_completa = self._menciona(pregunta, ["flota", "completa", "todos", "todas"])

        resultados = []
        if not solo_ramplas:
            resultados.append(self._resultado_neto_por_tipo("Patente Tracto", "Tracto", incluir_flota_completa))
        if not solo_tractos:
            resultados.append(self._resultado_neto_por_tipo("Patente Rampla", "Rampla", incluir_flota_completa))

        resultados = [resultado for resultado in resultados if resultado is not None and not resultado.empty]
        if not resultados:
            return "No hay datos suficientes para calcular el resultado neto por vehiculo."

        datos = self._concatenar_resultados(resultados)

        if incluir_flota_completa:
            datos = self._agregar_patentes_solo_mantencion(datos)

        datos = datos.sort_values("Resultado neto estimado", ascending=False).head(10)

        lineas = []
        for _, fila in datos.iterrows():
            lineas.append(
                f"- {fila['Patente']} ({fila['Tipo']}): "
                f"Ingreso {self._formatear_pesos(fila['Ingreso neto'])} | "
                f"Mantenciones {self._formatear_pesos(fila['Costo mantenciones'])} | "
                f"Resultado {self._formatear_pesos(fila['Resultado neto estimado'])}"
            )

        return "Resultado neto estimado por vehiculo:\n\n" + "\n".join(lineas)

    def _resultado_neto_por_tipo(self, columna_patente, tipo, incluir_flota_completa=False):
        ingresos = self._sumar_por_columna(self.viajes, columna_patente, "Ingreso Neto", None).reset_index()
        ingresos = ingresos.rename(columns={columna_patente: "Patente", "Ingreso Neto": "Ingreso neto"})
        ingresos["Tipo"] = tipo

        mantenciones = self._costos_mantencion_por_patente()

        datos = ingresos.merge(mantenciones, on="Patente", how="left")

        datos["Ingreso neto"] = datos["Ingreso neto"].fillna(0)
        datos["Costo mantenciones"] = datos["Costo mantenciones"].fillna(0)
        datos["Resultado neto estimado"] = datos["Ingreso neto"] - datos["Costo mantenciones"]

        return datos[["Patente", "Tipo", "Ingreso neto", "Costo mantenciones", "Resultado neto estimado"]]

    def _agregar_patentes_solo_mantencion(self, datos):
        mantenciones = self._costos_mantencion_por_patente()
        if mantenciones.empty:
            return datos

        patentes_con_ingreso = set(datos["Patente"].dropna().astype(str))
        solo_mantencion = mantenciones[~mantenciones["Patente"].astype(str).isin(patentes_con_ingreso)].copy()

        if solo_mantencion.empty:
            return datos

        solo_mantencion["Tipo"] = "Solo mantencion"
        solo_mantencion["Ingreso neto"] = 0
        solo_mantencion["Resultado neto estimado"] = -solo_mantencion["Costo mantenciones"]

        solo_mantencion = solo_mantencion[
            ["Patente", "Tipo", "Ingreso neto", "Costo mantenciones", "Resultado neto estimado"]
        ]
        return self._concatenar_resultados([datos, solo_mantencion])

    def _costos_mantencion_por_patente(self):
        if self.mantenciones is None or self.mantenciones.empty:
            return self.viajes[["Patente Tracto"]].head(0).rename(columns={"Patente Tracto": "Patente"}).assign(
                **{"Costo mantenciones": []}
            )

        datos = self.mantenciones.copy()
        datos["Patente"] = datos["Patente"].fillna("Sin dato").astype(str).str.strip()
        datos = datos[datos["Patente"] != ""]

        return (
            datos.groupby("Patente", dropna=False)["Costo Total"]
            .sum()
            .reset_index(name="Costo mantenciones")
        )

    def _grupo_viajes_mencionado(self, pregunta):
        if self._menciona(pregunta, ["conductor", "conductores", "chofer", "choferes", "operador", "operadores"]):
            return "Conductor"
        if self._menciona(pregunta, ["ruta", "rutas", "origen", "destino"]):
            return "Ruta"
        if self._menciona(pregunta, ["fuente", "informe", "cosecha", "materiales", "redes"]):
            return "Fuente"
        return "Centro"

    def _menciona(self, pregunta, palabras):
        return any(palabra in pregunta for palabra in palabras)

    def _normalizar_pregunta(self, pregunta):
        pregunta_normalizada = self._normalizar_texto(pregunta)
        for sinonimo, canonico in self.SINONIMOS.items():
            pregunta_normalizada = re.sub(
                rf"\b{re.escape(sinonimo)}\b",
                canonico,
                pregunta_normalizada,
            )

        return pregunta_normalizada

    def _normalizar_texto(self, texto):
        texto = "" if texto is None else str(texto).lower()
        texto = unicodedata.normalize("NFKD", texto)
        texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
        return re.sub(r"\s+", " ", texto).strip()

    def _es_resultado_por_vehiculo(self, pregunta):
        palabras_resultado = [
            "resultado",
            "utilidad",
            "neto",
            "margen",
            "rentabilidad",
            "ingreso menos mantencion",
            "ingresos menos mantencion",
            "ingreso menos mantenimiento",
            "ingresos menos mantenimiento",
        ]
        palabras_vehiculo = self._palabras_vehiculo() + ["tracto", "tractos", "rampla", "ramplas", "flota"]

        return self._menciona(pregunta, palabras_resultado) and self._menciona(pregunta, palabras_vehiculo)

    def _es_monto_mantencion_por_vehiculo(self, pregunta):
        palabras_mantencion = ["mantencion", "mantenciones", "mantenimiento"]
        palabras_vehiculo = self._palabras_vehiculo() + ["tracto", "tractos", "rampla", "ramplas"]

        return self._menciona(pregunta, palabras_mantencion) and self._menciona(pregunta, palabras_vehiculo)

    def _palabras_vehiculo(self):
        return [
            "patente",
            "patentes",
            "vehiculo",
            "vehiculos",
            "equipo",
            "equipos",
            "camion",
            "camiones",
        ]

    def _validar_columnas(self, datos, columnas, nombre_datos):
        faltantes = [columna for columna in columnas if columna not in datos.columns]

        if not faltantes:
            return None

        return f"No se puede calcular porque falta la columna: {faltantes[0]}"

    def _sumar_por_columna(self, datos, grupo, columna, limite=10):
        datos_validos = datos.copy()
        datos_validos[grupo] = datos_validos[grupo].fillna("Sin dato").astype(str).str.strip()
        datos_validos = datos_validos[datos_validos[grupo] != ""]

        ranking = (
            datos_validos.groupby(grupo, dropna=False)[columna]
            .sum()
            .sort_values(ascending=False)
        )

        if limite is None:
            return ranking

        return ranking.head(limite)

    def _formatear_ranking_montos(self, ranking):
        if ranking.empty:
            return "- Sin datos disponibles."

        return "\n".join(f"- {nombre}: ${valor:,.0f}" for nombre, valor in ranking.items())

    def _formatear_pesos(self, valor):
        return f"${float(valor):,.0f}".replace(",", ".")

    def _concatenar_resultados(self, resultados):
        import pandas as pd

        return pd.concat(resultados, ignore_index=True)

    def _es_pregunta_calculada_mantenciones(self, pregunta):
        palabras_mantencion = ["mantencion", "mantenciones", "mantenimiento", "repuesto", "mano de obra"]
        palabras_calculo = [
            "costo",
            "costos",
            "mayor",
            "mayores",
            "ranking",
            "top",
            "patente",
            "patentes",
            "tipo",
            "tipos",
            "registradas",
            "total",
        ]

        return self._menciona(pregunta, palabras_mantencion) and self._menciona(pregunta, palabras_calculo)
