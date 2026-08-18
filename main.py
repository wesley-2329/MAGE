import argparse
import sys
from dataset import load_local_dataset
from train import train_all_models
from app import launch_app

from openset import train_openset_pipeline

def main():
    parser = argparse.ArgumentParser(description="MAGE Text Detection Framework (ACL 2024 Reproduction)")
    parser.add_argument(
        "--action",
        type=str,
        required=True,
        choices=["prep", "train", "app", "openset_train"],
        help="Action to execute: 'prep' (verify data), 'train' (train classifiers), 'app' (launch dashboard), or 'openset_train' (train open-set novelty)."
    )
    parser.add_argument(
        "--local_test",
        action="store_true",
        help="Runs a quick functional check on a small subset of data with 1 training epoch."
    )
    parser.add_argument(
        "--pooling_method",
        type=str,
        choices=["cls", "mean"],
        default="cls",
        help="Embedding pooling method for Open-Set pipeline: 'cls' or 'mean'."
    )
    parser.add_argument(
        "--distance_method",
        type=str,
        choices=["mahalanobis", "cosine"],
        default="mahalanobis",
        help="OOD distance calculation metric: 'mahalanobis' or 'cosine'."
    )
    parser.add_argument(
        "--unseen_generator",
        type=str,
        choices=["opt", "llama", "gpt"],
        default="opt",
        help="Held-out generator family for Experiment 3: 'opt', 'llama', or 'gpt'."
    )
    
    args = parser.parse_args()
    
    print("\n==================================================")
    print("MAGE TEXT DETECTION PIPELINE")
    print("==================================================")
    print(f"Action Selection : {args.action.upper()}")
    print(f"Local Test Mode  : {args.local_test}")
    print(f"Pooling Method   : {args.pooling_method.upper()}")
    print(f"Distance Method  : {args.distance_method.upper()}")
    print(f"Unseen Generator : {args.unseen_generator.upper()}")
    print("==================================================\n")
    
    if args.action == "prep":
        print("Executing action: Checking and loading local dataset files...")
        load_local_dataset()
        print("Local dataset loaded and validated successfully.")
        
    elif args.action == "train":
        print("Executing action: Training and evaluating classifiers...")
        train_all_models(local_test=args.local_test)
        print("Training execution finished successfully.")
        
    elif args.action == "openset_train":
        print(f"Executing action: Training Open-Set attribution pipeline (Pooling: {args.pooling_method.upper()}, Distance: {args.distance_method.upper()}, Unseen: {args.unseen_generator.upper()})...")
        train_openset_pipeline(
            local_test=args.local_test,
            pooling_method=args.pooling_method,
            distance_method=args.distance_method,
            unseen_gen=args.unseen_generator
        )
        print("Open-Set pipeline execution finished successfully.")
        
    elif args.action == "app":
        print("Executing action: Launching Gradio Web App...")
        launch_app()

if __name__ == "__main__":
    main()
