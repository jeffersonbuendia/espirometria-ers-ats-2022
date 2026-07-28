# Informe de espirometría — ERS/ATS 2022

Aplicación web en **Streamlit** que carga un reporte espirométrico en PDF,
extrae los datos, permite validarlos manualmente y genera un informe conforme
a los estándares interpretativos vigentes.

## Estándares aplicados

| Aspecto | Criterio | Fuente |
|---|---|---|
| Ecuaciones de referencia | GLI-2012 (3-95 años) | Quanjer 2012; SEPAR/ALAT 2026 Tabla 11 |
| Normalidad | z-score < −1,645 (percentil 5) | ERS/ATS 2022 |
| Obstrucción | FEV1/FVC < LIN | ERS/ATS 2022 |
| Severidad | z(FEV1): leve −1,645 a −2,5 · moderada −2,5 a −4,0 · grave < −4,0 | ERS/ATS 2022 |
| Respuesta broncodilatadora | cambio > 10 % del valor **predicho** en FEV1 o FVC | ERS/ATS 2022 |
| Restricción | requiere TLC < LIN; sin ella se informa PRISm | ERS/ATS 2022 |
| Calidad técnica | gradación A-F | ATS/ERS 2019; SEPAR/ALAT 2026 Tabla 10 |

**No se emplean** los cortes fijos del 80 % del predicho ni del 0,70 para el
cociente FEV1/FVC: el primero es arbitrario y el segundo no contempla el efecto
de la edad, causando sobrediagnóstico en el anciano e infradiagnóstico en el
adulto joven.

### Referencias

1. Stanojevic S, Kaminsky DA, Miller MR, et al. ERS/ATS technical standard on
   interpretive strategies for routine lung function tests.
   *Eur Respir J* 2022;60:2101499. doi:10.1183/13993003.01499-2021
2. Vukoja M, Franczuk M, Kivastik J. Interpretation. ERS Spirometry Resource Centre.
3. García-García R, Gimeno-Peribáñez MA, Albi-Rodríguez MS, et al. Recommendations
   for Performing Spirometry. *Arch Bronconeumol* 2026. doi:10.1016/j.arbres.2025.12.016
4. Quanjer PH, Stanojevic S, Cole TJ, et al. Multi-ethnic reference values for
   spirometry for the 3-95-yr age range. *Eur Respir J* 2012;40:1324-43.
5. Graham BL, Steenbruggen I, Miller MR, et al. Standardization of Spirometry
   2019 Update. *Am J Respir Crit Care Med* 2019;200:e70-88.
6. Culver BH, Graham BL, Coates AL, et al. Recommendations for a standardized
   pulmonary function report. *Am J Respir Crit Care Med* 2017;196:1463-72.
7. Quanjer PH, Pretto JJ, Brazzale DJ, Boros PW. Grading the severity of airways
   obstruction. *Eur Respir J* 2014;43:505-12.

## Funciones

- Extrae automáticamente datos demográficos, FEV1/FVC, FVC, FEV1 y FEF25-75 con
  sus valores predichos, LIN, z-score y resultados posbroncodilatador, además de
  la gradación de calidad A-F de cada serie.
- Permite editar todos los campos antes de emitir el informe. Los campos vacíos
  se tratan como ausentes, no como cero.
- Clasifica los siete patrones del algoritmo ERS/ATS 2022: normal, obstructivo,
  restrictivo, mixto, obstructivo con atrapamiento aéreo, inespecífico/PRISm y
  disanapsis; el patrón se determina sobre los valores posbroncodilatador.
- Detecta sospecha de obstrucción de vía aérea central (FEV1/PEF > 8 mL/L/min y
  cociente FIF50/FEF50) y suprime la gradación de severidad en ese contexto.
- Contrasta el resultado con la conclusión automática del espirómetro y deja
  constancia explícita cuando discrepan.
- Genera un PDF con datos del paciente, calidad técnica, valores con z-score,
  prueba broncodilatadora, interpretación, conclusión, firma y una tabla final
  con los parámetros normativos aplicados y su fuente exacta.
- Anexa como última página la primera hoja del reporte original.
- Si el médico edita la conclusión, el PDF emite su texto y conserva la
  clasificación automática como respaldo trazable.

## Arquitectura

```
app.py                   Interfaz Streamlit: revisión y corrección
        ↓
interpretation.py        Adapta los modelos al motor normativo
        ↓
pdf_report.py            Construye el diccionario del informe
        ↓
informe_espirometria.py  Motor ERS/ATS 2022 + generación del PDF
        ↓
                         Anexa la hoja original del espirómetro
```

`informe_espirometria.py` es autónomo y puede importarse en cualquier proyecto:

```python
from informe_espirometria import InformeEspirometria, EstandaresERS2022

generador = InformeEspirometria(
    institucion="SALUD ES VIVIR IPS",
    firmante="Jefferson Antonio Buendía",
    credenciales="MD · Neumólogo Pediatra",
)

pdf = generador.generar(datos)          # -> bytes
analisis = generador.analizar(datos)    # sólo interpretación, sin PDF
```

El motor no calcula ecuaciones de referencia: recibe predicho, LIN y z-score.
Si sólo se dispone de predicho y LIN, estima el z-score analíticamente. Para
acoplar un motor GLI propio basta con pasar `proveedor_referencia=funcion`
al constructor.

## Alcance y limitaciones

La extracción automática está optimizada para reportes con estructura similar a
**Pneumotrac / Vitalograph**. Otros formatos requieren corrección manual o un
parser específico. Cuando faltan FEV1/FVC, FVC o FEV1 la aplicación lo advierte
de forma explícita en lugar de emitir una conclusión silenciosamente vacía.

El **puntaje de cambio longitudinal** del estándar no se aplica. Su fórmula de
correlación (`r = 0,642 − 0,04·t + 0,020·edad`) es lineal en la edad y supera la
unidad por encima de los cincuenta años, y el puntaje resultante no reproduce el
ejemplo publicado en el propio documento; los autores reconocieron después que
esa sección era limitada (Miller MR, et al. *Eur Respir J* 2023;61:2202025). En
su lugar se informa la diferencia de z-scores entre estudios.

La aplicación **no sustituye la revisión del médico**. Los valores extraídos, la
calidad técnica y la conclusión deben verificarse antes de emitir el informe.

## Instalación local

```bash
git clone <URL-DE-ESTE-REPOSITORIO>
cd <CARPETA-DEL-REPOSITORIO>

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
streamlit run app.py
```

La app se abre en `http://localhost:8501`.

## Pruebas

```bash
pytest
```

41 pruebas que cubren los siete patrones ventilatorios, la gradación de
severidad por z-score, la discrepancia entre los criterios de respuesta
broncodilatadora de 2005 y 2022, el umbral pediátrico, la gradación de calidad
A-F y los casos en que el estándar exige abstenerse de clasificar.

## Privacidad

Los reportes espirométricos contienen datos personales y datos de salud.

- **Use un repositorio privado** para uso clínico real.
- No suba PDFs de pacientes. El `.gitignore` excluye `*.pdf` como medida de
  contención, pero no sustituye a la revisión antes de cada commit.
- Implemente autenticación, control de acceso, cifrado y políticas de retención.
- Revise las condiciones del servicio de la plataforma de despliegue.
- Considere un despliegue institucional o local si los documentos identificables
  no pueden alojarse en servicios externos.

## Estructura

```
.
├── app.py                     Interfaz Streamlit
├── parser.py                  Extracción del PDF del espirómetro
├── models.py                  Modelos de dominio
├── interpretation.py          Adaptador al motor normativo
├── informe_espirometria.py    Motor ERS/ATS 2022 + generador de PDF
├── pdf_report.py              Ensamblado y anexado del reporte original
├── requirements.txt
├── .gitignore
├── .streamlit/config.toml
└── tests/
    ├── conftest.py
    └── test_interpretation.py
```

## Aviso clínico

Herramienta de apoyo a la elaboración de informes. No realiza diagnóstico
autónomo y no reemplaza la interpretación clínica, la revisión de la calidad de
las maniobras ni la confirmación de restricción mediante volúmenes pulmonares.

## Licencia

MIT. Ver [LICENSE](LICENSE).
