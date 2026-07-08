# Chatbot Gerencial

Aplicacion en Streamlit para consultar la base `base_datos_chatbot_rag_transportes.sql`.

## Funcionalidades

- Carga el dump SQL en una base SQLite en memoria.
- Convierte instrucciones MySQL del dump para poder ejecutarlo localmente sin MySQL.
- Une los viajes de `viajes_materiales_redes` y `viajes_cosecha` en una vista operacional.
- Mantiene las mantenciones como un conjunto separado para KPIs, rankings y contexto RAG.
- Usa `documentos_rag` como contexto adicional para preguntas abiertas.
- Lee automaticamente los PDF ubicados en `data/` y los agrega al contexto RAG.
- KPIs gerenciales: viajes, ingreso neto por tarifa flete, mantenciones, costo de mantenciones, resultado neto y guias.
- La `Tarifa Flete` se considera ingreso neto cobrado al cliente por realizar el movimiento.
- Los costos de mantencion se consideran egresos.
- Respuestas calculadas con `pandas` para preguntas frecuentes de negocio.
- Uso de Gemini 2.5 Flash mediante OpenRouter para preguntas abiertas, con contexto recuperado por RAG semantico hibrido.
- RAG semantico con embeddings multilingues, fragmentos de documentos, agregados de negocio y ranking semantico/lexico.
- Historial de conversacion durante la sesion.

## RAG semantico avanzado

El proyecto conserva el RAG simple como respaldo, pero las preguntas abiertas usan `SemanticRAG` cuando las dependencias de embeddings estan disponibles.

El recuperador semantico:

- Usa embeddings multilingues con `paraphrase-multilingual-MiniLM-L12-v2`.
- Fragmenta documentos largos de `documentos_rag`.
- Indexa viajes, mantenciones y documentos en un corpus unificado.
- Agrega resumenes de negocio por centro, ruta, conductor, fuente, patente y tipo de mantencion.
- Reordena resultados con una mezcla de similitud semantica, coincidencias lexicas y menciones exactas.
- Normaliza vocabulario operacional: por ejemplo `chofer`, `operario`, `piloto` y `camionero` se interpretan como `conductor`.
- Si faltan `sentence-transformers` o `scikit-learn` en el entorno de ejecucion, la app muestra un aviso y usa el RAG simple para no romper la interfaz.

## Estructura

- `app.py`: interfaz principal en Streamlit.
- `modules/lector_sql.py`: lectura del dump, compatibilidad SQLite y normalizacion de tablas.
- `modules/lector_pdf.py`: lectura de PDF en `data/` y preparacion en formato de documentos RAG.
- `modules/analizador_operacional.py`: metricas y respuestas calculadas.
- `modules/rag.py`: RAG simple y RAG semantico hibrido para recuperar contexto relevante.
- `modules/chatbot_openrouter.py`: cliente de OpenRouter configurado con `google/gemini-2.5-flash`.
- `data/base_datos_chatbot_rag_transportes.sql`: base principal del chatbot.
- `data/administracion.xlsx`: facturas, gastos y KPIs administrativos.
- `data/*.pdf`: documentos usados como contexto adicional para el chatbot.

## Configuracion

1. Crea un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Copia `.env.example` a `.env` y configura:

```bash
OPENROUTER_API_KEY=tu_api_key_aqui
```

El proyecto usa el identificador `google/gemini-2.5-flash` de OpenRouter. No requiere
una API key directa de Google Gemini.

4. Ejecuta la app:

```bash
streamlit run app.py
```

En Windows, si tienes problemas de dependencias, ejecuta Streamlit usando explicitamente el Python del entorno virtual:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

La primera consulta abierta puede tardar mas porque `sentence-transformers` descarga y cachea el modelo de embeddings. Las siguientes consultas reutilizan el indice con `st.cache_resource`.

## Publicacion en Streamlit Community Cloud

Antes de publicar, verifica que estos archivos esten en el repositorio:

- `app.py`
- `requirements.txt`
- `modules/`
- `data/base_datos_chatbot_rag_transportes.sql`
- `data/administracion.xlsx`
- `.env.example`

No subas `.env` a GitHub. La API key se configura como secreto en Streamlit Cloud.

### Pasos

1. Sube este proyecto a un repositorio de GitHub.
2. Entra a https://share.streamlit.io/.
3. Haz clic en `Create app`.
4. Selecciona el repositorio, la rama y usa este archivo principal:

```text
app.py
```

5. En `Advanced settings`, agrega el secreto:

```toml
OPENROUTER_API_KEY = "tu_api_key_aqui"
```

6. Guarda la configuracion y presiona `Deploy`.

Si la app no necesita responder preguntas abiertas con IA, puede funcionar sin la API key para dashboards y tablas. La API key solo es necesaria cuando se usa el chatbot con OpenRouter.

## Preguntas sugeridas

- Dame un resumen general.
- Que centros tienen mayor ingreso neto.
- Que conductores concentran mayor ingreso neto.
- Que rutas tienen mayor ingreso neto.
- Compara ingresos por fuente de viaje.
- Que patentes tienen mayor costo de mantencion.
- Que tipos de mantencion tienen mayor costo.
