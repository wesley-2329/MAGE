# MAGE-based Open-Set AI Text Detection and Generator Rejection

This repository implements a multi-angle benchmarking framework reproducing ACL 2024 MAGE benchmarks for AI-generated text detection in the wild, alongside an **academic research extension**: an explicit two-stage open-set generator rejection layer that identifies and rejects unseen generator families as `UNKNOWN`.

---

## 1. Project Setup & Environment

To set up the environment and run the pipeline locally (optimized for Apple Silicon GPU acceleration using PyTorch MPS):

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Running the Python Pipeline

All actions are routed through the unified entry point `main.py`:

### Supervised Attribution Model
```bash
# Train known-class binary/multi-class classifier
python main.py --action openset_train
```

### Reproducing OOD Rejection Experiments
*   **Experiment 1 (Representation Study - Mean Pooling):**
    ```bash
    python main.py --action openset_train --pooling_method mean --distance_method mahalanobis --unseen_generator opt
    ```
*   **Experiment 2 (Distance Study - Cosine Distance):**
    ```bash
    python main.py --action openset_train --pooling_method cls --distance_method cosine --unseen_generator opt
    ```
*   **Experiment 3 (Cross-Generator Generalization Study):**
    ```bash
    # 3A: OPT unseen
    python main.py --action openset_train --unseen_generator opt
    # 3B: LLaMA unseen
    python main.py --action openset_train --unseen_generator llama
    # 3C: GPT unseen
    python main.py --action openset_train --unseen_generator gpt
    ```

### Live Gradio Interface Demo
```bash
# Launch Graduation Web App
python main.py --action app
```

---

## 3. Compiling the LaTeX Beamer Presentation

A professional academic Beamer presentation has been created in `presentation.tex` along with references in `presentation.bib`.

### Prerequisites
Ensure you have a complete LaTeX distribution installed (e.g., **TeX Live** or **MacTeX** on macOS).

### Compilation Commands

To compile the presentation and compile references, run the following commands sequentially:

```bash
# Step 1: Compile LaTeX document once
pdflatex presentation.tex

# Step 2: Compile BibTeX references
bibtex presentation

# Step 3: Recompile LaTeX to link references
pdflatex presentation.tex

# Step 4: Final pass to resolve citations and page counts
pdflatex presentation.tex
```

Alternatively, use `latexmk` to automate the build:
```bash
latexmk -pdf -use-make presentation.tex
```

The resulting `presentation.pdf` will contain the 20-slide Beamer presentation suitable for academic review.
