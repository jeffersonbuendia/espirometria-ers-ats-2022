from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Optional, Tuple

import pymupdf

from models import PatientData, QualityData, QualitySeries, SpirometryValue

DECIMAL = r"[-+]?\d+(?:[.,]\d+)?"


def _num(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value.strip().replace("%", "").replace(",", "."))
    except ValueError:
        return None


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extrae texto del PDF usando PyMuPDF."""
    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return "\n".join(page.get_text("text", sort=True) for page in document)
    finally:
        document.close()


def _first(patterns, text: str, flags=re.IGNORECASE | re.MULTILINE) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def _normalize_date(raw: Optional[str]) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return raw


def parse_patient(text: str) -> PatientData:
    name = _first([
        r"Sujeto\s+(?:General\s+FVC\s+(?:base|post)\s+)?\n([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s]{4,})\nLAB\.",
        r"Paciente\s*[:\-]\s*([^\n]+)",
        r"Nombre\s*[:\-]\s*([^\n]+)",
    ], text)
    if name:
        name = " ".join(name.split()).title()

    age = _num(_first([rf"\bEda(?:d)?\s+({DECIMAL})", rf"\bEdad\s*[:\-]?\s*({DECIMAL})"], text))
    sex = _first([
        r"Sexo al nacer\s+(Mujer|Hombre|Femenino|Masculino)",
        r"\bSexo\s*[:\-]?\s*(Mujer|Hombre|Femenino|Masculino)",
    ], text) or ""
    sex = {"mujer": "Femenino", "hombre": "Masculino"}.get(sex.lower(), sex.title()) if sex else ""

    weight = _num(_first([rf"\bPeso\s+({DECIMAL})\s*kg", rf"\bPeso\s*[:\-]?\s*({DECIMAL})"], text))
    height = _num(_first([rf"\bAltura\s+({DECIMAL})\s*cm", rf"\bTalla\s*[:\-]?\s*({DECIMAL})"], text))
    exam_date = _normalize_date(_first([
        r"REALIZADO:\s*(\d{1,2}/\d{1,2}/\d{4})",
        r"Fecha del examen\s*[:\-]\s*(\d{1,2}/\d{1,2}/\d{4})",
    ], text))

    return PatientData(name=name or "", age_years=age, sex=sex, weight_kg=weight, height_cm=height, exam_date=exam_date)


def _line_after_header(text: str, parameter: str, occurrence: int = 1) -> Optional[str]:
    matches = list(re.finditer(rf"(?m)^{re.escape(parameter)}\s+(.+)$", text))
    return matches[occurrence - 1].group(1).strip() if len(matches) >= occurrence else None


def _numbers_from_line(line: Optional[str]) -> list[float]:
    if not line:
        return []
    return [n for token in re.findall(DECIMAL, line) if (n := _num(token)) is not None]


def _parse_baseline_row(text: str, parameter: str, unit: str) -> SpirometryValue:
    numbers = _numbers_from_line(_line_after_header(text, parameter))
    result = SpirometryValue(parameter=parameter, unit=unit)
    if len(numbers) >= 5:
        result.baseline, result.lln, result.z_score, result.predicted, result.percent_predicted = numbers[:5]
    return result


def _extract_post_table_section(text: str) -> str:
    position = text.find("Valores en BTPS Base Post")
    return text[position:] if position >= 0 else text


def _parse_post_row(text: str, parameter: str, unit: str) -> SpirometryValue:
    numbers = _numbers_from_line(_line_after_header(_extract_post_table_section(text), parameter))
    result = SpirometryValue(parameter=parameter, unit=unit)
    if len(numbers) >= 10:
        result.baseline = numbers[0]
        result.lln = numbers[1]
        result.z_score = numbers[2]
        result.predicted = numbers[3]
        result.percent_predicted = numbers[4]
        result.post = numbers[5]
        result.post_percent_predicted = numbers[7]
        result.absolute_change = numbers[8]
        result.percent_change_baseline = numbers[9]
    return result


def parse_spirometry_values(text: str) -> Dict[str, SpirometryValue]:
    parameters = {
        "FEV1/FVC": ("FEV1/FVC", ""),
        "FVC": ("FVC (L)", "L"),
        "FEV1": ("FEV1 (L)", "L"),
        "FEF25-75": ("FEF25-75 (L/s)", "L/s"),
    }
    values: Dict[str, SpirometryValue] = {}
    for key, (label, unit) in parameters.items():
        parsed = _parse_post_row(text, label, unit)
        if parsed.baseline is None:
            parsed = _parse_baseline_row(text, label, unit)
        parsed.parameter = key
        values[key] = parsed
    return values


def parse_quality(text: str) -> QualityData:
    """
    Extrae la gradación de calidad A-F de FVC y FEV1 para cada serie.

    Además del texto descriptivo, rellena `QualitySeries` para que el motor
    pueda recalcular el grado cuando se disponga del número de maniobras
    aceptables y de la repetibilidad, o trasladar el grado del equipo cuando no.
    """
    baseline = ""
    post = ""
    baseline_series = QualitySeries()
    post_series = QualitySeries()

    baseline_match = re.search(
        r"Base\s+[\d.,]+L\s+\([^)]+\)\s+[\d.,]+L\s+\([^)]+\)\s+([A-F])\s+([A-F])",
        text,
        re.IGNORECASE,
    )
    if baseline_match:
        baseline_series.grade_fvc = baseline_match.group(1).upper()
        baseline_series.grade_fev1 = baseline_match.group(2).upper()
        baseline = (f"Grado {baseline_series.grade_fvc} para FVC y grado "
                    f"{baseline_series.grade_fev1} para FEV1")

    post_match = re.search(
        r"Post\s+[\d.,]+L\s+\([^)]+\)\s+[\d.,]+L\s+\([^)]+\)\s+([A-F])\s+([A-F])",
        text,
        re.IGNORECASE,
    )
    if post_match:
        post_series.grade_fvc = post_match.group(1).upper()
        post_series.grade_fev1 = post_match.group(2).upper()
        post = (f"Grado {post_series.grade_fvc} para FVC y grado "
                f"{post_series.grade_fev1} para FEV1")

    if not baseline:
        baseline = _first([r"Aceptabilidad\s+(Buena sesión|Aceptable|Buena)"], text) or "No extraída automáticamente"
    if not post:
        post = _first([r"Aceptabilidad\s+(Repetibilidad insufic\w*)"], text) or "No extraída automáticamente"

    return QualityData(baseline=baseline, post=post,
                       baseline_series=baseline_series,
                       post_series=post_series)


def parse_report(pdf_bytes: bytes) -> Tuple[PatientData, Dict[str, SpirometryValue], QualityData, str]:
    text = extract_pdf_text(pdf_bytes)
    return parse_patient(text), parse_spirometry_values(text), parse_quality(text), text
