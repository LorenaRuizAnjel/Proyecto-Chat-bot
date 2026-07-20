from datetime import datetime
from pathlib import Path
import sqlite3
import unicodedata

import pandas as pd


ESTADOS_MEJORA = ["Pendiente", "En revision", "Resuelta", "Descartada"]


class MonitoreoCalidad:
    """Persistencia local de consultas y senales de calidad del agente."""

    def __init__(self, ruta=".runtime/operacion_agente.db"):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    def _conexion(self):
        return sqlite3.connect(self.ruta)

    def _inicializar(self):
        with self._conexion() as conexion:
            conexion.execute(
                """
                CREATE TABLE IF NOT EXISTS consultas_calidad (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL,
                    pregunta TEXT NOT NULL,
                    sin_respuesta INTEGER NOT NULL DEFAULT 0,
                    tiempo_respuesta_ms REAL NOT NULL,
                    tiene_fuentes INTEGER NOT NULL DEFAULT 0,
                    feedback TEXT,
                    modelo TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conexion.execute(
                """
                CREATE TABLE IF NOT EXISTS acciones_mejora (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo TEXT NOT NULL,
                    pregunta TEXT NOT NULL,
                    ocurrencias INTEGER NOT NULL DEFAULT 0,
                    recomendacion TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'Pendiente',
                    responsable TEXT NOT NULL DEFAULT '',
                    ultima_detectada TEXT NOT NULL,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tipo, pregunta)
                )
                """
            )

    def registrar_consulta(self, pregunta, respuesta, tiempo_respuesta_ms, modelo=""):
        sin_respuesta = int(self._es_respuesta_insuficiente(respuesta))
        tiene_fuentes = int("fuentes documentales recuperadas" in str(respuesta).lower())
        with self._conexion() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO consultas_calidad
                    (fecha, pregunta, sin_respuesta, tiempo_respuesta_ms, tiene_fuentes, modelo)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    str(pregunta).strip(),
                    sin_respuesta,
                    float(tiempo_respuesta_ms),
                    tiene_fuentes,
                    str(modelo),
                ),
            )
            return int(cursor.lastrowid)

    def registrar_feedback(self, consulta_id, feedback):
        if feedback not in {"positivo", "negativo"}:
            raise ValueError("El feedback debe ser positivo o negativo.")

        with self._conexion() as conexion:
            conexion.execute(
                "UPDATE consultas_calidad SET feedback = ? WHERE id = ?",
                (feedback, int(consulta_id)),
            )

    def resumen(self):
        with self._conexion() as conexion:
            fila = conexion.execute(
                """
                SELECT
                    COUNT(*) AS total_consultas,
                    COALESCE(SUM(sin_respuesta), 0) AS sin_respuesta,
                    COALESCE(AVG(tiempo_respuesta_ms), 0) AS tiempo_promedio_ms,
                    COALESCE(SUM(CASE WHEN feedback IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluadas,
                    COALESCE(SUM(CASE WHEN feedback = 'negativo' THEN 1 ELSE 0 END), 0) AS negativas
                FROM consultas_calidad
                """
            ).fetchone()

        total, sin_respuesta, tiempo_promedio, evaluadas, negativas = fila
        return {
            "total_consultas": int(total),
            "tasa_sin_respuesta": (int(sin_respuesta) / total) if total else 0.0,
            "tiempo_promedio_ms": float(tiempo_promedio),
            "evaluadas": int(evaluadas),
            "tasa_feedback_negativo": (int(negativas) / evaluadas) if evaluadas else 0.0,
        }

    def preguntas_sin_respuesta(self, limite=10):
        with self._conexion() as conexion:
            return pd.read_sql_query(
                """
                SELECT pregunta, COUNT(*) AS consultas, MAX(fecha) AS ultima_consulta
                FROM consultas_calidad
                WHERE sin_respuesta = 1
                GROUP BY pregunta
                ORDER BY consultas DESC, ultima_consulta DESC
                LIMIT ?
                """,
                conexion,
                params=(int(limite),),
            )

    def feedback_negativo(self, limite=10):
        with self._conexion() as conexion:
            return pd.read_sql_query(
                """
                SELECT fecha, pregunta, tiempo_respuesta_ms, tiene_fuentes
                FROM consultas_calidad
                WHERE feedback = 'negativo'
                ORDER BY fecha DESC
                LIMIT ?
                """,
                conexion,
                params=(int(limite),),
            )

    def sincronizar_acciones_mejora(self):
        """Convierte senales de calidad en acciones curatoriales o tecnicas."""
        oportunidades = []
        preguntas_sin_respuesta = self.preguntas_sin_respuesta(limite=1000)
        for _, fila in preguntas_sin_respuesta.iterrows():
            oportunidades.append(
                (
                    "Cobertura documental",
                    fila["pregunta"],
                    int(fila["consultas"]),
                    "Agregar o actualizar un documento oficial que cubra esta pregunta.",
                    fila["ultima_consulta"],
                )
            )

        with self._conexion() as conexion:
            feedback_agrupado = pd.read_sql_query(
                """
                SELECT pregunta, COUNT(*) AS consultas, MAX(fecha) AS ultima_consulta
                FROM consultas_calidad
                WHERE feedback = 'negativo'
                GROUP BY pregunta
                """,
                conexion,
            )

            for _, fila in feedback_agrupado.iterrows():
                oportunidades.append(
                    (
                        "Calidad de respuesta",
                        fila["pregunta"],
                        int(fila["consultas"]),
                        "Revisar los fragmentos recuperados, las fuentes citadas y las instrucciones del agente.",
                        fila["ultima_consulta"],
                    )
                )

            for tipo, pregunta, ocurrencias, recomendacion, ultima_detectada in oportunidades:
                conexion.execute(
                    """
                    INSERT INTO acciones_mejora
                        (tipo, pregunta, ocurrencias, recomendacion, ultima_detectada)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(tipo, pregunta) DO UPDATE SET
                        ocurrencias = excluded.ocurrencias,
                        recomendacion = excluded.recomendacion,
                        ultima_detectada = excluded.ultima_detectada,
                        actualizado_en = CURRENT_TIMESTAMP
                    """,
                    (tipo, str(pregunta), ocurrencias, recomendacion, str(ultima_detectada)),
                )

    def acciones_mejora(self):
        self.sincronizar_acciones_mejora()
        with self._conexion() as conexion:
            return pd.read_sql_query(
                """
                SELECT id, tipo, pregunta, ocurrencias, recomendacion, estado, responsable, ultima_detectada
                FROM acciones_mejora
                ORDER BY
                    CASE estado WHEN 'Pendiente' THEN 0 WHEN 'En revision' THEN 1 ELSE 2 END,
                    ocurrencias DESC,
                    ultima_detectada DESC
                """,
                conexion,
            )

    def guardar_acciones_mejora(self, acciones):
        with self._conexion() as conexion:
            for _, fila in acciones.iterrows():
                conexion.execute(
                    """
                    UPDATE acciones_mejora
                    SET estado = ?, responsable = ?, actualizado_en = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        str(fila.get("estado", "Pendiente")),
                        "" if pd.isna(fila.get("responsable")) else str(fila.get("responsable")).strip(),
                        int(fila["id"]),
                    ),
                )

    @staticmethod
    def _es_respuesta_insuficiente(respuesta):
        texto = unicodedata.normalize("NFKD", str(respuesta).lower())
        texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
        indicadores = (
            "no encontre esta informacion",
            "no encontre informacion relevante",
            "no puedo entregar una respuesta",
            "no hay datos disponibles",
        )
        return any(indicador in texto for indicador in indicadores)
