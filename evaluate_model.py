import os
import glob
import pickle
import numpy as np
from PIL import Image
from transformers import pipeline
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix

model_name = "prithivMLmods/Deep-Fake-Detector-Model"
print(f"Loading {model_name}...")
detector = pipeline("image-classification", model=model_name)

print("Loading Isotonic Calibrator...")
with open('calibrator.pkl', 'rb') as f:
    calibrator = pickle.load(f)

# Collect test images
datasets = ["Test_Dataset", "Gold_Standard_Dataset"]
all_files = []
for d in datasets:
    all_files.extend(glob.glob(os.path.join(d, "*.jpg")))
    all_files.extend(glob.glob(os.path.join(d, "*.jpeg")))
    all_files.extend(glob.glob(os.path.join(d, "*.png")))

y_true = []
y_pred = []
y_scores = []

def get_ai_score(img_path):
    try:
        res = detector(img_path)
        ai_score = 0.0
        for entry in res:
            label = entry['label'].lower()
            if 'fake' in label or 'ai' in label or 'synthetic' in label:
                ai_score = entry['score']
                break
            elif 'real' in label or 'human' in label or 'authentic' in label:
                ai_score = 1.0 - entry['score']
        return ai_score
    except Exception as e:
        return None

print(f"Evaluating on {len(all_files)} images...")
for file in all_files:
    fname = os.path.basename(file).lower()
    
    if 'human' in fname or 'real' in fname or 'family' in fname or 'portrait_of_man' in fname:
        is_ai = 0
    elif 'dalle' in fname or 'firefly' in fname or 'midjourney' in fname or 'stablediffusion' in fname or 'ai' in fname or 'claude' in fname or 'gpt' in fname or 'gemini' in fname or 'llama' in fname:
        is_ai = 1
    else:
        continue

    raw_score = get_ai_score(file)
    if raw_score is not None:
        # Calibrate the score
        calibrated_prob = calibrator.predict([raw_score])[0]
        
        y_true.append(is_ai)
        y_scores.append(calibrated_prob)
        # Threshold at 50%
        y_pred.append(1 if calibrated_prob >= 0.5 else 0)

if len(y_true) > 0:
    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred)
    rec = recall_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred)
    
    # Calculate ROC-AUC if we have both classes
    if len(set(y_true)) > 1:
        roc_auc = roc_auc_score(y_true, y_scores)
    else:
        roc_auc = float('nan')
        
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0,0,0,0)
    
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0

    print("\n" + "="*50)
    print("EVALUATION RESULTS (CALIBRATED HF MODEL)")
    print("="*50)
    print(f"Accuracy:  {acc:.4f}")
    print(f"Precision: {prec:.4f}")
    print(f"Recall:    {rec:.4f}")
    print(f"F1 Score:  {f1:.4f}")
    print(f"ROC-AUC:   {roc_auc:.4f}")
    print("-" * 50)
    print(f"False Positive Rate (Real classified as AI): {fpr:.4f}")
    print(f"False Negative Rate (AI classified as Real): {fnr:.4f}")
    print("-" * 50)
    print("Confusion Matrix:")
    print(f"                 Predicted Real | Predicted AI")
    print(f"Actual Real    | {tn:<14} | {fp:<12}")
    print(f"Actual AI      | {fn:<14} | {tp:<12}")
    print("="*50)
else:
    print("No valid test data found for evaluation.")
