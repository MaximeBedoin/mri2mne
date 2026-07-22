# Données d'exemple

Deux patients de démonstration, pour montrer **l'architecture des données** et
faire tourner le pipeline (run simple et lot). Structure par patient :

```
data/
  patient01/
    dicom/                 # série IRM T1w en DICOM (384 coupes)
    patient01_eeg.edf      # enregistrement EEG
    patient01_dig.fif      # digitalisation des électrodes
    patient01-eve.fif      # événements (pour l'épochage)
  patient02/               # même structure (pour démontrer le lot)
    ...
```

Les sorties d'analyse se rangent dans des **sous-dossiers du patient** :

```
  patient01/
    surface/               # sortie route surfacique (FEM)  -> .../patient01/mne/patient01-lh.stc
    volumetric/            # sortie route volumique (BEM)    -> .../patient01/mne/patient01-vol-vl.stc
```

Les commandes exactes (surfacique + volumique, run simple + lot) sont dans le
[README principal](../README.md), section « Exemple de bout en bout ».

## Provenance et avertissement

- **DICOM** : jeu public anonymisé (`datalad/example-dicom-structural`,
  `PatientIdentityRemoved=YES`). Une IRM structurelle T1w réelle.
- **EEG + digitalisation** : jeu `sample` de MNE-Python — un **sujet différent**
  de l'IRM. Ce sont des **substituts** pour illustrer la structure et les
  commandes ; l'EEG n'est pas apparié à cette anatomie, donc **le résultat n'a
  pas de sens clinique**. Pour un vrai sujet, l'EEG et la digitalisation doivent
  provenir du **même** patient que l'IRM.
- `patient02` est une copie de `patient01`, uniquement pour démontrer le lot.

> Note : la route volumique (BEM) peut **signaler** ce T1 clinique précis
> (surfaces de crâne watershed auto-intersectantes) — c'est le comportement
> attendu sur certaines acquisitions atypiques (voir le README principal).
