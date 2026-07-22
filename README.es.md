> 🌍 [Français](README.md) · [English](README.en.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · **Español** · [العربية](README.ar.md)

# RM → MNE: análisis de fuentes EEG corticales (FEM SimNIBS, nativo en Windows)

Pipeline completo que va de una **RM en DICOM** + un **registro EEG** a una
**estimación de fuentes corticales** con MNE-Python. Controlado en Python, se
ejecuta de forma nativa en Windows, **sin FreeSurfer, sin WSL, sin Docker**. (Una
ruta volumétrica BEM opcional se describe más abajo; esa sí usa WSL + FreeSurfer.)

El método está construido enteramente sobre librerías **consolidadas y citables**:
segmentación y forward **FEM** por **SimNIBS** (`charm`, `compute_tdcs_leadfield`,
`make_forward`), corregistro e inverso por **MNE-Python**. El código de este
repositorio es solo la orquestación entre ambos.

Cuente **~1,5 h por sujeto** para `charm` + **~20-40 min** para el leadfield FEM,
en lugar de las 10-20 h de `recon-all`.

---

## Entrada → salida, en una frase

**Se parte de** la RM anatómica del paciente en DICOM + el registro EEG (EDF u
otro) + la digitalización de los electrodos. **Se llega a** la estimación de
fuentes EEG sobre la **corteza**: la localización de la actividad medida, más un
morph a `fsaverage` para el análisis de grupo.

## Lo que produce el pipeline

Para cada sujeto, en `derivatives/<sujeto>/mne/`:

| Archivo | Contenido |
|---|---|
| `<sujeto>-trans.fif` | Corregistro cabeza ↔ RM |
| `<sujeto>-fwd.fif` | Forward **FEM** sobre el espacio de fuentes **cortical** (lh+rh) |
| `<sujeto>-noise-cov.fif` | Covarianza del ruido |
| `<sujeto>-inv.fif` | Operador inverso |
| `<sujeto>-lh.stc` / `-rh.stc` | **Estimación de fuentes cortical** — el entregable |
| `<sujeto>-morph.h5` | Morph a `fsaverage` (análisis de grupo) |

Dos niveles de uso:

* **`reconstruct_sources()`** (un sujeto, ver más abajo) va de la RM+EEG hasta la
  estimación de fuentes.
* **`run_pipeline.py`** (lote) encadena conversión → `charm` → corregistro →
  forward FEM para N sujetos; el inverso (que depende de los datos EEG) se hace
  luego mediante el wrapper.

---

## Ejemplo de extremo a extremo (carpeta `data/`)

El repositorio incluye un ejemplo listo para usar en [`data/`](data/README.en.md):
un paciente con RM DICOM + EEG + digitalización (más un segundo para el lote).

```
data/
  patient01/
    dicom/                 # serie RM T1w (DICOM)
    patient01_eeg.edf      # EEG
    patient01_dig.fif      # digitalización de los electrodos
    patient01-eve.fif      # eventos
  patient02/               # igual (para el lote)
  config.batch.yaml        # configuración de lote lista para usar
  README.md                # detalle de la estructura y la procedencia
```

**Procedencia de los archivos** (detalle en [data/README.en.md](data/README.en.md)):

| Archivo | Origen | Naturaleza |
|---|---|---|
| `dicom/` | Conjunto público `datalad/example-dicom-structural` (`PatientIdentityRemoved=YES`) | RM T1w real, **anonimizada** |
| `*_eeg.edf`, `*_dig.fif`, `*-eve.fif` | Conjunto `sample` de **MNE-Python** | EEG + digitalización de **otro** sujeto |
| `patient02/` | Copia de `patient01` | Solo para demostrar el lote |

> ⚠️ El EEG y la RM provienen de **sujetos diferentes**: son **sustitutos** para
> ilustrar la estructura de carpetas y los comandos. La cadena se ejecuta de
> principio a fin, pero **el resultado no tiene sentido clínico**. Para un sujeto
> real, el EEG y la digitalización deben provenir del **mismo** paciente que la RM.

### Ejecución simple — un paciente, salidas guardadas bajo el paciente

Superficie (FEM, nativo en Windows):

```python
from mri2mne.wrapper import reconstruct_sources

reconstruct_sources(
    subject="patient01",
    output_dir="data/patient01/surface",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- REEMPLAZAR con su ruta
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/surface/patient01/mne/patient01-lh.stc  (+ -rh.stc)
```

Volumétrico (BEM, vía WSL + FreeSurfer):

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="data/patient01/volumetric",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/volumetric/patient01/mne/patient01-vol-vl.stc
```

### Lote — varios pacientes, un comando

> **Antes de ejecutar**: edite [`data/config.batch.yaml`](data/config.batch.yaml)
> y reemplace `simnibs.bin_dir` (marcador `C:/Users/YOUR_NAME/...`) por la carpeta
> `Scripts` de su `simnibs_env`. `--check` lo verifica y señala un error claro si
> la ruta sigue siendo el marcador.

```powershell
python run_pipeline.py --config data/config.batch.yaml --check   # verifica herramientas + entradas
python run_pipeline.py --config data/config.batch.yaml
```

El campo `head_model` de la configuración (`fem` o `bem`) elige la ruta; las
salidas del lote van bajo `data/_batch_derivatives/`. El inverso EEG se hace luego
por sujeto con el wrapper correspondiente.

> El EEG/digitalización del ejemplo provienen de **otro** sujeto que la RM
> (sustitutos para la demo): la cadena se ejecuta, pero el resultado no tiene
> sentido clínico. Ver [data/README.en.md](data/README.en.md).

---

## Arquitectura: dos entornos

El pipeline usa **dos entornos conda**:

* **`irm2mne`** — controla todo (este repositorio). **Nunca** importa `simnibs`.
* **`simnibs_env`** — SimNIBS 4.6 + MNE. Ejecuta los pasos propios de SimNIBS,
  invocados como **subprocesos** por `irm2mne`.

Esto es lo que permite usar SimNIBS y MNE en sus versiones nativas sin conflicto
de dependencias (numpy en particular).

### Los pasos, y la librería detrás de cada uno

| # | Paso | Función | Librería |
|---|---|---|---|
| 1 | DICOM → NIfTI + anonimización + selección T1 | `dcm2niix`, `pydicom` | — |
| 2 | Segmentación + malla FEM + superficies corticales | `charm` | SimNIBS |
| 3a | Superficie del cuero cabelludo (para el ICP) | `mesh.crop_mesh` | SimNIBS |
| 3b | Fiduciales del sujeto | `read_csv_positions` | SimNIBS |
| 3c | Alineación fiducial + ICP | `Coregistration` | MNE |
| 4a | Montaje de electrodos → sujeto | `prepare_montage` | SimNIBS |
| 4b | Leadfield FEM (reciprocidad) | `compute_tdcs_leadfield` | SimNIBS |
| 4c | Conversión a `mne.Forward` (+ morph fsaverage) | `make_forward` | SimNIBS |
| 5 | EEG: lectura, filtrado, covarianza | `mne.io`, `compute_covariance` | MNE |
| 6 | Operador inverso + aplicación | `make_inverse_operator`, `apply_inverse` | MNE |

Marco de coordenadas: el mundo de la malla SimNIBS se trata como el marco "MRI" de
MNE, lo que permite reutilizar `Coregistration` sin conversión.

---

## Función wrapper: de la RM+EEG a las fuentes, en una llamada

```python
from mri2mne.wrapper import reconstruct_sources

result = reconstruct_sources(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # o t1_path="..." para un T1 listo
    eeg_file="D:/eeg/patient01.edf",         # .edf .bdf .vhdr .set .fif ...
    digitization="D:/dig/patient01.elc",     # posiciones de los electrodos
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- REEMPLAZAR con su ruta
    events="find",                            # detecta los triggers; o un array / -eve.fif
    event_id={"spike": 1},
    tmin=-0.2, tmax=0.5,
    inverse_method="dSPM",                    # o MNE / sLORETA / eLORETA
)

print(result.source_estimate_file)   # ...-lh.stc
print(result.peak)                    # pico: tiempo + hemisferio + posición (mm)
stc = result.stc                      # SourceEstimate cortical en memoria
```

Argumentos principales (los demás tienen valores por defecto razonables):

| Grupo | Argumentos |
|---|---|
| Anatomía | `dicom_dir` **o** `t1_path`, `t2_path` |
| EEG | `eeg_file`, `digitization` |
| SimNIBS | `simnibs_bin_dir` (carpeta Scripts de `simnibs_env`) |
| Forward FEM | `fem_subsampling` (fuentes corticales/hemisferio), `fem_cpus`, `morph_to_fsaverage` |
| Corregistro | `icp_iterations`, `omit_distance_mm` |
| Procesamiento EEG | `l_freq`, `h_freq`, `eeg_reference`, `events`, `event_id`, `tmin`, `tmax`, `baseline`, `reject`, `noise_cov_tmin/tmax` |
| Inverso | `inverse_method`, `snr` |

`reconstruct_sources()` nunca lanza una excepción ante un error de procesamiento:
devuelve un `SourceResult` con `status="failed"` y el mensaje, para seguir siendo
segura de llamar en un bucle. Las etapas ya calculadas se omiten (reanudación por
existencia de archivos; `force=[...]` para recalcular).

> Alternativa: un beamformer LCMV (`mne.beamformer.make_lcmv`) se usa a menudo en
> clínica; sería una extensión directa de `inverse.py`.

---

## Ruta alternativa: fuentes volumétricas (BEM, WSL2 + FreeSurfer)

Además de la ruta de superficie FEM (por defecto, 100% Windows), el repositorio
proporciona una **segunda ruta, volumétrica**, construida sobre el **BEM de 3
capas de FreeSurfer** — el método BEM estándar, reconocido en clínica. Las fuentes
llenan el volumen cerebral (rejilla 3D) en lugar de la corteza, y la salida es un
`VolSourceEstimate` (`-vl.stc`) que se lee como **superposición sobre la RM**
(cortes).

Las dos rutas son **independientes y complementarias** (marcos de coordenadas
distintos, archivos distintos). De nuevo, todo cálculo es una llamada de librería:
FreeSurfer `recon-all -autorecon1` / `mri_watershed`; MNE `make_bem_solution` /
`setup_volume_source_space` / `make_forward_solution` / `make_inverse_operator`.

### Requisitos previos: WSL2 + FreeSurfer

Como FreeSurfer es solo para Linux, esta ruta lo ejecuta dentro de **WSL2** (el
controlador permanece en Windows y lo invoca como subproceso, igual que SimNIBS).

```powershell
wsl --install            # WSL2 + Ubuntu, si aún no está presente
```

Luego, en la terminal Ubuntu, instale FreeSurfer 7.x mediante su **tarball**
(recomendado en Ubuntu 24.04):

```bash
sudo apt install -y tcsh          # requerido por los scripts de FreeSurfer
cd ~ && wget https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
sudo tar -C /usr/local -xzf freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
# licencia gratuita: https://surfer.nmr.mgh.harvard.edu/registration.html
cp /mnt/c/ruta/a/license.txt $FREESURFER_HOME/license.txt
```

Prevea ~20 GB para la instalación. Verifique desde Python:
`from mri2mne import wsl; print(wsl.check_freesurfer().describe())` debe mostrar
"... (licensed)".

### Uso

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

result = reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # o t1_path="..."
    eeg_file="D:/eeg/patient01.edf",
    digitization="D:/dig/patient01.elc",
    events="find", event_id={"spike": 1},
    pos_mm=5.0,                               # espaciado de la rejilla volumétrica
    inverse_method="dSPM", snr=3.0,
)
print(result.source_estimate_file)   # ...-vl.stc
```

Costo: **~20 min/sujeto** en un T1 limpio — no las horas de un `recon-all`
completo, que no es necesario aquí.

**En lote**, basta con poner `head_model: "bem"` en `config.yaml` (sección `bem:`
para los ajustes): `run_pipeline.py` enruta entonces los pasos
`headmodel`/`coreg`/`forward` hacia FreeSurfer/BEM en lugar de SimNIBS/FEM,
reutilizando la misma caché, el mismo `--check` (que verifica WSL + FreeSurfer) y
el mismo QC. El inverso EEG se hace luego mediante `reconstruct_sources_volumetric`.

### Advertencia: calidad de las superficies watershed

`mri_watershed` es **sensible a la calidad del T1**. En un T1 de investigación
limpio (1 mm) produce superficies cerradas y anidadas; en algunas adquisiciones
clínicas atípicas (FOV grande, contraste inusual) el cráneo puede
autointersecarse. El pipeline **detecta y señala** este caso
(`volumetric.check_bem_surfaces`) con un mensaje claro en lugar de fallar — el
sujeto necesita entonces un QC de superficies o un T1 más limpio. Para una corteza
3D nítida en la visualización, prefiera la **ruta de superficie** (esa es su
vocación).

---

## Instalación

### 1. `simnibs_env` — SimNIBS 4 (proporciona `charm` + el solver FEM)

Método por línea de comandos (validado aquí, sin clics):

```powershell
curl -L -o environment_windows.yml https://github.com/simnibs/simnibs/releases/download/v4.6.0/environment_windows.yml
conda env create -f environment_windows.yml
conda activate simnibs_env
pip install https://github.com/simnibs/simnibs/releases/download/v4.6.0/simnibs-4.6.0-cp311-cp311-win_amd64.whl
pip install "mne>=1.6"     # requerido para make_forward (salida MNE)
```

Verifique: `charm --version` debe mostrar `4.6.0`. La carpeta
`…\envs\simnibs_env\Scripts` es la que se pasa a `simnibs_bin_dir`. (El instalador
gráfico oficial de <https://simnibs.github.io> también funciona; entonces hay que
hacer `pip install mne` en su Python.)

### 2. `irm2mne` — el entorno que controla

```powershell
conda env create -f environment.yml
conda activate irm2mne
```

### 3. Configuración

```powershell
copy config.example.yaml config.yaml
```

Edite `config.yaml`: rutas de los datos, `simnibs.bin_dir` (la carpeta `Scripts`
de `simnibs_env`) y la plantilla `paths.digitisation`.

### 4. (Opcional) Instalar como paquete pip

El repositorio es un paquete instalable (`pyproject.toml`, layout `src/`). Es la
forma más simple de desplegarlo **sin WSL**: la ruta de superficie FEM y el lote
solo dependen de librerías de PyPI. Desde la raíz del repositorio:

```powershell
pip install .                # instala el paquete + sus dependencias
pip install ".[viz]"         # + PyVista/VTK (QC 3D + visor de fuentes)
pip install ".[all]"         # + dcm2niix (binario) + pytest
pip install -e ".[dev]"      # modo desarrollo (editable) + pytest
```

Después de la instalación:

```python
from mri2mne.wrapper import reconstruct_sources   # importable en cualquier lugar
```

y el comando de lote está disponible directamente (ya no hace falta
`run_pipeline.py`):

```powershell
mri2mne --config config.yaml --check
mri2mne --config config.yaml
```

Lo que la instalación pip **no** cubre, por diseño:

* **SimNIBS** (`charm` + solver FEM) permanece en su propio `simnibs_env`,
  invocado como subproceso (ver §1) — nunca instalado en el mismo entorno que el
  controlador (conflicto numpy).
* La **ruta volumétrica BEM** requiere **FreeSurfer en WSL2** (requisito de
  sistema, ver arriba); no añade ninguna dependencia Python. La ruta de
  superficie, en cambio, se instala y funciona **enteramente sin WSL**.

> `pip install .` sigue siendo posible incluso sin SimNIBS ni WSL: la biblioteca
> se importa y las pruebas pasan; solo los pasos que realmente invocan
> `charm`/FreeSurfer requieren esas herramientas en tiempo de ejecución.

---

## Uso en lote

```powershell
# Verificación previa: herramientas, archivos de cada sujeto, espacio en disco
python run_pipeline.py --config config.yaml --check

# Procesar a todos
python run_pipeline.py --config config.yaml

# Un subconjunto
python run_pipeline.py --config config.yaml --subjects sub-001 sub-002

# Reejecutar algunas etapas tras un cambio
python run_pipeline.py --config config.yaml --force coreg forward
```

Organización esperada:

```
dicom_root/
  sub-001/            <- una carpeta por sujeto, DICOM dentro (recursivo)
digitisation/
  sub-001_electrodes.elc
```

Formatos de digitalización reconocidos: `.fif`, `.hsp`/`.elp` (Polhemus), `.bvct`
(CapTrak), `.sfp`, `.elc`, `.hpts`, `.csd`, `.xyz`. Formatos EEG: `.edf`, `.bdf`,
`.vhdr` (BrainVision), `.set` (EEGLAB), `.fif`, `.mff`, `.eeg`.

### Reanudación y caché

Cada etapa registra una huella de sus entradas en
`derivatives/<sujeto>/status.json`. Reejecutar solo recalcula lo que cambió — y
sobre todo no reejecuta las ~1,5 h de `charm` innecesariamente.

### Tolerancia a fallos

`continue_on_error` protege contra las excepciones; y si un **proceso** worker
muere (típicamente el OOM killer sobre `charm`, 4-8 GB), el lote lo detecta y
**reejecuta en secuencial** en lugar de perderlo todo. La verdadera solución sigue
siendo bajar `run.n_jobs`.

---

## Control de calidad

Un informe HTML por sujeto (`derivatives/<sujeto>/qc/`) y un resumen de lote, con
las métricas, el residuo del corregistro y la figura de alineación 3D.

**Mire la alineación electrodos/cuero cabelludo antes de explotar los
resultados.** Un residuo dig→cuero cabelludo bajo no garantiza un buen ajuste:
sobre un cuero cabelludo liso, el ICP puede deslizarse un centímetro manteniendo
los puntos cerca de la superficie. Lo que fija el ajuste son los fiduciales — que
`charm` proporciona en espacio del sujeto.

Retoma manual de un sujeto señalado:

```powershell
conda activate irm2mne
mne coreg --subject sub-001 --subjects-dir D:\data\derivatives\subjects
```

Guarde los fiduciales corregidos en
`subjects/<sujeto>/bem/<sujeto>-fiducials.fif`, luego reejecute con
`--force coreg forward`.

---

## Visualización de las fuentes

El espacio de fuentes proviene de SimNIBS (la superficie cortical *central*), no de
FreeSurfer — pero `stc.plot()` de MNE espera un árbol
`subjects_dir/<sujeto>/surf/lh.white`. El módulo `mri2mne.viz` hace de **puente**:
escribe una vez la malla SimNIBS (`-src.fif`) en formato FreeSurfer, tras lo cual
**todo el instrumental 3D nativo de MNE** (ventana rotable con el ratón, deslizador
temporal, películas, cursos temporales por ROI) funciona tal cual. Es MNE + SimNIBS,
por tanto citable, sin código de renderizado casero.

**Ventana interactiva** (rotar/zoom/tiempo con el ratón), desde un script:

```powershell
conda activate irm2mne
python examples/open_source_viewer.py D:/derivatives patient01 --time 0.1
```

o en Python:

```python
from mri2mne.viz import open_viewer, block_on_viewer
brain = open_viewer("D:/derivatives", "patient01", initial_time=0.1)
block_on_viewer()   # mantiene la ventana abierta hasta que se cierra
```

**Figura estática** (renderizado *offscreen*, para un informe o una máquina sin
pantalla):

```python
from pathlib import Path
from mri2mne.paths import SubjectPaths
from mri2mne.viz import save_views

paths = SubjectPaths("patient01", Path("D:/derivatives"),
                     Path("D:/derivatives/subjects"))
save_views(paths, "patient01_sources.png", initial_time=0.1,
           views=("lateral", "medial", "dorsal"), hemi="lh")
```

La API: `write_freesurfer_surfaces(paths)` (el puente, idempotente),
`plot_sources(paths, ...)` (devuelve un `mne.viz.Brain`), `open_viewer(...)`
(atajo desde `output_dir`+`subject`), `save_views(...)` (PNG multivista).

> `surface="inflated"` es idéntico a `white` (SimNIBS no infla las superficies).
> Para el cerebro *inflado* liso estándar, haga morph a `fsaverage`
> (`morph_to_fsaverage`) y luego grafique con `subject="fsaverage"`.

---

## Lo que se ha validado

Pipeline ejecutado **de extremo a extremo mediante el wrapper público** sobre el
conjunto `sample` de MNE (anatomía real, EEG real en EDF), `status: ok`:

| Control | Resultado |
|---|---|
| Corregistro (marco de malla, MNE) | residuo mediano **1,85 mm** |
| Forward FEM | **10000 fuentes corticales × 60 canales**, ganancia finita |
| EEG | 17 épocas auditivas izquierdas promediadas (EDF) |
| Inverso dSPM | operador + estimación OK |
| Salida | `sample-lh.stc` / `-rh.stc` |
| Pico (estim. auditiva izquierda) | **hemisferio izquierdo**, lateral (−55, −35, 34) mm |

El pico es lateral izquierdo, anatómicamente plausible para una respuesta
auditiva.

**También validado sobre un DICOM clínico real** (serie T1w, 384 cortes, 0,7 mm):
la cadena completa `reconstruct_sources(dicom_dir=...)` — anonimización →
conversión → `charm` sobre el T1 del DICOM → malla → corregistro → leadfield FEM →
dSPM — se ejecuta sin contratiempos, `status: ok`, salida cortical `-lh/-rh.stc`.
El EEG usado era deliberadamente ajeno (validación de la *fontanería*, no de la
localización). Tiempo de cálculo **neto** medido en esta máquina (mono-hilo):
`charm` ≈ 2 h sobre este T1 de alta resolución, leadfield FEM ≈ 18 min, el resto
< 1 min.

**No validado por falta de datos:** un par DICOM + **digitalización real**
(Polhemus/CapTrak) del **mismo** sujeto. Haga una primera pasada sobre **un
sujeto** antes del lote.

Para reproducir la validación (requiere una salida `charm`):

```powershell
python examples/run_full_pipeline_sample.py <ruta-a-m2m_sampleE2E> <scratch>
```

---

## Limitaciones a conocer

**Dos marcos de fuentes según la ruta.** La ruta FEM (por defecto) coloca las
fuentes sobre la superficie cortical (materia gris media, lh+rh); la ruta BEM
(`head_model: bem`) las coloca en el volumen. Ambas son métodos documentados y
publicables; elija según su análisis.

**El corregistro es el eslabón débil, no la anatomía.** Con una digitalización
cuidadosa y una verificación visual de la alineación, se está bien. Sin
digitalización, la precisión cae.

**Una imagen T2 mejora el cráneo.** Si sus protocolos incluyen una, indique
`simnibs.t2_template`.

**Costo de cálculo.** El leadfield FEM resuelve un sistema por electrodo sobre una
malla de ~800k nodos. Para 60-256 electrodos, cuente 20 min a ~2 h. En Windows, el
solver corre en un solo proceso (`fem.cpus` forzado a 1: la paralelización de
SimNIBS no es picklable con el `spawn` de Windows).

---

## Pruebas

```powershell
conda activate irm2mne
pytest tests -q
```

Las pruebas cubren la configuración, la ingesta DICOM (scorer de series), la
lectura EEG / el montaje, la localización del pico, las verificaciones previas, la
validación de los argumentos del wrapper y el puente SimNIBS→FreeSurfer de la
visualización. Las etapas pesadas (charm, leadfield FEM) se validan con
`examples/run_full_pipeline_sample.py` sobre datos reales.

---

## Estructura

```
run_pipeline.py            Punto de entrada CLI del lote
config.example.yaml        Configuración comentada
environment.yml            Entorno irm2mne (controlador)
src/mri2mne/
  config.py                Carga y validación YAML
  paths.py                 Árbol del sujeto + caché de etapas
  anonymize.py             PHI DICOM + defacing opcional
  dicom_convert.py         DICOM → NIfTI + selección de la serie T1
  headmodel.py             Wrapper de charm
  coregistration.py        Digitalización + ICP (MNE Coregistration)
  simnibs_mesh.py          Extracción de cuero cabelludo + fiduciales de la malla (controlador)
  simnibs_forward.py       Forward FEM SimNIBS (controlador)
  _simnibs_fem_helper.py   Leadfield + make_forward (corre en simnibs_env)
  _simnibs_mesh_helper.py  crop_mesh + fiduciales (corre en simnibs_env)
  eeg.py                   Lectura EEG, preprocesamiento, covarianza
  inverse.py               Operador inverso + estimación de fuentes (superficie)
  viz.py                   Puente SimNIBS→FreeSurfer + visualización 3D MNE
  wsl.py                   Puente WSL2 (ruta volumétrica): rutas, ejecutor, sonda
  freesurfer_bem.py        autorecon1 + watershed vía WSL (ruta volumétrica)
  volumetric.py            BEM 3 capas + espacio de fuentes + forward/inverso volumétricos
  wrapper.py               reconstruct_sources[/_volumetric]() : RM+EEG -> fuentes
  preflight.py             Verificaciones antes de lanzar el lote
  qc.py                    Informes HTML
  pipeline.py              Orquestación por sujeto (lote)
  batch.py                 Descubrimiento de sujetos + paralelismo
examples/
  run_full_pipeline_sample.py   Validación de extremo a extremo de superficie sobre datos reales
  run_volumetric_sample.py      Ruta volumétrica (BEM/WSL) de extremo a extremo
  open_source_viewer.py         Ventana 3D interactiva para un sujeto procesado
```
