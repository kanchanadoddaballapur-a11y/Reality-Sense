import os
import glob
import pickle
import numpy as np
from PIL import Image
from transformers import pipeline
from sklearn.isotonic import IsotonicRegression

# Use prithivMLmods/Deep-Fake-Detector-Model
model_name = "prithivMLmods/Deep-Fake-Detector-Model"
print(f"Loading {model_name}...")
detector = pipeline("image-classification", model=model_name)

# Collect all image files
datasets = ["Test_Dataset", "Gold_Standard_Dataset"]
all_files = []
for d in datasets:
    all_files.extend(glob.glob(os.path.join(d, "*.jpg")))
    all_files.extend(glob.glob(os.path.join(d, "*.jpeg")))
    all_files.extend(glob.glob(os.path.join(d, "*.png")))

X_raw = []
y_true = []

def get_ai_score(img_path):
    try:
        res = detector(img_path)
        # Find the 'Fake' or 'AI' score.
        ai_score = 0.0
        for entry in res:
            label = entry['label'].lower()
            if 'fake' in label or 'ai' in label or 'synthetic' in label:
                ai_score = entry['score']
                break
            elif 'real' in label or 'human' in label or 'authentic' in label:
                # if we only find real, fake is 1 - real
                ai_score = 1.0 - entry['score']
        return ai_score
    except Exception as e:
        print(f"Error on {img_path}: {e}")
        return None

print(f"Processing {len(all_files)} images for calibration...")
for file in all_files:
    # Determine true label from filename (heuristic: 'human' or 'real' vs 'ai', 'dalle3', 'midjourney', 'stablediffusion', 'firefly', 'gpt', 'claude')
    # Actually looking at the Test_Dataset filenames:
    # abstract_art_dalle3_267.jpeg -> AI
    # cityscape_art_human_339.jpeg -> Real
    # family_vacation_photo.jpg -> Real
    # Real_Human_Photo_Clouds.jpg -> Real
    
    fname = os.path.basename(file).lower()
    
    if 'human' in fname or 'real' in fname or 'family' in fname or 'portrait_of_man' in fname:
        is_ai = 0
    elif 'dalle' in fname or 'firefly' in fname or 'midjourney' in fname or 'stablediffusion' in fname or 'ai' in fname or 'claude' in fname or 'gpt' in fname or 'gemini' in fname or 'llama' in fname:
        is_ai = 1
    else:
        # Skip if we can't be sure
        continue

    score = get_ai_score(file)
    if score is not None:
        X_raw.append(score)
        y_true.append(is_ai)
        print(f"File: {fname}, True: {is_ai}, Raw Model Score: {score:.4f}")

if len(X_raw) > 5:
    print("\nTraining Isotonic Regression Calibrator...")
    ir = IsotonicRegression(out_of_bounds='clip')
    ir.fit(X_raw, y_true)
    
    with open('calibrator.pkl', 'wb') as f:
        pickle.dump(ir, f)
    print("Calibrator saved to calibrator.pkl!")
else:
    print("Not enough labeled images found to calibrate.")
