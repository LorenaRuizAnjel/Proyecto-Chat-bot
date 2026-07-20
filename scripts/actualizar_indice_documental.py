"""Reconstruye el indice documental fuera de Streamlit.

Ejecuta este archivo desde la raiz del proyecto, por ejemplo con el Programador de
tareas de Windows: python scripts/actualizar_indice_documental.py
"""

from pathlib import Path
import sys


RAIZ_PROYECTO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_PROYECTO))

from modules.lector_pdf import LectorPDF  # noqa: E402
from modules.rag import SemanticRAG  # noqa: E402
from services import create_storage, load_storage_settings, materialize_files  # noqa: E402


def main():
    settings = load_storage_settings(RAIZ_PROYECTO)
    storage = create_storage(settings)
    try:
        archivos, _version = materialize_files(storage, settings.oci_rag_prefix, ".pdf")
        documentos = LectorPDF().cargar_archivos(archivos)
        rag = SemanticRAG(
            None,
            None,
            documentos,
            ruta_indice=RAIZ_PROYECTO / ".runtime" / "indice_documental",
        )
        estado = "reutilizado" if rag.indice_desde_disco else "actualizado"
        print(f"Indice documental {estado}: {len(rag.docs_df)} fragmentos.")
    finally:
        storage.close()


if __name__ == "__main__":
    main()
