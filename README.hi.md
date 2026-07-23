> 🌍 [Français](README.md) · [English](README.en.md) · [中文](README.zh.md) · **हिन्दी** · [Español](README.es.md) · [العربية](README.ar.md)

# MRI → MNE: कॉर्टिकल EEG स्रोत विश्लेषण (SimNIBS FEM, Windows-नेटिव)

[![Tests](https://github.com/MaximeBedoin/mri2mne/actions/workflows/tests.yml/badge.svg)](https://github.com/MaximeBedoin/mri2mne/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![Docs](https://img.shields.io/badge/docs-tutorials-brightgreen.svg)](https://maximebedoin.github.io/mri2mne/tutorials/index.en.html)

**DICOM में MRI** + एक **EEG रिकॉर्डिंग** से MNE-Python के साथ **कॉर्टिकल स्रोत
अनुमान** तक का सम्पूर्ण पाइपलाइन। Python से संचालित, Windows पर नेटिव रूप से चलता है,
**FreeSurfer के बिना, WSL के बिना, Docker के बिना**। (एक वैकल्पिक वॉल्यूमेट्रिक BEM रूट
नीचे वर्णित है; वह WSL + FreeSurfer का उपयोग करता है।)

यह विधि पूरी तरह से **स्थापित और उद्धरण-योग्य** लाइब्रेरियों पर बनी है: सेगमेंटेशन और
**FEM** फ़ॉरवर्ड **SimNIBS** द्वारा (`charm`, `compute_tdcs_leadfield`,
`make_forward`), को-रजिस्ट्रेशन और इनवर्स **MNE-Python** द्वारा। इस रिपॉज़िटरी का कोड
केवल दोनों के बीच का ऑर्केस्ट्रेशन है।

प्रति विषय `charm` के लिए लगभग **~1.5 घंटे** + FEM लीडफ़ील्ड के लिए **~20-40 मिनट**
मानें, `recon-all` के 10-20 घंटों के बजाय।

> 📚 **सचित्र ट्यूटोरियल** — **हर चरण** की छवि के साथ चरण-दर-चरण (T1, ऊतक विभाजन,
> EEG, इवोक्ड रिस्पॉन्स, 3D कोरजिस्ट्रेशन, कॉर्टिकल स्रोत):
> **[maximebedoin.github.io/mri2mne/tutorials](https://maximebedoin.github.io/mri2mne/tutorials/index.en.html)** (अंग्रेज़ी/फ़्रेंच, पहले **GitHub Pages** सक्षम करें)।
> या `docs/tutorials/index.en.html` को स्थानीय रूप से खोलें।

---

## इनपुट → आउटपुट, एक वाक्य में

**शुरुआत होती है** रोगी की DICOM में शारीरिक MRI + EEG रिकॉर्डिंग (EDF या अन्य) +
इलेक्ट्रोड डिजिटलीकरण से। **पहुँचते हैं** **कॉर्टेक्स** पर EEG स्रोत अनुमान तक: मापी गई
गतिविधि का स्थानीयकरण, साथ ही समूह विश्लेषण के लिए `fsaverage` की ओर एक morph।

## पाइपलाइन क्या उत्पन्न करता है

प्रत्येक विषय के लिए, `derivatives/<विषय>/mne/` में:

| फ़ाइल | सामग्री |
|---|---|
| `<विषय>-trans.fif` | सिर ↔ MRI को-रजिस्ट्रेशन |
| `<विषय>-fwd.fif` | **कॉर्टिकल** स्रोत स्थान (lh+rh) पर **FEM** फ़ॉरवर्ड |
| `<विषय>-noise-cov.fif` | शोर सहप्रसरण |
| `<विषय>-inv.fif` | इनवर्स ऑपरेटर |
| `<विषय>-lh.stc` / `-rh.stc` | **कॉर्टिकल स्रोत अनुमान** — अंतिम परिणाम |
| `<विषय>-morph.h5` | `fsaverage` की ओर morph (समूह विश्लेषण) |

उपयोग के दो स्तर:

* **`reconstruct_sources()`** (एक विषय, नीचे देखें) MRI+EEG से स्रोत अनुमान तक जाता है।
* **`run_pipeline.py`** (बैच) N विषयों के लिए रूपांतरण → `charm` → को-रजिस्ट्रेशन →
  FEM फ़ॉरवर्ड को जोड़ता है; इनवर्स (जो EEG डेटा पर निर्भर है) उसके बाद wrapper के
  माध्यम से किया जाता है।

---

## आद्योपांत उदाहरण (`data/` फ़ोल्डर)

रिपॉज़िटरी में [`data/`](data/README.en.md) में एक तैयार-उपयोग उदाहरण शामिल है: MRI
DICOM + EEG + डिजिटलीकरण वाला एक रोगी (बैच के लिए एक दूसरा भी)।

```
data/
  patient01/
    dicom/                 # T1w MRI शृंखला (DICOM)
    patient01_eeg.edf      # EEG
    patient01_dig.fif      # इलेक्ट्रोड डिजिटलीकरण
    patient01-eve.fif      # इवेंट्स
  patient02/               # वही (बैच के लिए)
  config.batch.yaml        # तैयार-उपयोग बैच कॉन्फ़िगरेशन
  README.md                # संरचना और स्रोत का विवरण
```

**फ़ाइलों का स्रोत** (विवरण [data/README.en.md](data/README.en.md) में):

| फ़ाइल | उद्गम | प्रकृति |
|---|---|---|
| `dicom/` | सार्वजनिक डेटासेट `datalad/example-dicom-structural` (`PatientIdentityRemoved=YES`) | वास्तविक T1w MRI, **अनामीकृत** |
| `*_eeg.edf`, `*_dig.fif`, `*-eve.fif` | **MNE-Python** का `sample` डेटासेट | **किसी अन्य** विषय का EEG + डिजिटलीकरण |
| `patient02/` | `patient01` की प्रतिलिपि | केवल बैच प्रदर्शित करने के लिए |

> ⚠️ EEG और MRI **अलग-अलग विषयों** से आते हैं: ये फ़ोल्डर संरचना और कमांड दर्शाने के
> लिए **स्थानापन्न** हैं। शृंखला आद्योपांत चलती है, परन्तु **परिणाम का कोई नैदानिक अर्थ
> नहीं है**। वास्तविक विषय के लिए, EEG और डिजिटलीकरण उसी **एक ही** रोगी से आने चाहिए
> जिससे MRI आती है।

### एकल रन — एक रोगी, आउटपुट रोगी के अंदर संग्रहीत

सतह (FEM, Windows-नेटिव):

```python
from mri2mne.wrapper import reconstruct_sources

reconstruct_sources(
    subject="patient01",
    output_dir="data/patient01/surface",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- अपने पथ से बदलें
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/surface/patient01/mne/patient01-lh.stc  (+ -rh.stc)
```

वॉल्यूमेट्रिक (BEM, WSL + FreeSurfer के माध्यम से):

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

### बैच — कई रोगी, एक कमांड

> **चलाने से पहले**: [`data/config.batch.yaml`](data/config.batch.yaml) को संपादित करें
> और `simnibs.bin_dir` (प्लेसहोल्डर `C:/Users/YOUR_NAME/...`) को अपने `simnibs_env` के
> `Scripts` फ़ोल्डर से बदलें। `--check` इसकी जाँच करता है और यदि पथ अब भी प्लेसहोल्डर है
> तो एक स्पष्ट त्रुटि दर्शाता है।

```powershell
python run_pipeline.py --config data/config.batch.yaml --check   # उपकरण + इनपुट जाँचता है
python run_pipeline.py --config data/config.batch.yaml
```

कॉन्फ़िगरेशन का `head_model` फ़ील्ड (`fem` या `bem`) रूट चुनता है; बैच के आउटपुट
`data/_batch_derivatives/` के अंतर्गत जाते हैं। EEG इनवर्स उसके बाद प्रति विषय संगत
wrapper के साथ किया जाता है।

> उदाहरण के EEG/डिजिटलीकरण MRI से **किसी अन्य** विषय से आते हैं (डेमो के लिए
> स्थानापन्न): शृंखला चलती है, परन्तु परिणाम का कोई नैदानिक अर्थ नहीं है। देखें
> [data/README.en.md](data/README.en.md)।

---

## संरचना: दो वातावरण

पाइपलाइन **दो conda वातावरणों** का उपयोग करता है:

* **`mri2mne`** — सब कुछ संचालित करता है (यह रिपॉज़िटरी)। `simnibs` को **कभी** import
  नहीं करता।
* **`simnibs_env`** — SimNIBS 4.6 + MNE। SimNIBS-विशिष्ट चरण चलाता है, जिन्हें
  `mri2mne` **सबप्रोसेस** के रूप में बुलाता है।

यही वह चीज़ है जो SimNIBS और MNE को उनके नेटिव संस्करणों में निर्भरता टकराव (विशेषकर
numpy) के बिना उपयोग करने देती है।

### चरण, और प्रत्येक के पीछे की लाइब्रेरी

| # | चरण | फ़ंक्शन | लाइब्रेरी |
|---|---|---|---|
| 1 | DICOM → NIfTI + अनामीकरण + T1 चयन | `dcm2niix`, `pydicom` | — |
| 2 | सेगमेंटेशन + FEM मेश + कॉर्टिकल सतहें | `charm` | SimNIBS |
| 3a | खोपड़ी की सतह (ICP के लिए) | `mesh.crop_mesh` | SimNIBS |
| 3b | विषय के फ़िड्यूशियल | `read_csv_positions` | SimNIBS |
| 3c | फ़िड्यूशियल संरेखण + ICP | `Coregistration` | MNE |
| 4a | इलेक्ट्रोड मॉन्टेज → विषय | `prepare_montage` | SimNIBS |
| 4b | FEM लीडफ़ील्ड (पारस्परिकता) | `compute_tdcs_leadfield` | SimNIBS |
| 4c | `mne.Forward` में रूपांतरण (+ fsaverage morph) | `make_forward` | SimNIBS |
| 5 | EEG: पठन, फ़िल्टरिंग, सहप्रसरण | `mne.io`, `compute_covariance` | MNE |
| 6 | इनवर्स ऑपरेटर + अनुप्रयोग | `make_inverse_operator`, `apply_inverse` | MNE |

निर्देशांक तंत्र: SimNIBS मेश जगत को MNE के "MRI" तंत्र के रूप में माना जाता है, जिससे
`Coregistration` को बिना रूपांतरण के पुनः उपयोग किया जा सकता है।

---

## Wrapper फ़ंक्शन: MRI+EEG से स्रोतों तक, एक ही कॉल में

```python
from mri2mne.wrapper import reconstruct_sources

result = reconstruct_sources(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # या तैयार T1 के लिए t1_path="..."
    eeg_file="D:/eeg/patient01.edf",         # .edf .bdf .vhdr .set .fif ...
    digitization="D:/dig/patient01.elc",     # इलेक्ट्रोड स्थितियाँ
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- अपने पथ से बदलें
    events="find",                            # ट्रिगर पहचानता है; या एक array / -eve.fif
    event_id={"spike": 1},
    tmin=-0.2, tmax=0.5,
    inverse_method="dSPM",                    # या MNE / sLORETA / eLORETA
)

print(result.source_estimate_file)   # ...-lh.stc
print(result.peak)                    # शिखर: समय + गोलार्ध + स्थिति (mm)
stc = result.stc                      # मेमोरी में कॉर्टिकल SourceEstimate
```

मुख्य आर्ग्युमेंट (शेष के पास उचित डिफ़ॉल्ट हैं):

| समूह | आर्ग्युमेंट |
|---|---|
| शारीरिकी | `dicom_dir` **या** `t1_path`, `t2_path` |
| EEG | `eeg_file`, `digitization` |
| SimNIBS | `simnibs_bin_dir` (`simnibs_env` का Scripts फ़ोल्डर) |
| FEM फ़ॉरवर्ड | `fem_subsampling` (प्रति गोलार्ध कॉर्टिकल स्रोत), `fem_cpus`, `morph_to_fsaverage` |
| को-रजिस्ट्रेशन | `icp_iterations`, `omit_distance_mm` |
| EEG प्रसंस्करण | `l_freq`, `h_freq`, `eeg_reference`, `events`, `event_id`, `tmin`, `tmax`, `baseline`, `reject`, `noise_cov_tmin/tmax` |
| इनवर्स | `inverse_method`, `snr` |

`reconstruct_sources()` प्रसंस्करण त्रुटि पर कभी अपवाद नहीं फेंकता: यह
`status="failed"` और संदेश के साथ एक `SourceResult` लौटाता है, ताकि लूप में बुलाना
सुरक्षित रहे। पहले से गणना किए गए चरण छोड़ दिए जाते हैं (फ़ाइल के अस्तित्व द्वारा पुनरारंभ;
पुनः गणना के लिए `force=[...]`)।

> विकल्प: एक LCMV बीमफ़ॉर्मर (`mne.beamformer.make_lcmv`) नैदानिक रूप से अक्सर प्रयुक्त
> होता है; यह `inverse.py` का सीधा विस्तार होगा।

---

## वैकल्पिक रूट: वॉल्यूमेट्रिक स्रोत (BEM, WSL2 + FreeSurfer)

सतह FEM रूट (डिफ़ॉल्ट, 100% Windows) के अतिरिक्त, रिपॉज़िटरी एक **दूसरा, वॉल्यूमेट्रिक
रूट** प्रदान करता है, जो **FreeSurfer के 3-परत BEM** पर बना है — मानक, नैदानिक रूप से
मान्य BEM विधि। स्रोत कॉर्टेक्स के बजाय मस्तिष्क आयतन (3D ग्रिड) को भरते हैं, और आउटपुट
एक `VolSourceEstimate` (`-vl.stc`) है जिसे MRI पर **ओवरले** (स्लाइस) के रूप में पढ़ा
जाता है।

दोनों रूट **स्वतंत्र और पूरक** हैं (भिन्न निर्देशांक तंत्र, भिन्न फ़ाइलें)। पुनः, हर
गणना एक लाइब्रेरी कॉल है: FreeSurfer `recon-all -autorecon1` / `mri_watershed`; MNE
`make_bem_solution` / `setup_volume_source_space` / `make_forward_solution` /
`make_inverse_operator`।

### पूर्वापेक्षाएँ: WSL2 + FreeSurfer

चूँकि FreeSurfer केवल Linux के लिए है, यह रूट इसे **WSL2** के भीतर चलाता है (ड्राइवर
Windows पर ही रहता है और इसे सबप्रोसेस के रूप में बुलाता है, SimNIBS की तरह)।

```powershell
wsl --install            # WSL2 + Ubuntu, यदि पहले से न हो
```

फिर, Ubuntu टर्मिनल में, FreeSurfer 7.x को उसके **tarball** के माध्यम से इंस्टॉल करें
(Ubuntu 24.04 पर अनुशंसित):

```bash
sudo apt install -y tcsh          # FreeSurfer स्क्रिप्ट्स के लिए आवश्यक
cd ~ && wget https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
sudo tar -C /usr/local -xzf freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
# निःशुल्क लाइसेंस: https://surfer.nmr.mgh.harvard.edu/registration.html
cp /mnt/c/path/to/license.txt $FREESURFER_HOME/license.txt
```

इंस्टॉलेशन के लिए ~20 GB रखें। Python से जाँचें:
`from mri2mne import wsl; print(wsl.check_freesurfer().describe())` को
"... (licensed)" दिखाना चाहिए।

### उपयोग

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

result = reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # या t1_path="..."
    eeg_file="D:/eeg/patient01.edf",
    digitization="D:/dig/patient01.elc",
    events="find", event_id={"spike": 1},
    pos_mm=5.0,                               # वॉल्यूमेट्रिक ग्रिड अंतराल
    inverse_method="dSPM", snr=3.0,
)
print(result.source_estimate_file)   # ...-vl.stc
```

लागत: स्वच्छ T1 पर **~20 मिनट/विषय** — पूर्ण `recon-all` के घंटों जैसा नहीं, जिसकी यहाँ
आवश्यकता नहीं है।

**बैच में**, बस `config.yaml` में `head_model: "bem"` सेट करें (सेटिंग्स के लिए `bem:`
अनुभाग): तब `run_pipeline.py` `headmodel`/`coreg`/`forward` चरणों को SimNIBS/FEM के
बजाय FreeSurfer/BEM की ओर भेजता है, वही कैश, वही `--check` (जो WSL + FreeSurfer जाँचता
है) और वही QC पुनः उपयोग करते हुए। EEG इनवर्स उसके बाद
`reconstruct_sources_volumetric` के माध्यम से किया जाता है।

### सावधानी: watershed सतह की गुणवत्ता

`mri_watershed` **T1 की गुणवत्ता के प्रति संवेदनशील** है। एक स्वच्छ शोध T1 (1 mm) पर यह
बंद और नेस्टेड सतहें देता है; कुछ असामान्य नैदानिक अधिग्रहणों (बड़ा FOV, असामान्य
कंट्रास्ट) पर खोपड़ी स्वयं-प्रतिच्छेदन कर सकती है। पाइपलाइन इस स्थिति को क्रैश होने के
बजाय एक स्पष्ट संदेश के साथ **पहचानता और चिह्नित करता** है
(`volumetric.check_bem_surfaces`) — तब उस विषय को सतह QC या एक स्वच्छ T1 चाहिए।
विज़ुअलाइज़ेशन में तीक्ष्ण 3D कॉर्टेक्स के लिए, **सतह रूट** को प्राथमिकता दें (यही उसका
उद्देश्य है)।

---

## इंस्टॉलेशन

### 1. `simnibs_env` — SimNIBS 4 (`charm` + FEM सॉल्वर प्रदान करता है)

कमांड-लाइन विधि (यहाँ मान्य, बिना क्लिक के):

```powershell
curl -L -o environment_windows.yml https://github.com/simnibs/simnibs/releases/download/v4.6.0/environment_windows.yml
conda env create -f environment_windows.yml
conda activate simnibs_env
pip install https://github.com/simnibs/simnibs/releases/download/v4.6.0/simnibs-4.6.0-cp311-cp311-win_amd64.whl
pip install "mne>=1.6"     # make_forward (MNE आउटपुट) के लिए आवश्यक
```

जाँचें: `charm --version` को `4.6.0` दिखाना चाहिए। फ़ोल्डर
`…\envs\simnibs_env\Scripts` वही है जो `simnibs_bin_dir` को दिया जाता है।
(<https://simnibs.github.io> का आधिकारिक ग्राफ़िकल इंस्टॉलर भी काम करता है; तब उसके
Python में `pip install mne` करना पड़ता है।)

### 2. `mri2mne` — संचालक वातावरण

```powershell
conda env create -f environment.yml
conda activate mri2mne
```

### 3. कॉन्फ़िगरेशन

```powershell
copy config.example.yaml config.yaml
```

`config.yaml` संपादित करें: डेटा पथ, `simnibs.bin_dir` (`simnibs_env` का `Scripts`
फ़ोल्डर), और `paths.digitisation` टेम्पलेट।

### 4. (वैकल्पिक) pip पैकेज के रूप में इंस्टॉल करें

रिपॉज़िटरी एक इंस्टॉल-योग्य पैकेज है (`pyproject.toml`, `src/` लेआउट)। इसे **WSL के
बिना** तैनात करने का यह सबसे सरल तरीका है: सतह FEM रूट और बैच केवल PyPI लाइब्रेरियों पर
निर्भर हैं। रिपॉज़िटरी की जड़ से:

```powershell
pip install .                # पैकेज + इसकी निर्भरताएँ इंस्टॉल करता है
pip install ".[viz]"         # + PyVista/VTK (3D QC + स्रोत व्यूअर)
pip install ".[all]"         # + dcm2niix (बाइनरी) + pytest
pip install -e ".[dev]"      # विकास (एडिटेबल) मोड + pytest
```

इंस्टॉलेशन के बाद:

```python
from mri2mne.wrapper import reconstruct_sources   # कहीं भी import-योग्य
```

और बैच कमांड सीधे उपलब्ध है (`run_pipeline.py` की अब आवश्यकता नहीं):

```powershell
mri2mne --config config.yaml --check
mri2mne --config config.yaml
```

pip इंस्टॉल जो कवर **नहीं** करता, डिज़ाइन द्वारा:

* **SimNIBS** (`charm` + FEM सॉल्वर) अपने ही `simnibs_env` में रहता है, सबप्रोसेस के रूप
  में बुलाया जाता है (§1 देखें) — संचालक के समान वातावरण में कभी इंस्टॉल नहीं किया जाता
  (numpy टकराव)।
* **वॉल्यूमेट्रिक BEM रूट** को **WSL2 में FreeSurfer** चाहिए (सिस्टम पूर्वापेक्षा, ऊपर
  देखें); यह कोई Python निर्भरता नहीं जोड़ता। दूसरी ओर सतह रूट **पूरी तरह WSL के बिना**
  इंस्टॉल होकर चलता है।

> SimNIBS या WSL के बिना भी `pip install .` संभव रहता है: लाइब्रेरी import होती है और
> परीक्षण पास होते हैं; केवल वे चरण जो वास्तव में `charm`/FreeSurfer को बुलाते हैं,
> रनटाइम पर उन उपकरणों की माँग करते हैं।

---

## बैच उपयोग

```powershell
# पूर्व-जाँच: उपकरण, प्रत्येक विषय की फ़ाइलें, डिस्क स्थान
python run_pipeline.py --config config.yaml --check

# सभी को संसाधित करें
python run_pipeline.py --config config.yaml

# एक उपसमुच्चय
python run_pipeline.py --config config.yaml --subjects sub-001 sub-002

# बदलाव के बाद कुछ चरण पुनः चलाएँ
python run_pipeline.py --config config.yaml --force coreg forward
```

अपेक्षित संगठन:

```
dicom_root/
  sub-001/            <- प्रति विषय एक फ़ोल्डर, DICOM उसके अंदर (पुनरावर्ती)
digitisation/
  sub-001_electrodes.elc
```

पहचाने गए डिजिटलीकरण प्रारूप: `.fif`, `.hsp`/`.elp` (Polhemus), `.bvct` (CapTrak),
`.sfp`, `.elc`, `.hpts`, `.csd`, `.xyz`। EEG प्रारूप: `.edf`, `.bdf`, `.vhdr`
(BrainVision), `.set` (EEGLAB), `.fif`, `.mff`, `.eeg`।

### पुनरारंभ और कैश

प्रत्येक चरण अपने इनपुट का एक फ़िंगरप्रिंट `derivatives/<विषय>/status.json` में दर्ज
करता है। पुनः चलाने पर केवल वही पुनर्गणना होता है जो बदला — और सबसे बढ़कर, `charm` के
~1.5 घंटे व्यर्थ में पुनः नहीं चलते।

### दोष सहिष्णुता

`continue_on_error` अपवादों से रक्षा करता है; और यदि कोई worker **प्रोसेस** मर जाए
(सामान्यतः `charm` पर OOM किलर, 4-8 GB), बैच इसे पहचानता है और सब कुछ खोने के बजाय
**क्रमिक रूप से पुनः चलाता** है। वास्तविक समाधान अब भी `run.n_jobs` घटाना है।

---

## गुणवत्ता नियंत्रण

प्रति विषय एक HTML रिपोर्ट (`derivatives/<विषय>/qc/`) और एक बैच सारांश, मेट्रिक्स,
को-रजिस्ट्रेशन अवशेष और 3D संरेखण आकृति सहित।

**परिणामों का उपयोग करने से पहले इलेक्ट्रोड/खोपड़ी संरेखण देखें।** कम dig→खोपड़ी अवशेष
अच्छे फ़िट की गारंटी नहीं देता: चिकनी खोपड़ी पर, ICP एक सेंटीमीटर खिसक सकता है फिर भी
बिंदुओं को सतह के निकट रख सकता है। फ़िट को जो कील ठोकता है वे फ़िड्यूशियल हैं — जिन्हें
`charm` विषय स्थान में प्रदान करता है।

चिह्नित विषय का मैन्युअल पुनर्कार्य:

```powershell
conda activate mri2mne
mne coreg --subject sub-001 --subjects-dir D:\data\derivatives\subjects
```

सुधारे गए फ़िड्यूशियल `subjects/<विषय>/bem/<विषय>-fiducials.fif` में सहेजें, फिर
`--force coreg forward` के साथ पुनः चलाएँ।

---

## स्रोत विज़ुअलाइज़ेशन

स्रोत स्थान SimNIBS से आता है (*केंद्रीय* कॉर्टिकल सतह), FreeSurfer से नहीं — पर MNE का
`stc.plot()` एक `subjects_dir/<विषय>/surf/lh.white` वृक्ष अपेक्षित करता है।
`mri2mne.viz` मॉड्यूल **सेतु** का काम करता है: यह SimNIBS मेश (`-src.fif`) को एक बार
FreeSurfer प्रारूप में लिखता है, जिसके बाद **MNE का समस्त नेटिव 3D साधन** (माउस से घूमने
वाली विंडो, समय स्लाइडर, फ़िल्में, ROI द्वारा समय-क्रम) यथावत काम करता है। यह MNE +
SimNIBS है, अतः उद्धरण-योग्य, बिना किसी घरेलू रेंडरिंग कोड के।

**इंटरैक्टिव विंडो** (माउस से घुमाना/ज़ूम/समय), एक स्क्रिप्ट से:

```powershell
conda activate mri2mne
python examples/open_source_viewer.py D:/derivatives patient01 --time 0.1
```

या Python में:

```python
from mri2mne.viz import open_viewer, block_on_viewer
brain = open_viewer("D:/derivatives", "patient01", initial_time=0.1)
block_on_viewer()   # विंडो को बंद होने तक खुला रखता है
```

**स्थिर आकृति** (*offscreen* रेंडरिंग, रिपोर्ट या बिना स्क्रीन वाली मशीन के लिए):

```python
from pathlib import Path
from mri2mne.paths import SubjectPaths
from mri2mne.viz import save_views

paths = SubjectPaths("patient01", Path("D:/derivatives"),
                     Path("D:/derivatives/subjects"))
save_views(paths, "patient01_sources.png", initial_time=0.1,
           views=("lateral", "medial", "dorsal"), hemi="lh")
```

API: `write_freesurfer_surfaces(paths)` (सेतु, idempotent), `plot_sources(paths, ...)`
(एक `mne.viz.Brain` लौटाता है), `open_viewer(...)` (`output_dir`+`subject` से शॉर्टकट),
`save_views(...)` (बहु-दृश्य PNG)।

> `surface="inflated"` `white` के समान है (SimNIBS सतहों को फुलाता नहीं)। मानक चिकने
> *फुलाए हुए* मस्तिष्क के लिए, `fsaverage` की ओर morph करें (`morph_to_fsaverage`) फिर
> `subject="fsaverage"` के साथ आलेखित करें।

---

## जो सत्यापित किया गया

पाइपलाइन **सार्वजनिक wrapper के माध्यम से आद्योपांत** MNE के `sample` डेटासेट (वास्तविक
शारीरिकी, EDF में वास्तविक EEG) पर चलाया गया, `status: ok`:

| जाँच | परिणाम |
|---|---|
| को-रजिस्ट्रेशन (मेश तंत्र, MNE) | माध्यिका अवशेष **1.85 mm** |
| FEM फ़ॉरवर्ड | **10000 कॉर्टिकल स्रोत × 60 चैनल**, परिमित गेन |
| EEG | 17 बायीं श्रवण epoch औसतित (EDF) |
| dSPM इनवर्स | ऑपरेटर + अनुमान OK |
| आउटपुट | `sample-lh.stc` / `-rh.stc` |
| शिखर (बायाँ श्रवण उद्दीपन) | **बायाँ गोलार्ध**, पार्श्व (−55, −35, 34) mm |

शिखर बायाँ-पार्श्व है, श्रवण अनुक्रिया के लिए शारीरिक रूप से प्रशंसनीय।

**एक वास्तविक नैदानिक DICOM पर भी सत्यापित** (T1w शृंखला, 384 स्लाइस, 0.7 mm): सम्पूर्ण
`reconstruct_sources(dicom_dir=...)` शृंखला — अनामीकरण → रूपांतरण → DICOM से प्राप्त T1
पर `charm` → मेश → को-रजिस्ट्रेशन → FEM लीडफ़ील्ड → dSPM — बिना अड़चन चलती है,
`status: ok`, कॉर्टिकल आउटपुट `-lh/-rh.stc`। प्रयुक्त EEG जान-बूझकर असंबद्ध था (*पाइपिंग*
का सत्यापन, स्थानीयकरण का नहीं)। इस मशीन पर मापा गया **शुद्ध** गणना समय (एकल-थ्रेड):
इस उच्च-रिज़ॉल्यूशन T1 पर `charm` ≈ 2 घंटे, FEM लीडफ़ील्ड ≈ 18 मिनट, शेष < 1 मिनट।

**डेटा के अभाव में असत्यापित:** **उसी** विषय से DICOM + **वास्तविक डिजिटलीकरण**
(Polhemus/CapTrak) का युग्म। बैच से पहले **एक** विषय पर पहला पास करें।

सत्यापन दोहराने के लिए (एक `charm` आउटपुट आवश्यक):

```powershell
python examples/run_full_pipeline_sample.py <m2m_sampleE2E-का-पथ> <scratch>
```

---

## जानने योग्य सीमाएँ

**रूट के अनुसार दो स्रोत तंत्र।** FEM रूट (डिफ़ॉल्ट) स्रोतों को कॉर्टिकल सतह (माध्य धूसर
पदार्थ, lh+rh) पर रखता है; BEM रूट (`head_model: bem`) उन्हें आयतन में रखता है। दोनों
प्रलेखित, प्रकाशन-योग्य विधियाँ हैं; अपने विश्लेषण के अनुसार चुनें।

**को-रजिस्ट्रेशन कमज़ोर कड़ी है, शारीरिकी नहीं।** सावधान डिजिटलीकरण और संरेखण की दृश्य
जाँच के साथ, स्थिति अच्छी रहती है। डिजिटलीकरण के बिना, सटीकता गिरती है।

**एक T2 छवि खोपड़ी को सुधारती है।** यदि आपके प्रोटोकॉल में एक शामिल है, तो
`simnibs.t2_template` सेट करें।

**गणना लागत।** FEM लीडफ़ील्ड ~800k नोड्स के मेश पर प्रति इलेक्ट्रोड एक तंत्र हल करता है।
60-256 इलेक्ट्रोड के लिए, 20 मिनट से ~2 घंटे मानें। Windows पर, सॉल्वर एकल प्रोसेस में
चलता है (`fem.cpus` को 1 पर बाध्य किया गया: SimNIBS का समांतरीकरण Windows के `spawn` के
साथ picklable नहीं है)।

---

## परीक्षण

```powershell
conda activate mri2mne
pytest tests -q
```

परीक्षण कॉन्फ़िगरेशन, DICOM अंतर्ग्रहण (शृंखला स्कोरर), EEG पठन / मॉन्टेज, शिखर
स्थानीयकरण, पूर्व-जाँच, wrapper आर्ग्युमेंट सत्यापन और विज़ुअलाइज़ेशन के
SimNIBS→FreeSurfer सेतु को कवर करते हैं। भारी चरण (charm, FEM लीडफ़ील्ड)
`examples/run_full_pipeline_sample.py` द्वारा वास्तविक डेटा पर सत्यापित होते हैं।

---

## संरचना

```
run_pipeline.py            बैच CLI प्रवेश बिंदु
config.example.yaml        टिप्पणीयुक्त कॉन्फ़िगरेशन
environment.yml            mri2mne वातावरण (संचालक)
src/mri2mne/
  config.py                YAML लोडिंग और सत्यापन
  paths.py                 विषय वृक्ष + चरण कैश
  anonymize.py             DICOM PHI + वैकल्पिक defacing
  dicom_convert.py         DICOM → NIfTI + T1 शृंखला चयन
  headmodel.py             charm wrapper
  coregistration.py        डिजिटलीकरण + ICP (MNE Coregistration)
  simnibs_mesh.py          मेश से खोपड़ी + फ़िड्यूशियल निष्कर्षण (संचालक)
  simnibs_forward.py       SimNIBS FEM फ़ॉरवर्ड (संचालक)
  _simnibs_fem_helper.py   leadfield + make_forward (simnibs_env में चलता है)
  _simnibs_mesh_helper.py  crop_mesh + फ़िड्यूशियल (simnibs_env में चलता है)
  eeg.py                   EEG पठन, पूर्वप्रसंस्करण, सहप्रसरण
  inverse.py               इनवर्स ऑपरेटर + स्रोत अनुमान (सतह)
  viz.py                   SimNIBS→FreeSurfer सेतु + MNE 3D विज़ुअलाइज़ेशन
  wsl.py                   WSL2 सेतु (वॉल्यूमेट्रिक रूट): पथ, निष्पादक, प्रोब
  freesurfer_bem.py        WSL के माध्यम से autorecon1 + watershed (वॉल्यूमेट्रिक रूट)
  volumetric.py            3-परत BEM + स्रोत स्थान + वॉल्यूमेट्रिक फ़ॉरवर्ड/इनवर्स
  wrapper.py               reconstruct_sources[/_volumetric]() : MRI+EEG -> स्रोत
  preflight.py             बैच शुरू करने से पहले की जाँचें
  qc.py                    HTML रिपोर्ट
  pipeline.py              प्रति विषय ऑर्केस्ट्रेशन (बैच)
  batch.py                 विषय खोज + समांतरता
examples/
  run_full_pipeline_sample.py   वास्तविक डेटा पर सतह आद्योपांत सत्यापन
  run_volumetric_sample.py      वॉल्यूमेट्रिक रूट (BEM/WSL) आद्योपांत
  open_source_viewer.py         संसाधित विषय के लिए इंटरैक्टिव 3D विंडो
```
