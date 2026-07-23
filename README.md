> 🌍 **Français** · [English](README.en.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [Español](README.es.md) · [العربية](README.ar.md)

# IRM → MNE : analyse de sources EEG corticale (FEM SimNIBS, Windows natif)

Pipeline complet allant d'un **IRM en DICOM** + un **enregistrement EEG** à
l'**estimation de sources corticale** avec MNE-Python. Piloté en Python,
exécutable nativement sous Windows, **sans FreeSurfer, sans WSL, sans Docker**.
(Une route volumique BEM optionnelle est décrite plus bas ; elle, utilise WSL +
FreeSurfer.)

La méthode est entièrement bâtie sur des librairies **établies et citables** :
segmentation et forward **FEM** par **SimNIBS** (`charm`, `compute_tdcs_leadfield`,
`make_forward`), coregistration et inverse par **MNE-Python**. Le code de ce dépôt
n'est que l'orchestration entre les deux.

Compter **~1h30 par sujet** pour `charm` + **~20-40 min** pour le leadfield FEM,
au lieu des 10-20 h de `recon-all`.

> 📚 **Tutoriels illustrés** — pas-à-pas, avec la figure de **chaque étape**
> (T1, segmentation des tissus, EEG, réponse évoquée, coregistration 3D, sources
> sur le cortex) : **[maximebedoin.github.io/mri2mne/tutorials](https://maximebedoin.github.io/mri2mne/tutorials/)**
> (une fois **GitHub Pages** activé). Sinon, ouvrez `docs/tutorials/index.html` en local.

---

## Entrée → sortie, en une phrase

**On part de** l'IRM anatomique du patient en DICOM + l'enregistrement EEG (EDF
ou autre) + la digitalisation des électrodes. **On arrive à** l'estimation de
sources EEG sur le **cortex** : la localisation de l'activité mesurée, avec en
prime un morph vers `fsaverage` pour l'analyse de groupe.

## Ce que le pipeline produit

Pour chaque sujet, dans `derivatives/<sujet>/mne/` :

| Fichier | Contenu |
|---|---|
| `<sujet>-trans.fif` | Corecalage tête ↔ IRM |
| `<sujet>-fwd.fif` | Forward **FEM** sur l'espace de sources **cortical** (lh+rh) |
| `<sujet>-noise-cov.fif` | Covariance du bruit |
| `<sujet>-inv.fif` | Opérateur inverse |
| `<sujet>-lh.stc` / `-rh.stc` | **Estimation de sources corticale** — le livrable |
| `<sujet>-morph.h5` | Morph vers `fsaverage` (analyse de groupe) |

Deux niveaux d'usage :

* **`reconstruct_sources()`** (un sujet, voir plus bas) va de l'IRM+EEG jusqu'à
  l'estimation de sources.
* **`run_pipeline.py`** (lot) enchaîne conversion → `charm` → coreg → forward FEM
  pour N sujets ; l'inverse (dépendant des données EEG) se fait ensuite via le
  wrapper.

---

## Exemple de bout en bout (dossier `data/`)

Le dépôt inclut un exemple prêt à l'emploi dans [`data/`](data/README.md) : un
patient avec IRM DICOM + EEG + digitalisation (plus un second pour le lot).

```
data/
  patient01/
    dicom/                 # série IRM T1w (DICOM)
    patient01_eeg.edf      # EEG
    patient01_dig.fif      # digitalisation des électrodes
    patient01-eve.fif      # événements
  patient02/               # idem (pour le lot)
  config.batch.yaml        # config de lot prête à l'emploi
  README.md                # détail de la structure et de la provenance
```

**Provenance des fichiers** (détail dans [data/README.md](data/README.md)) :

| Fichier | Origine | Nature |
|---|---|---|
| `dicom/` | Jeu public `datalad/example-dicom-structural` (`PatientIdentityRemoved=YES`) | IRM T1w réelle, **anonymisée** |
| `*_eeg.edf`, `*_dig.fif`, `*-eve.fif` | Jeu `sample` de **MNE-Python** | EEG + digitalisation d'un **autre** sujet |
| `patient02/` | Copie de `patient01` | Uniquement pour démontrer le lot |

> ⚠️ L'EEG et l'IRM viennent de **sujets différents** : ce sont des **substituts**
> pour illustrer la structure des dossiers et les commandes. La chaîne tourne
> jusqu'au bout, mais **le résultat n'a aucun sens clinique**. Pour un vrai sujet,
> l'EEG et la digitalisation doivent provenir du **même** patient que l'IRM.

### Run simple — un patient, sorties rangées sous le patient

Surfacique (FEM, Windows natif) :

```python
from mri2mne.wrapper import reconstruct_sources

reconstruct_sources(
    subject="patient01",
    output_dir="data/patient01/surface",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    simnibs_bin_dir="C:/Users/moi/Miniconda3/envs/simnibs_env/Scripts",  # <- REMPLACER par votre chemin
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/surface/patient01/mne/patient01-lh.stc  (+ -rh.stc)
```

Volumique (BEM, via WSL + FreeSurfer) :

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

### Lot — plusieurs patients, une commande

> **Avant de lancer** : éditer [`data/config.batch.yaml`](data/config.batch.yaml)
> et remplacer `simnibs.bin_dir` (placeholder `C:/Users/VOTRE_NOM/...`) par le
> dossier `Scripts` de votre `simnibs_env`. `--check` le vérifie et signale une
> erreur claire si le chemin est encore le placeholder.

```powershell
python run_pipeline.py --config data/config.batch.yaml --check   # vérifie outils + entrées
python run_pipeline.py --config data/config.batch.yaml
```

Le champ `head_model` du config (`fem` ou `bem`) choisit la route ; les sorties
du lot vont sous `data/_batch_derivatives/`. L'inverse EEG se fait ensuite par
sujet avec le wrapper correspondant.

> L'EEG/digitalisation de l'exemple viennent d'un **autre** sujet que l'IRM
> (substituts pour la démo) : la chaîne tourne, mais le résultat n'a pas de sens
> clinique. Voir [data/README.md](data/README.md).

---

## Architecture : deux environnements

Le pipeline utilise **deux environnements conda** :

* **`mri2mne`** — pilote tout (ce dépôt). N'importe **jamais** `simnibs`.
* **`simnibs_env`** — SimNIBS 4.6 + MNE. Exécute les étapes propres à SimNIBS,
  appelées en **sous-processus** par `mri2mne`.

C'est ce qui permet d'utiliser SimNIBS et MNE dans leurs versions natives sans
conflit de dépendances (numpy notamment).

### Les étapes, et la librairie derrière chacune

| # | Étape | Fonction | Librairie |
|---|---|---|---|
| 1 | DICOM → NIfTI + anonymisation + sélection T1 | `dcm2niix`, `pydicom` | — |
| 2 | Segmentation + maillage FEM + surfaces corticales | `charm` | SimNIBS |
| 3a | Surface de scalp (pour l'ICP) | `mesh.crop_mesh` | SimNIBS |
| 3b | Fiduciaux sujet | `read_csv_positions` | SimNIBS |
| 3c | Alignement fiduciaire + ICP | `Coregistration` | MNE |
| 4a | Montage électrodes → sujet | `prepare_montage` | SimNIBS |
| 4b | Leadfield FEM (réciprocité) | `compute_tdcs_leadfield` | SimNIBS |
| 4c | Conversion en `mne.Forward` (+ morph fsaverage) | `make_forward` | SimNIBS |
| 5 | EEG : lecture, filtrage, covariance | `mne.io`, `compute_covariance` | MNE |
| 6 | Opérateur inverse + application | `make_inverse_operator`, `apply_inverse` | MNE |

Repère de coordonnées : le monde du maillage SimNIBS est traité comme le repère
« MRI » de MNE, ce qui permet de réutiliser `Coregistration` sans conversion.

---

## Fonction wrapper : de l'IRM+EEG aux sources, en un appel

```python
from mri2mne.wrapper import reconstruct_sources

result = reconstruct_sources(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # ou t1_path="..." pour un T1 prêt
    eeg_file="D:/eeg/patient01.edf",         # .edf .bdf .vhdr .set .fif ...
    digitization="D:/dig/patient01.elc",     # positions des électrodes
    simnibs_bin_dir="C:/Users/moi/Miniconda3/envs/simnibs_env/Scripts",  # <- REMPLACER par votre chemin
    events="find",                            # détecte les triggers ; ou un tableau/-eve.fif
    event_id={"spike": 1},
    tmin=-0.2, tmax=0.5,
    inverse_method="dSPM",                    # ou MNE / sLORETA / eLORETA
)

print(result.source_estimate_file)   # ...-lh.stc
print(result.peak)                    # pic : temps + hémisphère + position (mm)
stc = result.stc                      # SourceEstimate corticale en mémoire
```

Arguments principaux (les autres ont des défauts raisonnables) :

| Groupe | Arguments |
|---|---|
| Anatomie | `dicom_dir` **ou** `t1_path`, `t2_path` |
| EEG | `eeg_file`, `digitization` |
| SimNIBS | `simnibs_bin_dir` (dossier Scripts de `simnibs_env`) |
| Forward FEM | `fem_subsampling` (sources corticales/hémisphère), `fem_cpus`, `morph_to_fsaverage` |
| Coregistration | `icp_iterations`, `omit_distance_mm` |
| Traitement EEG | `l_freq`, `h_freq`, `eeg_reference`, `events`, `event_id`, `tmin`, `tmax`, `baseline`, `reject`, `noise_cov_tmin/tmax` |
| Inverse | `inverse_method`, `snr` |

`reconstruct_sources()` ne lève jamais d'exception sur une erreur de traitement :
elle renvoie un `SourceResult` avec `status="failed"` et le message, pour rester
sûre à appeler en boucle. Les stades déjà calculés sont sautés (reprise par
existence des fichiers ; `force=[...]` pour recalculer).

> Alternative : un beamformer LCMV (`mne.beamformer.make_lcmv`) est souvent
> utilisé en clinique ; ce serait une extension directe de `inverse.py`.

---

## Route alternative : sources volumiques (BEM, WSL2 + FreeSurfer)

En plus de la route surfacique FEM (par défaut, 100 % Windows), le dépôt fournit
une **seconde route, volumique**, bâtie sur le **BEM 3 couches de FreeSurfer** —
la méthode BEM standard, reconnue en clinique. Les sources remplissent le volume
cérébral (grille 3D) au lieu du cortex, et la sortie est une `VolSourceEstimate`
(`-vl.stc`) qui se lit en **overlay sur l'IRM** (coupes).

Les deux routes sont **indépendantes et complémentaires** (repères de coordonnées
distincts, fichiers distincts). À nouveau, tout calcul est un appel de librairie :
FreeSurfer `recon-all -autorecon1` / `mri_watershed` ; MNE `make_bem_solution` /
`setup_volume_source_space` / `make_forward_solution` / `make_inverse_operator`.

### Pré-requis : WSL2 + FreeSurfer

FreeSurfer étant Linux, cette route l'exécute dans **WSL2** (le pilote reste sous
Windows et l'appelle en sous-processus, comme SimNIBS).

```powershell
wsl --install            # WSL2 + Ubuntu, si pas déjà là
```

Puis, dans le terminal Ubuntu, installer FreeSurfer 7.x via son **tarball**
(recommandé sur Ubuntu 24.04) :

```bash
sudo apt install -y tcsh          # requis par les scripts FreeSurfer
cd ~ && wget https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
sudo tar -C /usr/local -xzf freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
# licence gratuite : https://surfer.nmr.mgh.harvard.edu/registration.html
cp /mnt/c/chemin/vers/license.txt $FREESURFER_HOME/license.txt
```

Prévoir ~20 Go pour l'installation. Vérifier depuis Python :
`from mri2mne import wsl; print(wsl.check_freesurfer().describe())` doit afficher
« ... (licensed) ».

### Usage

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

result = reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # ou t1_path="..."
    eeg_file="D:/eeg/patient01.edf",
    digitization="D:/dig/patient01.elc",
    events="find", event_id={"spike": 1},
    pos_mm=5.0,                               # espacement de la grille volumique
    inverse_method="dSPM", snr=3.0,
)
print(result.source_estimate_file)   # ...-vl.stc
```

Coût : **~20 min/sujet** sur un T1 propre — pas les heures du `recon-all`
complet, qui n'est pas nécessaire ici.

**En lot**, il suffit de mettre `head_model: "bem"` dans `config.yaml` (section
`bem:` pour les réglages) : `run_pipeline.py` route alors les étapes
`headmodel`/`coreg`/`forward` vers FreeSurfer/BEM au lieu de SimNIBS/FEM, tout en
réutilisant le même cache, le même `--check` (qui vérifie WSL + FreeSurfer) et la
même QC. L'inverse EEG se fait ensuite via `reconstruct_sources_volumetric`.

### Attention : qualité des surfaces watershed

`mri_watershed` est **sensible à la qualité du T1**. Sur un T1 de recherche propre
(1 mm) il donne des surfaces fermées et emboîtées ; sur certaines acquisitions
cliniques atypiques (grand FOV, contraste inhabituel) le crâne peut
s'auto-intersecter. Le pipeline **détecte et signale** ce cas
(`volumetric.check_bem_surfaces`) avec un message clair au lieu de planter — le
sujet demande alors une QC des surfaces ou un T1 plus propre. Pour du cortex 3D
net en visualisation, préférez la **route surfacique** (c'est sa vocation).

---

## Installation

### 1. `simnibs_env` — SimNIBS 4 (fournit `charm` + le solveur FEM)

Méthode en ligne de commande (validée ici, sans clic) :

```powershell
curl -L -o environment_windows.yml https://github.com/simnibs/simnibs/releases/download/v4.6.0/environment_windows.yml
conda env create -f environment_windows.yml
conda activate simnibs_env
pip install https://github.com/simnibs/simnibs/releases/download/v4.6.0/simnibs-4.6.0-cp311-cp311-win_amd64.whl
pip install "mne>=1.6"     # requis pour make_forward (sortie MNE)
```

Vérifier : `charm --version` doit afficher `4.6.0`. Le dossier
`…\envs\simnibs_env\Scripts` est celui que l'on passe à `simnibs_bin_dir`.
(L'installateur graphique officiel de <https://simnibs.github.io> fonctionne
aussi ; il faut alors `pip install mne` dans sa Python.)

### 2. `mri2mne` — l'environnement qui pilote

```powershell
conda env create -f environment.yml
conda activate mri2mne
```

### 3. Configuration

```powershell
copy config.example.yaml config.yaml
```

Éditer `config.yaml` : chemins des données, `simnibs.bin_dir` (le dossier
`Scripts` de `simnibs_env`), et le gabarit `paths.digitisation`.

### 4. (Optionnel) Installer en tant que paquet pip

Le dépôt est un paquet installable (`pyproject.toml`, layout `src/`). C'est la
manière la plus simple de le déployer **hors WSL** : la route surfacique FEM et
le lot ne dépendent que de librairies PyPI. Depuis la racine du dépôt :

```powershell
pip install .                # installe le paquet + ses dépendances
pip install ".[viz]"         # + PyVista/VTK (QC 3D + visualiseur de sources)
pip install ".[all]"         # + dcm2niix (binaire) + pytest
pip install -e ".[dev]"      # mode développement (éditable) + pytest
```

Après installation :

```python
from mri2mne.wrapper import reconstruct_sources   # importable partout
```

et la commande de lot est disponible directement (plus besoin de
`run_pipeline.py`) :

```powershell
mri2mne --config config.yaml --check
mri2mne --config config.yaml
```

Ce que l'install pip **ne** couvre **pas**, par conception :

* **SimNIBS** (`charm` + solveur FEM) reste dans son propre env `simnibs_env`,
  appelé en sous-processus (voir §1) — jamais installé dans le même env que le
  pilote (conflit numpy).
* La **route volumique BEM** exige **FreeSurfer dans WSL2** (prérequis système,
  voir plus haut) ; elle n'ajoute aucune dépendance Python. La route surfacique,
  elle, s'installe et tourne **entièrement sans WSL**.

> `pip install .` reste possible même sans SimNIBS ni WSL : la bibliothèque
> s'importe et les tests passent ; seules les étapes qui appellent réellement
> `charm`/FreeSurfer requièrent ces outils au moment de l'exécution.

---

## Utilisation en lot

```powershell
# Contrôle préalable : outils, fichiers de chaque sujet, espace disque
python run_pipeline.py --config config.yaml --check

# Traiter tout le monde
python run_pipeline.py --config config.yaml

# Un sous-ensemble
python run_pipeline.py --config config.yaml --subjects sub-001 sub-002

# Reprendre certaines étapes après un changement
python run_pipeline.py --config config.yaml --force coreg forward
```

Organisation attendue :

```
dicom_root/
  sub-001/            <- un dossier par sujet, DICOM à l'intérieur (récursif)
digitisation/
  sub-001_electrodes.elc
```

Formats de digitalisation reconnus : `.fif`, `.hsp`/`.elp` (Polhemus), `.bvct`
(CapTrak), `.sfp`, `.elc`, `.hpts`, `.csd`, `.xyz`. Formats EEG : `.edf`, `.bdf`,
`.vhdr` (BrainVision), `.set` (EEGLAB), `.fif`, `.mff`, `.eeg`.

### Reprise et cache

Chaque étape enregistre une empreinte de ses entrées dans
`derivatives/<sujet>/status.json`. Relancer ne recalcule que ce qui a changé —
et surtout ne relance pas les ~1h30 de `charm` inutilement.

### Résistance aux pannes

`continue_on_error` protège des exceptions ; et si un **processus** worker meurt
(typiquement l'OOM killer sur `charm`, 4-8 Go), le lot le détecte et **rejoue en
séquentiel** au lieu de tout perdre. Le vrai correctif reste de baisser
`run.n_jobs`.

---

## Contrôle qualité

Un rapport HTML par sujet (`derivatives/<sujet>/qc/`) et un récapitulatif de lot,
avec les métriques, le résidu de coregistration et la figure d'alignement 3D.

**Regardez l'alignement électrodes/scalp avant d'exploiter les résultats.** Un
faible résidu dig→scalp ne garantit pas une bonne pose : sur un scalp lisse,
l'ICP peut glisser d'un centimètre tout en gardant les points près de la surface.
Ce qui pinne la pose, ce sont les fiduciaux — que `charm` fournit en espace sujet.

Reprise manuelle d'un sujet signalé :

```powershell
conda activate mri2mne
mne coreg --subject sub-001 --subjects-dir D:\data\derivatives\subjects
```

Sauvegarder les fiduciaux corrigés dans
`subjects/<sujet>/bem/<sujet>-fiducials.fif`, puis relancer avec
`--force coreg forward`.

---

## Visualisation des sources

L'espace de sources vient de SimNIBS (surface corticale *centrale*), pas de
FreeSurfer — or `stc.plot()` de MNE attend une arborescence
`subjects_dir/<sujet>/surf/lh.white`. Le module `mri2mne.viz` fait le **pont** :
il écrit une fois le maillage SimNIBS (`-src.fif`) au format FreeSurfer, après
quoi **tout l'outillage 3D natif de MNE** (fenêtre rotative à la souris, slider
temporel, films, décours par ROI) fonctionne tel quel. C'est du MNE + SimNIBS,
donc citable, sans code de rendu maison.

**Fenêtre interactive** (rotation/zoom/temps à la souris), depuis un script :

```powershell
conda activate mri2mne
python examples/open_source_viewer.py D:/derivatives patient01 --time 0.1
```

ou en Python :

```python
from mri2mne.viz import open_viewer, block_on_viewer
brain = open_viewer("D:/derivatives", "patient01", initial_time=0.1)
block_on_viewer()   # garde la fenêtre ouverte jusqu'à sa fermeture
```

**Figure statique** (rendu *offscreen*, pour un rapport ou une machine sans
écran) :

```python
from pathlib import Path
from mri2mne.paths import SubjectPaths
from mri2mne.viz import save_views

paths = SubjectPaths("patient01", Path("D:/derivatives"),
                     Path("D:/derivatives/subjects"))
save_views(paths, "patient01_sources.png", initial_time=0.1,
           views=("lateral", "medial", "dorsal"), hemi="lh")
```

L'API : `write_freesurfer_surfaces(paths)` (le pont, idempotent),
`plot_sources(paths, ...)` (renvoie un `mne.viz.Brain`), `open_viewer(...)`
(raccourci depuis `output_dir`+`subject`), `save_views(...)` (PNG multi-vues).

> `surface="inflated"` est identique à `white` (SimNIBS ne gonfle pas les
> surfaces). Pour le cerveau *gonflé* lisse standard, morphez vers `fsaverage`
> (`morph_to_fsaverage`) puis tracez avec `subject="fsaverage"`.

---

## Ce qui a été validé

Pipeline exécuté **de bout en bout via le wrapper public** sur le jeu `sample`
de MNE (vraie anatomie, vrai EEG en EDF), `status: ok` :

| Contrôle | Résultat |
|---|---|
| Coregistration (repère maillage, MNE) | résidu médian **1,85 mm** |
| Forward FEM | **10000 sources corticales × 60 canaux**, gain fini |
| EEG | 17 epochs auditifs gauches moyennés (EDF) |
| Inverse dSPM | opérateur + estimation OK |
| Sortie | `sample-lh.stc` / `-rh.stc` |
| Pic (stim. auditive gauche) | **hémisphère gauche**, latéral (−55, −35, 34) mm |

Le pic est latéral gauche, anatomiquement plausible pour une réponse auditive.

**Validé aussi sur un vrai DICOM clinique** (série T1w 384 coupes, 0,7 mm) : la
chaîne complète `reconstruct_sources(dicom_dir=...)` — anonymisation → conversion
→ `charm` sur le T1 issu du DICOM → maillage → coreg → leadfield FEM → dSPM — se
déroule sans accroc, `status: ok`, sortie corticale `-lh/-rh.stc`. L'EEG utilisé
était volontairement sans rapport (validation de la *plomberie*, pas de la
localisation). Temps de calcul **net** mesuré sur cette machine (mono-thread) :
`charm` ≈ 2 h sur ce T1 haute-résolution, leadfield FEM ≈ 18 min, reste < 1 min.

**Non validé faute de données :** un couple DICOM + **vraie digitalisation**
(Polhemus/CapTrak) du **même** sujet. Faites un premier passage sur **un sujet**
avant le lot.

Pour rejouer la validation (nécessite une sortie `charm`) :

```powershell
python examples/run_full_pipeline_sample.py <chemin-vers-m2m_sampleE2E> <scratch>
```

---

## Limites à connaître

**Deux repères de sources selon la route.** La route FEM (défaut) place les
sources sur la surface corticale (matière grise moyenne lh+rh) ; la route BEM
(`head_model: bem`) les place dans le volume. Les deux sont des méthodes
documentées et publiables ; choisissez selon votre analyse.

**Le corecalage est le maillon faible, pas l'anatomie.** Avec une digitalisation
soignée et une vérification visuelle de l'alignement, on est bon. Sans
digitalisation, la précision chute.

**Une image T2 améliore le crâne.** Si vos protocoles en incluent une,
renseignez `simnibs.t2_template`.

**Coût de calcul.** Le leadfield FEM résout un système par électrode sur un
maillage à ~800k nœuds. Pour 60-256 électrodes, comptez 20 min à ~2 h. Sous
Windows, le solveur tourne en un seul processus (`fem.cpus` forcé à 1 : la
parallélisation SimNIBS n'est pas picklable avec le `spawn` de Windows).

---

## Tests

```powershell
conda activate mri2mne
pytest tests -q
```

Les tests couvrent la config, l'ingestion DICOM (scorer de séries), la lecture
EEG / le montage, la localisation du pic, les contrôles préalables, la validation
des arguments du wrapper et le pont SimNIBS→FreeSurfer de la visualisation. Les
étapes lourdes (charm, leadfield FEM) sont validées par
`examples/run_full_pipeline_sample.py` sur données réelles.

---

## Structure

```
run_pipeline.py            Point d'entrée CLI du lot
config.example.yaml        Configuration commentée
environment.yml            Environnement mri2mne (pilote)
src/mri2mne/
  config.py                Chargement et validation YAML
  paths.py                 Arborescence sujet + cache d'étapes
  anonymize.py             PHI DICOM + défaçage optionnel
  dicom_convert.py         DICOM → NIfTI + sélection de la série T1
  headmodel.py             Wrapper charm
  coregistration.py        Digitalisation + ICP (MNE Coregistration)
  simnibs_mesh.py          Extraction scalp + fiduciaux du maillage (pilote)
  simnibs_forward.py       Forward FEM SimNIBS (pilote)
  _simnibs_fem_helper.py   Leadfield + make_forward (tourne dans simnibs_env)
  _simnibs_mesh_helper.py  crop_mesh + fiduciaux (tourne dans simnibs_env)
  eeg.py                   Lecture EEG, prétraitement, covariance
  inverse.py               Opérateur inverse + estimation de sources (surfacique)
  viz.py                   Pont SimNIBS→FreeSurfer + visualisation 3D MNE
  wsl.py                   Pont WSL2 (route volumique) : chemins, exécuteur, probe
  freesurfer_bem.py        autorecon1 + watershed via WSL (route volumique)
  volumetric.py            BEM 3 couches + source space + forward/inverse volumiques
  wrapper.py               reconstruct_sources[/_volumetric]() : IRM+EEG -> sources
  preflight.py             Contrôles avant lancement du lot
  qc.py                    Rapports HTML
  pipeline.py              Orchestration par sujet (lot)
  batch.py                 Découverte des sujets + parallélisme
examples/
  run_full_pipeline_sample.py   Validation end-to-end surfacique sur données réelles
  run_volumetric_sample.py      Route volumique (BEM/WSL) end-to-end
  open_source_viewer.py         Fenêtre 3D interactive pour un sujet traité
```
