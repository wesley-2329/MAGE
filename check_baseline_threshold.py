import os
import numpy as np
import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from openset import load_openset_data, extract_embeddings
from models import device

def main():
    base_dir = "/Users/wesley/Desktop/MAGE_1"
    train_df, valid_df, test_df, opt_df = load_openset_data(base_dir, local_test=False, unseen_gen="opt")
    
    model_path = os.path.join(base_dir, "models/openset/openset_model")
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(model_path).to(device)
    model.eval()
    
    train_embeddings = extract_embeddings(model, tokenizer, train_df["text"].tolist(), pooling_method="cls")
    labels = np.array(train_df["label"].tolist())
    
    centroids = {}
    covariances = {}
    for cls in [0, 1]:
        cls_embeds = train_embeddings[labels == cls]
        centroids[str(cls)] = np.mean(cls_embeds, axis=0)
        cov = np.cov(cls_embeds.T) + 1e-4 * np.eye(cls_embeds.shape[1])
        covariances[str(cls)] = cov
        
    valid_embeddings = extract_embeddings(model, tokenizer, valid_df["text"].tolist(), pooling_method="cls")
    
    def mahalanobis_distance(x, mean, cov):
        diff = x - mean
        inv_cov = np.linalg.inv(cov)
        if diff.ndim == 1:
            return np.sqrt(np.dot(np.dot(diff, inv_cov), diff.T))
        else:
            return np.sqrt(np.sum(np.dot(diff, inv_cov) * diff, axis=1))
            
    valid_dists = []
    for embed in valid_embeddings:
        d0 = mahalanobis_distance(embed, centroids["0"], covariances["0"])
        d1 = mahalanobis_distance(embed, centroids["1"], covariances["1"])
        valid_dists.append(min(d0, d1))
        
    valid_dists = np.array(valid_dists)
    threshold = np.percentile(valid_dists, 95)
    print(f"Computed threshold: {threshold:.6f}")
    
    # Calculate stats
    test_df["generator"] = test_df["src"].apply(lambda s: 'gpt' if 'gpt' in s.lower() else 'llama')
    test_embeddings = extract_embeddings(model, tokenizer, test_df[test_df["generator"].isin(["gpt", "llama"])]["text"].tolist(), pooling_method="cls")
    test_dists = []
    for embed in test_embeddings:
        d0 = mahalanobis_distance(embed, centroids["0"], covariances["0"])
        d1 = mahalanobis_distance(embed, centroids["1"], covariances["1"])
        test_dists.append(min(d0, d1))
    test_dists = np.array(test_dists)
    print(f"Test false rejection rate at {threshold:.4f}: {np.mean(test_dists > threshold)*100:.2f}%")

if __name__ == "__main__":
    main()
