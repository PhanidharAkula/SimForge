# Chapter prose → BibTeX key mapping

Generated 2026-05-20 as part of the bibliography drop (commit
following `64c223a`). Use this table when converting chapter prose
from author-year `[Author 2022]` placeholders to LaTeX `\cite{key}`.

The BibTeX entries live in [`doc/references.bib`](references.bib).
Six entries carry `% TODO` or `% NOTE` comments flagging ambiguous
citations the user should verify before final submission.

| Chapter prose form | BibTeX key | Confidence |
|---|---|---|
| `[Krajzewicz et al. 2012]` | `krajzewicz2012sumo` | high |
| `[Horni et al. 2016]` | `horni2016matsim` | high |
| `[Zhou and Taylor 2014]` | `zhou2014dtalite` | high |
| `[Auld et al. 2016]` | `auld2016polaris` | high |
| `[Cao et al. 2022]` | `cao2022lpsim` | **TODO VERIFY** — best plausible match for LPSim |
| `[Boulmakoul et al. 2023]` | `chen2020qarsumo` | **NOTE** — no Boulmakoul QarSUMO paper exists; substituted canonical Chen et al. 2020 SIGSPATIAL QarSUMO paper |
| `[Zhang et al. 2019]` | `zhang2019cityflow` | high |
| `[Krauss 1998]` | `krauss1998microscopic` | high |
| `[Treiber et al. 2000]` | `treiber2000idm` | high |
| `[Goodman et al. 2016]` | `goodman2016reproducibility` | high |
| `[Stodden et al. 2018]` | `stodden2018empirical` | high |
| `[Wilkinson et al. 2016]` | `wilkinson2016fair` | high |
| `[Mattson et al. 2020]` | `mattson2020mlperf` | high |
| `[Studer et al. 2019]` | `pineau2021reproducibility` | **NOTE** — no Studer ML reproducibility paper exists; substituted Pineau et al. 2021 JMLR paper as the closest match |
| `[TRB 2022]` | `trb2022survey` | **TODO VERIFY** — placeholder; replace with specific TRB report |
| `[Nagel and Bazzan 2019]` | `nagel2019hybrid` | **TODO VERIFY** — closest plausible Nagel + Bazzan collaboration |
| `[Chan et al. 2018]` | `chan2018gpu` | **TODO VERIFY** — author, title, venue, year all uncertain |
| LWR / Lighthill-Whitham (Chapter 2 §2.1, unbracketed) | `lighthill1955kinematic` + `richards1956shock` | high |
| `path4gmns` GitHub URL (Chapter 2 §2.3.1) | `path4gmns2024` | high |
| GMNS specification (Chapter 2 §2.3.1) | `zephyr2024gmns` | high |
| OpenStreetMap (Chapter 3 §3.3) | `openstreetmap` | high |
| Geofabrik PBFs (Chapter 3 §3.3) | `geofabrik` | high |
| US Census PUMS (Chapter 3 §3.3) | `uscensus_pums` | high |
| TIGER/Line shapefiles (Chapter 3 §3.9 viz basemap) | `tiger2024` | high |
| SimForge software (self-cite) | `simforge2026` | high |

## Items requiring user attention before final submission

1. **`cao2022lpsim`** — confirm LPSim paper details (journal, exact title, DOI)
2. **`chen2020qarsumo`** — chapter prose should be updated from "[Boulmakoul et al. 2023]" to "[Chen et al. 2020]" if substitution is accepted, or the bib entry should be replaced with whatever Boulmakoul paper was actually intended
3. **`pineau2021reproducibility`** — chapter prose should be updated from "[Studer et al. 2019]" to "[Pineau et al. 2021]" if substitution is accepted
4. **`trb2022survey`** — replace with a specific TRB publication or remove the citation
5. **`nagel2019hybrid`** — verify exact paper and add missing fields (volume, pages)
6. **`chan2018gpu`** — verify all fields or remove the citation

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
