import os
import json
import numpy as np
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from models import device

# Path definitions
MODEL_PATH = "models/openset/openset_model"

tokenizer = None
model = None
c0 = None
c1 = None
cov0 = None
cov1 = None
threshold = None
current_pooling_method = "cls"

def load_openset_inference():
    global tokenizer, model, c0, c1, cov0, cov1, threshold, current_pooling_method
    if model is not None:
        return True
        
    config_path = "models/openset/openset_config.json"
    centroids_path = "models/openset/centroids.npz"
    
    # Fallback to mean configuration if default is not present
    if not os.path.exists(config_path):
        config_path = "models/openset/openset_config_mean.json"
        centroids_path = "models/openset/centroids_mean.npz"
        
    if not (os.path.exists(MODEL_PATH) and os.path.exists(centroids_path) and os.path.exists(config_path)):
        return False
        
    try:
        print(f"Loading Open-Set inference components from {config_path}...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH).to(device)
        model.eval()
        
        data = np.load(centroids_path)
        c0 = data["c0"]
        c1 = data["c1"]
        cov0 = data["cov0"]
        cov1 = data["cov1"]
        
        with open(config_path, "r") as f:
            config_data = json.load(f)
            threshold = config_data["threshold"]
            current_pooling_method = config_data.get("pooling_method", "cls")
            
        print(f"Open-Set inference initialized successfully (Pooling: {current_pooling_method.upper()}, Threshold: {threshold:.4f})")
        return True
    except Exception as e:
        print(f"Error loading Open-Set components: {str(e)}")
        return False

def mahalanobis_distance(x, mean, cov):
    diff = x - mean
    inv_cov = np.linalg.inv(cov)
    return np.sqrt(np.dot(np.dot(diff, inv_cov), diff.T))

def compute_ood_score(text):
    if not load_openset_inference():
        return "Model not trained."
        
    with torch.no_grad():
        inputs = tokenizer(
            text,
            padding="max_length",
            truncation=True,
            max_length=512,
            return_tensors="pt"
        ).to(device)
        
        # Forward pass to get predictions and pool representation
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)[0].cpu().numpy()
        pred_class = int(np.argmax(probs))
        confidence = probs[pred_class]
        
        # Extract representation based on the loaded pooling method
        hidden_states = model.distilbert(**inputs)
        last_hidden = hidden_states.last_hidden_state
        
        if current_pooling_method == "cls":
            embed = last_hidden[0, 0, :].cpu().numpy()
        elif current_pooling_method == "mean":
            attention_mask = inputs["attention_mask"]
            mask = attention_mask.unsqueeze(-1)
            masked_hidden_states = last_hidden * mask
            sum_embeddings = masked_hidden_states.sum(dim=1)
            valid_token_count = mask.sum(dim=1)
            valid_token_count = torch.clamp(valid_token_count, min=1.0)
            embed = (sum_embeddings / valid_token_count)[0].cpu().numpy()
            
        # Calculate distances
        d0 = mahalanobis_distance(embed, c0, cov0)
        d1 = mahalanobis_distance(embed, c1, cov1)
        min_dist = min(d0, d1)
        
        if min_dist > threshold:
            return f"Unknown / Possibly Unseen Generator (Distance: {min_dist:.2f} > Threshold: {threshold:.2f})"
        else:
            class_name = "GPT-family" if pred_class == 0 else "LLaMA-family"
            return f"{class_name} (Confidence: {confidence*100:.1f}%, Distance: {min_dist:.2f})"
