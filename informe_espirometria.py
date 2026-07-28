# -*- coding: utf-8 -*-
"""
informe_espirometria.py
=======================

Generación de informes de espirometría en PDF conforme a los estándares vigentes:

  [1] Stanojevic S, Kaminsky DA, Miller MR, et al.
      ERS/ATS technical standard on interpretive strategies for routine lung
      function tests. Eur Respir J 2022; 60: 2101499.
      DOI: 10.1183/13993003.01499-2021
      https://publications.ersnet.org/content/erj/60/1/2101499

  [2] Vukoja M, Franczuk M, Kivastik J.
      Interpretation — ERS Spirometry Resource Centre.
      https://channel.ersnet.org/media-113710-interpretation

  [3] García-García R, Gimeno-Peribáñez MA, Albi-Rodríguez MS, et al.
      Recommendations for Performing Spirometry (SEPAR/ALAT).
      Arch Bronconeumol 2026. DOI: 10.1016/j.arbres.2025.12.016
      https://www.archbronconeumol.org/es-recommendations-for-performing-spirometry-articulo-S0300289626000128

Referencias secundarias citadas por los documentos anteriores y aplicadas aquí:

  [4] Quanjer PH, Stanojevic S, Cole TJ, et al. Multi-ethnic reference values
      for spirometry for the 3-95-yr age range: the Global Lung Function 2012
      equations. Eur Respir J 2012; 40: 1324-1343.
  [5] Graham BL, Steenbruggen I, Miller MR, et al. Standardization of
      Spirometry 2019 Update. Am J Respir Crit Care Med 2019; 200: e70-e88.
  [6] Culver BH, Graham BL, Coates AL, et al. Recommendations for a
      standardized pulmonary function report. Am J Respir Crit Care Med 2017;
      196: 1463-1472.
  [7] Quanjer PH, Pretto JJ, Brazzale DJ, Boros PW. Grading the severity of
      airways obstruction: new wine in new bottles. Eur Respir J 2014; 43: 505-512.

--------------------------------------------------------------------------------
DISEÑO
--------------------------------------------------------------------------------
El módulo separa deliberadamente dos responsabilidades:

  * ``EstandaresERS2022``  -> motor de cálculo puro (sin dependencias de PDF).
    Cualquier proyecto puede importarlo para clasificar patrón, severidad,
    respuesta broncodilatadora y calidad técnica sin generar documento alguno.

  * ``InformeEspirometria`` -> compone el PDF a partir de un diccionario de
    valores YA CONVERTIDOS A NÚMERO por el consumidor (parser de PDF del
    espirómetro, HL7, entrada manual, base de datos, etc.).

El motor no calcula ecuaciones de referencia: recibe predicho / LIN / z-score.
Si sólo se dispone de predicho y LIN, el z-score se estima analíticamente
(ver ``EstandaresERS2022.z_desde_lln``). Si se dispone de un motor GLI propio,
se puede inyectar mediante el parámetro ``proveedor_referencia``.

--------------------------------------------------------------------------------
USO MÍNIMO
--------------------------------------------------------------------------------
    from informe_espirometria import InformeEspirometria

    generador = InformeEspirometria(
        institucion="SALUD ES VIVIR IPS",
        laboratorio="Laboratorio de Función Pulmonar",
        ciudad="Medellín, Colombia",
        firmante="Jefferson Antonio Buendía",
        credenciales="MD · Neumólogo Pediatra",
    )

    pdf_bytes = generador.generar(datos)            # -> bytes
    ruta      = generador.generar(datos, "out.pdf") # -> bytes y además escribe

--------------------------------------------------------------------------------
ESQUEMA DE ``datos``
--------------------------------------------------------------------------------
Todas las claves son opcionales salvo ``paciente`` y ``parametros``.

    {
      "paciente": {
          "nombre": str,
          "documento": str,
          "sexo": "M" | "F",
          "edad_anios": float,            # con 1 decimal (ver [3])
          "talla_cm": float,
          "peso_kg": float,
          "etnia": str,                   # grupo GLI utilizado
          "tabaquismo": str,
          "fecha_estudio": "YYYY-MM-DD" | datetime.date,
          "posicion": "sedente" | "bipedestación" | "supino",
          "talla_estimada_por": str | None,   # "envergadura", "rodilla-talón"...
      },

      "referencia": {
          "ecuacion": "GLI-2012",
          "grupo_etnico": "Otro/Mixto",
      },

      "broncodilatador": {
          "farmaco": "Salbutamol",
          "dosis_mcg": 400,
          "via": "IDM con cámara espaciadora",
          "espera_min": 15,
      },

      # --- Núcleo: cualquier parámetro que entregue el espirómetro -----------
      "parametros": {
          "FVC":      {"pred": 2.84, "lln": 2.30, "pre": 2.93, "post": 2.85,
                       "z_pre": 0.20, "z_post": 0.03, "unidad": "L"},
          "FEV1":     {...},
          "FEV1/FVC": {..., "unidad": "%"},
          "PEF":      {..., "unidad": "L/s"},
          "FEF25-75": {...},
          "FIF50":    {...},
          ...           # claves libres; las desconocidas se tabulan sin juicio
      },

      "calidad": {
          "pre":  {"n_aceptables": 3, "n_utilizables": 3,
                   "dif_fvc_L": 0.06, "dif_fev1_L": 0.04,
                   "bev_ok": True, "meseta_ok": True, "fet_s": 7.2},
          "post": {...},
      },

      "volumenes": {                       # opcional; confirma restricción
          "TLC": {"pred": 5.9, "lln": 4.7, "valor": 4.2, "z": -2.1},
          "RV":  {...}, "RV/TLC": {...},
      },

      "seguimiento": {                     # opcional; cambio longitudinal [1]
          "z_fev1_previo": -1.10,
          "anios_transcurridos": 2.0,
          "edad_previa_anios": 58.0,
      },

      "conclusion_equipo": str | None,     # texto automático del espirómetro
      "observaciones_tecnico": str | None,
      "indicacion": str | None,
      "n_reporte": str | None,
    }
"""

from __future__ import annotations

import datetime as _dt
import io as _io
import math as _math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

__all__ = [
    "EstandaresERS2022",
    "InformeEspirometria",
    "ResultadoParametro",
    "ResultadoBDR",
    "ResultadoCalidad",
    "ResultadoPatron",
    "PARAMETROS_APLICADOS",
]

__version__ = "1.0.0"


# =============================================================================
# CONSTANTES NORMATIVAS
# =============================================================================

#: Z-score que define el límite inferior de la normalidad (percentil 5).  [1][2][3]
Z_LIN: float = -1.645

#: Z-score que define el límite superior de la normalidad (percentil 95).  [1]
Z_LSN: float = 1.645

#: Umbral de respuesta broncodilatadora, expresado como cambio porcentual
#: respecto al VALOR PREDICHO (criterio ERS/ATS 2022).  [1][2][3]
UMBRAL_BDR_2022_PCT_PREDICHO: float = 10.0

#: Criterio histórico ATS/ERS 2005, conservado sólo como referencia comparativa
#: porque numerosas guías clínicas (GOLD, GINA) aún lo emplean.  [2][3]
UMBRAL_BDR_2005_PCT_BASAL: float = 12.0
UMBRAL_BDR_2005_ML: float = 200.0

#: Criterio pediátrico alternativo admitido por SEPAR/ALAT 2026 ante evidencia
#: insuficiente: 12% sobre el basal ó 9-10% sobre el predicho. Debe elegirse
#: uno y aplicarse de forma consistente.  [3]
UMBRAL_BDR_PEDIATRICO_PCT_PREDICHO: float = 9.0
UMBRAL_BDR_PEDIATRICO_PCT_BASAL: float = 12.0

#: Cortes de severidad de la alteración funcional por z-score del FEV1.  [1][2][3][7]
CORTE_SEVERIDAD_LEVE: float = -1.645
CORTE_SEVERIDAD_MODERADA: float = -2.5
CORTE_SEVERIDAD_GRAVE: float = -4.0

#: Cociente FEV1/PEF (mL / (L/min)) por encima del cual debe sospecharse
#: obstrucción de vía aérea central o superior.  [1][2]
UMBRAL_FEV1_PEF: float = 8.0

#: Umbrales de repetibilidad para la gradación de calidad A-F.  [3][5]
#: Adultos y niños > 6 años.
REPETIBILIDAD_ADULTO = {"A_B": 0.150, "C": 0.200, "D": 0.250}
#: Niños <= 6 años o FVC <= 1 L (o 10 % del valor mayor, lo que sea mayor).
REPETIBILIDAD_PEDIATRICA = {"A_B": 0.100, "C": 0.150, "D": 0.200}
REPETIBILIDAD_PEDIATRICA_PCT = 0.10

#: Volumen retroextrapolado máximo aceptable.  [3][5]
BEV_MAX_PCT_FVC: float = 5.0
BEV_MAX_ML: float = 100.0

#: Duración máxima de la espiración forzada.  [3][5]
FET_MAX_S: float = 15.0

#: Grados de calidad utilizables para interpretación.  [3]
GRADOS_INTERPRETABLES = ("A", "B", "C")
GRADOS_BUENA_CALIDAD = ("A", "B")

#: Tiempos de abstinencia recomendados antes de la espirometría basal.  [3]
ABSTINENCIA_BRONCODILATADOR_H = {
    "SABA": 6, "SAMA": 12, "LABA": 24, "Ultra-LABA": 48,
    "LAMA": 48, "Teofilinas de liberación sostenida": 48,
    "Ensifentrina": 12, "Corticoides": 0,
}


#: Tabla que se imprime AL PIE del informe: cada parámetro normativo empleado,
#: su valor y la fuente exacta. Cumple el requisito de trazabilidad del
#: informe estandarizado.  [6]
PARAMETROS_APLICADOS: Sequence[Tuple[str, str, str]] = (
    ("Ecuaciones de referencia",
     "GLI-2012 (3-95 años), grupo étnico declarado",
     "Quanjer 2012 [4]; SEPAR/ALAT 2026 Tabla 11 [3]"),
    ("Límite inferior de normalidad (LIN)",
     "Percentil 5  =  z-score −1,645",
     "ERS/ATS 2022 [1]; ERS Interpretation [2]"),
    ("Límite superior de normalidad (LSN)",
     "Percentil 95  =  z-score +1,645",
     "ERS/ATS 2022 [1]"),
    ("Definición de obstrucción",
     "FEV1/FVC < LIN  (se descartan los cortes fijos 0,70 y 80 % del predicho)",
     "ERS/ATS 2022 [1]; SEPAR/ALAT 2026 §Interpretación [3]"),
    ("Sospecha de restricción",
     "FVC < LIN con FEV1/FVC ≥ LIN; requiere TLC < LIN para confirmarse",
     "ERS/ATS 2022 Tabla 1 [1]"),
    ("Patrón inespecífico / PRISm",
     "FEV1 y FVC < LIN, FEV1/FVC ≥ LIN, TLC normal o no disponible",
     "ERS/ATS 2022 [1]; SEPAR/ALAT 2026 §3 [3]"),
    ("Disanapsis",
     "FEV1/FVC < LIN con FEV1 normal y FVC normal o elevada",
     "ERS/ATS 2022 Tabla 1 [1]; SEPAR/ALAT 2026 §5 [3]"),
    ("Severidad de la alteración",
     "z(FEV1): leve −1,645 a −2,5 · moderada −2,5 a −4,0 · grave < −4,0",
     "ERS/ATS 2022 [1]; ERS Interpretation Tabla 3 [2]; Quanjer 2014 [7]"),
    ("Respuesta broncodilatadora (BDR)",
     "Δ > 10 % del valor PREDICHO en FEV1 o FVC:  (post − pre)/predicho × 100",
     "ERS/ATS 2022 [1][2]; SEPAR/ALAT 2026 §Variables de respuesta [3]"),
    ("BDR — criterio histórico (informativo)",
     "Δ ≥ 12 % del basal Y ≥ 200 mL  (ATS/ERS 2005; aún usado por GOLD/GINA)",
     "ERS Interpretation [2]; SEPAR/ALAT 2026 [3]"),
    ("Gradación de calidad",
     "A-F según nº de maniobras aceptables y repetibilidad FEV1/FVC",
     "ATS/ERS 2019 [5]; SEPAR/ALAT 2026 Tabla 10 [3]"),
    ("Repetibilidad (> 6 años)",
     "Diferencia entre los dos mejores FVC y FEV1 ≤ 0,150 L",
     "SEPAR/ALAT 2026 Tabla 7 [3]"),
    ("Repetibilidad (≤ 6 años o FVC ≤ 1 L)",
     "Diferencia ≤ 0,100 L ó 10 % del valor mayor (el que sea mayor)",
     "SEPAR/ALAT 2026 Tablas 8-9 [3]"),
    ("Volumen retroextrapolado (BEV)",
     "≤ 5 % de la FVC ó ≤ 100 mL",
     "SEPAR/ALAT 2026 Tabla 6 [3]"),
    ("Fin de espiración forzada",
     "Meseta ≤ 0,025 L durante ≥ 1 s, o 15 s de espiración",
     "SEPAR/ALAT 2026 Tabla 6 [3]"),
    ("Obstrucción de vía aérea central",
     "FEV1(mL)/PEF(L/min) > 8;  FIF50/FEF50 ≈1 fija, <1 extratorácica variable, "
     ">1 intratorácica variable",
     "ERS/ATS 2022 Tabla 2 [1]; SEPAR/ALAT 2026 Tabla 12 [3]"),
    ("FEF25-75 y flujos distales",
     "Se informan de forma descriptiva; alta variabilidad y baja especificidad "
     "para enfermedad de vía aérea pequeña: NO se usan para definir patrón",
     "SEPAR/ALAT 2026 §5 [3]"),
    ("Cambio longitudinal del FEV1",
     "Se informa la diferencia de z-scores entre estudios. El puntaje de "
     "cambio del estándar no se aplica: su fórmula de correlación excede la "
     "unidad por encima de los 50 años y no reproduce el ejemplo publicado",
     "ERS/ATS 2022 [1]; réplica Miller MR, Eur Respir J 2023;61:2202025"),
    ("Broncodilatador de prueba",
     "Salbutamol 400 µg (4 inhalaciones separadas 30 s), lectura a los 15 min",
     "SEPAR/ALAT 2026 §Procedimiento [3]"),
)


# =============================================================================
# ESTRUCTURAS DE RESULTADO
# =============================================================================

@dataclass
class ResultadoParametro:
    """Un parámetro espirométrico ya evaluado contra su referencia."""
    clave: str
    unidad: str = ""
    pred: Optional[float] = None
    lln: Optional[float] = None
    uln: Optional[float] = None
    pre: Optional[float] = None
    post: Optional[float] = None
    z_pre: Optional[float] = None
    z_post: Optional[float] = None
    pct_pred_pre: Optional[float] = None
    pct_pred_post: Optional[float] = None
    z_estimado: bool = False          # True si el z se derivó de pred/LIN
    derivado: bool = False            # True si el parámetro se calculó, no se midió
    bajo_lin_pre: Optional[bool] = None
    bajo_lin_post: Optional[bool] = None
    sobre_lsn_pre: Optional[bool] = None
    sobre_lsn_post: Optional[bool] = None

    @property
    def z_vigente(self) -> Optional[float]:
        """z post-BD si existe; si no, el pre-BD."""
        return self.z_post if self.z_post is not None else self.z_pre

    @property
    def valor_vigente(self) -> Optional[float]:
        return self.post if self.post is not None else self.pre


@dataclass
class ResultadoBDR:
    """Respuesta broncodilatadora evaluada con ambos criterios."""
    parametro: str
    pre: Optional[float] = None
    post: Optional[float] = None
    pred: Optional[float] = None
    delta_abs: Optional[float] = None        # en unidades del parámetro
    delta_ml: Optional[float] = None         # sólo si el parámetro es volumen
    pct_predicho: Optional[float] = None     # criterio 2022
    pct_basal: Optional[float] = None        # criterio 2005
    positivo_2022: Optional[bool] = None
    positivo_2005: Optional[bool] = None
    criterio_pediatrico: Optional[str] = None
    positivo_pediatrico: Optional[bool] = None


@dataclass
class ResultadoCalidad:
    """Gradación A-F de una serie (pre o post)."""
    serie: str
    grado_fvc: str = "F"
    grado_fev1: str = "F"
    grado_global: str = "F"
    n_aceptables: int = 0
    n_utilizables: int = 0
    dif_fvc_L: Optional[float] = None
    dif_fev1_L: Optional[float] = None
    umbral_aplicado: str = ""
    interpretable: bool = False
    notas: List[str] = field(default_factory=list)


@dataclass
class ResultadoPatron:
    """Clasificación del patrón ventilatorio."""
    etiqueta: str = "No clasificable"
    detalle: str = ""
    base: str = "post-BD"                 # sobre qué serie se clasificó
    severidad: Optional[str] = None
    z_fev1: Optional[float] = None
    requiere_volumenes: bool = False
    banderas: List[str] = field(default_factory=list)


# =============================================================================
# MOTOR DE CÁLCULO  (sin dependencias de PDF)
# =============================================================================

class EstandaresERS2022:
    """
    Implementación de los criterios interpretativos ERS/ATS 2022 [1][2] con las
    precisiones operativas de SEPAR/ALAT 2026 [3].

    Todos los métodos son estáticos y puros: no mutan estado ni requieren
    instanciación. Aceptan ``None`` y lo propagan, de modo que un espirómetro
    que no entregue determinado campo no rompe el cálculo.
    """

    # ---------------------------------------------------------------- z-score
    @staticmethod
    def z_desde_lln(observado: Optional[float],
                    predicho: Optional[float],
                    lln: Optional[float]) -> Optional[float]:
        """
        Estima el z-score cuando sólo se conocen el predicho y el LIN.

        Dado que el LIN se define en z = −1,645 [1][2], la desviación estándar
        equivalente es DE = (predicho − LIN)/1,645, de donde:

            z = (observado − predicho) · 1,645 / (predicho − LIN)

        Es exacta cuando la distribución residual es simétrica. En GLI-2012 el
        parámetro L de la transformación LMS introduce asimetría, por lo que el
        valor debe rotularse como ESTIMADO. Siempre que el espirómetro o un
        motor GLI entreguen el z real, éste tiene prioridad.
        """
        if observado is None or predicho is None or lln is None:
            return None
        denominador = predicho - lln
        if denominador == 0:
            return None
        return (observado - predicho) * abs(Z_LIN) / denominador

    @staticmethod
    def lln_desde_z(predicho: Optional[float],
                    z_observado: Optional[float],
                    observado: Optional[float]) -> Optional[float]:
        """Deriva el LIN cuando se conocen predicho, observado y z real."""
        if None in (predicho, z_observado, observado) or z_observado == 0:
            return None
        de = (observado - predicho) / z_observado
        return predicho + Z_LIN * de

    @staticmethod
    def porcentaje_predicho(observado: Optional[float],
                            predicho: Optional[float]) -> Optional[float]:
        """
        % del predicho. Se informa por costumbre y compatibilidad, pero NO se
        usa para decidir normalidad: SEPAR/ALAT 2026 y ERS/ATS 2022 desaconsejan
        expresamente los cortes fijos (80 %, 0,70). [1][3]
        """
        if observado is None or predicho in (None, 0):
            return None
        return observado / predicho * 100.0

    # -------------------------------------------------------------- severidad
    @staticmethod
    def clasificar_severidad(z_fev1: Optional[float]) -> Optional[str]:
        """
        Sistema de tres niveles basado en el z-score del FEV1. [1][2][7]

            −1,645 ≥ z > −2,5   -> leve
            −2,5   ≥ z > −4,0   -> moderada
                     z ≤ −4,0   -> grave

        No debe aplicarse a obstrucción de vía aérea superior, donde una
        obstrucción potencialmente letal puede clasificarse como leve. [2]
        """
        if z_fev1 is None:
            return None
        if z_fev1 > CORTE_SEVERIDAD_LEVE:
            return "Sin alteración (dentro de límites normales)"
        if z_fev1 > CORTE_SEVERIDAD_MODERADA:
            return "Leve"
        if z_fev1 > CORTE_SEVERIDAD_GRAVE:
            return "Moderada"
        return "Grave"

    # --------------------------------------------------------------------- BDR
    @staticmethod
    def evaluar_bdr(parametro: str,
                    pre: Optional[float],
                    post: Optional[float],
                    predicho: Optional[float],
                    es_volumen: bool = True,
                    pediatrico: bool = False,
                    criterio_pediatrico: str = "predicho") -> ResultadoBDR:
        """
        Evalúa la respuesta broncodilatadora con el criterio vigente y, en
        paralelo, con el histórico.

        Criterio primario (ERS/ATS 2022) [1][2][3]:

            Δ% = (post − pre) / predicho × 100      ->  positivo si > 10 %

        Criterio histórico (ATS/ERS 2005), sólo informativo:

            Δ ≥ 12 % del basal  Y  Δ ≥ 200 mL

        En pediatría SEPAR/ALAT 2026 admite ≥ 12 % sobre el basal ó 9-10 %
        sobre el predicho, exigiendo elegir uno y mantenerlo. [3]
        """
        r = ResultadoBDR(parametro=parametro, pre=pre, post=post, pred=predicho)
        if pre is None or post is None:
            return r

        r.delta_abs = post - pre
        if es_volumen:
            r.delta_ml = r.delta_abs * 1000.0

        # --- criterio 2022 ---------------------------------------------------
        if predicho not in (None, 0):
            r.pct_predicho = (post - pre) / predicho * 100.0
            r.positivo_2022 = r.pct_predicho > UMBRAL_BDR_2022_PCT_PREDICHO

        # --- criterio 2005 (informativo) ------------------------------------
        if pre not in (None, 0):
            r.pct_basal = (post - pre) / pre * 100.0
            if es_volumen and r.delta_ml is not None:
                r.positivo_2005 = (r.pct_basal >= UMBRAL_BDR_2005_PCT_BASAL
                                   and r.delta_ml >= UMBRAL_BDR_2005_ML)
            else:
                r.positivo_2005 = r.pct_basal >= UMBRAL_BDR_2005_PCT_BASAL

        # --- criterio pediátrico --------------------------------------------
        if pediatrico:
            if criterio_pediatrico == "basal":
                r.criterio_pediatrico = (
                    f"≥ {UMBRAL_BDR_PEDIATRICO_PCT_BASAL:.0f} % sobre el basal")
                if r.pct_basal is not None:
                    r.positivo_pediatrico = (
                        r.pct_basal >= UMBRAL_BDR_PEDIATRICO_PCT_BASAL)
            else:
                r.criterio_pediatrico = (
                    f"≥ {UMBRAL_BDR_PEDIATRICO_PCT_PREDICHO:.0f} % del predicho")
                if r.pct_predicho is not None:
                    r.positivo_pediatrico = (
                        r.pct_predicho >= UMBRAL_BDR_PEDIATRICO_PCT_PREDICHO)

        return r

    # ---------------------------------------------------------------- calidad
    @staticmethod
    def grado_calidad(n_aceptables: Optional[int],
                      dif_L: Optional[float],
                      n_utilizables: Optional[int] = None,
                      pediatrico_estricto: bool = False,
                      valor_mayor: Optional[float] = None) -> Tuple[str, str]:
        """
        Gradación A-F de un parámetro (FEV1 o FVC) en una serie.
        [3] Tabla 10; [5].

            A : ≥3 aceptables y repetibilidad dentro del umbral estricto
            B : 2 aceptables y repetibilidad dentro del umbral estricto
            C : ≥2 aceptables, repetibilidad dentro del umbral intermedio
            D : ≥2 aceptables, repetibilidad dentro del umbral laxo
            E : ≥2 aceptables, repetibilidad fuera de todos los umbrales
            U : 0 aceptables, ≥1 utilizable
            F : 0 aceptables, 0 utilizables

        ``pediatrico_estricto`` aplica los umbrales de niños ≤ 6 años o FVC ≤ 1 L
        (0,100 / 0,150 / 0,200 L ó 10 % del valor mayor, lo que sea mayor).

        Devuelve ``(grado, descripción_del_umbral)``.
        """
        n_aceptables = n_aceptables or 0
        n_utilizables = n_utilizables if n_utilizables is not None else n_aceptables

        if pediatrico_estricto:
            base = REPETIBILIDAD_PEDIATRICA
            piso = (valor_mayor * REPETIBILIDAD_PEDIATRICA_PCT) if valor_mayor else 0.0
            t_ab = max(base["A_B"], piso)
            t_c = max(base["C"], piso)
            t_d = max(base["D"], piso)
            desc = (f"≤ {t_ab*1000:.0f} mL (pediátrico / FVC ≤ 1 L: "
                    f"0,100 L ó 10 % del mayor)")
        else:
            base = REPETIBILIDAD_ADULTO
            t_ab, t_c, t_d = base["A_B"], base["C"], base["D"]
            desc = f"≤ {t_ab*1000:.0f} mL (adulto / > 6 años)"

        if n_aceptables == 0:
            return ("U" if n_utilizables >= 1 else "F"), desc

        if dif_L is None:
            # Sin dato de repetibilidad no puede asignarse grado A-E con rigor.
            return ("U" if n_utilizables >= 1 else "F"), desc + " · sin dato de repetibilidad"

        d = abs(dif_L)
        if n_aceptables >= 3 and d <= t_ab:
            return "A", desc
        if n_aceptables == 2 and d <= t_ab:
            return "B", desc
        if n_aceptables >= 2 and d <= t_c:
            return "C", desc
        if n_aceptables >= 2 and d <= t_d:
            return "D", desc
        if n_aceptables >= 2:
            return "E", desc
        # Una sola maniobra aceptable: no cumple ningún grado A-E.
        return ("U" if n_utilizables >= 1 else "F"), desc

    @staticmethod
    def evaluar_calidad(serie: str,
                        bloque: Optional[Dict[str, Any]],
                        pediatrico_estricto: bool = False,
                        fvc_mayor: Optional[float] = None,
                        fev1_mayor: Optional[float] = None) -> ResultadoCalidad:
        """Aplica ``grado_calidad`` a FVC y FEV1 y consolida el grado global."""
        r = ResultadoCalidad(serie=serie)
        if not bloque:
            r.notas.append("Sin datos de control de calidad aportados.")
            return r

        # El equipo puede reportar el grado A-F sin entregar el número de
        # maniobras ni la repetibilidad. En ese caso se traslada el grado tal
        # como lo informó el espirómetro, sin recalcularlo ni fabricar cifras.
        reportado = bloque.get("grado_reportado")
        if reportado and bloque.get("n_aceptables") is None:
            grados = [g.strip().upper() for g in str(reportado).split("/")
                      if g.strip()]
            if grados:
                r.grado_fvc = grados[0]
                r.grado_fev1 = grados[-1]
                orden = "ABCDEUF"
                validos = [g for g in grados if g in orden]
                r.grado_global = (max(validos, key=orden.index) if validos
                                  else grados[0])
                r.interpretable = r.grado_global in GRADOS_INTERPRETABLES
                r.umbral_aplicado = "grado informado por el equipo"
                r.notas.append(
                    "Grado de calidad tomado del reporte del espirómetro; no "
                    "se dispone del número de maniobras aceptables ni de la "
                    "repetibilidad para recalcularlo de forma independiente.")
                return r

        r.n_aceptables = int(bloque.get("n_aceptables") or 0)
        r.n_utilizables = int(bloque.get("n_utilizables") or r.n_aceptables)
        r.dif_fvc_L = bloque.get("dif_fvc_L")
        r.dif_fev1_L = bloque.get("dif_fev1_L")

        r.grado_fvc, desc = EstandaresERS2022.grado_calidad(
            r.n_aceptables, r.dif_fvc_L, r.n_utilizables,
            pediatrico_estricto, fvc_mayor)
        r.grado_fev1, _ = EstandaresERS2022.grado_calidad(
            r.n_aceptables, r.dif_fev1_L, r.n_utilizables,
            pediatrico_estricto, fev1_mayor)
        r.umbral_aplicado = desc

        orden = "ABCDEUF"
        r.grado_global = max(r.grado_fvc, r.grado_fev1, key=orden.index)
        r.interpretable = r.grado_global in GRADOS_INTERPRETABLES

        # Criterios de aceptabilidad individuales -----------------------------
        if bloque.get("bev_ok") is False:
            r.notas.append(
                f"Volumen retroextrapolado fuera de norma "
                f"(> {BEV_MAX_PCT_FVC:.0f} % de la FVC ó > {BEV_MAX_ML:.0f} mL).")
        if bloque.get("meseta_ok") is False:
            r.notas.append(
                "No se documenta meseta espiratoria (< 0,025 L durante ≥ 1 s); "
                "la FVC puede estar subestimada y el cociente FEV1/FVC sobreestimado.")
        fet = bloque.get("fet_s")
        if fet is not None and fet > FET_MAX_S:
            r.notas.append(f"Tiempo espiratorio forzado de {fet:.1f} s "
                           f"(máximo recomendado {FET_MAX_S:.0f} s).")
        if bloque.get("tos_primer_segundo"):
            r.notas.append("Tos en el primer segundo de la espiración: "
                           "el FEV1 no es utilizable.")
        if not r.interpretable:
            r.notas.append(
                f"Grado {r.grado_global}: la interpretación es menos fiable y "
                "depende en alto grado del juicio clínico.")
        return r

    # ----------------------------------------------------------------- patrón
    @staticmethod
    def clasificar_patron(z_fev1: Optional[float],
                          z_fvc: Optional[float],
                          z_ratio: Optional[float],
                          z_tlc: Optional[float] = None,
                          pef_definido: bool = True,
                          base: str = "post-BD") -> ResultadoPatron:
        """
        Algoritmo de clasificación del ERS/ATS 2022 (Figura 4 y Tabla 1) [1][2],
        replicado en el algoritmo diagnóstico de SEPAR/ALAT 2026 (Figura 3) [3].

        Se parte SIEMPRE del cociente FEV1/FVC frente a su LIN; después se
        examina la FVC; la TLC, cuando existe, resuelve restricción frente a
        patrón inespecífico.
        """
        r = ResultadoPatron(base=base, z_fev1=z_fev1)

        if z_ratio is None or z_fvc is None:
            r.etiqueta = "No clasificable"
            faltantes = []
            if z_ratio is None:
                faltantes.append("del cociente FEV1/FVC")
            if z_fvc is None:
                faltantes.append("de la FVC")
            r.detalle = (
                "No se dispone del z-score o del límite inferior de normalidad "
                + " ni ".join(faltantes) + ". El algoritmo interpretativo del "
                "ERS/ATS 2022 parte necesariamente de la comparación del cociente "
                "FEV1/FVC con su LIN, por lo que el patrón ventilatorio no puede "
                "establecerse. Debe completarse el estudio con los valores de "
                "referencia correspondientes antes de emitir una clasificación.")
            return r

        ratio_bajo = z_ratio < Z_LIN
        fvc_baja = z_fvc < Z_LIN
        fvc_alta = z_fvc > Z_LSN
        fev1_bajo = (z_fev1 is not None) and (z_fev1 < Z_LIN)
        tlc_baja = (z_tlc is not None) and (z_tlc < Z_LIN)
        tlc_normal = (z_tlc is not None) and (z_tlc >= Z_LIN)

        # ---- Rama izquierda: cociente conservado ---------------------------
        if not ratio_bajo:
            if not fvc_baja:
                r.etiqueta = "Normal"
                r.detalle = ("FEV1/FVC y FVC por encima de sus respectivos "
                             "límites inferiores de normalidad. No se identifica "
                             "alteración ventilatoria obstructiva ni restrictiva.")
                return r

            # FVC baja con cociente conservado
            if tlc_baja:
                r.etiqueta = "Restrictivo"
                r.detalle = ("FVC < LIN con FEV1/FVC conservado y TLC < LIN: "
                             "alteración ventilatoria restrictiva confirmada por "
                             "volúmenes pulmonares estáticos.")
            elif tlc_normal:
                r.etiqueta = "Patrón inespecífico"
                r.detalle = ("FEV1 y FVC < LIN con FEV1/FVC y TLC normales. "
                             "Dos tercios de los sujetos mantienen esta alteración "
                             "a tres años; el tercio restante evoluciona a un patrón "
                             "obstructivo o restrictivo definido.")
            else:
                r.etiqueta = "Posible restricción / PRISm"
                r.requiere_volumenes = True
                r.detalle = ("FVC < LIN con FEV1/FVC conservado. No es posible "
                             "confirmar restricción sin medición de la TLC. En "
                             "ausencia de volúmenes estáticos este patrón se "
                             "denomina PRISm (preserved ratio impaired spirometry).")
            if not pef_definido:
                r.banderas.append(
                    "PEF sin pico definido: considerar debilidad muscular "
                    "respiratoria o esfuerzo submáximo como causa del patrón "
                    "(diagnóstico diferencial del patrón inespecífico).")
            return r

        # ---- Rama derecha: cociente bajo -> hay obstrucción ----------------
        if not fvc_baja:
            if not fev1_bajo and (fvc_alta or not fvc_baja):
                if fvc_alta:
                    r.etiqueta = "Disanapsis"
                    r.detalle = ("FEV1/FVC < LIN con FEV1 dentro del rango de "
                                 "referencia y FVC elevada. Corresponde a un "
                                 "crecimiento desproporcionado entre parénquima y "
                                 "vía aérea; se ha considerado una variante "
                                 "fisiológica, si bien datos recientes sugieren que "
                                 "puede representar un estadio precoz de obstrucción.")
                    return r
                r.etiqueta = "Obstructivo"
                r.detalle = ("FEV1/FVC < LIN con FVC y FEV1 dentro del rango de "
                             "referencia: alteración ventilatoria obstructiva sin "
                             "repercusión sobre el FEV1.")
                return r
            r.etiqueta = "Obstructivo"
            r.detalle = ("FEV1/FVC < LIN con FVC conservada: alteración "
                         "ventilatoria obstructiva.")
            return r

        # cociente bajo + FVC baja
        if tlc_baja:
            r.etiqueta = "Mixto"
            r.detalle = ("FEV1/FVC y FVC < LIN con TLC < LIN: alteración "
                         "ventilatoria mixta confirmada por volúmenes estáticos.")
        elif tlc_normal:
            r.etiqueta = "Obstructivo con atrapamiento aéreo"
            r.detalle = ("FEV1/FVC y FVC < LIN con TLC normal: la reducción de la "
                         "FVC es atribuible a atrapamiento aéreo y no a restricción "
                         "verdadera.")
        else:
            r.etiqueta = "Mixto (sospecha)"
            r.requiere_volumenes = True
            r.detalle = ("FEV1/FVC y FVC < LIN. La confirmación del componente "
                         "restrictivo exige demostrar TLC < LIN mediante volúmenes "
                         "pulmonares estáticos; con TLC normal el patrón "
                         "correspondería a obstrucción con atrapamiento aéreo.")
        return r

    # --------------------------------------------- vía aérea central/superior
    @staticmethod
    def indice_fev1_pef(fev1_L: Optional[float],
                        pef_L_s: Optional[float]) -> Optional[float]:
        """
        Cociente FEV1 (mL) / PEF (L/min). Valores > 8 mL/L/min sugieren
        obstrucción de vía aérea central o superior. [1][2]
        """
        if fev1_L is None or not pef_L_s:
            return None
        pef_L_min = pef_L_s * 60.0
        if pef_L_min == 0:
            return None
        return (fev1_L * 1000.0) / pef_L_min

    @staticmethod
    def clasificar_via_aerea_central(fev1_L: Optional[float],
                                     pef_L_s: Optional[float],
                                     fif50: Optional[float] = None,
                                     fef50: Optional[float] = None
                                     ) -> Tuple[Optional[float], Optional[float], str]:
        """
        Devuelve ``(indice_fev1_pef, cociente_fif50_fef50, texto)``.

        FIF50/FEF50 ≈ 1  -> obstrucción extratorácica fija
        FIF50/FEF50 < 1  -> obstrucción extratorácica variable
        FIF50/FEF50 > 1  -> obstrucción intratorácica variable
        [1] Tabla 2; [3] Tabla 12.
        """
        idx = EstandaresERS2022.indice_fev1_pef(fev1_L, pef_L_s)
        coc = None
        if fif50 is not None and fef50:
            coc = fif50 / fef50

        partes: List[str] = []
        if idx is not None:
            if idx > UMBRAL_FEV1_PEF:
                partes.append(
                    f"El cociente FEV1/PEF es de {idx:.1f} mL/L/min, por encima "
                    f"del umbral de {UMBRAL_FEV1_PEF:.0f} mL/L/min, lo que obliga "
                    "a descartar obstrucción de vía aérea central o superior. "
                    "Debe diferenciarse de un esfuerzo submáximo, que también "
                    "reduce el PEF.")
            else:
                partes.append(
                    f"El cociente FEV1/PEF es de {idx:.1f} mL/L/min (umbral "
                    f"{UMBRAL_FEV1_PEF:.0f} mL/L/min): no hay indicio de "
                    "obstrucción de vía aérea central o superior.")
        if coc is not None:
            if abs(coc - 1.0) <= 0.10:
                partes.append(
                    f"El cociente FIF50/FEF50 es de {coc:.2f} (≈ 1), patrón "
                    "compatible con obstrucción extratorácica fija.")
            elif coc < 1.0:
                partes.append(
                    f"El cociente FIF50/FEF50 es de {coc:.2f} (< 1), patrón "
                    "compatible con obstrucción extratorácica variable.")
            else:
                partes.append(
                    f"El cociente FIF50/FEF50 es de {coc:.2f} (> 1), patrón "
                    "compatible con obstrucción intratorácica variable.")
        return idx, coc, " ".join(partes)

    # ------------------------------------------------- cambio longitudinal
    @staticmethod
    def correlacion_longitudinal(anios: Optional[float],
                                 edad_previa: Optional[float]) -> Optional[float]:
        """
        Correlación esperada entre dos determinaciones de FEV1 [1][2]:

            r = 0,642 − 0,04 · t(años) + 0,020 · edad(años en t1)

        Reproduce exactamente los ejemplos publicados en el estándar
        (varón de 14 años: r = 0,912 a los 3 meses y r = 0,762 a los 4 años).

        ADVERTENCIA DE RANGO. La expresión es lineal en la edad y supera la
        unidad por encima de los ~50 años, lo que es imposible para un
        coeficiente de correlación. Sólo es aplicable dentro del rango etario
        de la cohorte de derivación. Fuera de él se devuelve ``None``.
        """
        if anios is None or edad_previa is None:
            return None
        r = 0.642 - 0.04 * anios + 0.020 * edad_previa
        if not 0.0 < r < 1.0:
            return None
        return r

    @staticmethod
    def delta_z(z_previo: Optional[float],
                z_actual: Optional[float]) -> Optional[float]:
        """
        Diferencia simple entre los z-scores de dos estudios.

        Se informa en lugar del «puntaje de cambio» del estándar porque este
        último no ha podido reproducirse: con los datos del ejemplo publicado
        (z −0,78 a −1,60 en 3 meses, r = 0,912) la expresión
        (z2 − z1)/√(2(1 − r)) devuelve −1,96, mientras que el artículo indica
        −2,17. Los propios autores reconocieron posteriormente que la sección
        sobre cambios naturales en el tiempo era limitada (Miller MR, et al.
        Eur Respir J 2023;61:2202025). Emitir un umbral de seguimiento que no
        reproduce su propio ejemplo sería incorrecto, de modo que este módulo
        se limita a exponer la magnitud del cambio y deja su valoración al
        criterio clínico.
        """
        if z_previo is None or z_actual is None:
            return None
        return z_actual - z_previo

    # ------------------------------------------------------------- utilidades
    @staticmethod
    def es_pediatrico(edad_anios: Optional[float]) -> bool:
        """Umbral pediátrico para criterios de BDR y repetibilidad."""
        return edad_anios is not None and edad_anios < 18.0

    @staticmethod
    def repetibilidad_estricta(edad_anios: Optional[float],
                               fvc_L: Optional[float]) -> bool:
        """Umbrales reducidos: ≤ 6 años o FVC ≤ 1 L. [3] Tablas 8-9."""
        if edad_anios is not None and edad_anios <= 6.0:
            return True
        if fvc_L is not None and fvc_L <= 1.0:
            return True
        return False


# =============================================================================
# GENERADOR DE PDF
# =============================================================================

# Parámetros que el motor reconoce e interpreta; el resto se tabula sin juicio.
_VOLUMENES = {"FVC", "FEV1", "FEV0.5", "FEV0.75", "FEV3", "FEV6",
              "FVC BEST", "FEV1 BEST", "FIVC", "VC", "SVC", "IC", "ERV",
              "TLC", "RV", "FRC", "FEV5", "FEV0.7"}
_COCIENTES = {"FEV1/FVC", "FEV0.5/FVC", "FEV0.75/FVC", "FEV1/FEV6",
              "FEV3/FVC", "RV/TLC", "FEV1/VC", "FEV0.55/FVC"}
_FLUJOS = {"PEF", "FEF25", "FEF50", "FEF75", "FEF25-75", "FEF2575",
           "FIF50", "PIF", "FEF75-85"}

# Alias tolerados en la entrada -> clave canónica.
_ALIAS = {
    "CVF": "FVC", "VEF1": "FEV1", "VEF1/CVF": "FEV1/FVC", "FEP": "PEF",
    "FEF2575": "FEF25-75", "FEF25_75": "FEF25-75", "FEF25/75": "FEF25-75",
    "VEF0.5": "FEV0.5", "VEF0.75": "FEV0.75", "VEF6": "FEV6",
    "CPT": "TLC", "VR": "RV", "CV": "VC",
}

# Etiquetas en español para la tabla principal.
_ETIQUETAS = {
    "FVC": "CVF", "FEV1": "VEF1", "FEV1/FVC": "VEF1/CVF", "PEF": "FEP",
    "FEV0.5": "VEF0,5", "FEV0.75": "VEF0,75", "FEV6": "VEF6",
    "FEV1/FEV6": "VEF1/VEF6", "FEF25-75": "FEF25-75", "TLC": "CPT",
    "RV": "VR", "RV/TLC": "VR/CPT", "VC": "CV", "IC": "CI", "FIVC": "CVIF",
}

# Orden preferente de aparición.
_ORDEN = ["FVC", "FEV1", "FEV1/FVC", "FEV6", "FEV1/FEV6", "FEV0.75",
          "FEV0.75/FVC", "FEV0.5", "PEF", "FEF25", "FEF50", "FEF75",
          "FEF25-75", "FIVC", "FIF50", "VC", "IC"]


class InformeEspirometria:
    """
    Compone el informe de espirometría en PDF.

    El constructor fija los datos invariables del laboratorio; ``generar``
    recibe los datos de un estudio concreto y devuelve el PDF en memoria.

    Parameters
    ----------
    institucion, laboratorio, ciudad, registro_lab
        Encabezado y pie institucional.
    firmante, credenciales, registro_medico
        Bloque de firma.
    ecuacion_referencia
        Texto por defecto para la ecuación de referencia (sobrescribible por
        estudio). GLI-2012 es la recomendada para 3-95 años. [3][4]
    criterio_bdr_pediatrico
        ``"predicho"`` (9 % del predicho) o ``"basal"`` (12 % del basal).
        SEPAR/ALAT 2026 exige elegir uno y mantenerlo constante. [3]
    incluir_criterio_2005
        Si ``True`` (por defecto) se tabula también el criterio ATS/ERS 2005
        como información complementaria, dado que GOLD y GINA aún lo emplean.
    proveedor_referencia
        Callable opcional ``f(clave, paciente) -> dict`` que devuelva
        ``{"pred":…, "lln":…, "z_pre":…, "z_post":…}`` para completar los
        parámetros que lleguen sin valores de referencia. Permite acoplar un
        motor GLI-2012 externo sin modificar esta clase.
    """

    # ------------------------------------------------------------------ init
    def __init__(self,
                 institucion: str = "",
                 laboratorio: str = "Laboratorio de Función Pulmonar",
                 ciudad: str = "",
                 registro_lab: str = "",
                 firmante: str = "",
                 credenciales: str = "",
                 registro_medico: str = "",
                 ecuacion_referencia: str = "GLI-2012",
                 criterio_bdr_pediatrico: str = "predicho",
                 incluir_criterio_2005: bool = True,
                 proveedor_referencia: Optional[Callable[[str, Dict[str, Any]],
                                                         Dict[str, Any]]] = None,
                 tamano_pagina: Tuple[float, float] = LETTER) -> None:
        self.institucion = institucion
        self.laboratorio = laboratorio
        self.ciudad = ciudad
        self.registro_lab = registro_lab
        self.firmante = firmante
        self.credenciales = credenciales
        self.registro_medico = registro_medico
        self.ecuacion_referencia = ecuacion_referencia
        if criterio_bdr_pediatrico not in ("predicho", "basal"):
            raise ValueError("criterio_bdr_pediatrico debe ser 'predicho' o 'basal'")
        self.criterio_bdr_pediatrico = criterio_bdr_pediatrico
        self.incluir_criterio_2005 = incluir_criterio_2005
        self.proveedor_referencia = proveedor_referencia
        self.tamano_pagina = tamano_pagina

        self._AZUL = colors.HexColor("#1F4E79")
        self._AZUL_CLARO = colors.HexColor("#EBF3FB")
        self._GRIS = colors.HexColor("#F5F5F5")
        self._GRIS_TXT = colors.HexColor("#555555")
        self._ROJO = colors.HexColor("#8B0000")
        self._ROJO_FONDO = colors.HexColor("#FDEDED")
        self._AMBAR = colors.HexColor("#7B4F00")
        self._AMBAR_FONDO = colors.HexColor("#FFF6E0")
        self._VERDE = colors.HexColor("#1A6B1A")
        self._VERDE_FONDO = colors.HexColor("#EAF4EA")
        self._BORDE = colors.HexColor("#B0B0B0")

        self._estilos = self._construir_estilos()

    # ------------------------------------------------------------- API pública
    def generar(self,
                datos: Dict[str, Any],
                ruta: Optional[str] = None) -> bytes:
        """
        Construye el informe y devuelve el PDF como ``bytes``.

        Si se indica ``ruta``, además escribe el archivo en disco.

        Raises
        ------
        ValueError
            Si faltan los bloques ``paciente`` o ``parametros``.
        """
        if not isinstance(datos, dict):
            raise ValueError("`datos` debe ser un diccionario.")
        if "paciente" not in datos:
            raise ValueError("`datos['paciente']` es obligatorio.")
        if "parametros" not in datos or not datos["parametros"]:
            raise ValueError("`datos['parametros']` es obligatorio y no puede estar vacío.")

        analisis = self.analizar(datos)
        pdf = self._render(datos, analisis)

        if ruta:
            with open(ruta, "wb") as fh:
                fh.write(pdf)
        return pdf

    def generar_archivo(self, datos: Dict[str, Any], ruta: str) -> str:
        """Igual que ``generar`` pero devuelve la ruta del archivo escrito."""
        self.generar(datos, ruta)
        return ruta

    # --------------------------------------------------------------- análisis
    def analizar(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ejecuta toda la interpretación sin generar PDF.

        Es público a propósito: permite usar el motor en una API, un cuadro de
        mando o una batería de pruebas sin el coste de renderizar el documento.
        """
        pac = datos.get("paciente", {}) or {}
        edad = _num(pac.get("edad_anios"))
        pediatrico = EstandaresERS2022.es_pediatrico(edad)

        params = self._normalizar_parametros(datos, pac)
        vol = self._normalizar_volumenes(datos)

        p_fvc = params.get("FVC")
        p_fev1 = params.get("FEV1")
        p_ratio = params.get("FEV1/FVC")
        p_pef = params.get("PEF")

        # ---- calidad -------------------------------------------------------
        fvc_ref = (p_fvc.post if p_fvc and p_fvc.post is not None
                   else (p_fvc.pre if p_fvc else None))
        estricta = EstandaresERS2022.repetibilidad_estricta(edad, fvc_ref)
        calidad_bloque = datos.get("calidad", {}) or {}
        calidad = {
            "pre": EstandaresERS2022.evaluar_calidad(
                "Pre-BD", calidad_bloque.get("pre"), estricta,
                p_fvc.pre if p_fvc else None, p_fev1.pre if p_fev1 else None),
            "post": EstandaresERS2022.evaluar_calidad(
                "Post-BD", calidad_bloque.get("post"), estricta,
                p_fvc.post if p_fvc else None, p_fev1.post if p_fev1 else None),
        }
        hay_post = any(p.post is not None for p in params.values())

        # ---- respuesta broncodilatadora ------------------------------------
        bdr: Dict[str, ResultadoBDR] = {}
        if hay_post:
            for clave in ("FVC", "FEV1"):
                p = params.get(clave)
                if p is None:
                    continue
                bdr[clave] = EstandaresERS2022.evaluar_bdr(
                    parametro=_ETIQUETAS.get(clave, clave),
                    pre=p.pre, post=p.post, predicho=p.pred,
                    es_volumen=True, pediatrico=pediatrico,
                    criterio_pediatrico=self.criterio_bdr_pediatrico)

        bdr_positiva_2022 = any(b.positivo_2022 for b in bdr.values()
                                if b.positivo_2022 is not None)
        bdr_positiva_2005 = any(b.positivo_2005 for b in bdr.values()
                                if b.positivo_2005 is not None)
        bdr_positiva_ped = any(b.positivo_pediatrico for b in bdr.values()
                               if b.positivo_pediatrico is not None)

        # ---- patrón ventilatorio -------------------------------------------
        z_tlc = vol.get("TLC").z_pre if vol.get("TLC") else None
        pef_definido = bool((datos.get("calidad", {}) or {})
                            .get("pef_definido", True))

        base_post = hay_post and (p_ratio and p_ratio.z_post is not None)
        patron = EstandaresERS2022.clasificar_patron(
            z_fev1=(p_fev1.z_post if base_post and p_fev1 else
                    (p_fev1.z_pre if p_fev1 else None)),
            z_fvc=(p_fvc.z_post if base_post and p_fvc else
                   (p_fvc.z_pre if p_fvc else None)),
            z_ratio=(p_ratio.z_post if base_post and p_ratio else
                     (p_ratio.z_pre if p_ratio else None)),
            z_tlc=z_tlc,
            pef_definido=pef_definido,
            base="post-BD" if base_post else "pre-BD",
        )
        patron_pre = EstandaresERS2022.clasificar_patron(
            z_fev1=p_fev1.z_pre if p_fev1 else None,
            z_fvc=p_fvc.z_pre if p_fvc else None,
            z_ratio=p_ratio.z_pre if p_ratio else None,
            z_tlc=z_tlc, pef_definido=pef_definido, base="pre-BD",
        )

        # ---- severidad ------------------------------------------------------
        z_fev1_sev = patron.z_fev1
        patron.severidad = EstandaresERS2022.clasificar_severidad(z_fev1_sev)

        # ---- vía aérea central ---------------------------------------------
        fev1_v = p_fev1.valor_vigente if p_fev1 else None
        pef_v = p_pef.valor_vigente if p_pef else None
        p_fif50 = params.get("FIF50")
        p_fef50 = params.get("FEF50")
        idx_pef, coc_fif, texto_central = EstandaresERS2022.clasificar_via_aerea_central(
            fev1_v, pef_v,
            p_fif50.valor_vigente if p_fif50 else None,
            p_fef50.valor_vigente if p_fef50 else None)
        sospecha_central = idx_pef is not None and idx_pef > UMBRAL_FEV1_PEF

        # ---- cambio longitudinal -------------------------------------------
        seg = datos.get("seguimiento") or {}
        delta_z = EstandaresERS2022.delta_z(
            _num(seg.get("z_fev1_previo")), z_fev1_sev)
        r_long = EstandaresERS2022.correlacion_longitudinal(
            _num(seg.get("anios_transcurridos")),
            _num(seg.get("edad_previa_anios")))

        # ---- discrepancia con el equipo -------------------------------------
        discrepancia = self._detectar_discrepancia(
            datos.get("conclusion_equipo"), bdr_positiva_2022,
            bdr_positiva_ped if pediatrico else None, pediatrico)

        return {
            "params": params,
            "volumenes": vol,
            "calidad": calidad,
            "hay_post": hay_post,
            "bdr": bdr,
            "bdr_positiva_2022": bdr_positiva_2022,
            "bdr_positiva_2005": bdr_positiva_2005,
            "bdr_positiva_pediatrica": bdr_positiva_ped if pediatrico else None,
            "patron": patron,
            "patron_pre": patron_pre,
            "pediatrico": pediatrico,
            "edad": edad,
            "indice_fev1_pef": idx_pef,
            "cociente_fif50_fef50": coc_fif,
            "texto_via_central": texto_central,
            "sospecha_via_central": sospecha_central,
            "delta_z_seguimiento": delta_z,
            "anios_seguimiento": _num(seg.get("anios_transcurridos")),
            "correlacion_longitudinal": r_long,
            "discrepancia_equipo": discrepancia,
            "repetibilidad_estricta": estricta,
        }

    # ----------------------------------------------- normalización de entrada
    def _normalizar_parametros(self, datos: Dict[str, Any],
                               pac: Dict[str, Any]) -> Dict[str, ResultadoParametro]:
        crudos = datos.get("parametros") or {}
        salida: Dict[str, ResultadoParametro] = {}

        for clave_in, bloque in crudos.items():
            if bloque is None:
                continue
            clave = _canon(clave_in)
            if not isinstance(bloque, dict):
                # Permite pasar sólo el valor pre: {"FVC": 3.34}
                bloque = {"pre": bloque}

            # Enriquecimiento opcional desde un motor GLI externo.
            if self.proveedor_referencia is not None:
                faltan = bloque.get("pred") is None or bloque.get("lln") is None
                if faltan:
                    try:
                        extra = self.proveedor_referencia(clave, pac) or {}
                    except Exception:
                        extra = {}
                    for k, v in extra.items():
                        bloque.setdefault(k, v)

            unidad = bloque.get("unidad") or _unidad_por_defecto(clave)
            p = ResultadoParametro(
                clave=clave,
                unidad=unidad,
                pred=_num(bloque.get("pred")),
                lln=_num(bloque.get("lln")),
                uln=_num(bloque.get("uln")),
                pre=_num(bloque.get("pre")),
                post=_num(bloque.get("post")),
                z_pre=_num(bloque.get("z_pre")),
                z_post=_num(bloque.get("z_post")),
            )

            # Z estimado si no viene dado.
            if p.z_pre is None:
                p.z_pre = EstandaresERS2022.z_desde_lln(p.pre, p.pred, p.lln)
                p.z_estimado = p.z_pre is not None
            if p.z_post is None and p.post is not None:
                p.z_post = EstandaresERS2022.z_desde_lln(p.post, p.pred, p.lln)
                p.z_estimado = p.z_estimado or (p.z_post is not None)

            # LIN derivado si no viene dado pero sí el z real.
            if p.lln is None:
                p.lln = EstandaresERS2022.lln_desde_z(p.pred, p.z_pre, p.pre)

            p.pct_pred_pre = EstandaresERS2022.porcentaje_predicho(p.pre, p.pred)
            p.pct_pred_post = EstandaresERS2022.porcentaje_predicho(p.post, p.pred)

            if p.z_pre is not None:
                p.bajo_lin_pre = p.z_pre < Z_LIN
                p.sobre_lsn_pre = p.z_pre > Z_LSN
            elif p.lln is not None and p.pre is not None:
                p.bajo_lin_pre = p.pre < p.lln
            if p.z_post is not None:
                p.bajo_lin_post = p.z_post < Z_LIN
                p.sobre_lsn_post = p.z_post > Z_LSN
            elif p.lln is not None and p.post is not None:
                p.bajo_lin_post = p.post < p.lln

            salida[clave] = p

        # Cociente derivado si el espirómetro no lo entregó.
        #
        # El predicho del cociente puede aproximarse como pred(FEV1)/pred(FVC),
        # pero su LIN NO es derivable de los LIN de numerador y denominador: la
        # distribución del cociente tiene dispersión propia en las ecuaciones
        # GLI. Sin LIN no puede decidirse la presencia de obstrucción, de modo
        # que el patrón se declara no clasificable en lugar de improvisarlo.
        if "FEV1/FVC" not in salida and {"FEV1", "FVC"} <= set(salida):
            f1, fv = salida["FEV1"], salida["FVC"]
            der = ResultadoParametro(clave="FEV1/FVC", unidad="%")
            der.derivado = True
            if f1.pre is not None and fv.pre:
                der.pre = f1.pre / fv.pre * 100.0
            if f1.post is not None and fv.post:
                der.post = f1.post / fv.post * 100.0
            if f1.pred is not None and fv.pred:
                der.pred = f1.pred / fv.pred * 100.0
                der.pct_pred_pre = EstandaresERS2022.porcentaje_predicho(
                    der.pre, der.pred)
                der.pct_pred_post = EstandaresERS2022.porcentaje_predicho(
                    der.post, der.pred)
            salida["FEV1/FVC"] = der

        return salida

    def _normalizar_volumenes(self, datos: Dict[str, Any]) -> Dict[str, ResultadoParametro]:
        crudos = datos.get("volumenes") or {}
        salida: Dict[str, ResultadoParametro] = {}
        for clave_in, bloque in crudos.items():
            if not isinstance(bloque, dict):
                bloque = {"valor": bloque}
            clave = _canon(clave_in)
            p = ResultadoParametro(
                clave=clave,
                unidad=bloque.get("unidad") or _unidad_por_defecto(clave),
                pred=_num(bloque.get("pred")),
                lln=_num(bloque.get("lln")),
                pre=_num(bloque.get("valor", bloque.get("pre"))),
                z_pre=_num(bloque.get("z", bloque.get("z_pre"))),
            )
            if p.z_pre is None:
                p.z_pre = EstandaresERS2022.z_desde_lln(p.pre, p.pred, p.lln)
                p.z_estimado = p.z_pre is not None
            p.pct_pred_pre = EstandaresERS2022.porcentaje_predicho(p.pre, p.pred)
            if p.z_pre is not None:
                p.bajo_lin_pre = p.z_pre < Z_LIN
            salida[clave] = p
        return salida

    @staticmethod
    def _detectar_discrepancia(conclusion_equipo: Optional[str],
                               positivo_2022: bool,
                               positivo_ped: Optional[bool],
                               pediatrico: bool) -> Optional[str]:
        """
        Compara la conclusión automática del espirómetro con el resultado
        recalculado. Los equipos que aplican criterios propios o ecuaciones
        antiguas producen clasificaciones erróneas con frecuencia; detectarlas
        y dejarlas documentadas forma parte de la validación del informe.
        """
        if not conclusion_equipo:
            return None
        texto = conclusion_equipo.lower()
        dice_negativa = ("negativ" in texto) or ("negative" in texto)
        dice_positiva = ("positiv" in texto) or ("positive" in texto)
        if not (dice_negativa or dice_positiva):
            return None

        propio = positivo_ped if (pediatrico and positivo_ped is not None) else positivo_2022
        if dice_negativa and propio:
            return ("El equipo informó la prueba broncodilatadora como NEGATIVA. "
                    "Recalculada con el criterio ERS/ATS 2022 (cambio > 10 % del "
                    "valor predicho) la prueba es POSITIVA. Prevalece la "
                    "clasificación de este informe.")
        if dice_positiva and not propio:
            return ("El equipo informó la prueba broncodilatadora como POSITIVA. "
                    "Recalculada con el criterio ERS/ATS 2022 (cambio > 10 % del "
                    "valor predicho) la prueba es NEGATIVA. Prevalece la "
                    "clasificación de este informe.")
        return None

    # ============================================================== RENDER PDF
    def _construir_estilos(self) -> Dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        e: Dict[str, ParagraphStyle] = {}
        e["cuerpo"] = ParagraphStyle(
            "cuerpo", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.6, leading=12.2, alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#1A1A1A"))
        e["seccion"] = ParagraphStyle(
            "seccion", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=11.5, leading=14, spaceBefore=10, spaceAfter=4,
            textColor=self._AZUL)
        e["subseccion"] = ParagraphStyle(
            "subseccion", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9.2, leading=12, spaceBefore=6, spaceAfter=2,
            textColor=self._AZUL)
        e["nota"] = ParagraphStyle(
            "nota", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=7.4, leading=9.6, alignment=TA_JUSTIFY,
            textColor=self._GRIS_TXT)
        e["celda"] = ParagraphStyle(
            "celda", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.6, leading=9.4)
        e["celda_c"] = ParagraphStyle(
            "celda_c", parent=e["celda"], alignment=TA_CENTER)
        e["alerta"] = ParagraphStyle(
            "alerta", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.6, leading=11.6, alignment=TA_JUSTIFY)
        e["firma"] = ParagraphStyle(
            "firma", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.4, leading=11, alignment=TA_CENTER)
        e["conclusion"] = ParagraphStyle(
            "conclusion", parent=e["cuerpo"], fontSize=9.0, leading=12.6,
            spaceAfter=3)
        return e

    def _render(self, datos: Dict[str, Any], a: Dict[str, Any]) -> bytes:
        buffer = _io.BytesIO()
        ancho, alto = self.tamano_pagina
        margen_x, margen_sup, margen_inf = 15 * mm, 26 * mm, 18 * mm

        doc = BaseDocTemplate(
            buffer, pagesize=self.tamano_pagina,
            leftMargin=margen_x, rightMargin=margen_x,
            topMargin=margen_sup, bottomMargin=margen_inf,
            title=f"Informe de espirometría — "
                  f"{(datos.get('paciente') or {}).get('nombre', '')}",
            author=self.firmante or self.institucion,
            subject="Espirometría forzada con prueba broncodilatadora "
                    "(ERS/ATS 2022)",
        )
        marco = Frame(margen_x, margen_inf,
                      ancho - 2 * margen_x, alto - margen_sup - margen_inf,
                      id="principal", showBoundary=0)
        doc.addPageTemplates([
            PageTemplate(id="std", frames=[marco],
                         onPage=lambda c, d: self._decorar_pagina(c, d, datos)),
        ])

        historia: List[Any] = []
        self._bloque_alertas(historia, datos, a)
        self._bloque_paciente(historia, datos, a)
        self._bloque_calidad(historia, datos, a)
        self._bloque_valores(historia, datos, a)
        self._bloque_bdr(historia, datos, a)
        self._bloque_interpretacion(historia, datos, a)
        self._bloque_conclusion(historia, datos, a)
        self._bloque_firma(historia, datos, a)
        self._bloque_parametros_aplicados(historia)

        doc.build(historia)
        return buffer.getvalue()

    # ------------------------------------------------------ encabezado / pie
    def _decorar_pagina(self, canv, doc, datos: Dict[str, Any]) -> None:
        canv.saveState()
        ancho, alto = self.tamano_pagina
        mx = 15 * mm

        # --- encabezado ---
        canv.setFont("Helvetica-Bold", 14)
        canv.setFillColor(self._AZUL)
        canv.drawString(mx, alto - 15 * mm, self.institucion or "")
        canv.setFont("Helvetica", 7.8)
        canv.setFillColor(self._GRIS_TXT)
        sub = self.laboratorio
        if self.registro_lab:
            sub += f"  ·  {self.registro_lab}"
        canv.drawString(mx, alto - 19.2 * mm, sub)

        canv.setFont("Helvetica-Bold", 8.6)
        canv.setFillColor(colors.HexColor("#333333"))
        canv.drawRightString(ancho - mx, alto - 15 * mm,
                             "INFORME DE ESPIROMETRÍA FORZADA")
        canv.setFont("Helvetica", 7.4)
        canv.setFillColor(self._GRIS_TXT)
        pac = datos.get("paciente") or {}
        canv.drawRightString(ancho - mx, alto - 18.6 * mm,
                             f"Fecha del estudio: {_fecha(pac.get('fecha_estudio'))}")
        nrep = datos.get("n_reporte")
        if nrep:
            canv.drawRightString(ancho - mx, alto - 21.8 * mm, f"Informe {nrep}")

        canv.setStrokeColor(self._AZUL)
        canv.setLineWidth(1.1)
        canv.line(mx, alto - 23.6 * mm, ancho - mx, alto - 23.6 * mm)

        # --- pie ---
        canv.setStrokeColor(self._AZUL)
        canv.setLineWidth(0.6)
        canv.line(mx, 13.5 * mm, ancho - mx, 13.5 * mm)
        canv.setFont("Helvetica", 6.6)
        canv.setFillColor(colors.HexColor("#888888"))
        izq = " · ".join(x for x in (self.laboratorio, self.institucion,
                                     self.ciudad) if x)
        canv.drawString(mx, 10.2 * mm, izq)
        canv.drawRightString(ancho - mx, 10.2 * mm, f"Página {doc.page}")
        canv.drawString(mx, 7.4 * mm,
                        "Interpretación conforme a ERS/ATS 2022 (Eur Respir J "
                        "2022;60:2101499) y SEPAR/ALAT 2026 (Arch Bronconeumol "
                        "10.1016/j.arbres.2025.12.016)")
        canv.restoreState()

    # ------------------------------------------------------ helpers de tabla
    def _tabla(self, filas: List[List[Any]], anchos: List[float],
               estilo_extra: Optional[List[Tuple]] = None,
               encabezado: bool = True,
               fondo_cabecera: Optional[colors.Color] = None) -> Table:
        t = Table(filas, colWidths=anchos, repeatRows=1 if encabezado else 0)
        cmds: List[Tuple] = [
            ("GRID", (0, 0), (-1, -1), 0.4, self._BORDE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ]
        if encabezado:
            cmds += [
                ("BACKGROUND", (0, 0), (-1, 0),
                 fondo_cabecera or self._AZUL),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.2),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ]
        if estilo_extra:
            cmds += estilo_extra
        t.setStyle(TableStyle(cmds))
        return t

    def _panel(self, titulo: str, cuerpo: str,
               color_texto: colors.Color, color_fondo: colors.Color) -> Table:
        st = ParagraphStyle("panel", parent=self._estilos["alerta"])
        contenido = (f'<font color="#{color_texto.hexval()[2:]}">'
                     f"<b>{titulo}</b></font>  {cuerpo}")
        t = Table([[Paragraph(contenido, st)]],
                  colWidths=[self._ancho_util()])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), color_fondo),
            ("BOX", (0, 0), (-1, -1), 0.9, color_texto),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    def _ancho_util(self) -> float:
        return self.tamano_pagina[0] - 30 * mm

    def _titulo(self, texto: str) -> List[Any]:
        p = Paragraph(texto, self._estilos["seccion"])
        linea = Table([[""]], colWidths=[self._ancho_util()], rowHeights=[1.2])
        linea.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1.0, self._AZUL),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return [p, linea, Spacer(1, 4)]

    # ------------------------------------------------------------- secciones
    def _bloque_alertas(self, h: List[Any], datos: Dict[str, Any],
                        a: Dict[str, Any]) -> None:
        disc = a.get("discrepancia_equipo")
        if disc:
            h.append(self._panel("CORRECCIÓN TÉCNICA DEL RESULTADO AUTOMÁTICO.",
                                 disc, self._AMBAR, self._AMBAR_FONDO))
            h.append(Spacer(1, 5))

        cal = a["calidad"]
        no_interp = [c for c in cal.values()
                     if c.n_aceptables and not c.interpretable]
        if no_interp:
            grados = ", ".join(f"{c.serie}: grado {c.grado_global}" for c in no_interp)
            h.append(self._panel(
                "CALIDAD TÉCNICA LIMITADA.",
                f"{grados}. Los grados inferiores a C no son útiles para "
                "interpretación; la lectura de este informe queda condicionada "
                "al juicio clínico y se recomienda repetir el estudio.",
                self._ROJO, self._ROJO_FONDO))
            h.append(Spacer(1, 5))

        if a.get("sospecha_via_central"):
            h.append(self._panel(
                "SOSPECHA DE OBSTRUCCIÓN DE VÍA AÉREA CENTRAL O SUPERIOR.",
                f"El cociente FEV1/PEF es de {a['indice_fev1_pef']:.1f} mL/L/min "
                f"(umbral {UMBRAL_FEV1_PEF:.0f}). En este escenario el sistema de "
                "gradación de severidad por z-score no debe aplicarse, dado que "
                "una obstrucción potencialmente crítica puede clasificarse como leve.",
                self._ROJO, self._ROJO_FONDO))
            h.append(Spacer(1, 5))

    def _bloque_paciente(self, h: List[Any], datos: Dict[str, Any],
                         a: Dict[str, Any]) -> None:
        pac = datos.get("paciente") or {}
        ref = datos.get("referencia") or {}
        bd = datos.get("broncodilatador") or {}

        talla = _num(pac.get("talla_cm"))
        peso = _num(pac.get("peso_kg"))
        imc = None
        if talla and peso:
            imc = peso / (talla / 100.0) ** 2

        antrop = []
        if talla:
            antrop.append(f"{talla:.1f} cm")
        if peso:
            antrop.append(f"{peso:.1f} kg")
        if imc:
            antrop.append(f"IMC {imc:.1f} kg/m²")

        eq = ref.get("ecuacion") or self.ecuacion_referencia
        grupo = ref.get("grupo_etnico") or pac.get("etnia")
        if grupo:
            eq = f"{eq} · grupo {grupo}"

        bd_txt = "—"
        if bd:
            piezas = [bd.get("farmaco", "")]
            if bd.get("dosis_mcg"):
                piezas.append(f"{bd['dosis_mcg']:.0f} µg")
            if bd.get("via"):
                piezas.append(bd["via"])
            if bd.get("espera_min"):
                piezas.append(f"lectura a los {bd['espera_min']:.0f} min")
            bd_txt = " · ".join(str(x) for x in piezas if x)

        edad_txt = f"{a['edad']:.1f} años" if a.get("edad") is not None else "—"
        talla_nota = pac.get("talla_estimada_por")
        if talla_nota:
            antrop.append(f"talla estimada por {talla_nota}")

        filas = [
            ["Nombre", pac.get("nombre", "—"), "Documento", pac.get("documento", "—")],
            ["Sexo biológico", _sexo(pac.get("sexo")), "Edad", edad_txt],
            ["Antropometría", " · ".join(antrop) or "—",
             "Tabaquismo", pac.get("tabaquismo", "—")],
            ["Posición", pac.get("posicion", "sedente"),
             "Indicación", pac.get("indicacion") or datos.get("indicacion") or "—"],
            ["Ecuaciones de referencia", eq, "Broncodilatador", bd_txt],
        ]
        cuerpo = [[Paragraph(f"<b>{f[0]}</b>", self._estilos["celda"]),
                   Paragraph(str(f[1]), self._estilos["celda"]),
                   Paragraph(f"<b>{f[2]}</b>", self._estilos["celda"]),
                   Paragraph(str(f[3]), self._estilos["celda"])] for f in filas]

        w = self._ancho_util()
        t = self._tabla(cuerpo, [w * 0.19, w * 0.31, w * 0.19, w * 0.31],
                        encabezado=False,
                        estilo_extra=[
                            ("BACKGROUND", (0, 0), (0, -1), self._AZUL_CLARO),
                            ("BACKGROUND", (2, 0), (2, -1), self._AZUL_CLARO),
                        ])
        h.extend(self._titulo("1.  DATOS DEL PACIENTE"))
        h.append(t)
        h.append(Spacer(1, 3))
        h.append(Paragraph(
            "La edad se expresa con un decimal y la talla se mide sin calzado, "
            "de acuerdo con SEPAR/ALAT 2026; ambas determinan directamente los "
            "valores de referencia. El sexo biológico es el determinante del "
            "tamaño pulmonar predicho.", self._estilos["nota"]))

    def _bloque_calidad(self, h: List[Any], datos: Dict[str, Any],
                        a: Dict[str, Any]) -> None:
        cal = a["calidad"]
        w = self._ancho_util()
        enc = ["Serie", "Maniobras aceptables", "Δ FVC (mL)", "Grado FVC",
               "Δ FEV1 (mL)", "Grado FEV1", "Grado global"]
        filas = [enc]
        estilos: List[Tuple] = []

        for i, clave in enumerate(("pre", "post"), start=1):
            c = cal[clave]
            if clave == "post" and not a["hay_post"]:
                continue
            filas.append([
                c.serie,
                str(c.n_aceptables) if c.n_aceptables else "—",
                _mL(c.dif_fvc_L), c.grado_fvc,
                _mL(c.dif_fev1_L), c.grado_fev1, c.grado_global,
            ])
            col = (self._VERDE if c.grado_global in GRADOS_BUENA_CALIDAD
                   else self._AMBAR if c.grado_global == "C" else self._ROJO)
            estilos.append(("TEXTCOLOR", (6, i), (6, i), col))
            estilos.append(("FONTNAME", (6, i), (6, i), "Helvetica-Bold"))

        estilos += [("ALIGN", (1, 1), (-1, -1), "CENTER"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, self._GRIS])]

        h.extend(self._titulo("2.  CALIDAD TÉCNICA DE LA MANIOBRA"))
        h.append(self._tabla(filas, [w * .12, w * .18, w * .13, w * .12,
                                     w * .13, w * .13, w * .19],
                             estilo_extra=estilos))
        h.append(Spacer(1, 3))

        umbral = cal["pre"].umbral_aplicado or cal["post"].umbral_aplicado
        texto = (
            "Gradación A-F según el número de maniobras aceptables y la "
            f"repetibilidad entre las dos mejores (umbral aplicado: {umbral}). "
            "Los grados A y B corresponden a buena calidad, C a calidad "
            "suficiente, y D o inferiores no son útiles para interpretación. "
            "En un 10-20 % de los estudios no se obtienen maniobras de buena "
            "calidad pese al esfuerzo del técnico y la cooperación del paciente.")
        if a.get("repetibilidad_estricta"):
            texto += (" Se aplicaron los umbrales reducidos por tratarse de un "
                      "paciente ≤ 6 años o con FVC ≤ 1 L.")
        h.append(Paragraph(texto, self._estilos["nota"]))

        notas = [n for c in cal.values() for n in c.notas]
        obs = datos.get("observaciones_tecnico")
        if obs:
            notas.append(f"Observaciones del técnico: {obs}")
        if notas:
            h.append(Spacer(1, 3))
            for n in notas:
                h.append(Paragraph(f"— {n}", self._estilos["nota"]))

    def _bloque_valores(self, h: List[Any], datos: Dict[str, Any],
                        a: Dict[str, Any]) -> None:
        params: Dict[str, ResultadoParametro] = a["params"]
        hay_post = a["hay_post"]
        w = self._ancho_util()

        if hay_post:
            enc = ["Parámetro", "Predicho", "LIN", "Pre-BD", "% pred.",
                   "z pre", "Post-BD", "% pred.", "z post"]
            anchos = [w * .17, w * .10, w * .09, w * .10, w * .09,
                      w * .10, w * .10, w * .09, w * .10]
        else:
            enc = ["Parámetro", "Predicho", "LIN", "Medido", "% pred.", "z-score"]
            anchos = [w * .26, w * .15, w * .13, w * .15, w * .13, w * .18]

        filas = [enc]
        estilos: List[Tuple] = []
        claves = _ordenar(params.keys())

        for i, clave in enumerate(claves, start=1):
            p = params[clave]
            etiqueta = _ETIQUETAS.get(clave, clave)
            if p.unidad:
                etiqueta += f" ({p.unidad})"
            fila = [etiqueta, _f(p.pred), _f(p.lln), _f(p.pre),
                    _pct(p.pct_pred_pre), _fz(p.z_pre)]
            if hay_post:
                fila += [_f(p.post), _pct(p.pct_pred_post), _fz(p.z_post)]
            filas.append(fila)

            # Resaltado por posición respecto a los límites de normalidad.
            col_z_pre = 5
            col_z_post = 8
            if p.bajo_lin_pre:
                estilos += [("TEXTCOLOR", (3, i), (col_z_pre, i), self._ROJO),
                            ("FONTNAME", (3, i), (col_z_pre, i), "Helvetica-Bold")]
            elif p.sobre_lsn_pre:
                estilos += [("TEXTCOLOR", (3, i), (col_z_pre, i), self._AZUL)]
            if hay_post:
                if p.bajo_lin_post:
                    estilos += [("TEXTCOLOR", (6, i), (col_z_post, i), self._ROJO),
                                ("FONTNAME", (6, i), (col_z_post, i), "Helvetica-Bold")]
                elif p.sobre_lsn_post:
                    estilos += [("TEXTCOLOR", (6, i), (col_z_post, i), self._AZUL)]

            if clave in ("FVC", "FEV1", "FEV1/FVC"):
                estilos.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
            if clave in _FLUJOS and clave != "PEF":
                estilos.append(("TEXTCOLOR", (0, i), (0, i), self._GRIS_TXT))

        estilos += [("ALIGN", (1, 1), (-1, -1), "CENTER"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, self._GRIS])]

        h.append(KeepTogether(
            self._titulo("3.  VALORES ESPIROMÉTRICOS")
            + [self._tabla(filas, anchos, estilo_extra=estilos)]))
        h.append(Spacer(1, 3))

        estimado = any(p.z_estimado for p in params.values())
        nota = (
            "El límite inferior de la normalidad (LIN) corresponde al percentil 5, "
            "equivalente a un z-score de −1,645; el límite superior al percentil 95 "
            "(z = +1,645). Los valores por debajo del LIN se destacan en rojo. "
            "El porcentaje del predicho se informa por compatibilidad, pero los "
            "cortes fijos del 80 % del predicho y del 0,70 para el cociente "
            "FEV1/FVC están desaconsejados: el primero es arbitrario y el segundo "
            "no contempla el efecto de la edad, causando sobrediagnóstico en el "
            "anciano e infradiagnóstico en el adulto joven.")
        if estimado:
            nota += (" Los z-scores no suministrados por el motor de referencia "
                     "se derivaron analíticamente del predicho y el LIN mediante "
                     "z = (observado − predicho)·1,645/(predicho − LIN); "
                     "cuando el motor entrega el z real, éste tiene prioridad.")
        h.append(Paragraph(nota, self._estilos["nota"]))

        derivados = [k for k, p in params.items() if p.derivado]
        if derivados:
            h.append(Spacer(1, 2))
            h.append(Paragraph(
                "El cociente FEV1/FVC no fue suministrado por el equipo y se "
                "calculó a partir del FEV1 y la FVC. Su valor predicho se "
                "aproximó como el cociente de los predichos, pero su límite "
                "inferior de normalidad no es derivable de los LIN del numerador "
                "y el denominador, ya que la distribución del cociente posee "
                "dispersión propia en las ecuaciones de referencia. Sin ese LIN "
                "no puede afirmarse ni descartarse obstrucción.",
                self._estilos["nota"]))

        flujos = [k for k in claves if k in _FLUJOS and k != "PEF"]
        if flujos:
            h.append(Spacer(1, 2))
            h.append(Paragraph(
                "Los flujos mesoespiratorios (FEF25-75 y flujos instantáneos) se "
                "informan de forma descriptiva. Presentan alta variabilidad, baja "
                "reproducibilidad y escasa especificidad para enfermedad de la vía "
                "aérea pequeña, por lo que no se emplean para definir el patrón "
                "ventilatorio ni para graduar su severidad.", self._estilos["nota"]))

        # --- volúmenes estáticos, si existen -------------------------------
        vol: Dict[str, ResultadoParametro] = a["volumenes"]
        if vol:
            h.append(Spacer(1, 6))
            h.append(Paragraph("Volúmenes pulmonares estáticos",
                               self._estilos["subseccion"]))
            filas_v = [["Parámetro", "Predicho", "LIN", "Medido", "% pred.", "z-score"]]
            est_v: List[Tuple] = []
            for i, (clave, p) in enumerate(vol.items(), start=1):
                filas_v.append([
                    _ETIQUETAS.get(clave, clave) + (f" ({p.unidad})" if p.unidad else ""),
                    _f(p.pred), _f(p.lln), _f(p.pre),
                    _pct(p.pct_pred_pre), _fz(p.z_pre)])
                if p.bajo_lin_pre:
                    est_v += [("TEXTCOLOR", (3, i), (5, i), self._ROJO),
                              ("FONTNAME", (3, i), (5, i), "Helvetica-Bold")]
            est_v += [("ALIGN", (1, 1), (-1, -1), "CENTER"),
                      ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                       [colors.white, self._GRIS])]
            h.append(self._tabla(
                filas_v, [w * .26, w * .15, w * .13, w * .15, w * .13, w * .18],
                estilo_extra=est_v))

    def _bloque_bdr(self, h: List[Any], datos: Dict[str, Any],
                    a: Dict[str, Any]) -> None:
        if not a["hay_post"] or not a["bdr"]:
            return
        bd = datos.get("broncodilatador") or {}
        w = self._ancho_util()

        enc = ["Parámetro", "Pre-BD", "Post-BD", "Δ (mL)",
               "Δ % del predicho", "Criterio ERS/ATS 2022"]
        anchos = [w * .16, w * .12, w * .12, w * .13, w * .21, w * .26]
        if self.incluir_criterio_2005:
            enc.insert(5, "Δ % del basal")
            anchos = [w * .14, w * .10, w * .10, w * .11, w * .17, w * .14, w * .24]

        filas = [enc]
        estilos: List[Tuple] = []

        for i, clave in enumerate(("FVC", "FEV1"), start=1):
            r = a["bdr"].get(clave)
            if r is None:
                continue
            veredicto = ("Positiva" if r.positivo_2022 else "Negativa"
                         if r.positivo_2022 is not None else "—")
            fila = [r.parametro, _f(r.pre), _f(r.post), _mL_signed(r.delta_ml),
                    _pct_signed(r.pct_predicho)]
            if self.incluir_criterio_2005:
                fila.append(_pct_signed(r.pct_basal))
            fila.append(veredicto)
            filas.append(fila)
            col = self._VERDE if r.positivo_2022 else self._AMBAR
            estilos += [("TEXTCOLOR", (len(fila) - 1, i), (len(fila) - 1, i), col),
                        ("FONTNAME", (len(fila) - 1, i), (len(fila) - 1, i),
                         "Helvetica-Bold")]

        estilos += [("ALIGN", (1, 1), (-1, -1), "CENTER"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, self._GRIS])]

        h.extend(self._titulo("4.  PRUEBA BRONCODILATADORA"))
        if bd:
            piezas = [str(bd.get("farmaco", ""))]
            if bd.get("dosis_mcg"):
                piezas.append(f"{bd['dosis_mcg']:.0f} µg")
            if bd.get("via"):
                piezas.append(bd["via"])
            if bd.get("espera_min"):
                piezas.append(f"segunda espirometría a los {bd['espera_min']:.0f} min")
            h.append(Paragraph("Fármaco administrado: " +
                               " · ".join(x for x in piezas if x) + ".",
                               self._estilos["cuerpo"]))
            h.append(Spacer(1, 3))

        h.append(self._tabla(filas, anchos, estilo_extra=estilos))
        h.append(Spacer(1, 4))

        # Veredicto global
        pediatrico = a["pediatrico"]
        positiva = a["bdr_positiva_2022"]
        if pediatrico and a["bdr_positiva_pediatrica"] is not None:
            positiva_ped = a["bdr_positiva_pediatrica"]
            crit = next((r.criterio_pediatrico for r in a["bdr"].values()
                         if r.criterio_pediatrico), "")
            titulo = ("PRUEBA BRONCODILATADORA POSITIVA."
                      if positiva_ped else "PRUEBA BRONCODILATADORA NEGATIVA.")
            cuerpo = (
                f"Criterio pediátrico aplicado: {crit}. SEPAR/ALAT 2026 reconoce "
                "que la evidencia en población pediátrica es insuficiente para "
                "una recomendación única y admite tanto el 12 % sobre el valor "
                "basal como el 9-10 % sobre el predicho, exigiendo elegir un "
                "criterio y aplicarlo de forma consistente. Con el criterio "
                f"ERS/ATS 2022 (> 10 % del predicho) el resultado es "
                f"{'positivo' if positiva else 'negativo'}.")
            color, fondo = ((self._VERDE, self._VERDE_FONDO) if positiva_ped
                            else (self._AMBAR, self._AMBAR_FONDO))
        else:
            titulo = ("PRUEBA BRONCODILATADORA POSITIVA."
                      if positiva else "PRUEBA BRONCODILATADORA NEGATIVA.")
            cuerpo = (
                "Se aplica el criterio ERS/ATS 2022: cambio superior al 10 % del "
                "valor predicho en el FEV1 o en la FVC. Expresar la respuesta "
                "respecto al predicho, y no respecto al basal, elimina el sesgo "
                "por sexo, talla y función pulmonar de partida que afectaba al "
                "criterio de 1991 y 2005. El término reversibilidad se ha "
                "abandonado, ya que implica la eliminación completa de la "
                "obstrucción.")
            if self.incluir_criterio_2005:
                cuerpo += (" Con el criterio histórico ATS/ERS 2005 (≥ 12 % del "
                           "basal y ≥ 200 mL), aún empleado por GOLD y GINA, el "
                           f"resultado sería "
                           f"{'positivo' if a['bdr_positiva_2005'] else 'negativo'}.")
            color, fondo = ((self._VERDE, self._VERDE_FONDO) if positiva
                            else (self._AMBAR, self._AMBAR_FONDO))

        h.append(self._panel(titulo, cuerpo, color, fondo))
        h.append(Spacer(1, 3))
        h.append(Paragraph(
            "La respuesta broncodilatadora no permite por sí sola discriminar "
            "entre asma y EPOC ni establecer la eficacia definitiva de un "
            "broncodilatador. Su ausencia no descarta el asma.",
            self._estilos["nota"]))

    def _bloque_interpretacion(self, h: List[Any], datos: Dict[str, Any],
                               a: Dict[str, Any]) -> None:
        patron: ResultadoPatron = a["patron"]
        patron_pre: ResultadoPatron = a["patron_pre"]
        params = a["params"]
        h.extend(self._titulo("5.  INTERPRETACIÓN"))

        # 5.1 Patrón ------------------------------------------------------
        h.append(Paragraph("5.1  Patrón ventilatorio", self._estilos["subseccion"]))
        base_txt = ("los valores posbroncodilatador" if patron.base == "post-BD"
                    else "los valores basales")
        txt = (f"Aplicando el algoritmo interpretativo del ERS/ATS 2022 sobre "
               f"{base_txt}, el patrón es <b>{patron.etiqueta.upper()}</b>. "
               f"{patron.detalle}")
        h.append(Paragraph(txt, self._estilos["cuerpo"]))

        if (a["hay_post"] and patron.base == "post-BD"
                and patron_pre.etiqueta != patron.etiqueta
                and patron_pre.etiqueta != "No clasificable"):
            h.append(Paragraph(
                f"Sobre los valores basales el patrón era "
                f"<b>{patron_pre.etiqueta.lower()}</b>; la administración del "
                "broncodilatador modificó la clasificación, lo que debe hacerse "
                "constar de forma explícita.", self._estilos["cuerpo"]))

        if patron.requiere_volumenes:
            h.append(Paragraph(
                "La confirmación de este patrón exige la medición de volúmenes "
                "pulmonares estáticos: sólo una capacidad pulmonar total por "
                "debajo de su límite inferior de normalidad demuestra restricción. "
                "La espirometría aislada no permite establecer ese diagnóstico.",
                self._estilos["cuerpo"]))
        for b in patron.banderas:
            h.append(Paragraph(b, self._estilos["cuerpo"]))

        # 5.2 Severidad ---------------------------------------------------
        h.append(Paragraph("5.2  Severidad de la alteración funcional",
                           self._estilos["subseccion"]))
        if a.get("sospecha_via_central"):
            h.append(Paragraph(
                "No se gradúa la severidad mediante z-score. Ante sospecha de "
                "obstrucción de vía aérea central o superior este sistema no es "
                "aplicable, dado que una obstrucción potencialmente letal puede "
                "quedar clasificada como leve.", self._estilos["cuerpo"]))
        elif patron.severidad and patron.z_fev1 is not None:
            h.append(Paragraph(
                f"El z-score del FEV1 es de {patron.z_fev1:+.2f}, lo que "
                f"corresponde a una alteración funcional de grado "
                f"<b>{patron.severidad.lower()}</b> en el sistema de tres niveles "
                "del ERS/ATS 2022 (leve entre −1,645 y −2,5; moderada entre −2,5 "
                "y −4,0; grave por debajo de −4,0). Este sistema sustituye a la "
                "gradación por porcentaje del predicho y describe la desviación "
                "de la función pulmonar respecto a la población sana de "
                "referencia; no equivale a la gravedad de la enfermedad, que es "
                "una medida multidimensional e incluye síntomas, calidad de vida "
                "e imagen.", self._estilos["cuerpo"]))
        else:
            h.append(Paragraph(
                "No se dispone del z-score del FEV1, imprescindible para graduar "
                "la severidad con el sistema vigente.", self._estilos["cuerpo"]))

        # 5.3 Vía aérea central -------------------------------------------
        if a.get("texto_via_central"):
            h.append(Paragraph("5.3  Vía aérea central y superior",
                               self._estilos["subseccion"]))
            h.append(Paragraph(a["texto_via_central"], self._estilos["cuerpo"]))

        # 5.4 Flujos distales ---------------------------------------------
        distales = [k for k in params if k in _FLUJOS and k != "PEF"]
        if distales:
            h.append(Paragraph("5.4  Flujos mesoespiratorios",
                               self._estilos["subseccion"]))
            desc = []
            for k in ("FEF50", "FEF75", "FEF25-75"):
                p = params.get(k)
                if p and p.pct_pred_pre is not None:
                    desc.append(f"{_ETIQUETAS.get(k, k)} {p.pct_pred_pre:.0f} % "
                                f"del predicho")
            frase = ("Valores registrados: " + "; ".join(desc) + ". " if desc else "")
            h.append(Paragraph(
                frase +
                "Estos índices se consignan con finalidad descriptiva. Su elevada "
                "variabilidad intraindividual, su baja reproducibilidad y su falta "
                "de especificidad hacen que no deban utilizarse para diagnosticar "
                "enfermedad de la vía aérea pequeña ni para modificar la "
                "clasificación del patrón ventilatorio, especialmente cuando el "
                "FEV1 y el cociente FEV1/FVC se encuentran dentro del rango de "
                "referencia.", self._estilos["cuerpo"]))

        # 5.5 Cambio longitudinal -----------------------------------------
        if a.get("delta_z_seguimiento") is not None:
            dz = a["delta_z_seguimiento"]
            anios = a.get("anios_seguimiento")
            h.append(Paragraph("5.5  Evolución respecto al estudio previo",
                               self._estilos["subseccion"]))
            periodo = (f" en un intervalo de {anios:.1f} años" if anios else "")
            h.append(Paragraph(
                f"El z-score del FEV1 ha variado {dz:+.2f} unidades{periodo} "
                f"(de {a['patron'].z_fev1 - dz:+.2f} a "
                f"{a['patron'].z_fev1:+.2f}). Se informa la magnitud del "
                "cambio en unidades de desviación estándar, que es "
                "independiente del sexo y la talla y por tanto comparable a lo "
                "largo del seguimiento.", self._estilos["cuerpo"]))
            h.append(Paragraph(
                "No se aplica el «puntaje de cambio» del estándar. Su fórmula "
                "de correlación es lineal en la edad y supera la unidad por "
                "encima de los cincuenta años, y el puntaje resultante no "
                "reproduce el ejemplo publicado en el propio documento. Los "
                "autores reconocieron posteriormente que la sección sobre "
                "cambios naturales en el tiempo era limitada (Miller MR, et al. "
                "Eur Respir J 2023;61:2202025). La valoración de la "
                "significación del cambio queda al criterio clínico.",
                self._estilos["nota"]))

    def _bloque_conclusion(self, h: List[Any], datos: Dict[str, Any],
                           a: Dict[str, Any]) -> None:
        patron: ResultadoPatron = a["patron"]
        puntos: List[str] = []

        # 1. patrón + severidad
        p1 = f"Patrón ventilatorio <b>{patron.etiqueta.lower()}</b>"
        if patron.base == "post-BD":
            p1 += " (clasificado sobre valores posbroncodilatador)"
        if patron.severidad and not a.get("sospecha_via_central"):
            if patron.severidad.startswith("Sin alteración"):
                p1 += f", con FEV1 dentro de límites normales (z {patron.z_fev1:+.2f})"
            else:
                p1 += (f", con alteración funcional de grado "
                       f"<b>{patron.severidad.lower()}</b> "
                       f"(z del FEV1 {patron.z_fev1:+.2f})")
        puntos.append(p1 + ".")

        # 2. BDR
        if a["hay_post"] and a["bdr"]:
            pediatrico = a["pediatrico"]
            pos = (a["bdr_positiva_pediatrica"]
                   if pediatrico and a["bdr_positiva_pediatrica"] is not None
                   else a["bdr_positiva_2022"])
            crit = ("criterio pediátrico" if pediatrico else
                    "criterio ERS/ATS 2022, > 10 % del valor predicho")
            detalle = []
            for clave in ("FEV1", "FVC"):
                r = a["bdr"].get(clave)
                if r and r.pct_predicho is not None:
                    detalle.append(f"{r.parametro} {r.pct_predicho:+.1f} % del predicho")
            puntos.append(
                f"Prueba broncodilatadora <b>"
                f"{'positiva' if pos else 'negativa'}</b> ({crit})"
                + (f": {', '.join(detalle)}." if detalle else "."))

        # 3. confirmación pendiente
        if patron.requiere_volumenes:
            puntos.append(
                "Se requiere medición de volúmenes pulmonares estáticos "
                "(capacidad pulmonar total) para confirmar o descartar el "
                "componente restrictivo.")

        # 4. vía aérea central
        if a.get("sospecha_via_central"):
            puntos.append(
                f"Cociente FEV1/PEF de {a['indice_fev1_pef']:.1f} mL/L/min: "
                "debe descartarse obstrucción de vía aérea central o superior. "
                "La severidad no se gradúa por z-score en este contexto.")

        # 5. calidad
        no_interp = [c for c in a["calidad"].values()
                     if c.n_aceptables and not c.interpretable]
        if no_interp:
            puntos.append(
                "La calidad técnica alcanzada limita la fiabilidad de esta "
                "interpretación; se recomienda repetir el estudio.")

        # 6. discrepancia
        if a.get("discrepancia_equipo"):
            puntos.append(
                "Se corrigió la conclusión automática del equipo, que aplicaba "
                "un criterio distinto al vigente.")

        h.extend(self._titulo("6.  CONCLUSIÓN"))

        # Si el médico editó la conclusión en la interfaz, ese texto es el que
        # se emite: la clasificación automática pasa a figurar como respaldo
        # trazable, nunca por encima del criterio del profesional que firma.
        revisada = (datos.get("conclusion_revisada") or "").strip()
        if revisada:
            t = Table([[Paragraph(revisada, self._estilos["conclusion"])]],
                      colWidths=[self._ancho_util()])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), self._VERDE_FONDO),
                ("BOX", (0, 0), (-1, -1), 0.9, self._VERDE),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            h.append(t)
            h.append(Spacer(1, 4))
            h.append(Paragraph("Clasificación automática de respaldo",
                               self._estilos["subseccion"]))
            for i, texto in enumerate(puntos, start=1):
                h.append(Paragraph(f"{i}. {texto}", self._estilos["nota"]))
            h.append(Spacer(1, 3))
            h.append(Paragraph(
                "La conclusión emitida es la revisada y validada por el médico "
                "firmante. Los puntos anteriores reproducen la clasificación "
                "generada automáticamente con los criterios ERS/ATS 2022 y se "
                "conservan únicamente con fines de trazabilidad.",
                self._estilos["nota"]))
            return

        celdas = [[Paragraph(f"<b>{i}.</b>&nbsp;&nbsp;{t}",
                             self._estilos["conclusion"])]
                  for i, t in enumerate(puntos, start=1)]
        t = Table(celdas, colWidths=[self._ancho_util()])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), self._VERDE_FONDO),
            ("BOX", (0, 0), (-1, -1), 0.9, self._VERDE),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        h.append(t)
        h.append(Spacer(1, 3))
        h.append(Paragraph(
            "La interpretación de las pruebas de función pulmonar debe "
            "complementarse siempre con la valoración clínica. La espirometría "
            "por sí sola no diagnostica una entidad patológica concreta, y la "
            "variabilidad biológica intraindividual obliga a la cautela cuando "
            "los resultados se sitúan próximos a los puntos de corte.",
            self._estilos["nota"]))

    def _bloque_firma(self, h: List[Any], datos: Dict[str, Any],
                      a: Dict[str, Any]) -> None:
        pac = datos.get("paciente") or {}
        w = self._ancho_util()
        izq = [
            Paragraph(f"<b>{self.firmante}</b>", self._estilos["firma"]),
            Paragraph(self.credenciales, self._estilos["firma"]),
        ]
        if self.registro_medico:
            izq.append(Paragraph(self.registro_medico, self._estilos["firma"]))
        izq.append(Paragraph(self.laboratorio, self._estilos["firma"]))
        if self.institucion:
            izq.append(Paragraph(self.institucion, self._estilos["firma"]))

        der = [Paragraph(f"{self.ciudad}", self._estilos["firma"]) if self.ciudad
               else Spacer(1, 1),
               Paragraph(f"Fecha del estudio: {_fecha(pac.get('fecha_estudio'))}",
                         self._estilos["firma"])]
        if datos.get("n_reporte"):
            der.append(Paragraph(f"Informe n.º {datos['n_reporte']}",
                                 self._estilos["firma"]))

        t = Table([[izq, der]], colWidths=[w * 0.5, w * 0.5])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEABOVE", (0, 0), (0, 0), 0.8, colors.HexColor("#333333")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        h.append(Spacer(1, 20))
        h.append(KeepTogether(t))

    def _bloque_parametros_aplicados(self, h: List[Any]) -> None:
        """
        Tabla al pie con cada parámetro normativo empleado y su fuente exacta.
        Permite auditar el informe y reproducir la interpretación. [6]
        """
        w = self._ancho_util()
        filas = [["Parámetro / criterio", "Valor aplicado", "Fuente"]]
        for nombre, valor, fuente in PARAMETROS_APLICADOS:
            filas.append([
                Paragraph(f"<b>{nombre}</b>", self._estilos["celda"]),
                Paragraph(valor, self._estilos["celda"]),
                Paragraph(fuente, self._estilos["celda"]),
            ])
        estilos = [("ROWBACKGROUNDS", (0, 1), (-1, -1),
                    [colors.white, self._GRIS]),
                   ("VALIGN", (0, 0), (-1, -1), "TOP")]

        h.append(Spacer(1, 16))
        h.extend(self._titulo("7.  PARÁMETROS Y CRITERIOS APLICADOS"))
        h.append(self._tabla(filas, [w * .26, w * .43, w * .31],
                             estilo_extra=estilos))
        h.append(Spacer(1, 6))
        h.append(Paragraph(
            "<b>Referencias.</b>&nbsp; "
            "[1] Stanojevic S, Kaminsky DA, Miller MR, et al. ERS/ATS technical "
            "standard on interpretive strategies for routine lung function tests. "
            "Eur Respir J 2022;60:2101499. doi:10.1183/13993003.01499-2021. &nbsp; "
            "[2] Vukoja M, Franczuk M, Kivastik J. Interpretation. ERS Spirometry "
            "Resource Centre. channel.ersnet.org/media-113710-interpretation. &nbsp; "
            "[3] García-García R, Gimeno-Peribáñez MA, Albi-Rodríguez MS, et al. "
            "Recommendations for Performing Spirometry. Arch Bronconeumol 2026. "
            "doi:10.1016/j.arbres.2025.12.016. &nbsp; "
            "[4] Quanjer PH, Stanojevic S, Cole TJ, et al. Multi-ethnic reference "
            "values for spirometry for the 3-95-yr age range. Eur Respir J "
            "2012;40:1324-43. &nbsp; "
            "[5] Graham BL, Steenbruggen I, Miller MR, et al. Standardization of "
            "Spirometry 2019 Update. Am J Respir Crit Care Med 2019;200:e70-88. &nbsp; "
            "[6] Culver BH, Graham BL, Coates AL, et al. Recommendations for a "
            "standardized pulmonary function report. Am J Respir Crit Care Med "
            "2017;196:1463-72. &nbsp; "
            "[7] Quanjer PH, Pretto JJ, Brazzale DJ, Boros PW. Grading the severity "
            "of airways obstruction. Eur Respir J 2014;43:505-12.",
            self._estilos["nota"]))


# =============================================================================
# UTILIDADES DE FORMATO
# =============================================================================

def _num(v: Any) -> Optional[float]:
    """Convierte a float tolerando None, cadenas vacías, guiones y comas."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if isinstance(v, float) and _math.isnan(v) else float(v)
    s = str(v).strip().replace(",", ".")
    if s in ("", "-", "--", "—", "N/A", "NA", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _canon(clave: str) -> str:
    k = str(clave).strip().upper().replace(" ", "")
    k = k.replace("[L/S]", "").replace("[L]", "").replace("[%]", "")
    return _ALIAS.get(k, k)


def _unidad_por_defecto(clave: str) -> str:
    if clave in _COCIENTES:
        return "%"
    if clave in _FLUJOS:
        return "L/s"
    if clave in _VOLUMENES:
        return "L"
    return ""


def _ordenar(claves) -> List[str]:
    claves = list(claves)
    conocidas = [k for k in _ORDEN if k in claves]
    resto = sorted(k for k in claves if k not in _ORDEN)
    return conocidas + resto


def _f(v: Optional[float], dec: int = 2) -> str:
    return "—" if v is None else f"{v:.{dec}f}".replace(".", ",")


def _fz(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:+.2f}".replace(".", ",")


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.0f} %"


def _pct_signed(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:+.1f} %".replace(".", ",")


def _mL(v: Optional[float]) -> str:
    return "—" if v is None else f"{abs(v) * 1000:.0f}"


def _mL_signed(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:+.0f}"


def _sexo(v: Any) -> str:
    if v is None:
        return "—"
    s = str(v).strip().upper()
    if s in ("M", "MASCULINO", "MALE", "H", "HOMBRE"):
        return "Masculino"
    if s in ("F", "FEMENINO", "FEMALE", "MUJER"):
        return "Femenino"
    return str(v)


def _fecha(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.strftime("%d/%m/%Y")
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s


# =============================================================================
# EJEMPLO EJECUTABLE
# =============================================================================

if __name__ == "__main__":
    generador = InformeEspirometria(
        institucion="SALUD ES VIVIR IPS",
        laboratorio="Laboratorio de Función Pulmonar",
        ciudad="Medellín, Colombia",
        registro_lab="RM 1271040",
        firmante="Jefferson Antonio Buendía",
        credenciales="MD · Neumólogo Pediatra",
    )

    ejemplo = {
        "paciente": {
            "nombre": "Paciente de demostración",
            "documento": "00000000",
            "sexo": "M",
            "edad_anios": 57.0,
            "talla_cm": 160.0,
            "peso_kg": 52.0,
            "etnia": "Otro/Mixto",
            "tabaquismo": "Nunca fumador",
            "fecha_estudio": "2026-03-24",
            "posicion": "sedente",
        },
        "referencia": {"ecuacion": "GLI-2012", "grupo_etnico": "Otro/Mixto"},
        "broncodilatador": {"farmaco": "Salbutamol", "dosis_mcg": 400,
                            "via": "IDM con cámara espaciadora", "espera_min": 15},
        "parametros": {
            "FVC":      {"pred": 3.72, "lln": 3.04, "pre": 3.58, "post": 3.64},
            "FEV1":     {"pred": 2.95, "lln": 2.24, "pre": 2.26, "post": 2.54},
            "FEV1/FVC": {"pred": 79.0, "lln": 69.5, "pre": 63.11, "post": 69.77},
            "PEF":      {"pred": 7.05, "pre": 7.01, "post": 7.24},
            "FEF25":    {"pred": 6.47, "pre": 3.67, "post": 4.57},
            "FEF50":    {"pred": 3.32, "lln": 1.45, "pre": 1.48, "post": 1.91},
            "FEF75":    {"pred": 1.17, "lln": 0.43, "pre": 0.46, "post": 0.60},
            "FEF25-75": {"pred": 2.68, "lln": 1.26, "pre": 1.17, "post": 1.62},
        },
        "calidad": {
            "pre":  {"n_aceptables": 3, "dif_fvc_L": 0.11, "dif_fev1_L": 0.04},
            "post": {"n_aceptables": 3, "dif_fvc_L": 0.11, "dif_fev1_L": 0.04},
            "pef_definido": True,
        },
        "conclusion_equipo": "Bronchial dilation test is negative",
        "n_reporte": "ESP-2026-0324-000",
    }

    ruta = generador.generar_archivo(ejemplo, "informe_demo.pdf")
    print("PDF generado:", ruta)

    # El motor también puede usarse aislado, sin producir documento alguno:
    resumen = generador.analizar(ejemplo)
    print("Patrón:", resumen["patron"].etiqueta)
    print("Severidad:", resumen["patron"].severidad)
    print("BDR positiva (2022):", resumen["bdr_positiva_2022"])
