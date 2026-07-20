# Preparacion y despliegue en Streamlit Community Cloud

La aplicacion usa OCI Object Storage como unico origen de SQL, Excel y PDF. En local
se autentica con `~/.oci/config`; en Streamlit Community Cloud usa secretos cargados
desde la consola de la aplicacion. Ninguna clave debe guardarse en GitHub.

## 1. Revisar los archivos que se publicaran

Desde la raiz del proyecto:

```powershell
git status --short
git ls-files data
```

Los archivos de `data/` estaban versionados previamente. Para retirarlos solamente
del indice Git, conservando las copias fisicas locales, ejecuta cuando estes listo:

```powershell
git rm -r --cached data
```

Antes de confirmar el cambio, verifica que los archivos sigan en el disco:

```powershell
Get-ChildItem -LiteralPath data
git status --short
```

No agregues al commit `.env`, `.streamlit/secrets.toml`, archivos `.pem`, `.runtime/`
ni la carpeta `data/`.

## 2. Preparar los secretos

Usa `.streamlit/secrets.toml.example` solo como plantilla. No escribas secretos reales
en ese archivo porque esta versionado. En Streamlit Community Cloud, abre **Advanced
settings > Secrets** y pega un TOML con estas claves:

```toml
STORAGE_BACKEND = "oci"
OCI_AUTH_MODE = "api_key"
OCI_REGION = "sa-santiago-1"
OCI_NAMESPACE = "axbguiv0hwl2"
OCI_BUCKET_NAME = "bucket-20260720-1446"
OCI_DATA_PREFIX = "data"
OCI_RAG_PREFIX = "data"

OCI_USER_OCID = "TU_USER_OCID"
OCI_TENANCY_OCID = "TU_TENANCY_OCID"
OCI_FINGERPRINT = "TU_FINGERPRINT"
OCI_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
CONTENIDO_COMPLETO_DE_TU_CLAVE
-----END PRIVATE KEY-----"""

OPENROUTER_API_KEY = "TU_CLAVE_OPENROUTER"
```

No incluyas `key_file`: en Cloud no existe la ruta de Windows. El PEM se entrega al
SDK de OCI directamente desde Secrets y no se escribe en el repositorio.

## 3. Comprobar permisos OCI

La identidad configurada debe poder inspeccionar el bucket, listar objetos y leer
objetos. No necesita permisos para crear, reemplazar ni eliminar objetos.

## 4. Publicar el codigo en GitHub

Revisa el diff y confirma que no aparezcan OCID reales, fingerprint, PEM ni API keys:

```powershell
git diff --check
git status --short
```

Crea el commit y publica usando tu flujo normal de GitHub. Este proyecto no ejecuta
automaticamente `git push` ni crea repositorios remotos.

## 5. Crear la aplicacion en Streamlit Community Cloud

1. Entra a `https://share.streamlit.io/` e inicia sesion con GitHub.
2. Selecciona **Create app**.
3. Elige repositorio y rama.
4. Usa `app.py` como archivo principal.
5. Abre **Advanced settings**.
6. Selecciona Python 3.12.
7. Pega el TOML del paso 2 en **Secrets**.
8. Guarda e inicia el despliegue.

## 6. Validacion posterior

Comprueba en este orden:

1. La barra lateral muestra `Datos estructurados: OCI`.
2. Resumen y Operaciones contienen viajes y mantenciones.
3. Finanzas contiene facturas y gastos.
4. Gestion del asistente muestra los cinco PDF.
5. Una pregunta sobre mantenimiento preventivo devuelve contexto documental.
6. Los logs no muestran `config`, `key_file`, `NotAuthenticated` ni `NotAuthorized`.

`.runtime/` es efimero en Community Cloud. El indice RAG puede reconstruirse, pero el
catalogo, feedback y monitoreo local pueden reiniciarse cuando el contenedor se recrea.
