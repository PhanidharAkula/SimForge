# SimForge thesis — local LaTeX compile
# Requires: TeX Live (pdflatex, biber, latexmk).
# On Overleaf, this Makefile is not used — Overleaf runs latexmk internally.

MAIN = main
TEX_FILES = $(shell find . -name "*.tex")
BIB_FILES = $(wildcard *.bib)
FIG_FILES = $(wildcard figures/*.pdf) $(wildcard figures/*.png)

.PHONY: all clean distclean watch

all: $(MAIN).pdf

$(MAIN).pdf: $(TEX_FILES) $(BIB_FILES) $(FIG_FILES)
	latexmk -pdf -bibtex -biber -file-line-error -halt-on-error $(MAIN).tex

# Continuous-rebuild mode: re-compile on any .tex/.bib change.
watch:
	latexmk -pdf -bibtex -biber -pvc -file-line-error -halt-on-error $(MAIN).tex

# Remove all intermediate files, keep the PDF.
clean:
	latexmk -c $(MAIN).tex
	rm -f *.bbl *.blg *.run.xml *.bcf

# Remove everything including the final PDF.
distclean: clean
	rm -f $(MAIN).pdf
