import os

from openai import OpenAI
import streamlit as st


def obtener_api_key():
    api_key = os.getenv("OPENROUTER_API_KEY")

    if api_key:
        return api_key

    return st.secrets.get("OPENROUTER_API_KEY")


class ChatbotOpenRouter:
    def __init__(self, modelo="openai/gpt-4.1-mini"):
        api_key = obtener_api_key()

        if not api_key:
            raise ValueError(
                "Falta configurar OPENROUTER_API_KEY en .env o en los secrets de Streamlit Cloud"
            )

        self.modelo = modelo
        self.cliente = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    def preguntar(self, pregunta, contexto):
        respuesta = self.cliente.chat.completions.create(
            model=self.modelo,
            messages=[
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
                        "Si la respuesta no se puede inferir desde el contexto, dilo claramente."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Contexto:\n{contexto}\n\nPregunta:\n{pregunta}",
                },
            ],
            max_tokens=500,
            temperature=0.2,
        )

        return respuesta.choices[0].message.content
