# Technical Audit Report: MAGE-Based AI Text Detection & Open-Set Rejection

This report presents a thorough technical audit of the experimental results, model checkpoints, and LaTeX presentation slides for your BTP defense. It resolves the numerical inconsistencies between the baseline and Experiment 3, verifies your system architecture, refines scientific wording, and provides answers to likely professor defense questions.

---

## SECTION A: Confirmed Correct

1. **Stage 1 Pipeline**: The parallel deployment of FastText, GLTR, and DistilBERT is correctly implemented. FastText captures lexical properties, GLTR evaluates token rank distributions, and DistilBERT handles contextual sequence classification.
2. **Open-Set Data Exclusion**: The unseen generator family is completely withheld during all training stages (training, validation, centroid calculation, covariance estimation, and threshold selection). It is strictly used for final testing.
3. **Threshold Selection Methodology**: The selection of $\tau$ at the 95th percentile of the known validation set's minimum Mahalanobis distances is mathematically correct. This guarantees that the known false rejection rate (FRR) is bounded by ~5% on validation data.
4. **Live Gradio Integration**: The live demonstration uses the baseline configuration (threshold $\tau = 63.60$, matching the Human-vs-AI embedding space). The output screenshot shows `Distance: 85.25 > Threshold: 63.60`, which is a correct and consistent test result.

---

## SECTION B: Technical Issues Found

1. **Incorrect GLTR Terminology**: The presentation and report repeatedly describe GLTR as using "prediction entropy". In your code (`models.py:L107-115`), GLTR actually computes the proportion of tokens falling into rank buckets ($<10$, $10\text{-}100$, $100\text{-}1000$, $\ge 1000$) under the reference model (GPT-2). The correct terminology is **Token Rank Distribution Proportions**.
2. **Ambiguous Embedding Model Labels**: The slides do not explicitly state that two separate fine-tuned DistilBERT models are deployed:
   * **Stage 1 DistilBERT**: Fine-tuned on the binary classification task (**Human vs. AI**).
   * **Stage 2 DistilBERT**: Fine-tuned on the generator attribution task (**GPT vs. LLaMA**).
   Using the same label for both causes confusion during the defense.
3. **Misleading Threshold Labels**: The term "Stored OOD Threshold" is used conceptually. Scientifically, it is better to label it as **Stored Rejection Threshold ($\tau$)** to emphasize that it is selected from known validation distances rather than unseen OOD data.

---

## SECTION C: Numerical Consistency Investigation

### The Discrepancy
* **Baseline Run (OPT Unseen)**: Threshold = `63.5972`, Unknown Rejection = `7.59%`, OOD AUROC = `0.6298`
* **Experiment 3A (OPT Unseen)**: Threshold = `5.9708`, Unknown Rejection = `1.41%`, OOD AUROC = `0.5263`

### The Investigation (Option A)
Both results are mathematically and experimentally valid, but they correspond to **two different training configurations**:

1. **The Baseline Configuration (Human-vs-AI Space)**:
   * **Model Used**: DistilBERT fine-tuned for **binary Human-vs-AI detection** (`models/distilbert/final_model`).
   * **Embedding space properties**: The model was optimized to separate human text from machine-generated structures, not to tell generators apart. As a result, the embedding representations of the known generators (GPT and LLaMA) are not compressed into tight clusters. The within-class variance is large (diagonal covariance mean of `0.0850`).
   * **OOD Behavior**: Because the embedding space is not collapsed, it retains general style-specific features. The unseen generator (OPT) lies further away from the known distributions, yielding a higher threshold (`63.60`), a higher rejection rate (`7.59%`), and a stronger AUROC (`0.6298`).

2. **The Experiment 3A Configuration (Generator-Attribution Space)**:
   * **Model Used**: DistilBERT fine-tuned for **generator classification** (`models/openset/openset_model`).
   * **Embedding space properties**: The model was fine-tuned specifically to classify GPT vs. LLaMA. This objective forces the model to compress representations of known classes into extremely tight, collinear clusters, shrinking within-class variance (diagonal covariance mean of `0.0045`).
   * **OOD Behavior**: The tight clustering drops the distance values and shifts the threshold down to `5.9708`. However, forcing the model to distinguish only between GPT and LLaMA collapses its generalization capability. The unseen generator (OPT) gets projected directly into the collapsed classification region, causing OOD separation to degrade (AUROC drops to `0.5263` and rejection rate falls to `1.41%`).

### Defense Recommendation
Frame this discrepancy as a **key scientific insight** rather than an error:
> Fine-tuning a transformer model on a multi-class generator classification task (GPT vs. LLaMA) causes representation collapse. This collapses the embedding space and degrades open-set generalization to unseen generators (OPT). In contrast, keeping the model in the binary Human-vs-AI feature space preserves general features, leading to significantly better out-of-distribution separation.

---

## SECTION D: Scientific Wording Corrections

1. **Avoid Universal Claims**:
   * *Do NOT say*: "CLS pooling is universally better than mean pooling."
   * *Say*: "In our experimental setting, CLS pooling provided better open-set separation than mean pooling."
   * *Do NOT say*: "Mahalanobis distance is universally essential."
   * *Say*: "Among the evaluated distance methods, Mahalanobis distance provided better separation than cosine distance."
2. **Frame Contributions Honestly**:
   * *Do NOT say*: "We created a new open-set model."
   * *Say*: "We proposed the integration of an open-set rejection mechanism into a multi-detector MAGE-based AI text detection pipeline."
3. **OPT and LLaMA Relationship**:
   * *Do NOT claim*: "OPT is a precursor to LLaMA" or "they share the same architecture."
   * *Say*: "The open-weights generator families (LLaMA and OPT) share substantial similarities in their pre-training web corpora and transformer architectures, leading to collinear representations in the embedding space."

---

## SECTION E: Architecture Corrections

1. **Clarify Dual Model Usage**: Explain that Stage 1 and Stage 2 utilize different model weights fine-tuned on different objectives.
2. **Label Decoupling**: Explicitly mark the Stage 1 encoder as the "Human/AI Classifier" and the Stage 2 encoder as the "Generator Attribution Model".

---

## SECTION F: Recommended Changes to the 13-Slide Presentation

| Slide Number | Title | Original Wording | Corrected Wording | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Slide 3** | Two-Stage Forensic Pipeline | TikZ diagram showing generic model | Add labels to distinguish **Stage-1 Classifier (Human/AI)** from **Stage-2 Encoder (GPT/LLaMA)** | Scientifically defines the dual-model pipeline. |
| **Slide 5** | Supervised Baseline Results | "GLTR prediction entropy" | **GLTR token rank distribution proportions** | Reflects actual implementation code. |
| **Slide 6** | Proposed Open-Set Rejection Layer | "The threshold $\tau = 63.5972$ is selected..." | "The threshold $\tau = 63.5972$ **(in the Human-vs-AI feature space)** is selected..." | Clarifies the configuration origin. |
| **Slide 6** | Proposed Open-Set Rejection Layer | "Stored OOD Threshold" | **Stored Rejection Threshold ($\tau$)** | More precise scientific naming. |
| **Slide 7** | Representation & Distance Studies | "Baseline (CLS + Mahalanobis)" | **Baseline (Human-vs-AI Feature Space)** | Distinguishes from Exp 3's collapsed space. |
| **Slide 7** | Representation & Distance Studies | Bullet points claiming CLS is universally better | Focus on "in our experimental setting..." | Prevents overclaiming. |
| **Slide 8** | Cross-Generator Generalization | Table showing Exp 3 results | Add explanation note on **Representation Collapse** during multi-class generator training | Explains the difference between 3A (`5.97`) and Baseline (`63.60`). |
| **Slide 11** | Live Demonstration | "Stored OOD Threshold" | **Stored Rejection Threshold ($\tau = 63.60$)** | Matches the baseline dashboard settings. |

---

## SECTION G: Defense Questions & Answers

### 1. What exactly is your novelty? Is open-set recognition itself novel?
> **Answer**: No, open-set recognition and Mahalanobis distance are established machine learning methods. Our contribution is the integration of these OOD methods into a multi-angle text forensics framework (MAGE) to solve the closed-set limitation where classifiers force unseen generators into known classes.

### 2. Why did you choose DistilBERT?
> **Answer**: DistilBERT is lightweight (66M parameters), enables fast local training and real-time inference on a CPU, and preserves ~97% of BERT's language comprehension capabilities.

### 3. Why CLS pooling instead of mean pooling?
> **Answer**: During supervised fine-tuning, the classification gradient propagates directly through the `[CLS]` token. This compresses classification features into the `[CLS]` embedding. Mean pooling averages across all tokens, which washes out these specific features with generic semantic context.

### 4. Why Mahalanobis instead of Euclidean or Cosine distance?
> **Answer**: Euclidean distance is isotropic and fails in high-dimensional spaces. Cosine distance measures only angles and ignores scale. Mahalanobis distance scales the distance by the regularized class covariance matrix, accounting for correlations between dimensions.

### 5. Why are your Experiment 3 results so different across generators?
> **Answer**: OPT and LLaMA share similar open-source transformer architectures and pre-training corpora (Common Crawl/Wikipedia), making them collinear and hard to separate. GPT text is generated by proprietary, closed-source models with different vocabulary distributions, making it much easier to detect as out-of-distribution (AUROC 0.7587).

### 6. What are the limitations of your work?
> **Answer**: High representation collinearity between similar open-source model families (OPT and LLaMA) limits the rejection rate. Additionally, the Mahalanobis threshold is sensitive to the style domain shift of the input text.
