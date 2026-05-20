# SimForge thesis — LaTeX assembly

Overleaf-ready LaTeX project. **Preamble + title-page + front-matter
formatting modeled after the December 2025 thesis plan**
(`Plan/plan.tex`), with the user's chapter content from
`doc/chapters/*.md` (pandoc-converted).

## Files

```
latex/
├── main.tex                       # Master document — pdfLaTeX + BibTeX
├── references.bib                 # 29 BibTeX entries (copy of doc/references.bib)
├── README.md                      # this file
├── Makefile                       # local compile via latexmk + bibtex
├── front/
│   ├── dedication.tex             # \section*{Dedication} — [FILL] one-line template
│   ├── acknowledgments.tex        # \section*{Acknowledgments} — [FILL] names
│   └── acronyms_notation.tex      # \section*{Acronyms, Symbols and Notation}
│                                    (xltabular layout, drawn from doc/GLOSSARY.md)
├── chapters/
│   ├── abstract.tex               # \section*{Abstract} (front-matter convention)
│   ├── introduction.tex           # \chapter{Introduction}
│   ├── background.tex             # \chapter{Background and Related Work}
│   ├── methods.tex                # \chapter{Methods} (heaviest: 2,800+ lines)
│   ├── experiments.tex            # \chapter{Experiments}
│   ├── results.tex                # \chapter{Results}
│   └── discussion.tex             # \chapter{Discussion and Conclusion}
└── figures/                       # 21 figures (PNG, 300 dpi)
    ├── fig_5_*.png  (10 data plots)
    └── fig_{1,3,6}_*.png (11 architecture diagrams)
```

**Note**: title page + copyright are inline in `main.tex` (plan
convention), not separate `front/titlepage.tex` / `front/copyright.tex`
files. The `\thesistitle`, `\thesisauthor`, `\thesisdegree`,
`\thesisdept`, `\thesisschool`, `\thesisyear`, `\advisor`,
`\readerone`, `\readertwo` commands at the top of `main.tex` carry the
user-fillable data.

## Upload to Overleaf (recommended path)

1. Zip the `latex/` directory: `zip -r simforge_thesis.zip latex/` from
   the repo root.
2. Log into Overleaf → **New Project** → **Upload Project**.
3. Drop `simforge_thesis.zip` in. Overleaf auto-detects `main.tex`.
4. Compile menu (top-right) → set engine to **pdfLaTeX** + **BibTeX**
   (not biber). The project uses `\bibliographystyle{plain}` +
   `\bibliography{references}` — the classic BibTeX backend.
5. Hit **Recompile**. Expect 3 compile passes for full TOC + cross-refs:
   - 1st: lays out content, references show as `[?]`
   - 2nd: BibTeX resolves citations against `references.bib`
   - 3rd: TOC, list of figures, list of tables stabilize

Overleaf does this automatically; you'll see the warnings clear after
the third pass.

## Style notes (plan-formatting heritage)

The preamble adopts the plan's choices wholesale:

- **Document class**: `\documentclass[12pt]{report}`
- **Font**: `lmodern` (Latin Modern Roman, matches pdfLaTeX defaults)
- **Geometry**: `\usepackage[a4paper,margin=1in]{geometry}`
- **Line spacing**: `\setstretch{1.25}` (plan-tight, not double-spaced)
- **Chapter format**: custom `\titleformat{\chapter}[display]` — prints
  "Chapter N" on one line then the title on the next; tight 12 pt
  spacing after
- **Tables**: `tabularx` + `xltabular` + custom `L{}` and `Y` column
  types for clean ragged-right wrap inside fixed-width columns
- **Bibliography**: BibTeX, numeric `\bibliographystyle{plain}` — cite
  appears as `[N]` in the body, ordered alphabetically by author in the
  references list
- **Hyperref**: black `linkcolor`, blue `urlcolor`, black `citecolor`
  (plan convention; keeps links subtle in print)
- **Page numbering**: roman in front matter (title page → ToC → LoF →
  LoT → dedication → acknowledgments → abstract → acronyms); arabic
  reset at Chapter 1 via `\pagenumbering{arabic}\setcounter{page}{1}`
- **Listings**: `\lstset` with `breaklines=true` + monospace font for
  inline `\icode{...}` and code blocks

## Local compile (optional — no Overleaf needed)

Requires a TeX Live install (`pdflatex`, `bibtex`, `latexmk`) — `brew install --cask mactex` on macOS, or `apt install texlive-full` on Debian/Ubuntu.

```bash
cd latex/
make            # compiles main.pdf via latexmk
make clean      # removes aux files but keeps main.pdf
make distclean  # removes everything including main.pdf
```

## What's filled in vs needs your input

| Status | Item |
|---|---|
| ✓ done | Title (locked: "SimForge: A Reproducible Cross-Simulator Testing Framework for Urban Mobility Simulation"), body chapters (all 6), abstract, bibliography (29 entries), figures (21 × PNG @ 300 dpi), acronyms/notation table, TOC + LOF + LOT auto-generated |
| ✓ done | 34 inline citations converted from `[Author Year]` to `\cite{key}` against `references.bib` |
| **[FILL]** | `\thesisschool` = university name + city/state (in `main.tex`) |
| **[FILL]** | `\advisor`, `\readerone`, `\readertwo` (in `main.tex`) |
| **[FILL]** | Dedication line (`front/dedication.tex`) |
| **[FILL]** | Acknowledgments — advisor name + 2 committee names + optional personal/colleague/OSC-staff acknowledgments (`front/acknowledgments.tex`) |
| optional | Appendices A-D — scaffolded in `main.tex` (commented out); populate by writing `latex/appendices/A_*.tex` etc. and uncommenting the `\input` lines |

## Known LaTeX-side caveats

1. **Cross-reference labels** auto-generated by pandoc look ugly
   (`chapter-1-introduction`, `153-scope-boundaries`, etc.). They
   compile fine but if you want clean `\ref{}` cross-references, do a
   search-and-replace in chapter files after the initial compile.

2. **The `cao2022lpsim` bibliography entry** carries a "verify DOI"
   note. Confirm the LPSim paper venue + DOI before final submission.
   See `doc/CITATION_KEY_MAP.md` for details.

3. **Markdown code blocks** were converted to `lstlisting` blocks
   with the plan's `\lstset` defaults. If you prefer `minted` or
   `verbatim`, swap the `\lstset{}` block at the top of `main.tex`.

4. **Methods chapter (`methods.tex`, ~2,900 lines)** is the biggest
   single chapter and includes many code listings + tables. Overleaf
   should still compile it in a few seconds, but if you hit memory
   limits on the free tier, split it into 3.4a/3.4b/etc. files and
   `\input` each separately from a chapter wrapper.

## Regenerating from markdown source

If you edit `doc/chapters/*.md` (the markdown source-of-truth), run:

```bash
# From the repo root:
for f in abstract introduction background methods experiments results discussion; do
    pandoc doc/chapters/${f}.md \
        -f gfm -t latex \
        --top-level-division=chapter \
        -o latex/chapters/${f}.tex
done

# Strip redundant numbering prefixes (LaTeX auto-numbers):
python3 -c "
import re
for f in ['abstract','introduction','background','methods','experiments','results','discussion']:
    p = f'latex/chapters/{f}.tex'
    s = open(p).read()
    s = re.sub(r'\\\\chapter\{Chapter \d+: ', r'\\\\chapter{', s)
    s = re.sub(r'\\\\section\{\d+\.\d+(\.\d+)? ', r'\\\\section{', s)
    s = re.sub(r'\\\\subsection\{\d+\.\d+\.\d+(\.\d+)? ', r'\\\\subsection{', s)
    open(p, 'w').write(s)
"

# Fix abstract to use \section* (front-matter convention):
sed -i.bak 's|\\chapter\*{Abstract}\\addcontentsline{toc}{chapter}{Abstract}|\\clearpage\n\\thispagestyle{plain}\n\\section\*{Abstract}\n\\phantomsection\n\\addcontentsline{toc}{section}{Abstract}|' latex/chapters/abstract.tex
rm -f latex/chapters/abstract.tex.bak

# Convert [Author Year] → \cite{key} (full Python script in CITATION_KEY_MAP.md
# or use the same script that produced the original conversion commit)
```

Pandoc 3.x is required (tested with 3.6.4).

## Final pre-submission checklist

- [ ] All `[FILL]` placeholders resolved (in `main.tex` + `front/*.tex`)
- [ ] `cao2022lpsim` DOI verified in `references.bib`
- [ ] Compiled PDF reviewed by advisor
- [ ] Margins / font / line-spacing match school template (currently 1in margins on a4paper, 12 pt `lmodern`, $\sim$1.25-line spacing per plan convention)
- [ ] Page numbering correct: roman in front matter, arabic from Chapter 1
