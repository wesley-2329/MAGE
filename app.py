import os
import pickle
import torch
import numpy as np
import gradio as gr
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from models import FastTextBaseline, GLTRDetector, device
from preprocess import preprocess

# Path definitions
FASTTEXT_PATH = "models/fasttext/baseline.pkl"
GLTR_PATH = "models/gltr/detector.pkl"
DISTILBERT_PATH = "models/distilbert/final_model"

# Lazy-loaded model instances
fasttext_model = None
gltr_detector = None
db_model = None
db_tokenizer = None

def load_models():
    global fasttext_model, gltr_detector, db_model, db_tokenizer
    
    # 1. Load FastText Baseline
    if os.path.exists(FASTTEXT_PATH):
        print(f"Loading FastText model from {FASTTEXT_PATH}...")
        fasttext_model = FastTextBaseline()
        fasttext_model.load(FASTTEXT_PATH)
    else:
        print("Warning: FastText baseline file not found.")
        
    # 2. Load GLTR Detector
    if os.path.exists(GLTR_PATH):
        print(f"Loading GLTR model from {GLTR_PATH}...")
        gltr_detector = GLTRDetector()
        gltr_detector.load(GLTR_PATH)
    else:
        print("Warning: GLTR detector file not found.")
        
    # 3. Load DistilBERT Model
    if os.path.exists(DISTILBERT_PATH):
        print(f"Loading DistilBERT model from {DISTILBERT_PATH}...")
        db_tokenizer = AutoTokenizer.from_pretrained(DISTILBERT_PATH)
        db_model = AutoModelForSequenceClassification.from_pretrained(DISTILBERT_PATH).to(device)
        db_model.eval()
    else:
        print("Warning: DistilBERT final model path not found.")

from ood import compute_ood_score

def predict_text(text):
    if not text.strip():
        return "Please input valid text.", "", "", ""
        
    # Clean input text
    cleaned_text = preprocess(text)
    
    results = {}
    
    # 1. FastText Prediction
    if fasttext_model is not None:
        try:
            prob = fasttext_model.predict_proba([cleaned_text])[0]
            label = "Human" if prob < 0.5 else "AI"
            conf = (1 - prob) if prob < 0.5 else prob
            results["FastText"] = f"Flag: {label} (Confidence: {conf*100:.1f}%)"
        except Exception as e:
            results["FastText"] = f"Error: {str(e)}"
    else:
        results["FastText"] = "Model not trained."
        
    # 2. GLTR Prediction
    if gltr_detector is not None:
        try:
            prob = gltr_detector.predict_proba([cleaned_text])[0]
            label = "Human" if prob < 0.5 else "AI"
            conf = (1 - prob) if prob < 0.5 else prob
            results["GLTR"] = f"Flag: {label} (Confidence: {conf*100:.1f}%)"
        except Exception as e:
            results["GLTR"] = f"Error: {str(e)}"
    else:
        results["GLTR"] = "Model not trained."
        
    # 3. DistilBERT Prediction
    if db_model is not None and db_tokenizer is not None:
        try:
            with torch.no_grad():
                inputs = db_tokenizer(cleaned_text, return_tensors="pt", truncation=True, max_length=512).to(device)
                outputs = db_model(**inputs)
                prob = torch.softmax(outputs.logits, dim=-1)[0, 1].item()
                label = "Human" if prob < 0.5 else "AI"
                conf = (1 - prob) if prob < 0.5 else prob
                results["DistilBERT"] = f"Flag: {label} (Confidence: {conf*100:.1f}%)"
        except Exception as e:
            results["DistilBERT"] = f"Error: {str(e)}"
    else:
        results["DistilBERT"] = "Model not trained."
        
    # 4. Open-Set Attribution
    try:
        results["OpenSet"] = compute_ood_score(cleaned_text)
    except Exception as e:
        results["OpenSet"] = f"Error: {str(e)}"
        
    return results.get("FastText"), results.get("GLTR"), results.get("DistilBERT"), results.get("OpenSet")

def launch_app():
    load_models()
    
    # Custom Premium CSS for modern macOS aesthetics (glassmorphism, clean layouts)
    custom_css = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0d1117; color: #c9d1d9; }
    .gradio-container { max-width: 900px !important; margin: 40px auto !important; border: 1px solid #30363d; border-radius: 12px; padding: 24px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); background-color: #161b22; }
    .main-title { text-align: center; color: #58a6ff; font-weight: 700; font-size: 2.2rem; margin-bottom: 8px; }
    .main-desc { text-align: center; color: #8b949e; font-size: 1.1rem; margin-bottom: 24px; }
    .predict-btn { background-color: #1f6feb !important; color: white !important; border-radius: 6px !important; padding: 10px 20px !important; font-weight: 600 !important; }
    .predict-btn:hover { background-color: #388bfd !important; }
    .output-box { background-color: #0d1117 !important; border: 1px solid #30363d !important; border-radius: 6px !important; color: #e6edf3 !important; }
    """
    
    with gr.Blocks(css=custom_css, title="MAGE Text Detection Dashboard") as demo:
        gr.Markdown("<div class='main-title'>MAGE Text Detection System</div>")
        gr.Markdown("<div class='main-desc'>A multi-angle framework reproducing ACL 2024 benchmarks for AI-generated text detection in the wild.</div>")
        
        with gr.Row():
            text_input = gr.Textbox(
                label="Enter Text Passage (minimum 10 lines recommended for optimal accuracy):",
                placeholder="Paste text here to evaluate...",
                lines=8
            )
            
        with gr.Row():
            submit_btn = gr.Button("Analyze Text", elem_classes="predict-btn")
            
        gr.Markdown("### Detector Results Comparison")
        with gr.Row():
            fasttext_out = gr.Textbox(label="FastText Classifier Output", elem_classes="output-box", interactive=False)
            gltr_out = gr.Textbox(label="GLTR Detector Output", elem_classes="output-box", interactive=False)
            db_out = gr.Textbox(label="DistilBERT Classifier Output", elem_classes="output-box", interactive=False)
            openset_out = gr.Textbox(label="Generator Attribution (Open-Set)", elem_classes="output-box", interactive=False)
            
        submit_btn.click(
            fn=predict_text,
            inputs=text_input,
            outputs=[fasttext_out, gltr_out, db_out, openset_out]
        )
        
    print("Launching Gradio Dashboard interface...")
    demo.launch(share=False)

if __name__ == "__main__":
    launch_app()
