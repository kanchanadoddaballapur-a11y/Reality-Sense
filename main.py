import os
import json
import docx
import PyPDF2
import pptx
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime, timedelta
from authlib.integrations.flask_client import OAuth
from google import genai
from google.genai import types as genai_types
import base64
import hashlib

load_dotenv(override=True)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Disable SSL verification globally for local environment issues
# SSL verification is handled by the system; manual clearing is disabled to avoid breaking gRPC.

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

db_url = os.getenv("DATABASE_URL", "sqlite:///users.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 # 100MB Limit
app.permanent_session_lifetime = timedelta(days=30)

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    analyses = db.relationship('Analysis', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    source = db.Column(db.String(200), nullable=False)
    file_hash = db.Column(db.String(64), nullable=True)
    probability = db.Column(db.String(10), nullable=False)
    explanation = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# OAuth Configuration
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
    client_kwargs={'scope': 'openid email profile'}
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin123")

def extract_text_from_file(file, filename):
    text = ""
    ext = filename.rsplit('.', 1)[1].lower()
    
    try:
        if ext == 'txt':
            text = file.read().decode('utf-8')
        elif ext == 'pdf':
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        elif ext == 'docx':
            doc = docx.Document(file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == 'pptx':
            prs = pptx.Presentation(file)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
    except Exception as e:
        print(f"Error extracting text from {ext}: {e}")
    
    return text.strip()

# google.genai client is instantiated per-call in analyze_multimodal

def analyze_multimodal(content_parts):
    if not GEMINI_API_KEY:
        return {"error": "Gemini API key not found."}
    
    # genai.configure already done above
    
    system_prompt = """
    You are an expert forensic AI Detection system. Your job is to analyze the provided content and determine with high confidence whether it was created or significantly assisted by AI tools.

    STEP 1 — WATERMARK SCAN (HIGHEST PRIORITY):
    Scan ALL corners and edges of every frame for ANY watermarks, logos, or text from AI tools including:
    InVideo, Instudio, Runway, Pika, Sora, HeyGen, D-ID, Synthesia, Pictory, Steve.ai, Lumen5, Fliki, Canva AI, CapCut AI, Adobe Firefly, DALL-E, Midjourney.
    If ANY such watermark is detected → probability MUST be "99%".

    STEP 2 — AI VIDEO DETECTION (for video frames):
    You are receiving multiple keyframes extracted from a video. Analyze them collectively.
    
    CHECK FOR THESE AI VIDEO SIGNATURES:
    A) STOCK FOOTAGE ASSEMBLY (InVideo, Pictory, Lumen5 style):
       - Frames show unrelated clips stitched together with no continuity of people or location
       - Text overlays, lower-thirds, or titles appear too perfect and polished
       - Background music feels generic (cannot see but infer from visuals being designed around audio beats)
       - People shown are clearly stock models in generic office/lifestyle settings
       - Scene cuts are abrupt with completely different environments across frames
    
    B) DEEPFAKE / AI AVATAR (HeyGen, D-ID, Synthesia style):
       - Talking head that never moves from its position
       - Background is a solid color, virtual office, or too-perfect studio
       - Lip sync artifacts, unnatural blinking rate, or glassy eyes
       - Skin texture is too smooth and plastic-looking
    
    C) AI-GENERATED VISUALS (Sora, Runway, Pika style):
       - Unnatural object physics or floating elements
       - Morphing or dissolving textures between frames
       - Impossible camera movements
       - Inconsistent lighting across the same scene
    
    D) AI SLIDESHOW VIDEO (Canva AI, PowerPoint AI):
       - Frames show slide-like compositions with text + stock image combinations
       - No natural camera movement, only static or Ken Burns effect slides

    STEP 3 — IMAGE DETECTION:
    Look for AI artifacts: extra fingers, warped backgrounds, unrealistic textures, perfect symmetry, missing reflections, skin that is too smooth.

    STEP 4 — TEXT/DOCUMENT DETECTION:
    Look for: repetitive sentence structures, lack of personal anecdotes, overly formal generic language, no typos or natural flow variation.

    IMPORTANT: Be STRICT and DECISIVE. Do NOT say "uncertain" if multiple AI signatures are present. If 2 or more signals from the above list are detected, the probability should be above 80%.

    Return the response ONLY as a valid JSON object with these exact keys:
    - "probability": "XX%" (string, e.g. "92%")
    - "pattern_consistency": "One sentence describing visual/text pattern consistency."
    - "structural_integrity": "One sentence about structural coherence."
    - "noise_signature": "One sentence about noise or artifact pattern."
    - "metadata_validation": "One sentence about metadata or watermark findings."
    - "explanation": "One clear expert sentence summarizing the verdict."
    """
    
    # Use full model path prefix (confirmed working in test_gemini.py)
    # NOTE: response_mime_type="application/json" is NOT used because
    # gemini-flash-latest does NOT support JSON mode and returns empty/broken JSON.
    # We parse JSON manually from the text response instead.
    models_to_try = [
        'models/gemini-2.5-pro',        # High accuracy - best reasoning and detail scanning
        'models/gemini-2.5-flash',      # Fast fallback - clean JSON responses
        'models/gemini-flash-latest',   # Legacy fallback
    ]
    
    client = genai.Client(api_key=GEMINI_API_KEY)

    for model_name in models_to_try:
        try:
            # Build typed content parts for the new SDK
            sdk_parts = []
            for part in content_parts:
                if isinstance(part, str):
                    sdk_parts.append(part)
                elif isinstance(part, dict) and 'data' in part:
                    import base64 as _b64
                    sdk_parts.append(
                        genai_types.Part.from_bytes(
                            data=_b64.b64decode(part['data']),
                            mime_type=part['mime_type']
                        )
                    )
                else:
                    sdk_parts.append(part)

            response = client.models.generate_content(
                model=model_name,
                contents=[system_prompt] + sdk_parts,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=2048,
                    temperature=0.0
                )
            )

            raw_text = response.text.strip()
            print(f"DEBUG: Model {model_name} raw response (first 200 chars): {raw_text[:200]}")

            # Strip markdown code fences if present
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            # Extract the JSON object from anywhere in the response
            start_idx = raw_text.find('{')
            end_idx = raw_text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                raw_text = raw_text[start_idx:end_idx+1]

            result = json.loads(raw_text)
            print(f"DEBUG: Analysis succeeded with model {model_name}")
            return result
        except Exception as e:
            print(f"DEBUG ERROR: Model {model_name} failed: {str(e)}")
            continue
            
    return {"error": "AI analysis failed. Please try again with a smaller file or different format."}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('signup'))
        
        import re
        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return redirect(url_for('signup'))
            
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('signup'))
        new_user = User(email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')


@app.route('/login', methods=['GET'])
def login():
    return render_template('login.html')

@app.route('/login/basic', methods=['POST'])
def login_basic():
    email = request.form.get('email')
    password = request.form.get('password')
    user = User.query.filter_by(email=email).first()
    if (user and user.check_password(password)) or (email == ADMIN_EMAIL and password == ADMIN_PASSWORD):
        session['user'] = {'email': email}
        session.permanent = True
        return redirect(url_for('dashboard'))
    flash('Invalid email or password', 'error')
    return redirect(url_for('login'))


@app.route('/login/google')
def google_login_route():
    try:
        redirect_uri = url_for('google_authorize_route', _external=True)
        return google.authorize_redirect(redirect_uri)
    except Exception as e:
        return f"Login Error: {str(e)}", 500

@app.route('/login/google/authorize')
def google_authorize_route():
    try:
        token = google.authorize_access_token()
        # Explicitly fetch user info to avoid any parsing issues with id_token
        resp = google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        user_info = resp.json()
        if user_info:
            email = user_info.get('email')
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(email=email)
                user.set_password(os.urandom(16).hex())
                db.session.add(user)
                db.session.commit()
            session['user'] = user_info
            session.permanent = True
        return redirect(url_for('dashboard'))
    except Exception as e:
        flash(f"Google Login failed: {str(e)}")
        return redirect(url_for('login'))

@app.route('/history')
@login_required
def history():
    user = User.query.filter_by(email=session['user']['email']).first()
    if not user:
        user_history = []
    else:
        user_history = Analysis.query.filter_by(user_id=user.id).order_by(Analysis.timestamp.desc()).all()
    return render_template('history.html', history=user_history)

@app.route('/history/clear', methods=['POST'])
@login_required
def clear_history():
    user = User.query.filter_by(email=session['user']['email']).first()
    if user:
        Analysis.query.filter_by(user_id=user.id).delete()
        db.session.commit()
        flash('History cleared successfully.')
    return redirect(url_for('history'))

@app.route('/history/delete/<int:analysis_id>', methods=['POST'])
@login_required
def delete_single_history(analysis_id):
    user = User.query.filter_by(email=session['user']['email']).first()
    if user:
        analysis = Analysis.query.filter_by(id=analysis_id, user_id=user.id).first()
        if analysis:
            db.session.delete(analysis)
            db.session.commit()
            flash('Item deleted successfully.')
    return redirect(url_for('history'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

@app.route('/')
def landing():
    # If user is already logged in, skip landing page and go straight to dashboard
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.filter_by(email=session['user']['email']).first()
    is_new_user = True
    if user:
        history_count = Analysis.query.filter_by(user_id=user.id).count()
        is_new_user = (history_count == 0)
    return render_template('index.html', is_new_user=is_new_user)

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    content_parts = []
    source_name = "Pasted Text"
    
    try:
        user = User.query.filter_by(email=session['user']['email']).first()
        file_hash = None
        
        if 'text' in request.form and request.form['text'].strip():
            text_input = request.form['text'].strip()
            file_hash = hashlib.md5(text_input.encode('utf-8')).hexdigest()
            content_parts.append(text_input)
        # ── New: Browser-side extracted video frames ──────────────
        elif 'video_frames' in request.files:
            frame_files = request.files.getlist('video_frames')
            video_name = request.form.get('video_filename', 'video')
            source_name = video_name

            # Hash all frames combined for caching
            combined = b''
            raw_frames = []
            for f in frame_files:
                data = f.read()
                combined += data
                raw_frames.append((data, f.content_type or 'image/jpeg'))
                f.seek(0)

            file_hash = hashlib.md5(combined).hexdigest()

            # Cache check
            if user and file_hash:
                cached = Analysis.query.filter_by(user_id=user.id, file_hash=file_hash).first()
                if cached:
                    print(f"Returning cached video analysis for {file_hash}")
                    return jsonify(json.loads(cached.explanation))

            # Add a guiding context message FIRST so Gemini treats frames as a video
            video_context = f"""IMPORTANT: The following {len(raw_frames)} images are NOT separate photos.
They are keyframes extracted at equal intervals from the SAME video file named '{video_name}'.
Analyze them COLLECTIVELY as a video, NOT as individual images.

Key things to check across ALL frames together:
1. Do the people, locations, or scenes change dramatically between frames? (stock footage assembly = AI-made)
2. Are there text overlays, titles, or lower-thirds visible? (AI video editor signature)
3. Do the frames look like professionally shot stock footage stitched together? (InVideo, Pictory, Lumen5 pattern)
4. Is there a talking head presenter who barely moves? (HeyGen, D-ID pattern)
5. Are the visuals surreal, morphing, or physically impossible? (Sora, Runway, Pika pattern)

Remember: A video made by InVideo uses real stock footage clips — so individual frames look real. 
But the KEY red flag is that each frame shows a COMPLETELY DIFFERENT scene, people, and location. 
That abrupt scene discontinuity across frames = AI-assembled video = HIGH AI probability.

Now analyze the following frames:"""
            content_parts.append(video_context)

            # Build content parts from the extracted frames
            for frame_data, mime in raw_frames:
                content_parts.append({
                    'mime_type': 'image/jpeg',
                    'data': base64.b64encode(frame_data).decode('utf-8')
                })

        elif 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                source_name = file.filename
                mime_type = file.content_type
                
                file_bytes = file.read()
                file_hash = hashlib.md5(file_bytes).hexdigest()
                file.seek(0)
                
                # Check cache before heavy processing
                if user and file_hash:
                    cached = Analysis.query.filter_by(user_id=user.id, file_hash=file_hash).first()
                    if cached:
                        print(f"Returning cached analysis for {file_hash}")
                        return jsonify(json.loads(cached.explanation))
                
                # Check file size (Gemini API limit is around 20MB for inline data)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                
                if file_size > 100 * 1024 * 1024: # 100MB limit
                    return jsonify({"error": "File too large. Please upload files under 100MB."}), 400
                
                # Text-based documents (Word, PPT, TXT)
                if mime_type in ['text/plain', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
                    text = extract_text_from_file(file, file.filename)
                    if text: content_parts.append(text)
                    else: return jsonify({"error": "Could not extract text from document."}), 400
                
                # Images, Videos, & PDFs (Multimodal)
                elif mime_type.startswith('image/') or mime_type.startswith('video/') or mime_type == 'application/pdf':
                    if mime_type.startswith('video/'):
                        print(f"Uploading video via File API for fast, accurate analysis...")
                        temp_path = f"temp_{file.filename}"
                        file.save(temp_path)
                        
                        try:
                            client = genai.Client(api_key=GEMINI_API_KEY)
                            uploaded_file = client.files.upload(file=temp_path, config={'display_name': file.filename})
                            
                            import time
                            # Poll until processing is complete (Videos are processed asynchronously)
                            while uploaded_file.state.name == "PROCESSING":
                                time.sleep(2)
                                uploaded_file = client.files.get(name=uploaded_file.name)
                            
                            if uploaded_file.state.name == "FAILED":
                                return jsonify({"error": "AI video processing failed."}), 500
                                
                            content_parts.append(uploaded_file)
                        except Exception as e:
                            print(f"Video File API upload failed: {e}")
                            return jsonify({"error": "Failed to upload video for analysis."}), 500
                        finally:
                            if os.path.exists(temp_path): os.remove(temp_path)
                            
                    elif mime_type == 'application/pdf' and file_size > 10 * 1024 * 1024:
                        print(f"Using File API for large PDF ({file_size} bytes)...")
                        temp_path = f"temp_{file.filename}"
                        file.save(temp_path)
                        uploaded_file = genai.upload_file(path=temp_path, display_name=file.filename)
                        
                        import time
                        while uploaded_file.state.name == "PROCESSING":
                            time.sleep(2)
                            uploaded_file = genai.get_file(uploaded_file.name)
                        
                        if uploaded_file.state.name == "FAILED":
                            return jsonify({"error": "AI file processing failed."}), 500
                            
                        content_parts.append(uploaded_file)
                        if os.path.exists(temp_path): os.remove(temp_path)
                    else:
                        if mime_type.startswith('image/'):
                            from PIL import Image
                            import io
                            img = Image.open(file)
                            if img.mode != 'RGB': img = img.convert('RGB')
                            img.thumbnail((1200, 1200)) # Optimized for speed & preservation of artifacts
                            img_byte_arr = io.BytesIO()
                            img.save(img_byte_arr, format='JPEG', quality=85)
                            file_bytes = img_byte_arr.getvalue()
                            mime_type = "image/jpeg"
                        else:
                            file_bytes = file.read()
                            
                        content_parts.append({
                            "mime_type": mime_type,
                            "data": base64.b64encode(file_bytes).decode('utf-8')
                        })
                else:
                    return jsonify({"error": f"Unsupported file type: {mime_type}"}), 400

        if not content_parts:
            return jsonify({"error": "No content provided."}), 400
            
        result = analyze_multimodal(content_parts)
        
        if "error" in result:
            return jsonify(result), 500
            
        # Save to Database
        if user:
            new_analysis = Analysis(
                user_id=user.id,
                source=source_name,
                file_hash=file_hash,
                probability=result.get("probability", "0%"),
                explanation=json.dumps(result)  # Store full JSON for advanced reporting
            )
            db.session.add(new_analysis)
            db.session.commit()
            
        return jsonify(result)
    except Exception as e:
        print(f"Internal Server Error in /analyze: {e}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
