# Chatbot Gerencial

Aplicacion en Streamlit para consultar la base `base_datos_chatbot_rag_transportes.sql`.

## Funcionalidades

- Carga el dump SQL en una base SQLite en memoria.
- Convierte instrucciones MySQL del dump para poder ejecutarlo localmente sin MySQL.
- Une los viajes de `viajes_materiales_redes` y `viajes_cosecha` en una vista operacional.
- Mantiene las mantenciones como un conjunto separado para KPIs, rankings y contexto RAG.
- Usa `documentos_rag` como contexto adicional para preguntas abiertas.
- Lee SQL, Excel y PDF exclusivamente desde un bucket privado de OCI Object Storage.
- KPIs gerenciales: viajes, ingreso neto por tarifa flete, mantenciones, costo de mantenciones, resultado neto y guias.
- La `Tarifa Flete` se considera ingreso neto cobrado al cliente por realizar el movimiento.
- Los costos de mantencion se consideran egresos.
- Respuestas calculadas con `pandas` para preguntas frecuentes de negocio.
- Uso de Gemini 2.5 Flash mediante OpenRouter para preguntas abiertas, con contexto recuperado por RAG semantico hibrido.
- RAG semantico con embeddings multilingues, fragmentos de documentos, agregados de negocio y ranking semantico/lexico.
- Historial de conversacion durante la sesion.
- Auditoria persistente en OCI Object Storage: un JSON por consulta con pregunta,
  contexto recuperado, fuentes, respuesta, latencia, versiones y estado de ejecucion.

## Navegación y acceso

La interfaz organiza el trabajo cotidiano en cinco secciones: **Resumen**, **Consultar a la IA**,
**Operaciones**, **Finanzas** y **Gestión del asistente**. Viajes y mantenciones se consultan como
subsecciones de Operaciones; los documentos RAG, la curaduría, el monitoreo y el ciclo de mejora
se concentran en Gestión del asistente.

El proyecto todavía no incorpora autenticación ni roles. Por ello, Gestión del asistente no está
restringida de forma artificial, pero se mantiene separada para aplicar una regla de administradores
cuando exista ese mecanismo.

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
- `modules/lector_pdf.py`: procesamiento de PDF materializados temporalmente desde OCI.
- `services/oci_storage.py`: autenticacion, listado, metadatos y descarga segura desde OCI.
- `services/storage_factory.py`: resolucion centralizada de los objetos requeridos.
- `modules/analizador_operacional.py`: metricas y respuestas calculadas.
- `modules/rag.py`: RAG simple y RAG semantico hibrido para recuperar contexto relevante.
- `modules/chatbot_openrouter.py`: cliente de OpenRouter configurado con `google/gemini-2.5-flash`.
- `.runtime/`: estado local generado por la aplicacion; no contiene archivos fuente.

## Configuracion

1. Crea un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Copia `.env.example` a `.env` y configura:

```bash
OPENROUTER_API_KEY=tu_api_key_aqui
STORAGE_BACKEND=oci
OCI_CONFIG_PROFILE=DEFAULT
OCI_BUCKET_NAME=nombre_bucket
OCI_NAMESPACE=namespace
OCI_DATA_PREFIX=data
OCI_RAG_PREFIX=data
OCI_AUDIT_PREFIX=auditoria/ejecuciones
APP_VERSION=hash_del_commit_desplegado
```

La autenticacion OCI se obtiene de `~/.oci/config`; la clave privada nunca se guarda
dentro del proyecto. No existe fallback hacia archivos fuente locales.

Cada consulta crea un objeto bajo `OCI_AUDIT_PREFIX/YYYY/MM/DD/`. La identidad OCI
necesita permiso para crear objetos en ese prefijo. El identificador mostrado junto a
la respuesta permite relacionar la conversacion con su JSON de auditoria.

La vista **Gestion del asistente > Auditoria de ejecuciones** permite consultar los
registros recientes, filtrar por estado o pregunta, revisar respuesta, contexto,
fuentes y metadatos, y descargar cada ejecucion como JSON.

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

La primera consulta abierta o documental puede tardar mas porque `sentence-transformers` descarga y cachea el modelo de embeddings. Las siguientes consultas reutilizan los indices con `st.cache_resource`.

## Actualizacion del indice documental

Los embeddings de los PDF se guardan en `.runtime/indice_documental/`. Si no cambian los
documentos, la app reutiliza ese indice; si se crea, modifica o elimina un PDF, genera
uno nuevo. Para actualizarlo fuera de la interfaz, por ejemplo mediante una tarea diaria
de Windows, ejecuta desde la raiz del proyecto:

```powershell
python scripts\actualizar_indice_documental.py
```

## Publicacion en Streamlit Community Cloud

Antes de publicar, verifica que estos archivos esten en el repositorio:

- `app.py`
- `requirements.txt`
- `modules/`
- `services/`
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
