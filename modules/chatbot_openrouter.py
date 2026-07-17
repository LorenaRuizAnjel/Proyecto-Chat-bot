import os
import json
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
)
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


MODELO_OPENROUTER = "google/gemini-2.5-flash"
TIMEOUT_OPENROUTER_SEGUNDOS = 30

load_dotenv()


@dataclass
class ErrorModeloExterno(Exception):
    mensaje_usuario: str
    detalle: str

    def __str__(self):
        return self.mensaje_usuario


def obtener_api_key():
    api_key = os.getenv("OPENROUTER_API_KEY")

    if api_key:
        return api_key.strip()

    try:
        api_key = st.secrets.get("OPENROUTER_API_KEY")
    except StreamlitSecretNotFoundError:
        return None

    return api_key.strip() if api_key else None


class ChatbotOpenRouter:
    def __init__(self, modelo=MODELO_OPENROUTER):
        api_key = obtener_api_key()

        if not api_key:
            raise ErrorModeloExterno(
                "Falta configurar OPENROUTER_API_KEY.",
                "OPENROUTER_API_KEY no esta definida en .env ni en secrets de Streamlit.",
            )

        self.modelo = modelo
        self.cliente = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=TIMEOUT_OPENROUTER_SEGUNDOS,
        )

    def preguntar(self, pregunta, contexto, historial=None):
        mensajes = [
            {
                "role": "system",
                "content": (
                    "Eres un asistente gerencial para operaciones logisticas. "
                    "Responde en espanol, de forma breve y ejecutiva. "
                    "El contexto puede incluir viajes de materiales/redes, viajes de cosecha, "
                    "mantenciones y documentos RAG. "
                    "Tarifa Flete es el ingreso neto cobrado al cliente por realizar el movimiento; "
                    "no lo trates como costo. Los costos de mantencion si son egresos. "
                    "Usa solo los datos entregados como contexto. "
                    "El historial sirve solo para comprender referencias de la conversacion; "
                    "no lo uses como fuente de hechos. "
                    "Si la respuesta no se puede inferir desde el contexto, dilo claramente. "
                    "Cuando el contexto provenga de documentos, cita junto a cada afirmacion "
                    "el nombre del archivo y la pagina con el formato [archivo.pdf, pagina N]. "
                    "No inventes fuentes ni cites documentos que no aparezcan en el contexto. "
                    "Entrega primero una respuesta directa y luego una seccion breve llamada Fuentes."
                ),
            }
        ]

        for intercambio in (historial or [])[-4:]:
            pregunta_anterior = str(intercambio.get("pregunta", "")).strip()
            respuesta_anterior = str(intercambio.get("respuesta", "")).strip()
            if pregunta_anterior:
                mensajes.append({"role": "user", "content": pregunta_anterior[:1200]})
            if respuesta_anterior:
                mensajes.append({"role": "assistant", "content": respuesta_anterior[:1800]})

        mensajes.append(
            {
                "role": "user",
                "content": f"Contexto:\n{contexto}\n\nPregunta:\n{pregunta}",
            }
        )

        try:
            respuesta = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=mensajes,
                max_tokens=300,
                temperature=0.2,
            )
        except AuthenticationError as error:
            raise ErrorModeloExterno(
                "La API key de OpenRouter no es valida o no fue aceptada.",
                f"Error 401 de OpenRouter: {error}",
            ) from error
        except PermissionDeniedError as error:
            raise ErrorModeloExterno(
                "OpenRouter rechazo la solicitud por permisos insuficientes.",
                f"Error 403 de OpenRouter: {error}",
            ) from error
        except NotFoundError as error:
            raise ErrorModeloExterno(
                f"El modelo configurado no fue encontrado: {self.modelo}.",
                f"Error 404 de OpenRouter: {error}",
            ) from error
        except APITimeoutError as error:
            raise ErrorModeloExterno(
                "La conexion con OpenRouter excedio el tiempo de espera.",
                f"Timeout de OpenRouter tras {TIMEOUT_OPENROUTER_SEGUNDOS} segundos: {error}",
            ) from error
        except APIConnectionError as error:
            raise ErrorModeloExterno(
                "No fue posible conectar con OpenRouter por un error de red.",
                f"Error de red al conectar con OpenRouter: {error}",
            ) from error
        except APIStatusError as error:
            raise ErrorModeloExterno(
                f"OpenRouter respondio con un error HTTP {error.status_code}.",
                f"Error HTTP {error.status_code} de OpenRouter: {error}",
            ) from error

        return respuesta.choices[0].message.content

    def verificar_respaldo_documental(self, respuesta, contexto):
        """Aprueba solo respuestas cuyas afirmaciones estan respaldadas por el contexto."""
        try:
            veredicto = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un verificador estricto de respuestas basadas en documentos. "
                            "Revisa si TODAS las afirmaciones factuales de la respuesta se pueden inferir "
                            "directamente del contexto. No uses conocimiento externo. "
                            "Responde solo APROBADA o RECHAZADA. "
                            "Rechaza si la respuesta agrega datos, fechas, reglas o conclusiones no respaldadas."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Contexto:\n{contexto}\n\nRespuesta a verificar:\n{respuesta}",
                    },
                ],
                max_tokens=10,
                temperature=0,
            )
        except Exception as error:
            raise ErrorModeloExterno(
                "No fue posible verificar que la respuesta este respaldada por los documentos.",
                f"Error al verificar el respaldo documental: {error}",
            ) from error

        contenido = (veredicto.choices[0].message.content or "").strip().upper()
        return bool(re.fullmatch(r"APROBADA[.!]?", contenido))

    def clasificar_intencion(self, pregunta):
        try:
            respuesta = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Clasifica consultas de un chatbot gerencial logistico. "
                            "Devuelve SOLO un JSON valido, sin markdown ni explicaciones, con esta estructura: "
                            '{"tipo":"analitica|documental","accion":"ranking|total|promedio|consulta",'
                            '"metrica":"ingreso_neto|costo_mantencion|facturas|gastos|otro",'
                            '"entidad":"conductor|patente_tracto|patente_rampla|vehiculo|centro|ruta|cliente|documento|otro"}. '
                            "Reglas: chofer, conductor u operador => conductor. "
                            "camion, vehiculo, equipo o patente => vehiculo. "
                            "tracto => patente_tracto. rampla => patente_rampla. "
                            "ingreso, ingresos, facturacion o flete => ingreso_neto. "
                            "mantencion, mantenimiento o reparacion => costo_mantencion. "
                            "manual, politica, procedimiento, plan, que dice o como se debe => documental/documento. "
                            "No calcules nada."
                        ),
                    },
                    {
                        "role": "user",
                        "content": pregunta,
                    },
                ],
                max_tokens=160,
                temperature=0,
            )
        except AuthenticationError as error:
            raise ErrorModeloExterno(
                "La API key de OpenRouter no es valida o no fue aceptada.",
                f"Error 401 de OpenRouter: {error}",
            ) from error
        except PermissionDeniedError as error:
            raise ErrorModeloExterno(
                "OpenRouter rechazo la solicitud por permisos insuficientes.",
                f"Error 403 de OpenRouter: {error}",
            ) from error
        except NotFoundError as error:
            raise ErrorModeloExterno(
                f"El modelo configurado no fue encontrado: {self.modelo}.",
                f"Error 404 de OpenRouter: {error}",
            ) from error
        except APITimeoutError as error:
            raise ErrorModeloExterno(
                "La conexion con OpenRouter excedio el tiempo de espera.",
                f"Timeout de OpenRouter tras {TIMEOUT_OPENROUTER_SEGUNDOS} segundos: {error}",
            ) from error
        except APIConnectionError as error:
            raise ErrorModeloExterno(
                "No fue posible conectar con OpenRouter por un error de red.",
                f"Error de red al conectar con OpenRouter: {error}",
            ) from error
        except APIStatusError as error:
            raise ErrorModeloExterno(
                f"OpenRouter respondio con un error HTTP {error.status_code}.",
                f"Error HTTP {error.status_code} de OpenRouter: {error}",
            ) from error

        contenido = respuesta.choices[0].message.content or ""
        return self._parsear_json_intencion(contenido)

    def _parsear_json_intencion(self, contenido):
        texto = contenido.strip()
        texto = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.IGNORECASE)
        texto = re.sub(r"\s*```$", "", texto)

        if not texto.startswith("{"):
            coincidencia = re.search(r"\{.*\}", texto, flags=re.DOTALL)
            if coincidencia:
                texto = coincidencia.group(0)

        intencion = json.loads(texto)
        campos_requeridos = ["tipo", "accion", "metrica", "entidad"]
        faltantes = [campo for campo in campos_requeridos if campo not in intencion]

        if faltantes:
            raise ValueError(f"JSON de intencion incompleto. Faltan campos: {', '.join(faltantes)}")

        return {campo: str(intencion[campo]).strip().lower() for campo in campos_requeridos}
