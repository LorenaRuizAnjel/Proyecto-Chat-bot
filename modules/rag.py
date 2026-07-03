import numpy as np
import pandas as pd
import re
import unicodedata


def cargar_dependencias_semanticas():
    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.neighbors import NearestNeighbors
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            f"Falta instalar {error.name} en el entorno que esta ejecutando Streamlit. "
            "Ejecuta: python -m pip install -r requirements.txt"
        ) from error

    return SentenceTransformer, NearestNeighbors


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


class SemanticRAG:
    """RAG semantico hibrido para datos operacionales."""

    STOPWORDS = {
        "sobre",
        "para",
        "como",
        "cual",
        "cuales",
        "dame",
        "dime",
        "que",
        "los",
        "las",
        "del",
        "una",
        "unos",
        "con",
        "por",
        "mas",
        "menos",
        "tiene",
        "tienen",
        "hay",
        "segun",
        "desde",
        "hasta",
        "entre",
    }

    def __init__(
        self,
        viajes=None,
        mantenciones=None,
        documentos=None,
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        candidate_k=30,
        min_score=0.12,
    ):
        self.viajes = viajes
        self.mantenciones = mantenciones
        self.documentos = documentos
        self.model_name = model_name
        self.candidate_k = candidate_k
        self.min_score = min_score

        SentenceTransformer, NearestNeighbors = cargar_dependencias_semanticas()
        self.model = SentenceTransformer(self.model_name)
        self.docs_df = self._construir_corpus()

        if self.docs_df.empty:
            dimension = self.model.get_sentence_embedding_dimension()
            self.embeddings = np.zeros((0, dimension))
            self.index = None
            return

        self.embeddings = self.model.encode(
            self.docs_df["texto_embedding"].tolist(),
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        self.index = NearestNeighbors(metric="cosine")
        self.index.fit(self.embeddings)

    def _construir_corpus(self):
        filas = []
        filas.extend(self._documentos_corpus())
        filas.extend(self._viajes_corpus())
        filas.extend(self._mantenciones_corpus())

        if filas:
            return pd.DataFrame(filas)

        return pd.DataFrame(
            columns=["tipo", "titulo", "texto", "texto_embedding", "meta", "tokens"]
        )

    def _documentos_corpus(self):
        if self.documentos is None or self.documentos.empty:
            return []

        filas = []
        for _, row in self.documentos.iterrows():
            contenido = self._limpiar_texto(row.get("Contenido", ""))
            if not contenido:
                continue

            meta = {
                "tipo_documento": row.get("Tipo Documento"),
                "referencia_tabla": row.get("Referencia Tabla"),
                "referencia_id": row.get("Referencia ID"),
            }
            titulo = self._titulo_desde_meta("Documento RAG", meta)

            for numero, chunk in enumerate(self._fragmentar(contenido), start=1):
                titulo_chunk = f"{titulo} fragmento {numero}"
                filas.append(self._crear_doc("documento", titulo_chunk, chunk, meta))

        return filas

    def _viajes_corpus(self):
        if self.viajes is None or self.viajes.empty:
            return []

        filas = []
        columnas = [
            "Fuente",
            "Fecha",
            "Centro",
            "Orden Control",
            "Conductor",
            "Tipo Camion",
            "Ruta",
            "Desde",
            "Hasta",
            "Patente Tracto",
            "Patente Rampla",
            "Tipo Carga",
            "Cantidad Guias",
            "Ingreso Neto",
        ]

        for _, row in self.viajes.iterrows():
            titulo = f"Viaje {self._valor(row, 'Orden Control')} - {self._valor(row, 'Ruta')}"
            texto = self._texto_campos("Viaje operacional", row, columnas)
            meta = {
                "orden_control": row.get("Orden Control"),
                "centro": row.get("Centro"),
                "conductor": row.get("Conductor"),
                "ruta": row.get("Ruta"),
                "fuente": row.get("Fuente"),
            }
            filas.append(self._crear_doc("viaje", titulo, texto, meta))

        filas.extend(
            self._agregados_viajes(
                [
                    ("centro", "Centro"),
                    ("ruta", "Ruta"),
                    ("conductor", "Conductor"),
                    ("fuente", "Fuente"),
                    ("tracto", "Patente Tracto"),
                ]
            )
        )
        return filas

    def _mantenciones_corpus(self):
        if self.mantenciones is None or self.mantenciones.empty:
            return []

        filas = []
        columnas = [
            "Fecha",
            "Patente",
            "Tipo Mantencion",
            "Motivo",
            "Costo Repuestos",
            "Costo Mano Obra",
            "Costo Total",
            "Fuente",
        ]

        for _, row in self.mantenciones.iterrows():
            titulo = f"Mantencion {self._valor(row, 'Patente')} - {self._valor(row, 'Tipo Mantencion')}"
            texto = self._texto_campos("Mantencion de equipo", row, columnas)
            meta = {
                "patente": row.get("Patente"),
                "tipo_mantencion": row.get("Tipo Mantencion"),
                "motivo": row.get("Motivo"),
            }
            filas.append(self._crear_doc("mantencion", titulo, texto, meta))

        filas.extend(
            self._agregados_mantenciones(
                [
                    ("patente", "Patente"),
                    ("tipo_mantencion", "Tipo Mantencion"),
                    ("motivo", "Motivo"),
                ]
            )
        )
        return filas

    def _agregados_viajes(self, grupos):
        filas = []
        for tipo_grupo, columna in grupos:
            if columna not in self.viajes.columns:
                continue

            resumen = (
                self.viajes.groupby(columna, dropna=False)
                .agg(
                    viajes=("ID", "count"),
                    ingreso_neto=("Ingreso Neto", "sum"),
                    guias=("Cantidad Guias", "sum"),
                )
                .sort_values(["ingreso_neto", "viajes"], ascending=False)
                .head(15)
            )

            for nombre, row in resumen.iterrows():
                texto = (
                    f"Resumen de viajes por {columna}: {nombre}. "
                    f"Total de viajes: {int(row['viajes'])}. "
                    f"Ingreso neto por tarifa flete: {self._formato_moneda(row['ingreso_neto'])}. "
                    f"Cantidad de guias: {int(row['guias'])}."
                )
                meta = {"grupo": columna, "valor": nombre}
                filas.append(self._crear_doc(f"resumen_viajes_{tipo_grupo}", str(nombre), texto, meta))

        return filas

    def _agregados_mantenciones(self, grupos):
        filas = []
        for tipo_grupo, columna in grupos:
            if columna not in self.mantenciones.columns:
                continue

            resumen = (
                self.mantenciones.groupby(columna, dropna=False)
                .agg(
                    mantenciones=("Patente", "count"),
                    costo_total=("Costo Total", "sum"),
                    costo_repuestos=("Costo Repuestos", "sum"),
                    costo_mano_obra=("Costo Mano Obra", "sum"),
                )
                .sort_values(["costo_total", "mantenciones"], ascending=False)
                .head(15)
            )

            for nombre, row in resumen.iterrows():
                texto = (
                    f"Resumen de mantenciones por {columna}: {nombre}. "
                    f"Total de mantenciones: {int(row['mantenciones'])}. "
                    f"Costo total: {self._formato_moneda(row['costo_total'])}. "
                    f"Repuestos: {self._formato_moneda(row['costo_repuestos'])}. "
                    f"Mano de obra: {self._formato_moneda(row['costo_mano_obra'])}."
                )
                meta = {"grupo": columna, "valor": nombre}
                filas.append(self._crear_doc(f"resumen_mantenciones_{tipo_grupo}", str(nombre), texto, meta))

        return filas

    def obtener_contexto(self, pregunta, top_k=8):
        if self.index is None:
            return "No hay datos disponibles para construir contexto semantico."

        pregunta = self._limpiar_texto(pregunta)
        if not pregunta:
            return "No hay pregunta disponible para construir contexto semantico."

        q_emb = self.model.encode(
            [pregunta],
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        n_candidatos = min(self.candidate_k, len(self.docs_df))
        distancias, indices = self.index.kneighbors(q_emb, n_neighbors=n_candidatos)
        tokens_pregunta = self._tokens(pregunta)

        candidatos = []
        for distancia, indice in zip(distancias[0], indices[0]):
            fila = self.docs_df.iloc[indice]
            semantic_score = max(0.0, 1.0 - float(distancia))
            lexical_score = self._score_lexico(tokens_pregunta, fila["tokens"])
            exact_score = self._score_menciones(pregunta, fila["meta"])
            final_score = (semantic_score * 0.75) + (lexical_score * 0.15) + (exact_score * 0.10)

            if final_score >= self.min_score:
                candidatos.append((final_score, semantic_score, lexical_score, fila))

        if not candidatos:
            return "No encontre contexto suficientemente relevante en los datos disponibles."

        candidatos.sort(key=lambda item: item[0], reverse=True)
        piezas = []
        for final_score, semantic_score, lexical_score, fila in candidatos[:top_k]:
            meta = fila["meta"] if isinstance(fila["meta"], dict) else {}
            meta_text = ", ".join(f"{k}={v}" for k, v in meta.items() if pd.notna(v) and v != "")
            encabezado = (
                f"Fuente: {fila['tipo']} | Relevancia: {final_score:.2f} "
                f"(semantica {semantic_score:.2f}, lexica {lexical_score:.2f})"
            )
            if meta_text:
                encabezado += f" | {meta_text}"

            piezas.append(f"{encabezado}\n{fila['texto']}")

        return "\n\n".join(piezas)

    def _crear_doc(self, tipo, titulo, texto, meta):
        texto = self._limpiar_texto(texto)
        titulo = self._limpiar_texto(titulo)
        texto_embedding = f"{tipo}. {titulo}. {texto}"
        return {
            "tipo": tipo,
            "titulo": titulo,
            "texto": texto,
            "texto_embedding": texto_embedding,
            "meta": meta,
            "tokens": self._tokens(texto_embedding),
        }

    def _texto_campos(self, prefijo, row, columnas):
        partes = [prefijo]
        for columna in columnas:
            if columna not in row.index:
                continue

            valor = self._valor(row, columna)
            if valor:
                partes.append(f"{columna}: {valor}")

        return ". ".join(partes) + "."

    def _fragmentar(self, texto, max_palabras=120, solape=25):
        palabras = texto.split()
        if len(palabras) <= max_palabras:
            return [texto]

        chunks = []
        paso = max(1, max_palabras - solape)
        for inicio in range(0, len(palabras), paso):
            chunk = " ".join(palabras[inicio : inicio + max_palabras])
            if chunk:
                chunks.append(chunk)

        return chunks

    def _score_lexico(self, tokens_pregunta, tokens_documento):
        if not tokens_pregunta or not tokens_documento:
            return 0.0

        coincidencias = tokens_pregunta & tokens_documento
        return len(coincidencias) / len(tokens_pregunta)

    def _score_menciones(self, pregunta, meta):
        if not isinstance(meta, dict):
            return 0.0

        valores = [self._normalizar(valor) for valor in meta.values() if pd.notna(valor)]
        valores = [valor for valor in valores if len(valor) >= 3]
        if not valores:
            return 0.0

        pregunta_normalizada = self._normalizar(pregunta)
        return 1.0 if any(valor in pregunta_normalizada for valor in valores) else 0.0

    def _tokens(self, texto):
        texto = self._normalizar(texto)
        tokens = set(re.findall(r"[a-z0-9]{3,}", texto))
        return {token for token in tokens if token not in self.STOPWORDS}

    def _normalizar(self, texto):
        texto = "" if texto is None else str(texto).lower()
        texto = unicodedata.normalize("NFKD", texto)
        texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
        return re.sub(r"\s+", " ", texto).strip()

    def _limpiar_texto(self, texto):
        if texto is None or pd.isna(texto):
            return ""

        return re.sub(r"\s+", " ", str(texto)).strip()

    def _titulo_desde_meta(self, prefijo, meta):
        valores = [str(valor) for valor in meta.values() if pd.notna(valor) and str(valor).strip()]
        return f"{prefijo}: " + " | ".join(valores) if valores else prefijo

    def _valor(self, row, columna):
        valor = row.get(columna, "")
        if pd.isna(valor):
            return ""

        if isinstance(valor, pd.Timestamp):
            return valor.strftime("%Y-%m-%d")

        if columna in ["Ingreso Neto", "Tarifa Flete", "Costo Total", "Costo Repuestos", "Costo Mano Obra"]:
            return self._formato_moneda(valor)

        return str(valor)

    def _formato_moneda(self, valor):
        try:
            return f"${float(valor):,.0f}"
        except (TypeError, ValueError):
            return str(valor)
