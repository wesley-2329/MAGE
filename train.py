import os
import gc
import json
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments
)
from dataset import load_local_dataset, get_balanced_subset
from models import FastTextBaseline, GLTRDetector, tokenize_dataset_sequential, device

def evaluate_predictions(labels, probs, preds):
    labels = np.array(labels)
    probs = np.array(probs)
    preds = np.array(preds)
    
    acc = accuracy_score(labels, preds)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, preds, average='binary', zero_division=0)
    try:
        auc = roc_auc_score(labels, probs)
    except Exception:
        auc = 0.5
        
    return {
        "accuracy": float(acc),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "auc": float(auc)
    }

def train_all_models(base_dir=".", local_test=False):
    print("=== Phase 1: Loading Local Dataset splits ===")
    train_df, valid_df, test_df = load_local_dataset(base_dir)
    
    # Paper-required subsampling parameters
    train_size = 12 if local_test else 15000
    val_size = 6 if local_test else 1872
    test_size = 6 if local_test else 1872
    epochs = 1 if local_test else 4
    
    print(f"Creating balanced subsamples for local MacBook run (Target size: {train_size} training samples)...")
    df_train_all = get_balanced_subset(train_df, sample_size=train_size)
    df_val_all = get_balanced_subset(valid_df, sample_size=val_size)
    df_test_all = get_balanced_subset(test_df, sample_size=test_size)
    
    print(f"Final training subset size   : {len(df_train_all)} rows")
    print(f"Final validation subset size : {len(df_val_all)} rows")
    print(f"Final testing subset size    : {len(df_test_all)} rows")
    
    results_db = {}
    results_file_path = os.path.join(base_dir, "results/results_db.json")
    os.makedirs(os.path.dirname(results_file_path), exist_ok=True)
    
    # ==========================================
    # 1. Train FastText baseline
    # ==========================================
    print("\n=== Phase 2: Training FastText Classifier ===")
    fasttext_model = FastTextBaseline()
    fasttext_model.fit(df_train_all["text"].tolist(), df_train_all["label"].tolist())
    fasttext_path = os.path.join(base_dir, "models/fasttext/baseline.pkl")
    fasttext_model.save(fasttext_path)
    
    # Evaluate FastText
    probs = fasttext_model.predict_proba(df_test_all["text"].tolist())
    preds = fasttext_model.predict(df_test_all["text"].tolist())
    results_db["FastText"] = evaluate_predictions(df_test_all["label"].tolist(), probs, preds)
    print("FastText Combined Test Results:", results_db["FastText"])
    
    # ==========================================
    # 2. Train GLTR baseline
    # ==========================================
    print("\n=== Phase 3: Training GLTR Detector ===")
    # GPT-2 XL is too large for local CPU/MPS runs, using gpt2-medium/base for stable execution
    gltr_model_name = "gpt2"
    gltr_detector = GLTRDetector(model_name=gltr_model_name)
    gltr_detector.fit(df_train_all["text"].tolist(), df_train_all["label"].tolist())
    gltr_path = os.path.join(base_dir, "models/gltr/detector.pkl")
    gltr_detector.save(gltr_path)
    gltr_detector.unload_reference_model()
    
    # Evaluate GLTR
    probs = gltr_detector.predict_proba(df_test_all["text"].tolist())
    preds = gltr_detector.predict(df_test_all["text"].tolist())
    results_db["GLTR"] = evaluate_predictions(df_test_all["label"].tolist(), probs, preds)
    print("GLTR Combined Test Results:", results_db["GLTR"])
    
    # ==========================================
    # 3. Train DistilBERT baseline
    # ==========================================
    print("\n=== Phase 4: Fine-tuning DistilBERT Classifier ===")
    db_model_name = "distilbert-base-uncased"
    tokenizer = AutoTokenizer.from_pretrained(db_model_name)
    
    # Sequential tokenization
    tokenized_train = tokenize_dataset_sequential(
        df_train_all["text"].tolist(), df_train_all["label"].tolist(), tokenizer
    )
    tokenized_val = tokenize_dataset_sequential(
        df_val_all["text"].tolist(), df_val_all["label"].tolist(), tokenizer
    )
    tokenized_test = tokenize_dataset_sequential(
        df_test_all["text"].tolist(), df_test_all["label"].tolist(), tokenizer
    )
    
    # Load model configuration
    config = AutoConfig.from_pretrained(db_model_name, num_labels=2)
    config.dropout = 0.1
    db_model = AutoModelForSequenceClassification.from_pretrained(db_model_name, config=config).to(device)
    
    db_output_dir = os.path.join(base_dir, "models/distilbert/checkpoints")
    
    training_args = TrainingArguments(
        output_dir=db_output_dir,
        learning_rate=3e-5,
        per_device_train_batch_size=4 if local_test else 8,
        per_device_eval_batch_size=4 if local_test else 8,
        num_train_epochs=epochs,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_steps=1 if local_test else 50,
        load_best_model_at_end=True,
        metric_for_best_model="loss",
        disable_tqdm=False,
        fp16=False # Standard float32 for CPU/MPS stability
    )
    
    def compute_metrics(eval_pred):
        predictions, labels = eval_pred
        preds = np.argmax(predictions, axis=1)
        acc = accuracy_score(labels, preds)
        return {"accuracy": acc}
        
    trainer = Trainer(
        model=db_model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_val,
        compute_metrics=compute_metrics
    )
    
    print(f"Training DistilBERT for {epochs} epochs...")
    trainer.train()
    
    # Save final model
    final_db_path = os.path.join(base_dir, "models/distilbert/final_model")
    trainer.save_model(final_db_path)
    print(f"Saved DistilBERT model to {final_db_path}")
    
    # Evaluate DistilBERT
    eval_predictions = trainer.predict(tokenized_test)
    probs = torch.softmax(torch.tensor(eval_predictions.predictions), dim=-1)[:, 1].numpy()
    preds = np.argmax(eval_predictions.predictions, axis=1)
    
    results_db["DistilBERT"] = evaluate_predictions(df_test_all["label"].tolist(), probs, preds)
    print("DistilBERT Combined Test Results:", results_db["DistilBERT"])
    
    # Save results DB
    with open(results_file_path, "w") as f:
        json.dump(results_db, f, indent=4)
    print(f"Saved all baseline evaluation metrics to {results_file_path}")
    
    # Final VRAM memory cleanup
    del db_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()
        
    print("\n==========================================")
    print("TRAINING & BASELINE EVALUATION COMPLETED")
    print("==========================================")
