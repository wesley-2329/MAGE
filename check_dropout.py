import numpy as np
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from models import device

def main():
    tokenizer = AutoTokenizer.from_pretrained('distilbert-base-uncased')
    model = AutoModelForSequenceClassification.from_pretrained('distilbert-base-uncased').to(device)
    
    texts = ['Hello world. this is a test.'] * 50
    inputs = tokenizer(texts, padding=True, truncation=True, return_tensors='pt').to(device)
    
    model.train()
    with torch.no_grad():
        e_train = model.distilbert(**inputs).last_hidden_state[:, 0, :].cpu().numpy()
        
    model.eval()
    with torch.no_grad():
        e_eval = model.distilbert(**inputs).last_hidden_state[:, 0, :].cpu().numpy()
        
    print('Train diag mean:', np.diag(np.cov(e_train.T)).mean())
    print('Eval diag mean :', np.diag(np.cov(e_eval.T)).mean())

if __name__ == "__main__":
    main()
