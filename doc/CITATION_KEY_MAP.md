# Chapter prose → BibTeX key mapping

Generated 2026-05-20 as part of the bibliography drop (commit
following `64c223a`). Updated 2026-05-20 to reflect the
TODO-VERIFY resolution pass: bad-substitute placeholders removed,
real verifiable references substituted, chapter prose aligned.

The BibTeX entries live in [`doc/references.bib`](references.bib).
All entries are now real, verifiable references; the prose has been
updated to cite them consistently. One entry (`cao2022lpsim`) carries
a "confirm DOI before final submission" note because the venue +
exact title need user verification, but author + year + topic are
correct.

| Chapter prose form (current) | BibTeX key | Notes |
|---|---|---|
| `[Krajzewicz et al. 2012]` | `krajzewicz2012sumo` | — |
| `[Horni et al. 2016]` | `horni2016matsim` | — |
| `[Zhou and Taylor 2014]` | `zhou2014dtalite` | — |
| `[Auld et al. 2016]` | `auld2016polaris` | — |
| `[Cao et al. 2022]` | `cao2022lpsim` | Confirm DOI + venue before final submission |
| `[Chen et al. 2020]` (was `[Boulmakoul et al. 2023]`) | `chen2020qarsumo` | Substituted in prose: SIGSPATIAL 2020 is the canonical QarSUMO paper |
| `[Zhang et al. 2019]` | `zhang2019cityflow` | — |
| `[Krauss 1998]` | `krauss1998microscopic` | — |
| `[Treiber et al. 2000]` | `treiber2000idm` | — |
| `[Goodman et al. 2016]` | `goodman2016reproducibility` | — |
| `[Stodden et al. 2018]` | `stodden2018empirical` | — |
| `[Wilkinson et al. 2016]` | `wilkinson2016fair` | — |
| `[Mattson et al. 2020]` | `mattson2020mlperf` | — |
| `[Pineau et al. 2021]` (was `[Studer et al. 2019]`) | `pineau2021reproducibility` | Substituted in prose: Pineau et al. 2021 JMLR is the canonical NeurIPS-reproducibility-program paper |
| `[Bazzan and Klügl 2014]` (was `[TRB 2022]` + `[Nagel and Bazzan 2019]`) | `bazzan2014review` | Replaced both stale placeholders: Bazzan + Klügl 2014 is the well-known agent-based transportation review |
| LWR / Lighthill-Whitham (Chapter 2 §2.1, unbracketed) | `lighthill1955kinematic` + `richards1956shock` | — |
| `path4gmns` GitHub URL (Chapter 2 §2.3.1) | `path4gmns2024` | — |
| GMNS specification (Chapter 2 §2.3.1) | `zephyr2024gmns` | — |
| OpenStreetMap (Chapter 3 §3.3 + Chapter 2 §2.3.4) | `openstreetmap` | — |
| Geofabrik PBFs (Chapter 3 §3.3) | `geofabrik` | — |
| US Census PUMS (Chapter 3 §3.3 + Chapter 2 §2.3.4) | `uscensus_pums` | — |
| TIGER/Line shapefiles (Chapter 3 §3.9 viz basemap) | `tiger2024` | — |
| **cityscape ModelGen** (Chapter 2 §2.3.4 + Chapter 3 §3.3) | `rao2023cityscape` | Real WSC 2023 paper by D. M. Rao (verified from supplied PDF) |
| **cityscape taxi-rides application** (Chapter 2 §2.3.4 — sibling demo) | `rao2023taxi` | Real ESM 2023 paper by D. M. Rao (verified from supplied PDF) |
| **LandScan population grid** (Chapter 2 §2.3.4 + Chapter 3 §3.3) | `landscan` | — |
| **IPUMS PUMA shapefiles** (Chapter 2 §2.3.4) | `ipums_puma` | — |
| **ActivitySim** (Chapter 2 §2.3.4 — contemporary alternative) | `activitysim` | project website cite |
| SimForge software (self-cite) | `simforge2026` | — |

## Removed entries

The following bibliography entries were removed when the corresponding
chapter-prose citations were rewritten to avoid them or substituted with
verifiable references:

- `trb2022survey` — generic placeholder for "[TRB 2022]"; chapter prose
  rewrote those mentions to cite Bazzan + Klügl 2014 (real review) or
  reframed without citation.
- `nagel2019hybrid` — couldn't be uniquely resolved; chapter prose
  rewrote those mentions to cite Bazzan + Klügl 2014 (real review).
- `chan2018gpu` — all fields uncertain; chapter prose rewrote those
  mentions to drop the citation while keeping the surrounding sentence.

## Net change

- Starting state (commit `64c223a`): 26 entries, 6 TODO/NOTE flags
- After TODO-VERIFY resolution (commit `55393aa`): 24 entries, 1 verify-DOI note on `cao2022lpsim`
- After demand-generation context expansion (this commit): 29 entries, 1 verify-DOI note on `cao2022lpsim`
  - +5 new entries: `rao2023cityscape`, `rao2023taxi`, `landscan`, `ipums_puma`, `activitysim`
  - All five cite real, verifiable artefacts (2 WSC/ESM 2023 papers verified from PDFs / ORNL dataset / IPUMS shapefiles / FHWA platform)

## Open items for user attention before final submission

1. **`cao2022lpsim`** — verify the exact DOI, venue, and title for the LPSim paper. The author + year + topic are correct; the journal/conference and DOI need user confirmation against the actual paper that motivated the LPSim integration retrospective.

## Workflow for LaTeX assembly

```bash
# Once chapter prose uses \cite{key} instead of [Author 2022]:
pandoc doc/chapters/{abstract,introduction,background,methods,experiments,results,discussion}.md \
       --bibliography=doc/references.bib \
       --citeproc \
       --csl=<your-citation-style.csl> \
       -o thesis.pdf
```

Or with biblatex (recommended for theses):

```latex
\usepackage[backend=biber,style=numeric,sorting=none]{biblatex}
\addbibresource{doc/references.bib}
% ... in the body ...
\cite{krajzewicz2012sumo}
% ... at the end ...
\printbibliography
```
