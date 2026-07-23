> 🌍 [Français](README.md) · [English](README.en.md) · **中文** · [हिन्दी](README.hi.md) · [Español](README.es.md) · [العربية](README.ar.md)

# MRI → MNE：皮层 EEG 源分析（SimNIBS FEM，Windows 原生）

从 **DICOM 格式的 MRI** + **EEG 记录**到用 MNE-Python 进行**皮层源估计**的完整流水线。
用 Python 驱动，在 Windows 上原生运行，**无需 FreeSurfer、无需 WSL、无需 Docker**。
（下文介绍一条可选的体积 BEM 路线；那条路线确实会用到 WSL + FreeSurfer。）

该方法完全建立在**成熟且可引用的**库之上：分割和 **FEM** 正问题由 **SimNIBS** 完成
（`charm`、`compute_tdcs_leadfield`、`make_forward`），配准和逆问题由 **MNE-Python** 完成。
本仓库的代码只是二者之间的编排。

每位受试者预计 `charm` 约 **1.5 小时**，FEM leadfield 约 **20-40 分钟**，
而不是 `recon-all` 的 10-20 小时。

> 📚 **图解教程** —— 逐步展示**每个阶段**的配图（T1、组织分割、EEG、诱发响应、
> 三维配准、皮层源）：**[maximebedoin.github.io/mri2mne/tutorials](https://maximebedoin.github.io/mri2mne/tutorials/index.en.html)**（英文/法文，需先启用 **GitHub Pages**）。
> 或在本地打开 `docs/tutorials/index.en.html`。

---

## 输入 → 输出，一句话概括

**从**患者的 DICOM 解剖 MRI + EEG 记录（EDF 或其他）+ 电极数字化开始。
**得到**大脑**皮层**上的 EEG 源估计：所测活动的定位，外加一个到 `fsaverage` 的 morph
以便进行组分析。

## 流水线产出什么

对每位受试者，在 `derivatives/<受试者>/mne/` 中：

| 文件 | 内容 |
|---|---|
| `<受试者>-trans.fif` | 头 ↔ MRI 配准 |
| `<受试者>-fwd.fif` | **皮层**源空间（lh+rh）上的 **FEM** 正问题 |
| `<受试者>-noise-cov.fif` | 噪声协方差 |
| `<受试者>-inv.fif` | 逆算子 |
| `<受试者>-lh.stc` / `-rh.stc` | **皮层源估计** —— 最终交付物 |
| `<受试者>-morph.h5` | 到 `fsaverage` 的 morph（组分析） |

两个使用层次：

* **`reconstruct_sources()`**（单个受试者，见下文）从 MRI+EEG 一直走到源估计。
* **`run_pipeline.py`**（批处理）为 N 个受试者串联 转换 → `charm` → 配准 → FEM 正问题；
  逆问题（取决于 EEG 数据）随后通过 wrapper 完成。

---

## 端到端示例（`data/` 文件夹）

仓库在 [`data/`](data/README.en.md) 中附带了一个开箱即用的示例：一位带有
MRI DICOM + EEG + 数字化的患者（外加第二位用于批处理）。

```
data/
  patient01/
    dicom/                 # T1w MRI 序列（DICOM）
    patient01_eeg.edf      # EEG
    patient01_dig.fif      # 电极数字化
    patient01-eve.fif      # 事件
  patient02/               # 相同（用于批处理）
  config.batch.yaml        # 开箱即用的批处理配置
  README.md                # 结构与来源的详细说明
```

**文件来源**（详见 [data/README.en.md](data/README.en.md)）：

| 文件 | 出处 | 性质 |
|---|---|---|
| `dicom/` | 公共数据集 `datalad/example-dicom-structural`（`PatientIdentityRemoved=YES`） | 真实的 T1w MRI，**已匿名化** |
| `*_eeg.edf`、`*_dig.fif`、`*-eve.fif` | **MNE-Python** 的 `sample` 数据集 | **另一位**受试者的 EEG + 数字化 |
| `patient02/` | `patient01` 的副本 | 仅用于演示批处理 |

> ⚠️ EEG 与 MRI 来自**不同的受试者**：它们是用来说明文件夹结构和命令的**替代品**。
> 整条链路能跑到底，但**结果没有任何临床意义**。对于真实受试者，EEG 和数字化必须与 MRI
> 来自**同一位**患者。

### 单次运行 —— 一位患者，输出存放在该患者目录下

表面（FEM，Windows 原生）：

```python
from mri2mne.wrapper import reconstruct_sources

reconstruct_sources(
    subject="patient01",
    output_dir="data/patient01/surface",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- 请替换为你的路径
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/surface/patient01/mne/patient01-lh.stc  (+ -rh.stc)
```

体积（BEM，通过 WSL + FreeSurfer）：

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

### 批处理 —— 多位患者，一条命令

> **运行前**：编辑 [`data/config.batch.yaml`](data/config.batch.yaml)，把
> `simnibs.bin_dir`（占位符 `C:/Users/YOUR_NAME/...`）替换为你的 `simnibs_env` 的
> `Scripts` 文件夹。`--check` 会检查它，如果路径仍是占位符会给出清晰的错误提示。

```powershell
python run_pipeline.py --config data/config.batch.yaml --check   # 检查工具 + 输入
python run_pipeline.py --config data/config.batch.yaml
```

配置中的 `head_model` 字段（`fem` 或 `bem`）选择路线；批处理输出进入
`data/_batch_derivatives/`。EEG 逆问题随后按受试者用相应的 wrapper 完成。

> 示例的 EEG/数字化来自与 MRI **不同**的受试者（用于演示的替代品）：链路能运行，
> 但结果没有临床意义。见 [data/README.en.md](data/README.en.md)。

---

## 架构：两个环境

流水线使用**两个 conda 环境**：

* **`mri2mne`** —— 驱动一切（本仓库）。**从不**导入 `simnibs`。
* **`simnibs_env`** —— SimNIBS 4.6 + MNE。执行 SimNIBS 专有步骤，由 `mri2mne` 以
  **子进程**方式调用。

正是这样才能使用 SimNIBS 和 MNE 各自的原生版本而不产生依赖冲突（尤其是 numpy）。

### 各步骤及其背后的库

| # | 步骤 | 函数 | 库 |
|---|---|---|---|
| 1 | DICOM → NIfTI + 匿名化 + T1 选择 | `dcm2niix`、`pydicom` | — |
| 2 | 分割 + FEM 网格 + 皮层表面 | `charm` | SimNIBS |
| 3a | 头皮表面（用于 ICP） | `mesh.crop_mesh` | SimNIBS |
| 3b | 受试者基准点 | `read_csv_positions` | SimNIBS |
| 3c | 基准点对齐 + ICP | `Coregistration` | MNE |
| 4a | 电极蒙太奇 → 受试者 | `prepare_montage` | SimNIBS |
| 4b | FEM leadfield（互易性） | `compute_tdcs_leadfield` | SimNIBS |
| 4c | 转换为 `mne.Forward`（+ fsaverage morph） | `make_forward` | SimNIBS |
| 5 | EEG：读取、滤波、协方差 | `mne.io`、`compute_covariance` | MNE |
| 6 | 逆算子 + 应用 | `make_inverse_operator`、`apply_inverse` | MNE |

坐标系：SimNIBS 网格世界被当作 MNE 的 “MRI” 坐标系，从而无需转换即可复用
`Coregistration`。

---

## Wrapper 函数：从 MRI+EEG 到源，一次调用

```python
from mri2mne.wrapper import reconstruct_sources

result = reconstruct_sources(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # 或 t1_path="..." 用于现成的 T1
    eeg_file="D:/eeg/patient01.edf",         # .edf .bdf .vhdr .set .fif ...
    digitization="D:/dig/patient01.elc",     # 电极位置
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- 请替换为你的路径
    events="find",                            # 检测触发；或一个数组 / -eve.fif
    event_id={"spike": 1},
    tmin=-0.2, tmax=0.5,
    inverse_method="dSPM",                    # 或 MNE / sLORETA / eLORETA
)

print(result.source_estimate_file)   # ...-lh.stc
print(result.peak)                    # 峰值：时间 + 半球 + 位置（mm）
stc = result.stc                      # 内存中的皮层 SourceEstimate
```

主要参数（其余均有合理默认值）：

| 组别 | 参数 |
|---|---|
| 解剖 | `dicom_dir` **或** `t1_path`、`t2_path` |
| EEG | `eeg_file`、`digitization` |
| SimNIBS | `simnibs_bin_dir`（`simnibs_env` 的 Scripts 文件夹） |
| FEM 正问题 | `fem_subsampling`（每半球皮层源数）、`fem_cpus`、`morph_to_fsaverage` |
| 配准 | `icp_iterations`、`omit_distance_mm` |
| EEG 处理 | `l_freq`、`h_freq`、`eeg_reference`、`events`、`event_id`、`tmin`、`tmax`、`baseline`、`reject`、`noise_cov_tmin/tmax` |
| 逆问题 | `inverse_method`、`snr` |

`reconstruct_sources()` 在处理出错时**从不抛出异常**：它返回一个带
`status="failed"` 和错误信息的 `SourceResult`，因此在循环中调用是安全的。已计算的
阶段会被跳过（按文件是否存在来续跑；用 `force=[...]` 重新计算）。

> 备选：LCMV 波束成形器（`mne.beamformer.make_lcmv`）在临床中常用；它将是
> `inverse.py` 的直接扩展。

---

## 备选路线：体积源（BEM，WSL2 + FreeSurfer）

除了表面 FEM 路线（默认，100% Windows）之外，仓库还提供**第二条体积路线**，
建立在 **FreeSurfer 的三层 BEM** 之上 —— 标准的、临床公认的 BEM 方法。源填充脑体积
（3D 网格）而非皮层，输出是一个 `VolSourceEstimate`（`-vl.stc`），可作为 MRI 上的
**叠加层**（切片）来查看。

两条路线**相互独立且互补**（坐标系不同、文件不同）。同样，一切计算都是库调用：
FreeSurfer `recon-all -autorecon1` / `mri_watershed`；MNE `make_bem_solution` /
`setup_volume_source_space` / `make_forward_solution` / `make_inverse_operator`。

### 前置条件：WSL2 + FreeSurfer

由于 FreeSurfer 仅限 Linux，此路线在 **WSL2** 内运行它（驱动器仍在 Windows 上，
以子进程方式调用它，与 SimNIBS 相同）。

```powershell
wsl --install            # 若尚未安装，则安装 WSL2 + Ubuntu
```

然后，在 Ubuntu 终端中，通过 **tarball** 安装 FreeSurfer 7.x（在 Ubuntu 24.04 上推荐）：

```bash
sudo apt install -y tcsh          # FreeSurfer 脚本所需
cd ~ && wget https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
sudo tar -C /usr/local -xzf freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
# 免费许可证：https://surfer.nmr.mgh.harvard.edu/registration.html
cp /mnt/c/path/to/license.txt $FREESURFER_HOME/license.txt
```

安装需预留约 20 GB。在 Python 中验证：
`from mri2mne import wsl; print(wsl.check_freesurfer().describe())` 应显示
“... (licensed)”。

### 用法

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

result = reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # 或 t1_path="..."
    eeg_file="D:/eeg/patient01.edf",
    digitization="D:/dig/patient01.elc",
    events="find", event_id={"spike": 1},
    pos_mm=5.0,                               # 体积网格间距
    inverse_method="dSPM", snr=3.0,
)
print(result.source_estimate_file)   # ...-vl.stc
```

代价：在干净的 T1 上**约 20 分钟/受试者** —— 而不是完整 `recon-all` 的数小时，
这里并不需要它。

**在批处理中**，只需在 `config.yaml` 中设置 `head_model: "bem"`（用 `bem:` 段落配置
参数）：`run_pipeline.py` 便会将 `headmodel`/`coreg`/`forward` 步骤路由到
FreeSurfer/BEM 而非 SimNIBS/FEM，同时复用相同的缓存、相同的 `--check`（它会检查
WSL + FreeSurfer）以及相同的 QC。EEG 逆问题随后通过 `reconstruct_sources_volumetric`
完成。

### 注意：watershed 表面质量

`mri_watershed` 对 **T1 质量敏感**。在干净的科研 T1（1 mm）上它给出闭合且嵌套的
表面；在某些非典型的临床采集（大 FOV、异常对比度）上，颅骨可能自相交。流水线会
**检测并标记**这种情况（`volumetric.check_bem_surfaces`），给出清晰的信息而不是崩溃 ——
此时该受试者需要表面 QC 或更干净的 T1。若要在可视化中得到清晰的 3D 皮层，请优先使用
**表面路线**（那正是它的用途）。

---

## 安装

### 1. `simnibs_env` —— SimNIBS 4（提供 `charm` + FEM 求解器）

命令行方法（此处已验证，无需点击）：

```powershell
curl -L -o environment_windows.yml https://github.com/simnibs/simnibs/releases/download/v4.6.0/environment_windows.yml
conda env create -f environment_windows.yml
conda activate simnibs_env
pip install https://github.com/simnibs/simnibs/releases/download/v4.6.0/simnibs-4.6.0-cp311-cp311-win_amd64.whl
pip install "mne>=1.6"     # make_forward（MNE 输出）所需
```

验证：`charm --version` 应显示 `4.6.0`。文件夹 `…\envs\simnibs_env\Scripts` 就是
传给 `simnibs_bin_dir` 的那个。（<https://simnibs.github.io> 的官方图形安装器也可用；
那样就需要在其 Python 中 `pip install mne`。）

### 2. `mri2mne` —— 驱动环境

```powershell
conda env create -f environment.yml
conda activate mri2mne
```

### 3. 配置

```powershell
copy config.example.yaml config.yaml
```

编辑 `config.yaml`：数据路径、`simnibs.bin_dir`（`simnibs_env` 的 `Scripts` 文件夹）
以及 `paths.digitisation` 模板。

### 4.（可选）作为 pip 包安装

本仓库是一个可安装的包（`pyproject.toml`，`src/` 布局）。这是**不用 WSL** 部署它的
最简单方式：表面 FEM 路线和批处理仅依赖 PyPI 上的库。在仓库根目录下：

```powershell
pip install .                # 安装包 + 其依赖
pip install ".[viz]"         # + PyVista/VTK（3D QC + 源查看器）
pip install ".[all]"         # + dcm2niix（二进制）+ pytest
pip install -e ".[dev]"      # 开发（可编辑）模式 + pytest
```

安装后：

```python
from mri2mne.wrapper import reconstruct_sources   # 到处都可导入
```

批处理命令也可直接使用（不再需要 `run_pipeline.py`）：

```powershell
mri2mne --config config.yaml --check
mri2mne --config config.yaml
```

pip 安装**按设计不**覆盖的内容：

* **SimNIBS**（`charm` + FEM 求解器）仍留在它自己的 `simnibs_env` 中，以子进程方式
  调用（见 §1）—— 绝不安装在与驱动器相同的环境里（numpy 冲突）。
* **体积 BEM 路线**需要 **WSL2 中的 FreeSurfer**（系统级前置条件，见上文）；它不增加
  任何 Python 依赖。而表面路线**完全不用 WSL** 即可安装并运行。

> 即便没有 SimNIBS 或 WSL，`pip install .` 依然可行：库能导入、测试能通过；只有真正
> 调用 `charm`/FreeSurfer 的步骤才在运行时需要这些工具。

---

## 批处理用法

```powershell
# 预检：工具、各受试者的文件、磁盘空间
python run_pipeline.py --config config.yaml --check

# 处理所有人
python run_pipeline.py --config config.yaml

# 一个子集
python run_pipeline.py --config config.yaml --subjects sub-001 sub-002

# 改动后重新运行某些阶段
python run_pipeline.py --config config.yaml --force coreg forward
```

预期的组织结构：

```
dicom_root/
  sub-001/            <- 每位受试者一个文件夹，DICOM 在其中（递归）
digitisation/
  sub-001_electrodes.elc
```

识别的数字化格式：`.fif`、`.hsp`/`.elp`（Polhemus）、`.bvct`（CapTrak）、`.sfp`、
`.elc`、`.hpts`、`.csd`、`.xyz`。EEG 格式：`.edf`、`.bdf`、`.vhdr`（BrainVision）、
`.set`（EEGLAB）、`.fif`、`.mff`、`.eeg`。

### 续跑与缓存

每个阶段都会在 `derivatives/<受试者>/status.json` 中记录其输入的指纹。重新运行只会
重算发生变化的部分 —— 尤其不会无谓地重跑约 1.5 小时的 `charm`。

### 容错

`continue_on_error` 防护异常；如果某个 worker **进程**死亡（通常是 `charm` 上的 OOM
杀手，4-8 GB），批处理会检测到并**改为顺序重放**，而不是全盘丢失。真正的修复仍是
调低 `run.n_jobs`。

---

## 质量控制

每位受试者一份 HTML 报告（`derivatives/<受试者>/qc/`）以及一份批处理汇总，包含各项
指标、配准残差和 3D 对齐图。

**在使用结果之前，请查看电极/头皮的对齐。** dig→头皮残差低并不保证贴合良好：在光滑
的头皮上，ICP 可能滑动一厘米却仍让各点靠近表面。真正钉住贴合的是基准点 —— `charm`
以受试者空间提供它们。

对被标记的受试者手动返工：

```powershell
conda activate mri2mne
mne coreg --subject sub-001 --subjects-dir D:\data\derivatives\subjects
```

将修正后的基准点保存到 `subjects/<受试者>/bem/<受试者>-fiducials.fif`，然后用
`--force coreg forward` 重新运行。

---

## 源可视化

源空间来自 SimNIBS（*中央*皮层表面），而非 FreeSurfer —— 但 MNE 的 `stc.plot()`
期望一个 `subjects_dir/<受试者>/surf/lh.white` 目录树。`mri2mne.viz` 模块充当**桥梁**：
它把 SimNIBS 网格（`-src.fif`）以 FreeSurfer 格式写入一次，此后 **MNE 全部原生的 3D
工具**（可用鼠标旋转的窗口、时间滑块、影片、按 ROI 的时间进程）都能照常工作。这是
MNE + SimNIBS，因此可引用，没有自制的渲染代码。

**交互窗口**（用鼠标旋转/缩放/调时间），从脚本运行：

```powershell
conda activate mri2mne
python examples/open_source_viewer.py D:/derivatives patient01 --time 0.1
```

或在 Python 中：

```python
from mri2mne.viz import open_viewer, block_on_viewer
brain = open_viewer("D:/derivatives", "patient01", initial_time=0.1)
block_on_viewer()   # 保持窗口打开直到被关闭
```

**静态图**（*离屏*渲染，用于报告或无显示器的机器）：

```python
from pathlib import Path
from mri2mne.paths import SubjectPaths
from mri2mne.viz import save_views

paths = SubjectPaths("patient01", Path("D:/derivatives"),
                     Path("D:/derivatives/subjects"))
save_views(paths, "patient01_sources.png", initial_time=0.1,
           views=("lateral", "medial", "dorsal"), hemi="lh")
```

API：`write_freesurfer_surfaces(paths)`（桥梁，幂等）、`plot_sources(paths, ...)`
（返回一个 `mne.viz.Brain`）、`open_viewer(...)`（从 `output_dir`+`subject` 的快捷方式）、
`save_views(...)`（多视角 PNG）。

> `surface="inflated"` 与 `white` 相同（SimNIBS 不对表面充气）。若要标准的光滑*充气*
> 大脑，请 morph 到 `fsaverage`（`morph_to_fsaverage`），然后用 `subject="fsaverage"`
> 绘制。

---

## 已验证的内容

流水线**通过公共 wrapper 端到端**运行于 MNE 的 `sample` 数据集（真实解剖、真实 EDF
格式 EEG），`status: ok`：

| 检查 | 结果 |
|---|---|
| 配准（网格坐标系，MNE） | 中位残差 **1.85 mm** |
| FEM 正问题 | **10000 个皮层源 × 60 通道**，增益有限 |
| EEG | 17 个左侧听觉 epoch 平均（EDF） |
| dSPM 逆问题 | 算子 + 估计 OK |
| 输出 | `sample-lh.stc` / `-rh.stc` |
| 峰值（左侧听觉刺激） | **左半球**，外侧 (−55, −35, 34) mm |

峰值位于左外侧，对听觉反应在解剖上是合理的。

**同样在真实的临床 DICOM 上验证过**（T1w 序列，384 层，0.7 mm）：完整的
`reconstruct_sources(dicom_dir=...)` 链路 —— 匿名化 → 转换 → 对 DICOM 得到的 T1 运行
`charm` → 网格 → 配准 → FEM leadfield → dSPM —— 顺利运行，`status: ok`，皮层输出
`-lh/-rh.stc`。所用 EEG 是故意无关的（验证的是*管路*，而非定位）。在本机测得的**净**
计算时间（单线程）：`charm` 在这块高分辨率 T1 上约 2 小时，FEM leadfield 约 18 分钟，
其余 < 1 分钟。

**因缺乏数据而未验证：**来自**同一**受试者的 DICOM + **真实数字化**
（Polhemus/CapTrak）配对。在批处理之前，请先对**一位**受试者做一次试跑。

要重放该验证（需要一份 `charm` 输出）：

```powershell
python examples/run_full_pipeline_sample.py <m2m_sampleE2E-路径> <scratch>
```

---

## 需要了解的局限

**按路线不同有两种源坐标系。** FEM 路线（默认）把源置于皮层表面（中间灰质，lh+rh）；
BEM 路线（`head_model: bem`）把它们置于体积中。两者都是有文献记载、可发表的方法；
请按你的分析选择。

**配准才是薄弱环节，而非解剖。** 有了细致的数字化和对对齐的目视核查，就没问题。没有
数字化，精度就会下降。

**一幅 T2 图像能改善颅骨。** 若你的协议包含一幅，请设置 `simnibs.t2_template`。

**计算代价。** FEM leadfield 在约 80 万节点的网格上为每个电极求解一个系统。对于
60-256 个电极，预计 20 分钟到约 2 小时。在 Windows 上，求解器在单个进程中运行
（`fem.cpus` 被强制为 1：SimNIBS 的并行化在 Windows 的 `spawn` 下不可 pickle）。

---

## 测试

```powershell
conda activate mri2mne
pytest tests -q
```

测试覆盖配置、DICOM 摄取（序列打分器）、EEG 读取 / 蒙太奇、峰值定位、预检、wrapper
参数校验以及可视化的 SimNIBS→FreeSurfer 桥梁。繁重的阶段（charm、FEM leadfield）由
`examples/run_full_pipeline_sample.py` 在真实数据上验证。

---

## 结构

```
run_pipeline.py            批处理 CLI 入口
config.example.yaml        带注释的配置
environment.yml            mri2mne 环境（驱动器）
src/mri2mne/
  config.py                YAML 加载与校验
  paths.py                 受试者目录树 + 阶段缓存
  anonymize.py             DICOM PHI + 可选去脸
  dicom_convert.py         DICOM → NIfTI + T1 序列选择
  headmodel.py             charm wrapper
  coregistration.py        数字化 + ICP（MNE Coregistration）
  simnibs_mesh.py          从网格提取头皮 + 基准点（驱动器）
  simnibs_forward.py       SimNIBS FEM 正问题（驱动器）
  _simnibs_fem_helper.py   leadfield + make_forward（在 simnibs_env 中运行）
  _simnibs_mesh_helper.py  crop_mesh + 基准点（在 simnibs_env 中运行）
  eeg.py                   EEG 读取、预处理、协方差
  inverse.py               逆算子 + 源估计（表面）
  viz.py                   SimNIBS→FreeSurfer 桥梁 + MNE 3D 可视化
  wsl.py                   WSL2 桥梁（体积路线）：路径、执行器、探针
  freesurfer_bem.py        通过 WSL 的 autorecon1 + watershed（体积路线）
  volumetric.py            三层 BEM + 源空间 + 体积正/逆问题
  wrapper.py               reconstruct_sources[/_volumetric]() ：MRI+EEG -> 源
  preflight.py             启动批处理前的检查
  qc.py                    HTML 报告
  pipeline.py              按受试者的编排（批处理）
  batch.py                 受试者发现 + 并行
examples/
  run_full_pipeline_sample.py   在真实数据上的表面端到端验证
  run_volumetric_sample.py      体积路线（BEM/WSL）端到端
  open_source_viewer.py         已处理受试者的交互式 3D 窗口
```
