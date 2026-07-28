"""
Motor de interpretación espirométrica.

Aplica los criterios del estándar técnico ERS/ATS 2022 (Stanojevic S, et al.
Eur Respir J 2022;60:2101499) con las precisiones operativas de la normativa
SEPAR/ALAT 2026 (Arch Bronconeumol, doi:10.1016/j.arbres.2025.12.016).

Toda la lógica normativa vive en `informe_espirometria.EstandaresERS2022`.
Este módulo se limita a adaptar los objetos del dominio de la aplicación
(`SpirometryValue`, `PatientData`, `QualityData`, `LungVolumes`) a ese motor,
de modo que exista una única fuente de verdad para los umbrales.

Cambios respecto a la versión anterior
--------------------------------------
* La severidad se gradúa con el z-score del FEV1 en tres niveles
  (leve / moderada / grave) y no con el porcentaje del predicho en seis.
* La clasificación distingue patrón mixto, inespecífico/PRISm y disanapsis,
  que antes se colapsaban en «obstructivo» o «restrictivo».
* El patrón se determina sobre los valores posbroncodilatador cuando existen.
* Se exige TLC para afirmar restricción; sin ella el informe dice
  «posible restricción / PRISm».
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from informe_espirometria import (
    UMBRAL_BDR_2005_ML,
    UMBRAL_BDR_2005_PCT_BASAL,
    UMBRAL_BDR_2022_PCT_PREDICHO,
    UMBRAL_BDR_PEDIATRICO_PCT_PREDICHO,
    Z_LIN,
    EstandaresERS2022,
    ResultadoPatron,
)
from models import LungVolumes, PatientData, QualityData, SpirometryValue

#: Criterio pediátrico aplicado de forma consistente en toda la aplicación.
#: SEPAR/ALAT 2026 admite 12 % sobre el basal ó 9-10 % sobre el predicho y
#: exige elegir uno y no alternarlos.
CRITERIO_BDR_PEDIATRICO = "predicho"


# ---------------------------------------------------------------------------
# Utilidades sobre SpirometryValue
# ---------------------------------------------------------------------------

def effective_z(value: Optional[SpirometryValue], post: bool = False) -> Optional[float]:
    """
    z-score utilizable de un parámetro.

    Prioriza el z suministrado por el equipo o por el motor de referencia;
    si falta, lo estima a partir del predicho y el LIN.
    """
    if value is None:
        return None
    directo = value.post_z_score if post else value.z_score
    if directo is not None:
        return directo
    observado = value.post if post else value.baseline
    return EstandaresERS2022.z_desde_lln(observado, value.predicted, value.lln)


def is_low(value: Optional[SpirometryValue], post: bool = False) -> bool:
    """Verdadero si el parámetro está por debajo del límite inferior de normalidad."""
    if value is None:
        return False
    z = effective_z(value, post=post)
    if z is not None:
        return z < Z_LIN
    observado = value.post if post else value.baseline
    if observado is not None and value.lln is not None:
        return observado < value.lln
    return False


def _is_low(value, lln, z_score) -> bool:  # pragma: no cover - compatibilidad
    """Firma antigua conservada para no romper importaciones externas."""
    if z_score is not None:
        return z_score < Z_LIN
    if value is not None and lln is not None:
        return value < lln
    return False


def has_post_values(values: Dict[str, SpirometryValue]) -> bool:
    return any(v.post is not None for v in values.values() if v)


# ---------------------------------------------------------------------------
# Severidad
# ---------------------------------------------------------------------------

def severity_from_fev1_zscore(z_score: Optional[float]) -> str:
    """
    Sistema de tres niveles del ERS/ATS 2022 sobre el z-score del FEV1:

        -1,645 >= z > -2,5   leve
        -2,5   >= z > -4,0   moderada
                 z <= -4,0   grave

    No debe aplicarse ante sospecha de obstrucción de vía aérea central o
    superior, donde una obstrucción crítica puede quedar clasificada como leve.
    """
    etiqueta = EstandaresERS2022.clasificar_severidad(z_score)
    if etiqueta is None:
        return "no clasificable"
    if etiqueta.startswith("Sin alteración"):
        return "sin reducción"
    return etiqueta.lower()


def severity_from_fev1_percent(percent: Optional[float]) -> str:
    """
    Gradación histórica ATS/ERS 2005 por porcentaje del predicho.

    OBSOLETA. Se conserva únicamente para poder mostrar la comparación con
    informes previos. No debe usarse para emitir conclusiones: el porcentaje
    del predicho no corrige la variabilidad por edad, sexo y talla.
    """
    if percent is None:
        return "no clasificable"
    if percent >= 80:
        return "sin reducción"
    if percent >= 70:
        return "leve"
    if percent >= 60:
        return "moderado"
    if percent >= 50:
        return "moderadamente grave"
    if percent >= 35:
        return "grave"
    return "muy grave"


# ---------------------------------------------------------------------------
# Patrón ventilatorio
# ---------------------------------------------------------------------------

def classify_pattern(values: Dict[str, SpirometryValue],
                     volumes: Optional[LungVolumes] = None,
                     quality: Optional[QualityData] = None,
                     force_baseline: bool = False) -> ResultadoPatron:
    """
    Clasifica el patrón ventilatorio con el algoritmo del ERS/ATS 2022.

    Parte del cociente FEV1/FVC frente a su LIN, después evalúa la FVC y,
    cuando existe, usa la TLC para separar restricción de patrón inespecífico.
    Emplea los valores posbroncodilatador si están disponibles.
    """
    ratio = values.get("FEV1/FVC")
    fvc = values.get("FVC")
    fev1 = values.get("FEV1")

    usar_post = (not force_baseline
                 and has_post_values(values)
                 and ratio is not None
                 and ratio.post is not None)

    z_tlc = None
    if volumes is not None and volumes.available:
        z_tlc = volumes.tlc_z_score
        if z_tlc is None:
            z_tlc = EstandaresERS2022.z_desde_lln(
                volumes.tlc, volumes.tlc_predicted, volumes.tlc_lln)

    pef_definido = True
    if quality is not None:
        serie = quality.post_series if usar_post else quality.baseline_series
        pef_definido = bool(getattr(serie, "sharp_pef", True))

    return EstandaresERS2022.clasificar_patron(
        z_fev1=effective_z(fev1, post=usar_post),
        z_fvc=effective_z(fvc, post=usar_post),
        z_ratio=effective_z(ratio, post=usar_post),
        z_tlc=z_tlc,
        pef_definido=pef_definido,
        base="post-BD" if usar_post else "pre-BD",
    )


def parameter_interpretation(key: str, value: SpirometryValue) -> str:
    """Lectura individual de un parámetro, para la tabla de resultados."""
    if value is None:
        return ""
    post = value.post is not None
    low = is_low(value, post=post)
    z = effective_z(value, post=post)
    sufijo = f" (z {z:+.2f})".replace(".", ",") if z is not None else ""

    if key == "FEV1/FVC":
        base = ("Por debajo del LIN; define obstrucción" if low
                else "Por encima del LIN; no demuestra obstrucción")
        return base + sufijo

    if key == "FVC":
        base = ("Por debajo del LIN; requiere TLC para diferenciar restricción "
                "de atrapamiento aéreo" if low else "Dentro de límites normales")
        return base + sufijo

    if key == "FEV1":
        if low:
            return f"Por debajo del LIN; alteración {severity_from_fev1_zscore(z)}{sufijo}"
        return "Dentro de límites normales" + sufijo

    if key in ("FEF25-75", "FEF50", "FEF75"):
        base = "Por debajo del LIN" if low else "Dentro de límites normales"
        return (base + sufijo +
                ". Índice descriptivo: no define patrón ni severidad")

    return ("Por debajo del LIN" if low else "Dentro de límites normales") + sufijo


# ---------------------------------------------------------------------------
# Respuesta broncodilatadora
# ---------------------------------------------------------------------------

def bronchodilator_details(values: Dict[str, SpirometryValue],
                           patient: Optional[PatientData] = None) -> Dict[str, object]:
    """
    Evalúa la respuesta broncodilatadora con el criterio ERS/ATS 2022 y, en
    paralelo, con el histórico ATS/ERS 2005, que GOLD y GINA aún emplean.

    Rellena además `percent_change_predicted` en cada SpirometryValue para que
    la tabla de la interfaz muestre el dato que decide el resultado.
    """
    pediatrico = bool(patient and patient.is_paediatric)
    resultados = {}
    positivos_2022, positivos_2005, positivos_ped = [], [], []

    for key in ("FEV1", "FVC"):
        v = values.get(key)
        if not v or v.post is None or v.baseline is None:
            continue
        r = EstandaresERS2022.evaluar_bdr(
            parametro=key, pre=v.baseline, post=v.post, predicho=v.predicted,
            es_volumen=True, pediatrico=pediatrico,
            criterio_pediatrico=CRITERIO_BDR_PEDIATRICO)
        resultados[key] = r
        v.percent_change_predicted = r.pct_predicho
        if v.absolute_change is None:
            v.absolute_change = r.delta_abs
        if v.percent_change_baseline is None:
            v.percent_change_baseline = r.pct_basal
        if r.positivo_2022:
            positivos_2022.append(key)
        if r.positivo_2005:
            positivos_2005.append(key)
        if r.positivo_pediatrico:
            positivos_ped.append(key)

    return {
        "results": resultados,
        "positive_2022": bool(positivos_2022),
        "positive_2005": bool(positivos_2005),
        "positive_paediatric": bool(positivos_ped) if pediatrico else None,
        "parameters_2022": positivos_2022,
        "parameters_2005": positivos_2005,
        "parameters_paediatric": positivos_ped,
        "paediatric": pediatrico,
    }


def bronchodilator_response(values: Dict[str, SpirometryValue],
                            patient: Optional[PatientData] = None
                            ) -> Tuple[bool, str]:
    """
    Devuelve `(positiva, texto)` según el criterio vigente.

    ERS/ATS 2022: incremento superior al 10 % del valor predicho en FEV1 o FVC,
    calculado como (post - pre) / predicho x 100. Expresar el cambio respecto
    al predicho elimina el sesgo por sexo, talla y función de partida que
    afectaba al criterio de 1991 y 2005.
    """
    detalle = bronchodilator_details(values, patient)
    if not detalle["results"]:
        return False, "No se dispone de valores posbroncodilatador."

    pediatrico = detalle["paediatric"]
    if pediatrico:
        positiva = bool(detalle["positive_paediatric"])
        parametros = detalle["parameters_paediatric"]
        umbral = (f"criterio pediátrico, {UMBRAL_BDR_PEDIATRICO_PCT_PREDICHO:.0f} % "
                  "del predicho")
    else:
        positiva = bool(detalle["positive_2022"])
        parametros = detalle["parameters_2022"]
        umbral = (f"ERS/ATS 2022, > {UMBRAL_BDR_2022_PCT_PREDICHO:.0f} % "
                  "del valor predicho")

    if positiva:
        texto = (f"Respuesta broncodilatadora significativa en "
                 f"{' y '.join(parametros)} ({umbral}).")
    else:
        texto = f"Sin respuesta broncodilatadora significativa ({umbral})."

    if not pediatrico and detalle["positive_2005"] != detalle["positive_2022"]:
        texto += (f" Con el criterio histórico ATS/ERS 2005 "
                  f"(≥ {UMBRAL_BDR_2005_PCT_BASAL:.0f} % del basal y "
                  f"≥ {UMBRAL_BDR_2005_ML:.0f} mL) el resultado sería "
                  f"{'positivo' if detalle['positive_2005'] else 'negativo'}.")
    return positiva, texto


# ---------------------------------------------------------------------------
# Conclusión
# ---------------------------------------------------------------------------

def generate_conclusion(values: Dict[str, SpirometryValue],
                        patient: Optional[PatientData] = None,
                        volumes: Optional[LungVolumes] = None,
                        quality: Optional[QualityData] = None) -> str:
    """
    Redacta la conclusión funcional.

    No emite diagnóstico clínico: describe el patrón, su severidad y la
    respuesta broncodilatadora, y señala las pruebas necesarias para
    confirmar lo que la espirometría no puede establecer por sí sola.
    """
    patron = classify_pattern(values, volumes=volumes, quality=quality)
    partes = []

    if patron.etiqueta == "No clasificable":
        partes.append("Patrón ventilatorio no clasificable con los datos "
                      "disponibles: falta el z-score o el límite inferior de "
                      "normalidad del cociente FEV1/FVC o de la FVC.")
    elif patron.etiqueta == "Normal":
        partes.append("Espirometría dentro de límites normales según los "
                      "criterios ERS/ATS 2022.")
    else:
        base = f"Patrón ventilatorio {patron.etiqueta.lower()}"
        if patron.base == "post-BD":
            base += " (clasificado sobre valores posbroncodilatador)"
        severidad = severity_from_fev1_zscore(patron.z_fev1)
        if severidad not in ("no clasificable", "sin reducción"):
            z_txt = f"{patron.z_fev1:+.2f}".replace(".", ",")
            base += (f", con alteración funcional de grado {severidad} "
                     f"(z del FEV1 {z_txt})")
        partes.append(base + ".")

    if patron.requiere_volumenes:
        partes.append("Se requiere medición de volúmenes pulmonares estáticos "
                      "para confirmar o descartar el componente restrictivo.")

    for bandera in patron.banderas:
        partes.append(bandera)

    if has_post_values(values):
        partes.append(bronchodilator_response(values, patient)[1])

    return " ".join(partes)
