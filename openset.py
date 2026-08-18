import os
import gc
import json
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from sklearn.metrics import roc_auc_score
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments
)
from datasets import Dataset
from models import tokenize_dataset_sequential, device

def parse_generator_label(src):
    src_lower = src.lower()
    if 'gpt' in src_lower or 'davinci' in src_lower:
        return 'gpt'
    elif 'llama' in src_lower or any(pat in src for pat in ['_7B', '_13B', '_30B', '_65B']):
        return 'llama'
    elif 'opt' in src_lower:
        return 'opt'
    return 'other'

def load_openset_data(base_dir=".", local_test=False, unseen_gen="opt"):
    """
    Loads raw datasets and filters them based on the selected unseen generator family.
    Hold out the unseen_gen completely from all training configurations.
    """
    dataset_dir = os.path.join(base_dir, "03_Dataset/raw")
    train_path = os.path.join(dataset_dir, "train.csv")
    valid_path = os.path.join(dataset_dir, "valid.csv")
    test_path = os.path.join(dataset_dir, "test.csv")
    
    print(f"Loading raw dataset splits for Open-Set routing (Unseen: {unseen_gen.upper()})...")
    train_df = pd.read_csv(train_path)
    valid_df = pd.read_csv(valid_path)
    test_df = pd.read_csv(test_path)
    
    # Fill NaNs and ensure string format
    train_df["text"] = train_df["text"].fillna("").astype(str)
    valid_df["text"] = valid_df["text"].fillna("").astype(str)
    test_df["text"] = test_df["text"].fillna("").astype(str)
    
    # Map generator family
    train_df["generator"] = train_df["src"].apply(parse_generator_label)
    valid_df["generator"] = valid_df["src"].apply(parse_generator_label)
    test_df["generator"] = test_df["src"].apply(parse_generator_label)
    
    # Identify known generators
    known_generators = ["gpt", "llama", "opt"]
    known_generators.remove(unseen_gen)
    
    known_train = train_df[train_df["generator"].isin(known_generators)].copy()
    known_valid = valid_df[valid_df["generator"].isin(known_generators)].copy()
    known_test = test_df[test_df["generator"].isin(known_generators)].copy()
    
    # Hold out unseen class completely
    unseen_test = test_df[test_df["generator"] == unseen_gen].copy()
    
    # Map class labels (0 for first known, 1 for second known)
    class_map = {known_generators[0]: 0, known_generators[1]: 1}
    known_train["label"] = known_train["generator"].map(class_map)
    known_valid["label"] = known_valid["generator"].map(class_map)
    known_test["label"] = known_test["generator"].map(class_map)
    
    # Draw balanced subsample to keep local training fast and stable
    train_size = 10 if local_test else 5000
    val_size = 5 if local_test else 500
    
    def get_balanced_classes(df, size):
        c0 = df[df["label"] == 0]
        c1 = df[df["label"] == 1]
        c0_sub = c0.sample(n=min(size, len(c0)), random_state=42)
        c1_sub = c1.sample(n=min(size, len(c1)), random_state=42)
        return pd.concat([c0_sub, c1_sub]).sample(frac=1, random_state=42).reset_index(drop=True)
        
    train_sub = get_balanced_classes(known_train, train_size)
    valid_sub = get_balanced_classes(known_valid, val_size)
    test_sub = get_balanced_classes(known_test, val_size)
    
    print(f"Subsampled Known Train size: {len(train_sub)}")
    print(f"Subsampled Known Valid size: {len(valid_sub)}")
    print(f"Subsampled Known Test size : {len(test_sub)}")
    print(f"Unseen {unseen_gen.upper()} Test size   : {len(unseen_test)}")
    
    return train_sub, valid_sub, test_sub, unseen_test

def extract_embeddings(model, tokenizer, texts, pooling_method="cls", batch_size=8):
    """
    Extracts high-dimensional representations using either CLS token pooling or
    attention-mask-aware mean pooling.
    """
    model.eval()
    embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        inputs = tokenizer(
            batch_texts,
            padding="max_length",
            truncation=True,
            max_length=512,
            return_tensors="pt"
        ).to(device)
        
        with torch.no_grad():
            outputs = model.distilbert(**inputs)
            last_hidden_state = outputs.last_hidden_state
            
            if pooling_method == "cls":
                cls_repr = last_hidden_state[:, 0, :].cpu().numpy()
                embeddings.append(cls_repr)
            elif pooling_method == "mean":
                attention_mask = inputs["attention_mask"]
                mask = attention_mask.unsqueeze(-1)
                masked_hidden_states = last_hidden_state * mask
                sum_embeddings = masked_hidden_states.sum(dim=1)
                valid_token_count = mask.sum(dim=1)
                valid_token_count = torch.clamp(valid_token_count, min=1.0)
                mean_repr = (sum_embeddings / valid_token_count).cpu().numpy()
                embeddings.append(mean_repr)
                
    return np.concatenate(embeddings, axis=0)

def train_openset_pipeline(base_dir=".", local_test=False, pooling_method="cls", distance_method="mahalanobis", unseen_gen="opt"):
    train_df, valid_df, test_df, opt_df = load_openset_data(base_dir, local_test, unseen_gen=unseen_gen)
    
    # Path suffixes to prevent file overwrite
    suffix = f"_holdout_{unseen_gen}"
    
    # Suffix modifiers for different pooling/distance configurations (Exp 1 and Exp 2)
    if pooling_method != "cls":
        suffix += f"_{pooling_method}"
    if distance_method != "mahalanobis":
        suffix += f"_{distance_method}"
        
    npz_path = os.path.join(base_dir, f"models/openset/centroids{suffix}.npz")
    config_path = os.path.join(base_dir, f"models/openset/openset_config{suffix}.json")
    results_path = os.path.join(base_dir, f"results/openset_results{suffix}.json")
    
    model_path = os.path.join(base_dir, f"models/openset/openset_model{suffix}")
    # For opt, default to original path to preserve baseline checkpoint (trained on GPT + LLaMA)
    if unseen_gen == "opt":
        model_path = os.path.join(base_dir, "models/openset/openset_model")
    
    # ------------------------------------------
    # Step 1: Train Generator-Attribution Model
    # ------------------------------------------
    if os.path.exists(model_path):
        print(f"\nFound existing trained model at {model_path}. Loading it directly to extract embeddings...")
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForSequenceClassification.from_pretrained(model_path).to(device)
    else:
        print(f"\n=== STEP 1: Fine-tuning Open-Set Attribution Model (Holdout: {unseen_gen.upper()}) ===")
        model_name = "distilbert-base-uncased"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        
        tokenized_train = tokenize_dataset_sequential(train_df["text"].tolist(), train_df["label"].tolist(), tokenizer)
        tokenized_valid = tokenize_dataset_sequential(valid_df["text"].tolist(), valid_df["label"].tolist(), tokenizer)
        
        config = AutoConfig.from_pretrained(model_name, num_labels=2)
        config.dropout = 0.1
        model = AutoModelForSequenceClassification.from_pretrained(model_name, config=config).to(device)
        
        output_dir = os.path.join(base_dir, f"models/openset/checkpoints{suffix}")
        training_args = TrainingArguments(
            output_dir=output_dir,
            learning_rate=3e-5,
            per_device_train_batch_size=4 if local_test else 8,
            per_device_eval_batch_size=4 if local_test else 8,
            num_train_epochs=1 if local_test else 4,
            eval_strategy="epoch",
            save_strategy="epoch",
            logging_steps=1 if local_test else 50,
            load_best_model_at_end=True,
            metric_for_best_model="loss",
            disable_tqdm=False,
            fp16=False
        )
        
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=tokenized_train,
            eval_dataset=tokenized_valid
        )
        
        trainer.train()
        trainer.save_model(model_path)
        print(f"Saved openset model to {model_path}")
    
    # ------------------------------------------
    # Step 2: Compute Class Centroids & Covariance
    # ------------------------------------------
    print(f"\n=== STEP 2: Extracting Embeddings & Calculating Centroids (Pooling: {pooling_method.upper()}, Distance: {distance_method.upper()}) ===")
    train_embeddings = extract_embeddings(model, tokenizer, train_df["text"].tolist(), pooling_method=pooling_method)
    labels = np.array(train_df["label"].tolist())
    
    centroids = {}
    covariances = {}
    
    for cls in [0, 1]:
        cls_embeds = train_embeddings[labels == cls]
        centroids[str(cls)] = np.mean(cls_embeds, axis=0)
        # Compute covariance (adding regularization for stability)
        cov = np.cov(cls_embeds.T) + 1e-4 * np.eye(cls_embeds.shape[1])
        covariances[str(cls)] = cov
        
    np.savez(npz_path,
             c0=centroids["0"], c1=centroids["1"],
             cov0=covariances["0"], cov1=covariances["1"])
    print(f"Saved class centroids and covariances to {npz_path}")
    
    # ------------------------------------------
    # Step 3: Choose Distance Threshold
    # ------------------------------------------
    print("\n=== STEP 3: Selecting Distance Threshold ===")
    valid_embeddings = extract_embeddings(model, tokenizer, valid_df["text"].tolist(), pooling_method=pooling_method)
    
    # Setup dynamic distance calculation function
    if distance_method == "mahalanobis":
        def compute_distance(x, mean, cov):
            diff = x - mean
            inv_cov = np.linalg.inv(cov)
            if diff.ndim == 1:
                return np.sqrt(np.dot(np.dot(diff, inv_cov), diff.T))
            else:
                return np.sqrt(np.sum(np.dot(diff, inv_cov) * diff, axis=1))
    elif distance_method == "cosine":
        def compute_distance(x, mean, cov=None):
            norm_mean = np.linalg.norm(mean)
            norm_mean = 1e-8 if norm_mean == 0 else norm_mean
            if x.ndim == 1:
                norm_x = np.linalg.norm(x)
                norm_x = 1e-8 if norm_x == 0 else norm_x
                sim = np.dot(x, mean) / (norm_x * norm_mean)
                return 1.0 - sim
            else:
                norm_x = np.linalg.norm(x, axis=1)
                norm_x = np.where(norm_x == 0, 1e-8, norm_x)
                sim = np.dot(x, mean) / (norm_x * norm_mean)
                return 1.0 - sim

    # Calculate minimum distance to known centroids for validation set
    valid_dists = []
    for embed in valid_embeddings:
        d0 = compute_distance(embed, centroids["0"], covariances["0"])
        d1 = compute_distance(embed, centroids["1"], covariances["1"])
        valid_dists.append(min(d0, d1))
        
    valid_dists = np.array(valid_dists)
    # Pick threshold holding 95% of known validation samples
    threshold = np.percentile(valid_dists, 95)
    print(f"Chosen Distance Threshold (95th percentile): {threshold:.4f}")
    
    # Save final threshold configuration
    with open(config_path, "w") as f:
        json.dump({
            "threshold": float(threshold),
            "pooling_method": pooling_method,
            "distance_method": distance_method,
            "unseen_gen": unseen_gen
        }, f, indent=4)
        
    # ------------------------------------------
    # Step 4: Evaluate on Unseen & Known Test Sets
    # ------------------------------------------
    print(f"\n=== STEP 4: Evaluating on Held-out {unseen_gen.upper()} Family ===")
    test_embeddings = extract_embeddings(model, tokenizer, test_df["text"].tolist(), pooling_method=pooling_method)
    
    # Local check for opt samples to avoid empty test evaluation
    opt_texts = opt_df["text"].tolist()
    if local_test:
        opt_texts = opt_texts[:10]
        
    opt_embeddings = extract_embeddings(model, tokenizer, opt_texts, pooling_method=pooling_method)
    
    # Compute minimum distances
    test_dists = np.array([min(
        compute_distance(e, centroids["0"], covariances["0"]),
        compute_distance(e, centroids["1"], covariances["1"])
    ) for e in test_embeddings])
    
    opt_dists = np.array([min(
        compute_distance(e, centroids["0"], covariances["0"]),
        compute_distance(e, centroids["1"], covariances["1"])
    ) for e in opt_embeddings])
    
    # Flagged unknown rate
    false_rejection_rate = np.mean(test_dists > threshold) * 100.0
    correct_unknown_rate = np.mean(opt_dists > threshold) * 100.0
    
    # Compute AUROC for OOD classification
    # Label 0 for known test, 1 for unseen OPT
    y_true = np.concatenate([np.zeros(len(test_dists)), np.ones(len(opt_dists))])
    y_scores = np.concatenate([test_dists, opt_dists])
    auroc = roc_auc_score(y_true, y_scores)
    
    # Calculate domain-wise AUROC if possible
    domain_aurocs = {}
    def get_domain(s):
        s_lower = s.lower()
        if 'xsum' in s_lower: return 'xsum'
        if 'eli5' in s_lower: return 'eli5'
        if 'wp' in s_lower or 'writing' in s_lower: return 'wp'
        return 'other'
        
    test_df["domain"] = test_df["src"].apply(get_domain)
    opt_df["domain"] = opt_df["src"].apply(get_domain)
    
    test_domains = test_df["domain"].tolist()
    # Handle slice truncation for local test
    opt_domains = opt_df["domain"].tolist()[:len(opt_dists)]
    
    for dom in ["xsum", "eli5", "wp"]:
        test_dom_mask = np.array([d == dom for d in test_domains])
        opt_dom_mask = np.array([d == dom for d in opt_domains])
        
        test_dom_dists = test_dists[test_dom_mask]
        opt_dom_dists = opt_dists[opt_dom_mask]
        
        if len(test_dom_dists) > 0 and len(opt_dom_dists) > 0:
            y_true_dom = np.concatenate([np.zeros(len(test_dom_dists)), np.ones(len(opt_dom_dists))])
            y_scores_dom = np.concatenate([test_dom_dists, opt_dom_dists])
            domain_aurocs[dom] = float(roc_auc_score(y_true_dom, y_scores_dom))
        else:
            domain_aurocs[dom] = None
            
    print("\n" + "="*50)
    print("OPEN-SET REJECTION PERFORMANCE SUMMARY")
    print("="*50)
    print(f"Selected Distance Threshold: {threshold:.4f}")
    print(f"Unseen Flagged Unknown: {correct_unknown_rate:.2f}%")
    print(f"Known Class False Rejection : {false_rejection_rate:.2f}%")
    print(f"Open-Set OOD Score AUROC     : {auroc:.4f}")
    print("="*50 + "\n")
    
    results = {
        "held_out_class": unseen_gen,
        "threshold": float(threshold),
        "correct_unknown_rate": float(correct_unknown_rate),
        "false_rejection_rate": float(false_rejection_rate),
        "auroc": float(auroc),
        "xsum_auroc": domain_aurocs.get("xsum"),
        "eli5_auroc": domain_aurocs.get("eli5"),
        "wp_auroc": domain_aurocs.get("wp"),
        "pooling_method": pooling_method,
        "distance_method": distance_method,
        "opt_samples": len(opt_embeddings),
        "opt_rejected": int(np.sum(opt_dists > threshold)),
        "known_samples": len(test_embeddings),
        "known_rejected": int(np.sum(test_dists > threshold))
    }
    
    os.makedirs(os.path.dirname(results_path), exist_ok=True)
    with open(results_path, "w") as f:
        json.dump(results, f, indent=4)
        
    print(f"Saved evaluation metrics to {results_path}")
    
    # Save a copy as openset_results_holdout_<unseen_gen>.json specifically for Exp 3
    exp3_results_path = os.path.join(base_dir, f"results/openset_results_holdout_{unseen_gen}.json")
    with open(exp3_results_path, "w") as f:
        json.dump(results, f, indent=4)
    print(f"Saved duplicate experiment 3 results to {exp3_results_path}")
    
    # Load comparison data for 3A, 3B, 3C
    res_a = None
    res_b = None
    res_c = None
    
    path_a = os.path.join(base_dir, "results/openset_results_holdout_opt.json")
    path_b = os.path.join(base_dir, "results/openset_results_holdout_llama.json")
    path_c = os.path.join(base_dir, "results/openset_results_holdout_gpt.json")
    
    # Fallback to default baseline results if holdout_opt results are not generated yet
    if not os.path.exists(path_a):
        path_a = os.path.join(base_dir, "results/openset_results.json")
        
    if os.path.exists(path_a):
        try:
            with open(path_a, "r") as f: res_a = json.load(f)
        except Exception: pass
    if os.path.exists(path_b):
        try:
            with open(path_b, "r") as f: res_b = json.load(f)
        except Exception: pass
    if os.path.exists(path_c):
        try:
            with open(path_c, "r") as f: res_c = json.load(f)
        except Exception: pass
            
    # Assign current result to the corresponding variable
    if unseen_gen == "opt": res_a = results
    elif unseen_gen == "llama": res_b = results
    elif unseen_gen == "gpt": res_c = results
        
    # Print comparison table
    print("\n" + "="*70)
    print("EXPERIMENT 3 — CROSS-GENERATOR GENERALIZATION")
    print("="*70)
    print(f"{'Metric':<25} | {'3A: OPT unseen':<13} | {'3B: LLaMA unseen':<15} | {'3C: GPT unseen':<13}")
    print("-" * 75)
    
    def get_val(res, key, fmt="{:.2f}%"):
        if res is None or key not in res:
            return "N/A"
        val = res[key]
        if val is None:
            return "N/A"
        if isinstance(val, float):
            if "rate" in key or "rejection" in key:
                return fmt.format(val)
            return f"{val:.4f}"
        return str(val)
        
    print(f"{'Known generators':<25} | {'GPT+LLaMA':<13} | {'GPT+OPT':<15} | {'LLaMA+OPT':<13}")
    print(f"{'Unseen generator':<25} | {'OPT':<13} | {'LLaMA':<15} | {'GPT':<13}")
    print(f"{'Threshold':<25} | {get_val(res_a, 'threshold', '{:.4f}'):<13} | {get_val(res_b, 'threshold', '{:.4f}'):<15} | {get_val(res_c, 'threshold', '{:.4f}'):<13}")
    print(f"{'Unknown rejection':<25} | {get_val(res_a, 'correct_unknown_rate'):<13} | {get_val(res_b, 'correct_unknown_rate'):<15} | {get_val(res_c, 'correct_unknown_rate'):<13}")
    print(f"{'Known false rejection':<25} | {get_val(res_a, 'false_rejection_rate'):<13} | {get_val(res_b, 'false_rejection_rate'):<15} | {get_val(res_c, 'false_rejection_rate'):<13}")
    print(f"{'OOD AUROC':<25} | {get_val(res_a, 'auroc', '{:.4f}'):<13} | {get_val(res_b, 'auroc', '{:.4f}'):<15} | {get_val(res_c, 'auroc', '{:.4f}'):<13}")
    print(f"{'Unseen samples':<25} | {get_val(res_a, 'opt_samples', '{}'):<13} | {get_val(res_b, 'opt_samples', '{}'):<15} | {get_val(res_c, 'opt_samples', '{}'):<13}")
    print(f"{'Unseen rejected':<25} | {get_val(res_a, 'opt_rejected', '{}'):<13} | {get_val(res_b, 'opt_rejected', '{}'):<15} | {get_val(res_c, 'opt_rejected', '{}'):<13}")
    print(f"{'Known samples':<25} | {get_val(res_a, 'known_samples', '{}'):<13} | {get_val(res_b, 'known_samples', '{}'):<15} | {get_val(res_c, 'known_samples', '{}'):<13}")
    print(f"{'Known rejected':<25} | {get_val(res_a, 'known_rejected', '{}'):<13} | {get_val(res_b, 'known_rejected', '{}'):<15} | {get_val(res_c, 'known_rejected', '{}'):<13}")
    print("="*70 + "\n")
    
    # Print domain-wise results
    print("="*70)
    print("DOMAIN-WISE AUROC RESULTS")
    print("="*70)
    print(f"{'Unseen Generator':<18} | {'XSum AUROC':<12} | {'ELI5 AUROC':<12} | {'WritingPrompts AUROC':<20}")
    print("-" * 75)
    print(f"{'OPT (3A)':<18} | {get_val(res_a, 'xsum_auroc', '{:.4f}'):<12} | {get_val(res_a, 'eli5_auroc', '{:.4f}'):<12} | {get_val(res_a, 'wp_auroc', '{:.4f}'):<20}")
    print(f"{'LLaMA (3B)':<18} | {get_val(res_b, 'xsum_auroc', '{:.4f}'):<12} | {get_val(res_b, 'eli5_auroc', '{:.4f}'):<12} | {get_val(res_b, 'wp_auroc', '{:.4f}'):<20}")
    print(f"{'GPT (3C)':<18} | {get_val(res_c, 'xsum_auroc', '{:.4f}'):<12} | {get_val(res_c, 'eli5_auroc', '{:.4f}'):<12} | {get_val(res_c, 'wp_auroc', '{:.4f}'):<20}")
    print("="*70 + "\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--local_test", action="store_true")
    parser.add_argument("--pooling_method", type=str, choices=["cls", "mean"], default="cls")
    parser.add_argument("--distance_method", type=str, choices=["mahalanobis", "cosine"], default="mahalanobis")
    parser.add_argument("--unseen_generator", type=str, choices=["opt", "llama", "gpt"], default="opt")
    args = parser.parse_args()
    train_openset_pipeline(
        local_test=args.local_test,
        pooling_method=args.pooling_method,
        distance_method=args.distance_method,
        unseen_gen=args.unseen_generator
    )
