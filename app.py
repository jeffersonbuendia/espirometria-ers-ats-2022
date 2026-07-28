"""
Interfaz Streamlit del generador de informe espirométrico.

Flujo: cargar el PDF del espirómetro, revisar y corregir lo extraído,
revisar la interpretación automática (ERS/ATS 2022) y descargar el informe.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from interpretation import (
    bronchodilator_details,
    classify_pattern,
    effective_z,
    generate_conclusion,
    parameter_interpretation,
    severity_from_fev1_percent,
    severity_from_fev1_zscore,
)
from models import LungVolumes, QualitySeries, SpirometryValue
from parser import parse_report
from pdf_report import build_pdf

st.set_page_config(page_title="Informe de espirometría", page_icon="🫁",
                   layout="wide")

PHYSICIAN_DEFAULT = "Jefferson Antonio Buendía, Médico Neumólogo. RM 13715940"
TECHNICIAN_DEFAULT = "Diana Guerrero Patiño, Enfermera"
INSTITUTION_DEFAULT = "SALUD ES VIVIR IPS"
CITY_DEFAULT = "Medellín, Colombia"

GRADOS = ["", "A", "B", "C", "D", "E", "U", "F"]
ETNIAS = ["Otro/Mixto", "Caucásico", "Afroamericano",
          "Asiático nororiental", "Asiático suroriental"]


def fmt_number(value, decimals=2):
    if value is None:
        return ""
    return f"{value:.{decimals}f}".replace(".", ",")


def opt(value):
    """Convierte 0.0 en None: un campo vacío no es un valor medido de cero."""
    return None if value in (None, 0, 0.0) else float(value)


def edit_value(key: str, value: SpirometryValue) -> SpirometryValue:
    st.markdown(f"**{key}**")
    labels = ["Basal", "Predicho", "% pred.", "LLN", "Z basal",
              "Pos-BD", "% pred. pos", "Z pos-BD"]
    attributes = ["baseline", "predicted", "percent_predicted", "lln",
                  "z_score", "post", "post_percent_predicted", "post_z_score"]

    for column, label, attribute in zip(st.columns(8), labels, attributes):
        with column:
            current = getattr(value, attribute)
            nuevo = st.number_input(
                label,
                value=float(current) if current is not None else 0.0,
                step=0.01, format="%.3f", key=f"{key}_{attribute}")
            setattr(value, attribute, opt(nuevo))

    if value.baseline is not None and value.post is not None:
        value.absolute_change = value.post - value.baseline
    return value


st.title("🫁 Generador de informe de espirometría")
st.caption("Interpretación conforme a ERS/ATS 2022 (Eur Respir J 2022;60:2101499) "
           "y SEPAR/ALAT 2026 (Arch Bronconeumol 10.1016/j.arbres.2025.12.016).")

# --------------------------------------------------------------- barra lateral
with st.sidebar:
    st.header("Configuración")
    institution = st.text_input("Institución", INSTITUTION_DEFAULT)
    laboratory = st.text_input("Laboratorio", "Laboratorio de Función Pulmonar")
    city = st.text_input("Ciudad", CITY_DEFAULT)
    lab_registration = st.text_input("Registro del laboratorio", "")
    physician = st.text_area("Médico", PHYSICIAN_DEFAULT, height=80)
    technician = st.text_area("Técnico", TECHNICIAN_DEFAULT, height=70)
    report_number = st.text_input("Número de informe", "")

    st.divider()
    st.subheader("Broncodilatador")
    bd_drug = st.text_input("Fármaco", "Salbutamol")
    bd_dose = st.number_input("Dosis (µg)", min_value=0, max_value=2000,
                              value=400, step=100)
    bd_route = st.text_input("Vía", "IDM con cámara espaciadora")
    bd_wait = st.number_input("Espera (min)", min_value=0, max_value=60,
                              value=15, step=5)

    st.info("El PDF descargado contiene el informe completo y, como última "
            "página, la primera hoja del reporte original del espirómetro.")
    st.warning("Verifique los valores extraídos, la calidad técnica y la "
               "conclusión antes de emitir el informe.")

uploaded = st.file_uploader("Subir reporte espirométrico en PDF", type=["pdf"])

if not uploaded:
    st.markdown("""
    ### Flujo de uso

    1. Suba el reporte espirométrico en PDF.
    2. Verifique y corrija los datos extraídos.
    3. Complete la calidad técnica y, si dispone de ellos, los volúmenes estáticos.
    4. Revise la interpretación automática y ajuste la conclusión.
    5. Descargue el informe.

    ### Criterios aplicados

    - **Normalidad:** z-score < −1,645 (percentil 5). No se usan los cortes
      fijos de 80 % del predicho ni 0,70 para el cociente FEV1/FVC.
    - **Severidad:** tres niveles sobre el z-score del FEV1
      (leve −1,645 a −2,5 · moderada −2,5 a −4,0 · grave < −4,0).
    - **Respuesta broncodilatadora:** cambio > 10 % del valor **predicho**
      en FEV1 o FVC.
    - **Restricción:** sólo se afirma con TLC por debajo de su LIN.
    """)
    st.stop()

original_pdf_bytes = uploaded.getvalue()

try:
    patient, values, quality, raw_text = parse_report(original_pdf_bytes)
except Exception as error:
    st.error(f"No fue posible procesar el PDF: {error}")
    st.stop()

# -------------------------------------------------- aviso de extracción parcial
faltantes = [k for k in ("FEV1/FVC", "FVC", "FEV1")
             if not values.get(k) or values[k].baseline is None]
if faltantes:
    st.error(
        "La extracción automática no encontró estos parámetros: "
        + ", ".join(faltantes)
        + ". Complételos manualmente antes de generar el informe; sin ellos "
          "el patrón ventilatorio no puede clasificarse."
    )
else:
    st.success("Documento procesado. Revise todos los campos antes de "
               "generar el informe.")

# ------------------------------------------------------------ datos personales
st.subheader("1. Datos del paciente")
c1, c2, c3, c4 = st.columns(4)

with c1:
    patient.name = st.text_input("Nombre", patient.name)
    sex_options = ["", "Femenino", "Masculino"]
    idx = sex_options.index(patient.sex) if patient.sex in sex_options else 0
    patient.sex = st.selectbox("Sexo biológico", sex_options, index=idx)

with c2:
    patient.age_years = st.number_input(
        "Edad (años)", min_value=0.0, max_value=120.0,
        value=float(patient.age_years or 0.0), step=0.1,
        help="Se expresa con un decimal: determina los valores de referencia.")
    patient.weight_kg = st.number_input(
        "Peso (kg)", min_value=0.0, max_value=400.0,
        value=float(patient.weight_kg or 0.0), step=0.5)

with c3:
    patient.height_cm = st.number_input(
        "Talla (cm)", min_value=0.0, max_value=250.0,
        value=float(patient.height_cm or 0.0), step=0.1,
        help="Sin calzado, espalda recta.")
    patient.exam_date = st.text_input("Fecha del examen", patient.exam_date)

with c4:
    patient.document_id = st.text_input("Documento", patient.document_id)
    patient.smoking = st.text_input("Tabaquismo", patient.smoking)
    patient.ethnicity = st.selectbox("Grupo étnico (GLI)", ETNIAS, index=0)

if patient.bmi:
    st.caption(f"IMC calculado: {patient.bmi:.1f} kg/m²")

# ------------------------------------------------------------- calidad técnica
st.subheader("2. Calidad técnica")
st.caption("Gradación A-F según ATS/ERS 2019 y SEPAR/ALAT 2026 (Tabla 10). "
           "Grados A y B: buena calidad. C: suficiente. D o inferior: no útil "
           "para interpretación.")

for etiqueta, serie_attr, texto_attr in (("Prebroncodilatador", "baseline_series", "baseline"),
                                         ("Posbroncodilatador", "post_series", "post")):
    with st.expander(f"{etiqueta} — {getattr(quality, texto_attr) or 'sin datos'}",
                     expanded=False):
        serie: QualitySeries = getattr(quality, serie_attr)
        q1, q2, q3, q4, q5 = st.columns(5)
        with q1:
            n = st.number_input("Maniobras aceptables", min_value=0, max_value=12,
                                value=int(serie.acceptable_manoeuvres or 0),
                                key=f"{serie_attr}_n")
            serie.acceptable_manoeuvres = n or None
        with q2:
            d = st.number_input("Δ FVC entre las 2 mejores (L)", min_value=0.0,
                                max_value=3.0, step=0.01, format="%.3f",
                                value=float(serie.fvc_difference_l or 0.0),
                                key=f"{serie_attr}_dfvc")
            serie.fvc_difference_l = opt(d)
        with q3:
            d = st.number_input("Δ FEV1 entre las 2 mejores (L)", min_value=0.0,
                                max_value=3.0, step=0.01, format="%.3f",
                                value=float(serie.fev1_difference_l or 0.0),
                                key=f"{serie_attr}_dfev1")
            serie.fev1_difference_l = opt(d)
        with q4:
            g = st.selectbox("Grado FVC informado por el equipo", GRADOS,
                             index=GRADOS.index(serie.grade_fvc)
                             if serie.grade_fvc in GRADOS else 0,
                             key=f"{serie_attr}_gfvc")
            serie.grade_fvc = g
        with q5:
            g = st.selectbox("Grado FEV1 informado por el equipo", GRADOS,
                             index=GRADOS.index(serie.grade_fev1)
                             if serie.grade_fev1 in GRADOS else 0,
                             key=f"{serie_attr}_gfev1")
            serie.grade_fev1 = g
        serie.sharp_pef = st.checkbox(
            "Pico de flujo espiratorio bien definido", value=serie.sharp_pef,
            key=f"{serie_attr}_pef",
            help="Un PEF sin pico definido sugiere esfuerzo submáximo o "
                 "debilidad muscular respiratoria.")

# ---------------------------------------------------------------- resultados
st.subheader("3. Resultados espirométricos")
st.caption("Los campos vacíos se envían como ausentes, no como cero. "
           "Si falta el z-score, se estima a partir del predicho y el LIN.")

order = ["FEV1/FVC", "FVC", "FEV1"]
if patient.is_paediatric:
    order.append("FEF25-75")

for key in order:
    values[key] = edit_value(key, values.get(key, SpirometryValue(parameter=key)))
    st.divider()

# ------------------------------------------------------- volúmenes estáticos
st.subheader("4. Volúmenes pulmonares estáticos (opcional)")
st.caption("Sólo una TLC por debajo de su LIN confirma restricción. Sin este "
           "dato, una FVC baja con cociente conservado se informa como "
           "posible restricción o PRISm.")

volumes = LungVolumes()
with st.expander("Introducir TLC y RV", expanded=False):
    v1, v2, v3, v4 = st.columns(4)
    with v1:
        volumes.tlc = opt(st.number_input("TLC medida (L)", min_value=0.0,
                                          step=0.01, format="%.2f", value=0.0))
    with v2:
        volumes.tlc_predicted = opt(st.number_input("TLC predicha (L)",
                                                    min_value=0.0, step=0.01,
                                                    format="%.2f", value=0.0))
    with v3:
        volumes.tlc_lln = opt(st.number_input("TLC LLN (L)", min_value=0.0,
                                              step=0.01, format="%.2f", value=0.0))
    with v4:
        volumes.tlc_z_score = opt(st.number_input("TLC z-score", min_value=-10.0,
                                                  max_value=10.0, step=0.01,
                                                  format="%.2f", value=0.0))

# --------------------------------------------------------- tabla y análisis
detalle = bronchodilator_details(values, patient)
patron = classify_pattern(values, volumes=volumes, quality=quality)

rows = []
for key in order:
    value = values[key]
    unidad = f" {value.unit}" if value.unit else ""
    basal = fmt_number(value.baseline)
    if key != "FEV1/FVC" and value.percent_predicted is not None:
        basal += f"{unidad}; {fmt_number(value.percent_predicted, 1)}%"
    post = fmt_number(value.post)
    if key != "FEV1/FVC" and value.post_percent_predicted is not None:
        post += f"{unidad}; {fmt_number(value.post_percent_predicted, 1)}%"

    if key == "FEV1/FVC" or value.percent_change_predicted is None:
        cambio = "No aplica" if key == "FEV1/FVC" else "-"
    else:
        cambio = (f"{fmt_number(value.percent_change_predicted, 1)}% del predicho; "
                  f"{fmt_number(value.percent_change_baseline, 1)}% del basal")

    rows.append({
        "Parámetro": key,
        "Basal": basal,
        "LLN": fmt_number(value.lln),
        "Z basal": fmt_number(effective_z(value), 2),
        "Pos-BD": post,
        "Z pos-BD": fmt_number(effective_z(value, post=True), 2),
        "Cambio": cambio,
        "Interpretación": parameter_interpretation(key, value),
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ------------------------------------------------------------- interpretación
st.subheader("5. Interpretación automática")
m1, m2, m3 = st.columns(3)
with m1:
    st.metric("Patrón ventilatorio", patron.etiqueta,
              help=f"Clasificado sobre valores {patron.base}.")
with m2:
    st.metric("Severidad (z del FEV1)",
              severity_from_fev1_zscore(patron.z_fev1).capitalize(),
              help="Tres niveles del ERS/ATS 2022 sobre el z-score, no sobre "
                   "el porcentaje del predicho.")
with m3:
    if detalle["results"]:
        positiva = (detalle["positive_paediatric"] if detalle["paediatric"]
                    else detalle["positive_2022"])
        st.metric("Prueba broncodilatadora",
                  "Positiva" if positiva else "Negativa",
                  help="Criterio ERS/ATS 2022: cambio > 10 % del predicho.")
    else:
        st.metric("Prueba broncodilatadora", "Sin datos pos-BD")

if patron.detalle:
    st.info(patron.detalle)

if detalle["results"] and detalle["positive_2022"] != detalle["positive_2005"]:
    st.warning(
        "Los dos criterios discrepan en este paciente. Con ERS/ATS 2022 "
        f"(> 10 % del predicho) la prueba es "
        f"{'positiva' if detalle['positive_2022'] else 'negativa'}; con el "
        f"histórico ATS/ERS 2005 (≥ 12 % del basal y ≥ 200 mL) sería "
        f"{'positiva' if detalle['positive_2005'] else 'negativa'}. "
        "El informe emite el criterio vigente."
    )

fev1 = values.get("FEV1")
if fev1 and fev1.percent_predicted:
    antigua = severity_from_fev1_percent(fev1.percent_predicted)
    nueva = severity_from_fev1_zscore(patron.z_fev1)
    if antigua != nueva and nueva != "no clasificable":
        st.caption(
            f"Comparación con la escala obsoleta ATS/ERS 2005 por % del "
            f"predicho: habría clasificado como «{antigua}»; con z-score "
            f"corresponde a «{nueva}». Se emite la clasificación vigente."
        )

# ------------------------------------------------------------------ conclusión
st.subheader("6. Conclusión")
automatic_conclusion = generate_conclusion(values, patient, volumes, quality)
conclusion = st.text_area("Conclusión del informe", value=automatic_conclusion,
                          height=140)
edited = conclusion.strip() != automatic_conclusion.strip()
if edited:
    st.caption("Conclusión modificada. El PDF emitirá su texto y conservará la "
               "clasificación automática como respaldo trazable.")

st.subheader("7. Profesionales responsables")
st.markdown(f"**Médico:** {physician}")
st.markdown(f"**Técnico:** {technician}")

# ------------------------------------------------------------------ descarga
try:
    pdf_bytes = build_pdf(
        patient=patient, quality=quality, values=values,
        conclusion=conclusion if edited else "",
        physician=physician, technician=technician,
        original_pdf_bytes=original_pdf_bytes, volumes=volumes,
        institution=institution, laboratory=laboratory, city=city,
        lab_registration=lab_registration, report_number=report_number,
        bronchodilator={"farmaco": bd_drug, "dosis_mcg": bd_dose,
                        "via": bd_route, "espera_min": bd_wait},
    )
except Exception as error:
    st.error(f"No fue posible generar el informe: {error}")
    st.stop()

safe_name = "_".join(patient.name.split()) if patient.name else "paciente"
st.download_button("Descargar informe", data=pdf_bytes,
                   file_name=f"Informe_espirometria_{safe_name}.pdf",
                   mime="application/pdf", type="primary")

st.caption("El archivo contiene el informe completo y, como última página, "
           "la primera hoja del reporte original del espirómetro.")

with st.expander("Ver texto extraído del PDF (depuración)"):
    st.text(raw_text)
