# Source note: the real-world context and what this project does and does not claim

This note records the desk research done before the network model was fixed (October 2026).
Sources are public web pages; none is a KPTCL, SLDC or ESCOM operational dataset. Where
only secondary sources exist, the note says so.

## 1. Findings

### 1.1 Sharavathi Generating Station (existing)

* KPCL's **Sharavathi Generating Station (SGS)** has **10 units of 103.5 MW (1035 MW)**, fed by
  the **Linganamakki** reservoir on the Sharavathi river near Jog Falls. Commissioned in the
  1960s; owned 100 % by Karnataka Power Corporation Ltd (KPCL).
  * Global Energy Monitor wiki: https://www.gem.wiki/Sharavathy_hydroelectric_plant
  * Deccan Herald (output history, switchyard overhauls): https://www.deccanherald.com/india/karnataka/sharavathi-plant-hasn-t-677288.html
  * Deccan Herald (Linganamakki levels): https://deccanherald.com/india/karnataka/power-output-doubles-as-linganamakki-reaches-max-level-758741.html
* Reported share of Karnataka's generation and unit maintenance outages appear in press
  reports; we did not find official 2026 dispatch data, so **generator dispatch in the model is
  illustrative**.

### 1.2 Sharavathy Pumped Storage Project (proposed, different)

* A **separate, proposed 2000 MW pumped-storage scheme** by KPCL (upper reservoir Talakalale,
  lower Gerusoppa). The CEA approved the detailed project report in **August 2024**; the State
  and National Boards for Wildlife gave conditional / in-principle approval amid opposition over
  forest land and the lion-tailed macaque habitat. It is **not an operating station**.
  * https://www.gem.wiki/Sharavathy_Pumped_Storage_hydroelectric_plant
  * https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Fcentral-electricity-authority-approves-hydro-pumped-storage-plant-in-karnataka-3134828
  * https://www.deccanherald.com/india/karnataka/amid-opposition-pumped-storage-project-in-sharavathi-sanctuary-gets-swbl-nod-3377063
  * https://www.etvbharat.com/en/!state/sharavathi-power-project-gets-conditional-clearance-from-karnataka-wildlife-board-enn25012902508
* The project does not model pumped storage.

### 1.3 Sharavathi Receiving Station (SRS), Peenya

* A **220/66/11 kV "Sharavathi Receiving Station", Peenya, Bengaluru 560058**, operated by
  KPTCL, is documented by a KPTCL internship report (2019) and a KPTCL works tender ("220kV
  Station Premises SRS Peenya").
  * https://pdfcoffee.com/srs-peenya-substation-report-5-pdf-free.html (student report, secondary)
  * https://tenders.infralens.in/tender/construction-of-office-building-in-first-floor-of-the-299758
* A different "SRS" exists at Hootagalli (Mysuru); it is unrelated.
* **We found no official single-line diagram, transformer list or feeder list for SRS Peenya.**

### 1.4 Roles in the supply chain

| Stage | Role | Karnataka entity |
|---|---|---|
| Generation | Converts energy (here hydro) to electricity | KPCL (Sharavathi) |
| Transmission (≥ 66 kV) | Bulk transfer over a meshed, interconnected network | KPTCL |
| System operation | Real-time despatch, SCADA, energy accounting | SLDC (hosted by KPTCL) |
| Receiving substation (e.g. 220/66 kV) | Steps transmission voltage down for sub-transmission | KPTCL |
| Distribution substation (66/11 kV) | Feeds 11 kV distribution feeders | KPTCL / ESCOM boundary |
| 11 kV feeder | Carries power to distribution transformers (DTs) | ESCOM |
| DT (11 kV/433 V) and LV network | Supplies consumers | ESCOM |

* KPTCL as transmission licensee and SLDC host: https://kptclsldc.in ,
  https://powerline.net.in/2017/11/04/kptcl/
* **Shivamogga is served by MESCOM** (with Dakshina Kannada, Udupi, Chikkamagaluru):
  https://en.wikipedia.org/wiki/Mangalore_Electricity_Supply_Company_Limited
* **Bengaluru Urban (including Peenya) is served by BESCOM**: Karnataka Legislative papers,
  https://kla.kar.nic.in/council/house/Paperlaid/20.pdf

### 1.5 Is there a dedicated Sharavathi → Peenya line?

**Not verified.** Public CEA transmission listings mention several 220 kV lines connected to
"Sharavathi" and to "Peenya" (e.g. LILO works), and the receiving station's name suggests a
historical link, but we could not verify a dedicated line, its route, conductor or rating.
Physically, power in an interconnected AC grid does not travel from a named generator to a
named substation: flows divide according to network impedances and all generation/load.
**The model therefore connects the generator and the receiving station only through a meshed
220 kV network plus a slack bus that represents the rest of the grid.**

### 1.6 Where energy-theft analysis is meaningful

* India's Bureau of Energy Efficiency (BEE) regulations of **6 October 2021** require DISCOMs to
  perform **quarterly energy accounting and annual energy audits**, by voltage level, including
  feeder- and DT-wise accounting where metered:
  https://www.india-briefing.com/news/new-audit-norms-for-india-electricity-distribution-companies-to-reduce-transmission-and-distribution-losses-23528.html
  (state audit reports on beeindia.gov.in show feeder-level metering sections).
* The digital twin quantifies the scale argument with its own power flow: the four modelled
  feeders draw ~0.17 MW, i.e. **~0.2 % of the ~100 MW** flowing on the 220 kV line into the
  receiving station in a typical snapshot. A few kW of unrecorded consumption cannot be resolved
  at transmission level, where flows are set by dispatch. Accounting is meaningful where metering
  brackets a small set of consumers: **the 11 kV feeder head and the DT**.

### 1.7 Loss context

AT&C loss = (energy input − energy realised) / energy input, where realised = billed ×
collection efficiency. BESCOM's distribution loss was reported near 11 % in 2021-22/2022-23
(Deccan Herald: https://www.deccanherald.com/india/karnataka/at-over-11-power-distribution-losses-weigh-bescom-down-1219673.html);
KERC tariff orders contain official per-ESCOM figures. Those include technical losses, so they
are **not** a theft estimate.

## 2. Related research (and what is not novel here)

* **Jokar, Arianpoo & Leung (2016)**, "Electricity Theft Detection in AMI Using Customers'
  Consumption Patterns", *IEEE Trans. Smart Grid* 7(1). Defines synthetic "attack" functions
  applied to real consumption data and combines a consumer-level classifier with
  **distribution-transformer meters** that flag areas with non-technical loss.
  *Cited from the authors' knowledge of the literature; the search tool could not retrieve the
  paper page, so verify the bibliographic details before citing.*
* **Zheng et al. (2018)**, "Wide and Deep Convolutional Neural Networks for Electricity-Theft
  Detection to Secure Smart Grids", *IEEE Trans. Industrial Informatics* (DOI
  10.1109/TII.2017.2785963), evaluated on the **SGCC** (State Grid Corporation of China) dataset:
  https://scholars.hkbu.edu.hk/en/publications/wide-and-deep-convolutional-neural-networks-for-electricity-theft/
* Later work combines consumption with network or communication signals, e.g. Ibrahem et al.
  (IEEE IoT J., 2022) and Kawoosa et al. (2024); fusion deep models on SGCC report ROC-AUC ≈ 0.97
  (https://ajic.wits.ac.za/article/view/20652).

**Novelty statement.** Combining consumer-level anomaly detection with transformer/feeder-level
energy balance is **established** (Jokar et al. 2016 already did this). This project does not
claim a new algorithm. Its contribution is a **reproducible, explainable, open workflow**:

1. a physically consistent synthetic benchmark generator with power flow, measured losses,
   meter errors, communication faults and benign confounders, rather than attack functions on a
   fixed dataset;
2. energy accounting with explicit uncertainty propagation and data-quality handling;
3. a controlled comparison of consumer-only, boundary-only and combined signals with run-grouped
   splits, paired bootstrap tests, robustness sweeps and loss-calibration ablation;
4. an interactive digital twin that exposes every step to an evaluator.

## 3. What remains unverified

* Any real topology, rating or measurement of KPTCL / BESCOM / MESCOM assets.
* A dedicated Sharavathi → Peenya line.
* Actual consumer load shapes, meter accuracy distributions or theft prevalence in Karnataka.
* Field-verified theft labels. **No real-world detection accuracy is claimed.**
