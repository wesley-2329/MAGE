import os
import gc
import pandas as pd
from preprocess import preprocess

def load_local_dataset(base_dir="."):
    """
    Loads dataset splits from the local 03_Dataset directory.
    """
    dataset_dir = os.path.join(base_dir, "03_Dataset/processed/cross_domains_cross_models")
    train_path = os.path.join(dataset_dir, "train.csv")
    valid_path = os.path.join(dataset_dir, "valid.csv")
    test_path = os.path.join(dataset_dir, "test.csv")
    
    if not (os.path.exists(train_path) and os.path.exists(valid_path) and os.path.exists(test_path)):
        raise FileNotFoundError(f"Required dataset CSV files not found in {dataset_dir}")
        
    print(f"Loading local dataset splits from: {dataset_dir}")
    train_df = pd.read_csv(train_path)
    valid_df = pd.read_csv(valid_path)
    test_df = pd.read_csv(test_path)
    
    # Clean text columns to fill NaNs and ensure string format
    train_df["text"] = train_df["text"].fillna("").astype(str)
    valid_df["text"] = valid_df["text"].fillna("").astype(str)
    test_df["text"] = test_df["text"].fillna("").astype(str)
    
    print(f"Loaded local sizes - Train: {len(train_df)} rows, Valid: {len(valid_df)} rows, Test: {len(test_df)} rows")
    return train_df, valid_df, test_df

def get_balanced_subset(df, sample_size=15000):
    """
    Selects a balanced subset of label=0 (AI) and label=1 (Human).
    """
    if len(df) <= sample_size:
        return df.sample(frac=1, random_state=42).reset_index(drop=True)
        
    half_size = sample_size // 2
    ai_df = df[df["label"] == 0]
    human_df = df[df["label"] == 1]
    
    # Slice half from each class
    ai_subset = ai_df.sample(n=min(half_size, len(ai_df)), random_state=42)
    human_subset = human_df.sample(n=min(half_size, len(human_df)), random_state=42)
    
    combined = pd.concat([ai_subset, human_subset]).sample(frac=1, random_state=42).reset_index(drop=True)
    combined["label"] = combined["label"].astype(int)
    return combined
