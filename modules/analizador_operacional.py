class AnalizadorOperacional:
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

    def generar_respuesta_calculada(self, pregunta):
        pregunta_normalizada = pregunta.lower().strip()

        if not pregunta_normalizada:
            return None

        if self._menciona(pregunta_normalizada, ["kpi", "indicador", "resumen", "general"]):
            return self._resumen_general()

        if self._menciona(pregunta_normalizada, ["mantencion", "mantenciones", "mantenimiento", "repuesto", "mano de obra"]):
            return self._respuesta_mantenciones(pregunta_normalizada)

        if self._menciona(pregunta_normalizada, ["ingreso", "ingresos", "venta", "ventas", "flete", "tarifa"]):
            grupo = self._grupo_viajes_mencionado(pregunta_normalizada)
            return self._ranking_viajes(grupo, "Ingreso Neto", "ingreso neto")

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

    def _grupo_viajes_mencionado(self, pregunta):
        if self._menciona(pregunta, ["conductor", "conductores"]):
            return "Conductor"
        if self._menciona(pregunta, ["ruta", "rutas", "origen", "destino"]):
            return "Ruta"
        if self._menciona(pregunta, ["fuente", "informe", "cosecha", "materiales", "redes"]):
            return "Fuente"
        return "Centro"

    def _menciona(self, pregunta, palabras):
        return any(palabra in pregunta for palabra in palabras)
