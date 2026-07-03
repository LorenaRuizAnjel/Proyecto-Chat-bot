class RAG:
    def __init__(self, viajes, mantenciones=None, documentos=None):
        self.viajes = viajes
        self.mantenciones = mantenciones
        self.documentos = documentos

    def obtener_contexto(self, pregunta="", limite_filas=12):
        partes = []

        contexto_viajes = self._contexto_viajes(pregunta, limite_filas)
        if contexto_viajes:
            partes.append("Viajes:\n" + contexto_viajes)

        contexto_mantenciones = self._contexto_mantenciones(pregunta, limite_filas)
        if contexto_mantenciones:
            partes.append("Mantenciones:\n" + contexto_mantenciones)

        contexto_documentos = self._contexto_documentos(pregunta, limite_filas)
        if contexto_documentos:
            partes.append("Documentos RAG:\n" + contexto_documentos)

        return "\n\n".join(partes) if partes else "No hay datos disponibles."

    def _contexto_viajes(self, pregunta, limite_filas):
        if self.viajes is None or self.viajes.empty:
            return ""

        datos_relevantes = self._filtrar_por_menciones(
            self.viajes,
            pregunta,
            [
                "Fuente",
                "Centro",
                "Conductor",
                "Tipo Camion",
                "Desde",
                "Hasta",
                "Ruta",
                "Patente Tracto",
                "Patente Rampla",
                "Tipo Carga",
            ],
        )

        columnas_contexto = [
            "Fuente",
            "Fecha",
            "Centro",
            "Orden Control",
            "Conductor",
            "Tipo Camion",
            "Ruta",
            "Cantidad Guias",
            "Ingreso Neto",
        ]

        datos_relevantes = datos_relevantes[columnas_contexto].head(limite_filas).copy()
        datos_relevantes["Fecha"] = datos_relevantes["Fecha"].dt.strftime("%Y-%m-%d")
        return datos_relevantes.to_string(index=False)

    def _contexto_mantenciones(self, pregunta, limite_filas):
        if self.mantenciones is None or self.mantenciones.empty:
            return ""

        datos_relevantes = self._filtrar_por_menciones(
            self.mantenciones,
            pregunta,
            ["Patente", "Tipo Mantencion", "Motivo", "Fuente"],
        )

        columnas_contexto = [
            "Fecha",
            "Patente",
            "Tipo Mantencion",
            "Motivo",
            "Costo Repuestos",
            "Costo Mano Obra",
            "Costo Total",
        ]

        datos_relevantes = datos_relevantes[columnas_contexto].head(limite_filas).copy()
        datos_relevantes["Fecha"] = datos_relevantes["Fecha"].dt.strftime("%Y-%m-%d")
        return datos_relevantes.to_string(index=False)

    def _contexto_documentos(self, pregunta, limite_filas):
        if self.documentos is None or self.documentos.empty:
            return ""

        pregunta = pregunta.lower()
        documentos = self.documentos.copy()

        if pregunta:
            mascara = documentos["Contenido"].fillna("").str.lower().apply(
                lambda contenido: any(palabra in contenido for palabra in pregunta.split() if len(palabra) > 3)
            )
            if mascara.any():
                documentos = documentos[mascara]

        columnas = ["Tipo Documento", "Referencia Tabla", "Referencia ID", "Contenido"]
        return documentos[columnas].head(limite_filas).to_string(index=False)

    def _filtrar_por_menciones(self, datos, pregunta, columnas_busqueda):
        pregunta = pregunta.lower()
        mascara = None

        for columna in columnas_busqueda:
            valores = datos[columna].dropna().astype(str).unique()

            for valor in valores:
                valor_normalizado = valor.lower()
                if valor_normalizado and valor_normalizado in pregunta:
                    coincidencia = datos[columna].astype(str).str.lower() == valor_normalizado
                    mascara = coincidencia if mascara is None else mascara | coincidencia

        if mascara is None:
            return datos.copy()

        return datos[mascara].copy()
