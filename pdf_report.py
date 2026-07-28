"""
Construcción del PDF final.

Adapta los objetos del dominio de la aplicación al diccionario que espera
`informe_espirometria.InformeEspirometria` y concatena el resultado con la
primera página del reporte original del espirómetro.

La firma pública `build_pdf(...)` se mantiene idéntica a la versión anterior,
de modo que `app.py` y cualquier integración existente siguen funcionando.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pymupdf

from informe_espirometria import InformeEspirometria
from models import (
    LungVolumes,
    PatientData,
    QualityData,
    QualitySeries,
    SpirometryValue,
)

#: Datos institucionales por defecto. Pueden sobrescribirse desde la interfaz.
INSTITUCION_DEFECTO = "SALUD ES VIVIR IPS"
LABORATORIO_DEFECTO = "Laboratorio de Función Pulmonar"
CIUDAD_DEFECTO = "Medellín, Colombia"

#: Parámetros que se envían al generador. Los flujos distales se incluyen
#: cuando existen, pero el motor los marca como descriptivos.
PARAMETROS_INFORME = ("FEV1/FVC", "FVC", "FEV1", "FEF25-75", "PEF",
                      "FEF50", "FEF75", "FIF50")


def _sexo_a_codigo(sexo: str) -> str:
    s = (sexo or "").strip().lower()
    if s.startswith("f") or s.startswith("m") and "mujer" in s:
        return "F"
    if s.startswith("mujer"):
        return "F"
    if s.startswith("m") or s.startswith("h"):
        return "M"
    return sexo or ""


def _serie_a_dict(serie: QualitySeries, texto: str) -> Optional[Dict]:
    """
    Convierte una QualitySeries en el bloque de calidad del generador.

    Si no hay datos estructurados pero el equipo reportó grados A-F, se
    reconstruye un número de maniobras y una diferencia coherentes con el
    grado informado, de modo que el informe pueda mostrarlo sin inventar cifras.
    """
    if serie is None:
        serie = QualitySeries()

    bloque: Dict[str, object] = {}
    if serie.acceptable_manoeuvres is not None:
        bloque["n_aceptables"] = serie.acceptable_manoeuvres
    if serie.usable_manoeuvres is not None:
        bloque["n_utilizables"] = serie.usable_manoeuvres
    if serie.fvc_difference_l is not None:
        bloque["dif_fvc_L"] = serie.fvc_difference_l
    if serie.fev1_difference_l is not None:
        bloque["dif_fev1_L"] = serie.fev1_difference_l
    if serie.bev_ok is not None:
        bloque["bev_ok"] = serie.bev_ok
    if serie.plateau_ok is not None:
        bloque["meseta_ok"] = serie.plateau_ok
    if serie.fet_seconds is not None:
        bloque["fet_s"] = serie.fet_seconds

    if not bloque and not texto:
        return None

    # Grado reportado por el equipo sin datos de repetibilidad: se traslada
    # tal cual como observación, sin fabricar cifras de diferencia.
    grados = [g for g in (serie.grade_fvc, serie.grade_fev1) if g]
    if grados and "n_aceptables" not in bloque:
        bloque["grado_reportado"] = "/".join(grados)
    return bloque or None


def _construir_datos(patient: PatientData,
                     quality: QualityData,
                     values: Dict[str, SpirometryValue],
                     volumes: Optional[LungVolumes],
                     conclusion: str,
                     technician: str,
                     equipment_conclusion: str,
                     report_number: str,
                     bronchodilator: Optional[Dict]) -> Dict:
    """Traduce el dominio de la app al esquema de `InformeEspirometria`."""
    parametros: Dict[str, Dict] = {}
    for clave in PARAMETROS_INFORME:
        v = values.get(clave)
        if not v:
            continue
        if v.baseline is None and v.post is None:
            continue
        parametros[clave] = {
            "pred": v.predicted,
            "lln": v.lln,
            "pre": v.baseline,
            "post": v.post,
            "z_pre": v.z_score,
            "z_post": v.post_z_score,
            "unidad": v.unit or ("%" if clave == "FEV1/FVC" else ""),
        }

    calidad: Dict[str, object] = {}
    bloque_pre = _serie_a_dict(quality.baseline_series, quality.baseline)
    bloque_post = _serie_a_dict(quality.post_series, quality.post)
    if bloque_pre:
        calidad["pre"] = bloque_pre
    if bloque_post:
        calidad["post"] = bloque_post
    calidad["pef_definido"] = bool(
        getattr(quality.baseline_series, "sharp_pef", True))

    datos: Dict[str, object] = {
        "paciente": {
            "nombre": patient.name or "",
            "documento": patient.document_id or "",
            "sexo": _sexo_a_codigo(patient.sex),
            "edad_anios": patient.age_years,
            "talla_cm": patient.height_cm,
            "peso_kg": patient.weight_kg,
            "etnia": patient.ethnicity,
            "tabaquismo": patient.smoking or "",
            "fecha_estudio": patient.exam_date,
            "posicion": patient.position or "sedente",
        },
        "referencia": {
            "ecuacion": patient.reference_equation or "GLI-2012",
            "grupo_etnico": patient.ethnicity,
        },
        "parametros": parametros,
        "calidad": calidad,
        "observaciones_tecnico": technician or None,
        "conclusion_equipo": equipment_conclusion or None,
        "n_reporte": report_number or None,
        "conclusion_revisada": conclusion or None,
    }

    if bronchodilator:
        datos["broncodilatador"] = bronchodilator

    if volumes is not None and volumes.available:
        bloque_vol: Dict[str, Dict] = {
            "TLC": {"pred": volumes.tlc_predicted, "lln": volumes.tlc_lln,
                    "valor": volumes.tlc, "z": volumes.tlc_z_score},
        }
        if volumes.rv is not None:
            bloque_vol["RV"] = {"pred": volumes.rv_predicted,
                                "lln": volumes.rv_lln, "valor": volumes.rv}
        datos["volumenes"] = bloque_vol

    return datos


def _merge_with_first_original_page(complementary_pdf: bytes,
                                    original_pdf_bytes: Optional[bytes]) -> bytes:
    """
    Concatena el informe generado con la primera página del reporte original.

    Si el PDF original no puede abrirse o no tiene páginas, devuelve solo el
    informe: la descarga nunca debe fallar por un problema del archivo de
    entrada.
    """
    output_document = pymupdf.open()
    complementary_document = None
    original_document = None
    try:
        complementary_document = pymupdf.open(stream=complementary_pdf,
                                              filetype="pdf")
        output_document.insert_pdf(complementary_document)

        if original_pdf_bytes:
            try:
                original_document = pymupdf.open(stream=original_pdf_bytes,
                                                 filetype="pdf")
                if original_document.page_count > 0:
                    output_document.insert_pdf(original_document,
                                               from_page=0, to_page=0)
            except Exception:
                pass

        return output_document.tobytes(garbage=4, deflate=True)
    finally:
        if complementary_document is not None:
            complementary_document.close()
        if original_document is not None:
            original_document.close()
        output_document.close()


def build_pdf(patient: PatientData,
              quality: QualityData,
              values: Dict[str, SpirometryValue],
              conclusion: str,
              physician: str,
              technician: str,
              original_pdf_bytes: Optional[bytes] = None,
              volumes: Optional[LungVolumes] = None,
              institution: str = INSTITUCION_DEFECTO,
              laboratory: str = LABORATORIO_DEFECTO,
              city: str = CIUDAD_DEFECTO,
              lab_registration: str = "",
              equipment_conclusion: str = "",
              report_number: str = "",
              bronchodilator: Optional[Dict] = None) -> bytes:
    """
    Genera el PDF final.

    Páginas 1-3: informe conforme a ERS/ATS 2022, con datos del paciente,
    calidad técnica A-F, valores con z-score, prueba broncodilatadora,
    interpretación, conclusión y tabla de parámetros normativos aplicados.

    Última página: primera página del reporte original del espirómetro.
    """
    nombre, _, credenciales = (physician or "").partition(",")
    generador = InformeEspirometria(
        institucion=institution,
        laboratorio=laboratory,
        ciudad=city,
        registro_lab=lab_registration,
        firmante=nombre.strip() or (physician or "").strip(),
        credenciales=credenciales.strip(),
    )

    datos = _construir_datos(
        patient=patient, quality=quality, values=values, volumes=volumes,
        conclusion=conclusion, technician=technician,
        equipment_conclusion=equipment_conclusion,
        report_number=report_number, bronchodilator=bronchodilator,
    )

    informe = generador.generar(datos)
    return _merge_with_first_original_page(informe, original_pdf_bytes)
