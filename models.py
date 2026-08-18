import os
import gc
import pickle
import numpy as np
import torch
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    AutoModelForCausalLM,
    pipeline
)
from datasets import Dataset

# Device configuration (native MPS acceleration for MacBook)
device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
print(f"Models package initialized. Target hardware device: {device.upper()}")

# ==========================================
# 1. FastText / TF-IDF + Logistic Regression
# ==========================================
class FastTextBaseline:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=50000)
        self.classifier = LogisticRegression(max_iter=1000, random_state=42)

    def fit(self, train_texts, train_labels):
        print("Fitting TF-IDF Vectorizer...")
        X_train = self.vectorizer.fit_transform(train_texts)
        print("Training Logistic Regression classifier...")
        self.classifier.fit(X_train, train_labels)

    def predict_proba(self, texts):
        features = self.vectorizer.transform(texts)
        return self.classifier.predict_proba(features)[:, 1]

    def predict(self, texts):
        features = self.vectorizer.transform(texts)
        return self.classifier.predict(features)

    def save(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            pickle.dump({"vectorizer": self.vectorizer, "classifier": self.classifier}, f)
        print(f"Saved FastText baseline to {filepath}")

    def load(self, filepath):
        with open(filepath, "rb") as f:
            data = pickle.load(f)
            self.vectorizer = data["vectorizer"]
            self.classifier = data["classifier"]
        print(f"Loaded FastText baseline from {filepath}")

# ==========================================
# 2. GLTR Feature Classifier
# ==========================================
class GLTRDetector:
    def __init__(self, model_name="gpt2"):
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self.classifier = LogisticRegression(random_state=42)

    def load_reference_model(self):
        if self.model is None:
            print(f"Loading GLTR reference Causal LM: {self.model_name}...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            # Safe local fallback configuration
            self.model = AutoModelForCausalLM.from_pretrained(self.model_name).to(device)
            self.model.eval()

    def unload_reference_model(self):
        self.model = None
        self.tokenizer = None
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
        elif device == "mps":
            torch.mps.empty_cache()

    def get_features(self, text):
        self.load_reference_model()
        
        with torch.no_grad():
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=1024).to(device)
            input_ids = inputs["input_ids"]
            if input_ids.size(1) <= 1:
                return [0.25, 0.25, 0.25, 0.25]
                
            outputs = self.model(**inputs)
            logits = outputs.logits
            
            # Shift predictions to match outputs
            shift_logits = logits[0, :-1, :]
            shift_labels = input_ids[0, 1:]
            
            ranks = []
            for token_idx, label_id in enumerate(shift_labels):
                prob_dist = torch.softmax(shift_logits[token_idx], dim=-1)
                sorted_probs, sorted_indices = torch.sort(prob_dist, descending=True)
                rank = (sorted_indices == label_id).nonzero(as_tuple=True)[0].item()
                ranks.append(rank)
                
            ranks = np.array(ranks)
            counts = [
                np.sum(ranks < 10),
                np.sum((ranks >= 10) & (ranks < 100)),
                np.sum((ranks >= 100) & (ranks < 1000)),
                np.sum(ranks >= 1000)
            ]
            total = len(ranks) if len(ranks) > 0 else 1
            proportions = [count / total for count in counts]
            return proportions

    def extract_features_batch(self, texts):
        from tqdm import tqdm
        features = []
        for i, text in enumerate(tqdm(texts, desc="Extracting GLTR features")):
            features.append(self.get_features(text))
        return np.array(features)

    def fit(self, train_texts, train_labels):
        print("Extracting GLTR features for training set...")
        X_train = self.extract_features_batch(train_texts)
        print("Training GLTR classifier...")
        self.classifier.fit(X_train, train_labels)

    def predict_proba(self, texts):
        features = self.extract_features_batch(texts)
        return self.classifier.predict_proba(features)[:, 1]

    def predict(self, texts):
        features = self.extract_features_batch(texts)
        return self.classifier.predict(features)

    def save(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            pickle.dump({"classifier": self.classifier, "model_name": self.model_name}, f)
        print(f"Saved GLTR detector to {filepath}")

    def load(self, filepath):
        with open(filepath, "rb") as f:
            data = pickle.load(f)
            self.classifier = data["classifier"]
            self.model_name = data["model_name"]
        print(f"Loaded GLTR detector from {filepath}")

# ==========================================
# 3. DistilBERT Classifier
# ==========================================
def tokenize_dataset_sequential(texts, labels, tokenizer, max_length=512):
    """
    Sequential dataset tokenization to guarantee memory stability on macOS.
    """
    def preprocess_fn(examples):
        return tokenizer(
            examples["text"],
            padding="max_length",
            truncation=True,
            max_length=max_length
        )
        
    ds = Dataset.from_dict({"text": [str(t) for t in texts], "label": labels})
    print("======================================================")
    print("TOKENIZATION CONFIGURATION (SEQUENTIAL)")
    print("num_proc = 1")
    print("======================================================")
    tokenized_ds = ds.map(
        preprocess_fn,
        batched=True,
        batch_size=None,
        num_proc=1,
        remove_columns=["text"]
    )
    return tokenized_ds

# ==========================================
# 4. DetectGPT-lite curvature scorer
# ==========================================
class DetectGPTScorer:
    def __init__(self, model_name="gpt2", mask_model_name="distilroberta-base"):
        self.model_name = model_name
        self.mask_model_name = mask_model_name
        self.tokenizer = None
        self.model = None
        self.mask_tokenizer = None
        self.mask_model = None

    def load_models(self):
        if self.model is None:
            print(f"Loading DetectGPT likelihood model: {self.model_name}...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForCausalLM.from_pretrained(self.model_name).to(device)
            self.model.eval()
            
            print(f"Loading DetectGPT mask/perturbation model: {self.mask_model_name}...")
            from transformers import AutoModelForMaskedLM
            self.mask_tokenizer = AutoTokenizer.from_pretrained(self.mask_model_name)
            self.mask_model = AutoModelForMaskedLM.from_pretrained(self.mask_model_name)
            self.fill_mask = pipeline("fill-mask", model=self.mask_model_name, device=device)

    def perturb_text(self, text, pct=0.15, span_len=2):
        self.load_models()
        words = text.split()
        num_to_mask = int(len(words) * pct)
        if num_to_mask < 1:
            num_to_mask = 1
            
        # Select random words to mask
        indices = sorted(np.random.choice(len(words), num_to_mask, replace=False))
        masked_words = words.copy()
        
        # Replace selected words with mask token
        for idx in indices:
            masked_words[idx] = self.fill_mask.tokenizer.mask_token
            
        masked_text = " ".join(masked_words)
        try:
            # Perturb text using mask filling pipeline
            res = self.fill_mask(masked_text)
            if isinstance(res, list) and len(res) > 0:
                if isinstance(res[0], list):
                    # Multimask fills
                    return res[0][0]["sequence"]
                return res[0]["sequence"]
        except Exception:
            pass
        return text

    def get_log_likelihood(self, text):
        self.load_models()
        with torch.no_grad():
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=1024).to(device)
            outputs = self.model(**inputs, labels=inputs["input_ids"])
            loss = outputs.loss
            # Log likelihood is negative loss * num_tokens
            return -loss.item() * inputs["input_ids"].size(1)

    def score_curvature(self, text, num_perturbations=10):
        orig_ll = self.get_log_likelihood(text)
        perturb_lls = []
        for _ in range(num_perturbations):
            p_text = self.perturb_text(text)
            perturb_lls.append(self.get_log_likelihood(p_text))
            
        mean_perturb_ll = np.mean(perturb_lls)
        std_perturb_ll = np.std(perturb_lls) if np.std(perturb_lls) > 0 else 1.0
        
        # Curvature score
        discrepancy = (orig_ll - mean_perturb_ll) / std_perturb_ll
        return discrepancy
