> 🌍 [Français](README.md) · [English](README.en.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [Español](README.es.md) · **العربية**

# التصوير بالرنين المغناطيسي ← MNE: تحليل مصادر EEG القشرية (SimNIBS FEM، أصيل على Windows)

[![Tests](https://github.com/MaximeBedoin/mri2mne/actions/workflows/tests.yml/badge.svg)](https://github.com/MaximeBedoin/mri2mne/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![Docs](https://img.shields.io/badge/docs-tutorials-brightgreen.svg)](https://maximebedoin.github.io/mri2mne/tutorials/index.en.html)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21513347.svg)](https://doi.org/10.5281/zenodo.21513347)

خط معالجة كامل ينطلق من **تصوير بالرنين المغناطيسي بصيغة DICOM** + **تسجيل EEG** ليصل
إلى **تقدير المصادر القشرية** باستخدام MNE-Python. يُدار ببايثون، ويعمل بصورة أصيلة على
Windows، **دون FreeSurfer، دون WSL، دون Docker**. (يُوصف أدناه مسار حجمي BEM اختياري؛
وهو يستخدم WSL + FreeSurfer.)

بُنِيت الطريقة بالكامل على مكتبات **راسخة وقابلة للاستشهاد**: التجزئة والمسألة الأمامية
**FEM** بواسطة **SimNIBS** (`charm`، `compute_tdcs_leadfield`، `make_forward`)،
والتسجيل المشترك والمسألة العكسية بواسطة **MNE-Python**. شيفرة هذا المستودع ليست سوى
التنسيق بين الاثنين.

احسب **~1.5 ساعة لكل مشارك** لأجل `charm` + **~20-40 دقيقة** لأجل leadfield الخاص بـ
FEM، بدلاً من 10-20 ساعة لـ `recon-all`.

> 📚 **دروس مصوّرة** — خطوة بخطوة، مع صورة **لكل مرحلة** (T1، تقسيم الأنسجة، EEG،
> الاستجابة المُحرَّضة، التسجيل المشترك ثلاثي الأبعاد، المصادر القشرية):
> **[maximebedoin.github.io/mri2mne/tutorials](https://maximebedoin.github.io/mri2mne/tutorials/index.en.html)** (بالإنجليزية/الفرنسية، بعد تفعيل **GitHub Pages**).
> أو افتح `docs/tutorials/index.en.html` محليًا.

> ⚠️ **`pip install mri2mne` يثبّت طبقة التنسيق بلغة Python** (خط المعالجة + اعتمادياته).
> أما الأدوات الثقيلة — **SimNIBS/`charm`** و**FreeSurfer** و**WSL2** — فتبقى
> **متطلبات نظام** تُثبَّت بشكل منفصل (انظر قسم «التثبيت» أدناه).

---

## المدخل ← المخرج، في جملة واحدة

**ننطلق من** التصوير التشريحي بالرنين المغناطيسي للمريض بصيغة DICOM + تسجيل EEG (بصيغة
EDF أو غيرها) + رقمنة الأقطاب. **نصل إلى** تقدير مصادر EEG على **القشرة الدماغية**: تحديد
موضع النشاط المقيس، مع morph إلى `fsaverage` لأجل التحليل الجماعي.

## ماذا يُنتج خط المعالجة

لكل مشارك، في `derivatives/<المشارك>/mne/`:

| الملف | المحتوى |
|---|---|
| `<المشارك>-trans.fif` | التسجيل المشترك رأس ↔ رنين مغناطيسي |
| `<المشارك>-fwd.fif` | مسألة أمامية **FEM** على فضاء المصادر **القشري** (lh+rh) |
| `<المشارك>-noise-cov.fif` | تباين الضوضاء |
| `<المشارك>-inv.fif` | المؤثر العكسي |
| `<المشارك>-lh.stc` / `-rh.stc` | **تقدير المصادر القشرية** — الناتج النهائي |
| `<المشارك>-morph.h5` | morph إلى `fsaverage` (التحليل الجماعي) |

مستويان للاستخدام:

* **`reconstruct_sources()`** (مشارك واحد، انظر أدناه) ينتقل من الرنين المغناطيسي+EEG
  حتى تقدير المصادر.
* **`run_pipeline.py`** (دفعة) يسلسل التحويل ← `charm` ← التسجيل المشترك ← المسألة
  الأمامية FEM لعدد N من المشاركين؛ أما المسألة العكسية (المعتمدة على بيانات EEG)
  فتُنجَز بعد ذلك عبر الـ wrapper.

---

## مثال من الطرف إلى الطرف (مجلد `data/`)

يتضمّن المستودع مثالاً جاهزاً للاستخدام في [`data/`](data/README.en.md): مريض واحد لديه
رنين مغناطيسي DICOM + EEG + رقمنة (بالإضافة إلى ثانٍ لأجل الدفعة).

```
data/
  patient01/
    dicom/                 # سلسلة رنين مغناطيسي T1w (DICOM)
    patient01_eeg.edf      # EEG
    patient01_dig.fif      # رقمنة الأقطاب
    patient01-eve.fif      # الأحداث
  patient02/               # نفسه (لأجل الدفعة)
  config.batch.yaml        # إعداد دفعة جاهز للاستخدام
  README.md                # تفصيل البنية والمصدر
```

**مصدر الملفات** (التفصيل في [data/README.en.md](data/README.en.md)):

| الملف | المنشأ | الطبيعة |
|---|---|---|
| `dicom/` | مجموعة بيانات عامة `datalad/example-dicom-structural` (`PatientIdentityRemoved=YES`) | رنين مغناطيسي T1w حقيقي، **مُجهَّل الهوية** |
| `*_eeg.edf`، `*_dig.fif`، `*-eve.fif` | مجموعة `sample` الخاصة بـ **MNE-Python** | EEG + رقمنة لمشارك **آخر** |
| `patient02/` | نسخة من `patient01` | لعرض الدفعة فقط |

> ⚠️ يأتي كل من EEG والرنين المغناطيسي من **مشاركَين مختلفَين**: فهما **بديلان** لتوضيح
> بنية المجلدات والأوامر. تعمل السلسلة حتى نهايتها، لكن **النتيجة بلا أي معنى سريري**.
> بالنسبة لمشارك حقيقي، يجب أن يأتي EEG والرقمنة من **نفس** المريض الذي أتى منه الرنين
> المغناطيسي.

### تشغيل مفرد — مريض واحد، والمخرجات تُحفظ ضمن مجلد المريض

سطحي (FEM، أصيل على Windows):

```python
from mri2mne.wrapper import reconstruct_sources

reconstruct_sources(
    subject="patient01",
    output_dir="data/patient01/surface",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- استبدله بمسارك
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/surface/patient01/mne/patient01-lh.stc  (+ -rh.stc)
```

حجمي (BEM، عبر WSL + FreeSurfer):

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

### دفعة — عدة مرضى، أمر واحد

> **قبل التشغيل**: حرِّر [`data/config.batch.yaml`](data/config.batch.yaml) واستبدل
> `simnibs.bin_dir` (النائب `C:/Users/YOUR_NAME/...`) بمجلد `Scripts` الخاص بـ
> `simnibs_env` لديك. يتحقق `--check` من ذلك ويُبلِّغ عن خطأ واضح إذا ظلّ المسار هو
> النائب.

```powershell
python run_pipeline.py --config data/config.batch.yaml --check   # يتحقق من الأدوات + المدخلات
python run_pipeline.py --config data/config.batch.yaml
```

يختار الحقل `head_model` في الإعداد (`fem` أو `bem`) المسار؛ وتذهب مخرجات الدفعة إلى
`data/_batch_derivatives/`. وتُنجَز المسألة العكسية لـ EEG بعد ذلك لكل مشارك بالـ
wrapper المقابل.

> يأتي EEG/الرقمنة في المثال من مشارك **آخر** غير صاحب الرنين المغناطيسي (بديلان للعرض):
> تعمل السلسلة، لكن النتيجة بلا معنى سريري. انظر [data/README.en.md](data/README.en.md).

---

## البنية المعمارية: بيئتان

يستخدم خط المعالجة **بيئتَي conda**:

* **`mri2mne`** — يدير كل شيء (هذا المستودع). لا يستورد `simnibs` **أبداً**.
* **`simnibs_env`** — SimNIBS 4.6 + MNE. ينفِّذ الخطوات الخاصة بـ SimNIBS، ويستدعيها
  `mri2mne` كـ **عمليات فرعية**.

هذا ما يتيح استخدام SimNIBS وMNE بإصداريهما الأصيلين دون تعارض في التبعيات (لا سيما
numpy).

### الخطوات، والمكتبة وراء كل واحدة

| # | الخطوة | الدالة | المكتبة |
|---|---|---|---|
| 1 | DICOM ← NIfTI + تجهيل الهوية + اختيار T1 | `dcm2niix`، `pydicom` | — |
| 2 | التجزئة + شبكة FEM + السطوح القشرية | `charm` | SimNIBS |
| 3a | سطح فروة الرأس (لأجل ICP) | `mesh.crop_mesh` | SimNIBS |
| 3b | النقاط المرجعية للمشارك | `read_csv_positions` | SimNIBS |
| 3c | محاذاة النقاط المرجعية + ICP | `Coregistration` | MNE |
| 4a | مخطط الأقطاب ← المشارك | `prepare_montage` | SimNIBS |
| 4b | leadfield الخاص بـ FEM (التبادلية) | `compute_tdcs_leadfield` | SimNIBS |
| 4c | التحويل إلى `mne.Forward` (+ morph لـ fsaverage) | `make_forward` | SimNIBS |
| 5 | EEG: القراءة، الترشيح، التباين | `mne.io`، `compute_covariance` | MNE |
| 6 | المؤثر العكسي + التطبيق | `make_inverse_operator`، `apply_inverse` | MNE |

الإطار الإحداثي: يُعامَل عالَم شبكة SimNIBS كإطار "MRI" الخاص بـ MNE، ما يتيح إعادة
استخدام `Coregistration` دون تحويل.

---

## دالة الـ wrapper: من الرنين المغناطيسي+EEG إلى المصادر، باستدعاء واحد

```python
from mri2mne.wrapper import reconstruct_sources

result = reconstruct_sources(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # أو t1_path="..." لـ T1 جاهز
    eeg_file="D:/eeg/patient01.edf",         # .edf .bdf .vhdr .set .fif ...
    digitization="D:/dig/patient01.elc",     # مواضع الأقطاب
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- استبدله بمسارك
    events="find",                            # يكتشف المشغِّلات؛ أو مصفوفة / -eve.fif
    event_id={"spike": 1},
    tmin=-0.2, tmax=0.5,
    inverse_method="dSPM",                    # أو MNE / sLORETA / eLORETA
)

print(result.source_estimate_file)   # ...-lh.stc
print(result.peak)                    # الذروة: زمن + نصف كرة + موضع (mm)
stc = result.stc                      # SourceEstimate قشري في الذاكرة
```

الوسائط الرئيسية (لبقيتها قيم افتراضية معقولة):

| المجموعة | الوسائط |
|---|---|
| التشريح | `dicom_dir` **أو** `t1_path`، `t2_path` |
| EEG | `eeg_file`، `digitization` |
| SimNIBS | `simnibs_bin_dir` (مجلد Scripts الخاص بـ `simnibs_env`) |
| المسألة الأمامية FEM | `fem_subsampling` (مصادر قشرية لكل نصف كرة)، `fem_cpus`، `morph_to_fsaverage` |
| التسجيل المشترك | `icp_iterations`، `omit_distance_mm` |
| معالجة EEG | `l_freq`، `h_freq`، `eeg_reference`، `events`، `event_id`، `tmin`، `tmax`، `baseline`، `reject`، `noise_cov_tmin/tmax` |
| المسألة العكسية | `inverse_method`، `snr` |

`reconstruct_sources()` لا يرمي استثناءً أبداً عند حدوث خطأ في المعالجة: بل يُعيد
`SourceResult` بحالة `status="failed"` مع الرسالة، ليبقى آمناً للاستدعاء داخل حلقة.
وتُتخطّى المراحل المحسوبة مسبقاً (الاستئناف بحسب وجود الملفات؛ استخدم `force=[...]` لإعادة
الحساب).

> بديل: مُشكِّل الحزمة LCMV (`mne.beamformer.make_lcmv`) كثير الاستخدام سريرياً؛ وسيكون
> امتداداً مباشراً لـ `inverse.py`.

---

## مسار بديل: مصادر حجمية (BEM، WSL2 + FreeSurfer)

إضافة إلى المسار السطحي FEM (الافتراضي، 100% Windows)، يوفِّر المستودع **مساراً ثانياً
حجمياً**، مبنياً على **BEM ثلاثي الطبقات من FreeSurfer** — طريقة BEM المعيارية المعترف
بها سريرياً. تملأ المصادر حجم الدماغ (شبكة ثلاثية الأبعاد) بدلاً من القشرة، والمخرج هو
`VolSourceEstimate` (`-vl.stc`) يُقرأ كـ **طبقة فوق الرنين المغناطيسي** (مقاطع).

المساران **مستقلان ومتكاملان** (إطارا إحداثيات مختلفان، ملفات مختلفة). ومجدداً، كل حساب
هو استدعاء لمكتبة: FreeSurfer `recon-all -autorecon1` / `mri_watershed`؛ وMNE
`make_bem_solution` / `setup_volume_source_space` / `make_forward_solution` /
`make_inverse_operator`.

### المتطلبات المسبقة: WSL2 + FreeSurfer

بما أن FreeSurfer خاص بـ Linux، يشغِّله هذا المسار داخل **WSL2** (يبقى المُشغِّل على
Windows ويستدعيه كعملية فرعية، مثل SimNIBS).

```powershell
wsl --install            # WSL2 + Ubuntu، إن لم يكن موجوداً بعد
```

ثم، في طرفية Ubuntu، ثبِّت FreeSurfer 7.x عبر **tarball** الخاص به (يُوصى به على
Ubuntu 24.04):

```bash
sudo apt install -y tcsh          # مطلوب لسكربتات FreeSurfer
cd ~ && wget https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
sudo tar -C /usr/local -xzf freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
# ترخيص مجاني: https://surfer.nmr.mgh.harvard.edu/registration.html
cp /mnt/c/path/to/license.txt $FREESURFER_HOME/license.txt
```

خصِّص نحو 20 غيغابايت للتثبيت. تحقَّق من بايثون:
`from mri2mne import wsl; print(wsl.check_freesurfer().describe())` يجب أن يُظهر
"... (licensed)".

### الاستخدام

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

result = reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # أو t1_path="..."
    eeg_file="D:/eeg/patient01.edf",
    digitization="D:/dig/patient01.elc",
    events="find", event_id={"spike": 1},
    pos_mm=5.0,                               # تباعد الشبكة الحجمية
    inverse_method="dSPM", snr=3.0,
)
print(result.source_estimate_file)   # ...-vl.stc
```

التكلفة: **~20 دقيقة/مشارك** على T1 نظيف — لا ساعات `recon-all` الكامل، الذي لا حاجة
إليه هنا.

**في الدفعة**، يكفي وضع `head_model: "bem"` في `config.yaml` (قسم `bem:` للإعدادات):
عندئذٍ يوجِّه `run_pipeline.py` خطوات `headmodel`/`coreg`/`forward` نحو FreeSurfer/BEM
بدلاً من SimNIBS/FEM، مع إعادة استخدام نفس المخبأ، ونفس `--check` (الذي يتحقق من WSL +
FreeSurfer)، ونفس ضبط الجودة. وتُنجَز المسألة العكسية لـ EEG بعدها عبر
`reconstruct_sources_volumetric`.

### تنبيه: جودة سطوح watershed

`mri_watershed` **حساس لجودة T1**. على T1 بحثي نظيف (1 مم) يعطي سطوحاً مغلقة ومتداخلة؛
وعلى بعض عمليات الاكتساب السريرية غير النمطية (مجال رؤية واسع، تباين غير معتاد) قد تتقاطع
الجمجمة مع نفسها. يكتشف خط المعالجة هذه الحالة **ويُبلِّغ عنها**
(`volumetric.check_bem_surfaces`) برسالة واضحة بدلاً من الانهيار — يحتاج المشارك عندئذٍ
إلى ضبط جودة للسطوح أو إلى T1 أنظف. وللحصول على قشرة ثلاثية الأبعاد واضحة في التصوّر،
فضِّل **المسار السطحي** (فذلك غرضه).

---

## التثبيت

### 1. `simnibs_env` — SimNIBS 4 (يوفِّر `charm` + حَلَّال FEM)

طريقة سطر الأوامر (مُتحقَّق منها هنا، دون نقر):

```powershell
curl -L -o environment_windows.yml https://github.com/simnibs/simnibs/releases/download/v4.6.0/environment_windows.yml
conda env create -f environment_windows.yml
conda activate simnibs_env
pip install https://github.com/simnibs/simnibs/releases/download/v4.6.0/simnibs-4.6.0-cp311-cp311-win_amd64.whl
pip install "mne>=1.6"     # مطلوب لـ make_forward (مخرج MNE)
```

تحقَّق: يجب أن يُظهر `charm --version` القيمة `4.6.0`. والمجلد
`…\envs\simnibs_env\Scripts` هو ما يُمرَّر إلى `simnibs_bin_dir`. (كذلك يعمل المُثبِّت
الرسومي الرسمي من <https://simnibs.github.io>؛ عندئذٍ يلزم `pip install mne` في
بايثونه.)

### 2. `mri2mne` — البيئة المُشغِّلة

```powershell
conda env create -f environment.yml
conda activate mri2mne
```

### 3. الإعداد

```powershell
copy config.example.yaml config.yaml
```

حرِّر `config.yaml`: مسارات البيانات، و`simnibs.bin_dir` (مجلد `Scripts` الخاص بـ
`simnibs_env`)، وقالب `paths.digitisation`.

### 4. (اختياري) التثبيت كحزمة pip

المستودع حزمة قابلة للتثبيت (`pyproject.toml`، مخطط `src/`). وهذه أبسط طريقة لنشره **دون
WSL**: إذ لا يعتمد المسار السطحي FEM ولا الدفعة إلا على مكتبات PyPI. من جذر المستودع:

```powershell
pip install mri2mne          # من PyPI (الأبسط)
pip install "mri2mne[viz]"   # + PyVista/VTK (ضبط جودة ثلاثي الأبعاد + عارض المصادر)
pip install "mri2mne[all]"   # + dcm2niix (ثنائي) + pytest

# …أو من نسخة من المستودع، للتطوير:
pip install -e ".[dev]"      # وضع التطوير (قابل للتحرير) + pytest
```

بعد التثبيت:

```python
from mri2mne.wrapper import reconstruct_sources   # قابل للاستيراد في كل مكان
```

ويتوفّر أمر الدفعة مباشرة (لم تعد هناك حاجة إلى `run_pipeline.py`):

```powershell
mri2mne --config config.yaml --check
mri2mne --config config.yaml
```

ما **لا** يشمله تثبيت pip، بحكم التصميم:

* **SimNIBS** (`charm` + حَلَّال FEM) يبقى في `simnibs_env` الخاصة به، يُستدعى كعملية
  فرعية (انظر §1) — ولا يُثبَّت أبداً في نفس بيئة المُشغِّل (تعارض numpy).
* **المسار الحجمي BEM** يتطلّب **FreeSurfer داخل WSL2** (متطلب على مستوى النظام، انظر
  أعلاه)؛ وهو لا يضيف أي تبعية بايثون. أما المسار السطحي فيُثبَّت ويعمل **بالكامل دون
  WSL**.

> يبقى `pip install .` ممكناً حتى دون SimNIBS أو WSL: تُستورَد المكتبة وتنجح
> الاختبارات؛ ولا تتطلّب هذه الأدوات وقت التشغيل إلا الخطوات التي تستدعي فعلاً
> `charm`/FreeSurfer.

---

## الاستخدام في دفعات

```powershell
# فحص مسبق: الأدوات، ملفات كل مشارك، مساحة القرص
python run_pipeline.py --config config.yaml --check

# معالجة الجميع
python run_pipeline.py --config config.yaml

# مجموعة جزئية
python run_pipeline.py --config config.yaml --subjects sub-001 sub-002

# إعادة تشغيل بعض المراحل بعد تغيير
python run_pipeline.py --config config.yaml --force coreg forward
```

التنظيم المتوقَّع:

```
dicom_root/
  sub-001/            <- مجلد لكل مشارك، وDICOM بداخله (تعاودياً)
digitisation/
  sub-001_electrodes.elc
```

صيغ الرقمنة المعترف بها: `.fif`، `.hsp`/`.elp` (Polhemus)، `.bvct` (CapTrak)، `.sfp`،
`.elc`، `.hpts`، `.csd`، `.xyz`. صيغ EEG: `.edf`، `.bdf`، `.vhdr` (BrainVision)،
`.set` (EEGLAB)، `.fif`، `.mff`، `.eeg`.

### الاستئناف والتخبئة

تسجِّل كل مرحلة بصمةً لمدخلاتها في `derivatives/<المشارك>/status.json`. وإعادة التشغيل
لا تُعيد حساب إلا ما تغيّر — والأهم أنها لا تُعيد تشغيل ساعة ونصف `charm` دون داعٍ.

### تحمُّل الأعطال

يحمي `continue_on_error` من الاستثناءات؛ وإذا مات **عملية** عاملة (عادةً قاتل نفاد
الذاكرة OOM على `charm`، 4-8 غيغابايت)، ترصد الدفعة ذلك و**تُعيد التشغيل تسلسلياً** بدلاً
من فقدان كل شيء. ويبقى الحل الحقيقي هو خفض `run.n_jobs`.

---

## ضبط الجودة

تقرير HTML لكل مشارك (`derivatives/<المشارك>/qc/`) وملخّص دفعة، مع المقاييس، وبقية
التسجيل المشترك، وشكل المحاذاة ثلاثي الأبعاد.

**انظر إلى محاذاة الأقطاب/فروة الرأس قبل استثمار النتائج.** فبقية منخفضة لـ dig←فروة
الرأس لا تضمن مطابقة جيدة: على فروة رأس ملساء، قد ينزلق ICP سنتيمتراً كاملاً مع إبقاء
النقاط قرب السطح. وما يُثبِّت المطابقة هو النقاط المرجعية — التي يوفِّرها `charm` في فضاء
المشارك.

المعالجة اليدوية لمشارك مُعلَّم:

```powershell
conda activate mri2mne
mne coreg --subject sub-001 --subjects-dir D:\data\derivatives\subjects
```

احفظ النقاط المرجعية المُصحَّحة في `subjects/<المشارك>/bem/<المشارك>-fiducials.fif`، ثم
أعِد التشغيل بـ `--force coreg forward`.

---

## تصوّر المصادر

يأتي فضاء المصادر من SimNIBS (السطح القشري *المركزي*)، لا من FreeSurfer — بينما يتوقّع
`stc.plot()` في MNE شجرة `subjects_dir/<المشارك>/surf/lh.white`. تقوم الوحدة
`mri2mne.viz` بدور **الجسر**: تكتب شبكة SimNIBS (`-src.fif`) مرةً واحدة بصيغة FreeSurfer،
وبعدها تعمل **كل أدوات MNE الأصيلة ثلاثية الأبعاد** (نافذة تدور بالفأرة، شريط زمن، أفلام،
مسارات زمنية بحسب المنطقة) كما هي. إنه MNE + SimNIBS، ومن ثمّ قابل للاستشهاد، دون أي شيفرة
تصيير منزلية.

**نافذة تفاعلية** (تدوير/تكبير/زمن بالفأرة)، من سكربت:

```powershell
conda activate mri2mne
python examples/open_source_viewer.py D:/derivatives patient01 --time 0.1
```

أو في بايثون:

```python
from mri2mne.viz import open_viewer, block_on_viewer
brain = open_viewer("D:/derivatives", "patient01", initial_time=0.1)
block_on_viewer()   # يُبقي النافذة مفتوحة حتى تُغلَق
```

**شكل ثابت** (تصيير *خارج الشاشة*، لتقرير أو لجهاز بلا شاشة):

```python
from pathlib import Path
from mri2mne.paths import SubjectPaths
from mri2mne.viz import save_views

paths = SubjectPaths("patient01", Path("D:/derivatives"),
                     Path("D:/derivatives/subjects"))
save_views(paths, "patient01_sources.png", initial_time=0.1,
           views=("lateral", "medial", "dorsal"), hemi="lh")
```

الواجهة البرمجية: `write_freesurfer_surfaces(paths)` (الجسر، عديم التأثير عند التكرار)،
`plot_sources(paths, ...)` (يُعيد `mne.viz.Brain`)، `open_viewer(...)` (اختصار من
`output_dir`+`subject`)، `save_views(...)` (صورة PNG متعددة المشاهد).

> `surface="inflated"` مطابق لـ `white` (لا يُنفِّخ SimNIBS السطوح). وللدماغ *المُنفَّخ*
> الأملس المعياري، طبِّق morph إلى `fsaverage` (`morph_to_fsaverage`) ثم ارسم بـ
> `subject="fsaverage"`.

---

## ما جرى التحقّق منه

شُغِّل خط المعالجة **من الطرف إلى الطرف عبر الـ wrapper العمومي** على مجموعة `sample`
الخاصة بـ MNE (تشريح حقيقي، وEEG حقيقي بصيغة EDF)، بحالة `status: ok`:

| الفحص | النتيجة |
|---|---|
| التسجيل المشترك (إطار الشبكة، MNE) | بقية وسيطة **1.85 مم** |
| المسألة الأمامية FEM | **10000 مصدر قشري × 60 قناة**، كسب منتهٍ |
| EEG | 17 حقبة سمعية يسرى مُتوسَّطة (EDF) |
| المسألة العكسية dSPM | المؤثر + التقدير سليمان |
| المخرج | `sample-lh.stc` / `-rh.stc` |
| الذروة (تنبيه سمعي أيسر) | **نصف الكرة الأيسر**، جانبي (−55، −35، 34) مم |

الذروة جانبية يسرى، وهي معقولة تشريحياً لاستجابة سمعية.

**كذلك جرى التحقّق على DICOM سريري حقيقي** (سلسلة T1w، 384 مقطعاً، 0.7 مم): تسير سلسلة
`reconstruct_sources(dicom_dir=...)` الكاملة — تجهيل الهوية ← التحويل ← `charm` على T1
المستخلص من DICOM ← الشبكة ← التسجيل المشترك ← leadfield الخاص بـ FEM ← dSPM — دون
عائق، بحالة `status: ok`، ومخرج قشري `-lh/-rh.stc`. وكان EEG المستخدم غير ذي صلة عمداً
(تحقّق من *السباكة*، لا من تحديد الموضع). زمن الحساب **الصافي** المقيس على هذا الجهاز
(خيط واحد): `charm` ≈ ساعتان على T1 عالي الدقة هذا، وleadfield الخاص بـ FEM ≈ 18 دقيقة،
والبقية < دقيقة واحدة.

**لم يُتحقّق منه لعدم توفّر البيانات:** زوج من DICOM + **رقمنة حقيقية** (Polhemus/CapTrak)
من **نفس** المشارك. أجرِ تمريرة أولى على **مشارك واحد** قبل الدفعة.

لإعادة تشغيل التحقّق (يتطلّب مخرج `charm`):

```powershell
python examples/run_full_pipeline_sample.py <مسار-m2m_sampleE2E> <scratch>
```

---

## قيود ينبغي معرفتها

**إطارا مصادر بحسب المسار.** يضع المسار FEM (الافتراضي) المصادر على السطح القشري (المادة
الرمادية الوسطى، lh+rh)؛ ويضعها المسار BEM (`head_model: bem`) في الحجم. وكلاهما طريقة
موثَّقة وقابلة للنشر؛ فاختر بحسب تحليلك.

**التسجيل المشترك هو الحلقة الأضعف، لا التشريح.** مع رقمنة دقيقة وتحقّق بصري من المحاذاة،
تكون الحال جيدة. ومن دون رقمنة، تنخفض الدقّة.

**صورة T2 تُحسِّن الجمجمة.** إن تضمّنت بروتوكولاتك واحدة، فحدِّد `simnibs.t2_template`.

**تكلفة الحساب.** يحلّ leadfield الخاص بـ FEM نظاماً لكل قطب على شبكة من ~800 ألف عقدة.
لأجل 60-256 قطباً، احسب من 20 دقيقة إلى ~2 ساعة. على Windows، يعمل الحَلَّال في عملية
واحدة (`fem.cpus` مُثبَّت على 1: توازي SimNIBS غير قابل للـ pickle مع `spawn` في
Windows).

---

## الاختبارات

```powershell
conda activate mri2mne
pytest tests -q
```

تغطّي الاختبارات الإعداد، وابتلاع DICOM (مُقيِّم السلاسل)، وقراءة EEG / المخطط، وتحديد
موضع الذروة، والفحوص المسبقة، والتحقّق من وسائط الـ wrapper، وجسر SimNIBS→FreeSurfer
الخاص بالتصوّر. أما المراحل الثقيلة (charm، وleadfield الخاص بـ FEM) فيتحقّق منها
`examples/run_full_pipeline_sample.py` على بيانات حقيقية.

---

## البنية

```
run_pipeline.py            نقطة دخول CLI للدفعة
config.example.yaml        إعداد معلَّق عليه
environment.yml            بيئة mri2mne (المُشغِّل)
src/mri2mne/
  config.py                تحميل YAML والتحقّق منه
  paths.py                 شجرة المشارك + تخبئة المراحل
  anonymize.py             معلومات PHI في DICOM + إخفاء الوجه اختيارياً
  dicom_convert.py         DICOM ← NIfTI + اختيار سلسلة T1
  headmodel.py             wrapper لـ charm
  coregistration.py        الرقمنة + ICP (MNE Coregistration)
  simnibs_mesh.py          استخلاص فروة الرأس + النقاط المرجعية من الشبكة (مُشغِّل)
  simnibs_forward.py       المسألة الأمامية FEM لـ SimNIBS (مُشغِّل)
  _simnibs_fem_helper.py   leadfield + make_forward (يعمل في simnibs_env)
  _simnibs_mesh_helper.py  crop_mesh + النقاط المرجعية (يعمل في simnibs_env)
  eeg.py                   قراءة EEG، المعالجة المسبقة، التباين
  inverse.py               المؤثر العكسي + تقدير المصادر (سطحي)
  viz.py                   جسر SimNIBS→FreeSurfer + تصوّر MNE ثلاثي الأبعاد
  wsl.py                   جسر WSL2 (المسار الحجمي): المسارات، المُنفِّذ، المسبار
  freesurfer_bem.py        autorecon1 + watershed عبر WSL (المسار الحجمي)
  volumetric.py            BEM ثلاثي الطبقات + فضاء المصادر + المسألتان الأمامية/العكسية الحجميتان
  wrapper.py               reconstruct_sources[/_volumetric]() : رنين مغناطيسي+EEG -> مصادر
  preflight.py             فحوص قبل إطلاق الدفعة
  qc.py                    تقارير HTML
  pipeline.py              التنسيق لكل مشارك (دفعة)
  batch.py                 اكتشاف المشاركين + التوازي
examples/
  run_full_pipeline_sample.py   تحقّق سطحي من الطرف إلى الطرف على بيانات حقيقية
  run_volumetric_sample.py      المسار الحجمي (BEM/WSL) من الطرف إلى الطرف
  open_source_viewer.py         نافذة ثلاثية الأبعاد تفاعلية لمشارك معالَج
```
