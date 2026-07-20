from pathlib import Path

import pandas as pd


class LectorPDF:
    def __init__(self, largo_fragmento=1200, solapamiento=180):
        self.largo_fragmento = largo_fragmento
        self.solapamiento = solapamiento

    def cargar_archivos(self, archivos):
        """Carga rutas materializadas conservando nombre y fecha del objeto remoto."""
        registros = []
        for ruta, nombre, fecha_modificacion in archivos:
            archivo = Path(ruta)
            if not archivo.is_file():
                raise FileNotFoundError(f"No se encontro el PDF materializado: {archivo}")
            if archivo.stat().st_size <= 0:
                raise ValueError(f"El PDF materializado esta vacio: {nombre}")
            registros.extend(self._leer_archivo(archivo, nombre, fecha_modificacion))
        return pd.DataFrame(registros) if registros else self._dataframe_vacio()

    def _leer_archivo(self, archivo, nombre=None, fecha_modificacion=None):
        texto_paginas = self._extraer_texto(archivo)
        registros = []
        nombre_documento = Path(nombre or archivo.name)
        fecha = (
            pd.to_datetime(fecha_modificacion)
            if fecha_modificacion
            else pd.to_datetime(archivo.stat().st_mtime, unit="s")
        )

        for numero_pagina, texto in texto_paginas:
            texto = self._limpiar_texto(texto)
            if not texto:
                continue

            for indice, fragmento in enumerate(self._fragmentar_texto(texto), start=1):
                registros.append(
                    {
                        "Tipo Documento": "PDF",
                        "Referencia Tabla": nombre_documento.stem,
                        "Referencia ID": f"{nombre_documento.stem}-p{numero_pagina}-f{indice}",
                        "Contenido": fragmento,
                        "Archivo": nombre_documento.name,
                        "Ruta Local": str(archivo),
                        "Pagina": numero_pagina,
                        "Fecha Modificacion": fecha,
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

        paginas = []
        with archivo.open("rb") as stream:
            lector = PdfReader(stream)
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
                "Ruta Local",
                "Pagina",
                "Fecha Modificacion",
            ]
        )
