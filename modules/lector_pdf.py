from pathlib import Path

import pandas as pd


class LectorPDF:
    def __init__(self, ruta_carpeta="data", patron="*.pdf", largo_fragmento=1200, solapamiento=180):
        self.ruta_carpeta = Path(ruta_carpeta)
        self.patron = patron
        self.largo_fragmento = largo_fragmento
        self.solapamiento = solapamiento

    def cargar_datos(self):
        if not self.ruta_carpeta.exists():
            raise FileNotFoundError(f"No se encontro la carpeta: {self.ruta_carpeta}")

        archivos = sorted(self.ruta_carpeta.glob(self.patron))
        if not archivos:
            return self._dataframe_vacio()

        registros = []
        for archivo in archivos:
            registros.extend(self._leer_archivo(archivo))

        if not registros:
            return self._dataframe_vacio()

        return pd.DataFrame(registros)

    def _leer_archivo(self, archivo):
        texto_paginas = self._extraer_texto(archivo)
        registros = []

        for numero_pagina, texto in texto_paginas:
            texto = self._limpiar_texto(texto)
            if not texto:
                continue

            for indice, fragmento in enumerate(self._fragmentar_texto(texto), start=1):
                registros.append(
                    {
                        "Tipo Documento": "PDF",
                        "Referencia Tabla": archivo.stem,
                        "Referencia ID": f"{archivo.stem}-p{numero_pagina}-f{indice}",
                        "Contenido": fragmento,
                        "Archivo": archivo.name,
                        "Pagina": numero_pagina,
                        "Fecha Modificacion": pd.to_datetime(archivo.stat().st_mtime, unit="s"),
                    }
                )

        return registros

    def _extraer_texto(self, archivo):
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ImportError(
                "Para leer archivos PDF instala la dependencia 'pypdf' con: pip install pypdf"
            ) from error

        lector = PdfReader(str(archivo))
        paginas = []

        for indice, pagina in enumerate(lector.pages, start=1):
            texto = pagina.extract_text() or ""
            paginas.append((indice, texto))

        return paginas

    def _limpiar_texto(self, texto):
        lineas = [linea.strip() for linea in str(texto).splitlines()]
        return " ".join(linea for linea in lineas if linea)

    def _fragmentar_texto(self, texto):
        if len(texto) <= self.largo_fragmento:
            return [texto]

        fragmentos = []
        inicio = 0

        while inicio < len(texto):
            fin = min(inicio + self.largo_fragmento, len(texto))
            fragmento = texto[inicio:fin].strip()

            if fragmento:
                fragmentos.append(fragmento)

            if fin == len(texto):
                break

            inicio = max(fin - self.solapamiento, inicio + 1)

        return fragmentos

    def _dataframe_vacio(self):
        return pd.DataFrame(
            columns=[
                "Tipo Documento",
                "Referencia Tabla",
                "Referencia ID",
                "Contenido",
                "Archivo",
                "Pagina",
                "Fecha Modificacion",
            ]
        )


if __name__ == "__main__":
    documentos = LectorPDF("data").cargar_datos()
    print(documentos.head())
