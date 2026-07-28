from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class SpirometryValue:
    """
    Un parámetro espirométrico con sus valores de referencia.

    El z-score es el criterio primario de normalidad (ERS/ATS 2022):
    un valor es anormal cuando z < -1,645 (percentil 5). Se conserva
    `percent_predicted` porque los equipos lo reportan, pero no debe
    usarse para decidir normalidad ni graduar severidad.
    """
    parameter: str
    unit: str = ""
    baseline: Optional[float] = None
    predicted: Optional[float] = None
    percent_predicted: Optional[float] = None
    lln: Optional[float] = None
    z_score: Optional[float] = None
    post: Optional[float] = None
    post_percent_predicted: Optional[float] = None
    post_z_score: Optional[float] = None
    absolute_change: Optional[float] = None
    percent_change_baseline: Optional[float] = None
    #: Cambio expresado como porcentaje del valor predicho (criterio ERS/ATS 2022).
    percent_change_predicted: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PatientData:
    name: str = ""
    age_years: Optional[float] = None
    sex: str = ""
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    exam_date: str = ""
    smoking: str = ""
    ethnicity: str = "Otro/Mixto"
    reference_equation: str = "GLI-2012"
    document_id: str = ""
    position: str = "sedente"

    @property
    def bmi(self) -> Optional[float]:
        if not self.height_cm or not self.weight_kg:
            return None
        return self.weight_kg / (self.height_cm / 100.0) ** 2

    @property
    def is_paediatric(self) -> bool:
        return self.age_years is not None and self.age_years < 18.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualitySeries:
    """
    Control de calidad de una serie (pre o post), según ATS/ERS 2019 y
    SEPAR/ALAT 2026 (Tabla 10). Los grados se recalculan a partir del
    número de maniobras aceptables y la repetibilidad cuando estos datos
    están disponibles; si no, se conservan los que reporte el equipo.
    """
    acceptable_manoeuvres: Optional[int] = None
    usable_manoeuvres: Optional[int] = None
    fvc_difference_l: Optional[float] = None
    fev1_difference_l: Optional[float] = None
    grade_fvc: str = ""
    grade_fev1: str = ""
    bev_ok: Optional[bool] = None
    plateau_ok: Optional[bool] = None
    fet_seconds: Optional[float] = None
    sharp_pef: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualityData:
    """Texto libre (compatibilidad) más los datos estructurados por serie."""
    baseline: str = ""
    post: str = ""
    baseline_series: QualitySeries = field(default_factory=QualitySeries)
    post_series: QualitySeries = field(default_factory=QualitySeries)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LungVolumes:
    """
    Volúmenes pulmonares estáticos. Sólo la TLC por debajo de su LIN
    confirma restricción; sin ella, un patrón con FVC baja y cociente
    conservado es únicamente 'posible restricción' o PRISm.
    """
    tlc: Optional[float] = None
    tlc_predicted: Optional[float] = None
    tlc_lln: Optional[float] = None
    tlc_z_score: Optional[float] = None
    rv: Optional[float] = None
    rv_predicted: Optional[float] = None
    rv_lln: Optional[float] = None

    @property
    def available(self) -> bool:
        return self.tlc is not None and (
            self.tlc_lln is not None or self.tlc_z_score is not None
        )

    def to_dict(self) -> dict:
        return asdict(self)
