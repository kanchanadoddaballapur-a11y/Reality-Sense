document.addEventListener('DOMContentLoaded', () => {
    const form            = document.getElementById('analyze-form');
    const fileInput       = document.getElementById('file-input');
    const filePreview     = document.getElementById('file-preview');
    const fileNameDisplay = document.getElementById('file-name');
    const fileClearBtn    = document.getElementById('file-clear-btn');
    const fileDropZone    = document.getElementById('file-drop-zone');
    const submitBtn       = document.getElementById('submit-btn');
    const btnText         = submitBtn.querySelector('.btn-text');
    const loader          = submitBtn.querySelector('.loader');
    const resultSection   = document.getElementById('result-section');
    const resultEmpty     = document.getElementById('result-empty');
    const errorMessage    = document.getElementById('error-message');
    const sampleBtn       = document.getElementById('sample-btn');

    // Result elements
    const probabilityValue = document.getElementById('probability-value');
    const explanationText  = document.getElementById('explanation-text');
    const progressCircle   = document.querySelector('.circular-progress .progress');
    const verdictBadge     = document.getElementById('verdict-badge');

    // ─── File Input: show preview ─────────────────────────────
    if (fileInput) {
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                showFilePreview(fileInput.files[0]);
            }
        });
    }

    // ─── File Clear Button ────────────────────────────────────
    fileClearBtn && fileClearBtn.addEventListener('click', clearFile);

    // ─── Drag & Drop ──────────────────────────────────────────
    if (fileDropZone) {
        fileDropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            fileDropZone.classList.add('drag-over');
        });
        fileDropZone.addEventListener('dragleave', () => {
            fileDropZone.classList.remove('drag-over');
        });
        fileDropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            fileDropZone.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                const dt = new DataTransfer();
                dt.items.add(e.dataTransfer.files[0]);
                fileInput.files = dt.files;
                showFilePreview(e.dataTransfer.files[0]);
            }
        });
    }

    function showFilePreview(file) {
        fileNameDisplay.textContent = file.name;
        filePreview.classList.remove('hidden');
        fileDropZone.style.display = 'none';

        const imgContainer = document.getElementById('image-preview-container');
        const imgThumb = document.getElementById('image-thumbnail');
        
        if (file.type.startsWith('image/')) {
            const reader = new FileReader();
            reader.onload = (e) => {
                imgThumb.src = e.target.result;
                imgContainer.classList.remove('hidden');
            };
            reader.readAsDataURL(file);
        } else {
            if (imgContainer) imgContainer.classList.add('hidden');
            if (imgThumb) imgThumb.src = '';
        }
    }

    function clearFile() {
        fileInput.value = '';
        fileNameDisplay.textContent = '';
        filePreview.classList.add('hidden');
        if (fileDropZone) fileDropZone.style.display = '';
        
        const imgContainer = document.getElementById('image-preview-container');
        const imgThumb = document.getElementById('image-thumbnail');
        if (imgContainer) imgContainer.classList.add('hidden');
        if (imgThumb) imgThumb.src = '';
    }

    // ─── Client-Side Video Frame Extractor ───────────────────
    // Instead of uploading the full video to the slow Render server,
    // we snap 8 keyframes directly in the browser and send only those.
    function extractVideoFrames(file, numFrames = 8) {
        return new Promise((resolve, reject) => {
            const video = document.createElement('video');
            video.preload = 'auto';
            video.muted = true;
            video.playsInline = true;
            const url = URL.createObjectURL(file);
            video.src = url;

            video.addEventListener('error', () => {
                URL.revokeObjectURL(url);
                reject(new Error('Could not load video for frame extraction.'));
            });

            video.addEventListener('loadedmetadata', async () => {
                const duration = video.duration;
                if (!duration || duration === Infinity) {
                    URL.revokeObjectURL(url);
                    reject(new Error('Cannot determine video duration.'));
                    return;
                }

                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                const MAX_DIM = 720;
                const frames = [];

                // Seek to each timestamp and capture a frame
                for (let i = 0; i < numFrames; i++) {
                    // Evenly space frames across the video, avoiding the very first/last frame
                    const t = (duration / (numFrames + 1)) * (i + 1);
                    await seekAndCapture(video, canvas, ctx, MAX_DIM, t)
                        .then(blob => frames.push(blob))
                        .catch(() => {}); // skip a bad frame silently
                }

                URL.revokeObjectURL(url);
                resolve(frames);
            });

            video.load();
        });
    }

    function seekAndCapture(video, canvas, ctx, maxDim, time) {
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error('seek timeout')), 5000);
            
            video.currentTime = time;
            video.addEventListener('seeked', function handler() {
                video.removeEventListener('seeked', handler);
                clearTimeout(timeout);
                try {
                    let w = video.videoWidth;
                    let h = video.videoHeight;
                    if (w > maxDim || h > maxDim) {
                        const scale = maxDim / Math.max(w, h);
                        w = Math.round(w * scale);
                        h = Math.round(h * scale);
                    }
                    canvas.width = w;
                    canvas.height = h;
                    ctx.drawImage(video, 0, 0, w, h);
                    canvas.toBlob((blob) => {
                        if (blob) resolve(blob);
                        else reject(new Error('canvas toBlob failed'));
                    }, 'image/jpeg', 0.82);
                } catch (err) {
                    reject(err);
                }
            }, { once: true });
        });
    }

    async function fetchWithRetry(url, options, maxRetries = 3, delayMs = 4000) {
        let lastError = null;
        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                const response = await fetch(url, options);
                
                // If it's a 502, 503, or 504 from Render's load balancer during spin up
                if (response.status === 502 || response.status === 503 || response.status === 504) {
                    throw new Error(`Server is starting up (status ${response.status}).`);
                }
                
                const contentType = response.headers.get('content-type') || '';
                if (!contentType.includes('application/json')) {
                    throw new Error('Server returned HTML instead of JSON (possibly gateway error).');
                }
                
                const data = await response.json();
                if (!response.ok) {
                    // Standard user/logic error from our own Flask server - do not retry
                    throw new Error(data.error || `Server error ${response.status}`);
                }
                return data;
            } catch (err) {
                console.warn(`Attempt ${attempt} failed:`, err);
                lastError = err;
                
                // If it is a logic error from Flask (status 400, etc.), do not retry
                if (err.message && !err.message.includes('starting up') && !err.message.includes('HTML') && !err.message.includes('Failed to fetch')) {
                    throw err;
                }
                
                if (attempt < maxRetries) {
                    const statusMsg = `Server is warming up (Attempt ${attempt}/${maxRetries})...`;
                    if (btnText) btnText.textContent = statusMsg;
                    const scannerTextDisplay = document.getElementById('scanner-text-display');
                    if (scannerTextDisplay) scannerTextDisplay.textContent = statusMsg;
                    
                    await new Promise(resolve => setTimeout(resolve, delayMs));
                    delayMs += 2000; // Increment backoff
                }
            }
        }
        throw lastError || new Error('Request failed after max retries.');
    }

    // ─── Form Submission ──────────────────────────────────────
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            hideResult();
            errorMessage.classList.add('hidden');

            const hasFile = fileInput.files.length > 0;
            if (!hasFile) { showError('Please select a file to analyze.'); return; }

            const selectedFile = fileInput.files[0];
            const isVideo = selectedFile.type.startsWith('video/');
            const isImage = selectedFile.type.startsWith('image/');

            // Loading state
            submitBtn.disabled = true;
            btnText.textContent = 'Analyzing...';
            loader.classList.remove('hidden');
            
            const videoScanner = document.getElementById('video-scanner');
            const imageScanner = document.getElementById('image-scanner');
            const scannerTextDisplay = document.getElementById('scanner-text-display');
            
            if (isVideo && videoScanner) videoScanner.classList.remove('hidden');
            if (isImage && imageScanner) imageScanner.classList.remove('hidden');

            let msgs = isVideo
                ? ['Extracting video frames...', 'Scanning for deepfake artifacts...', 'Analyzing temporal consistency...', 'Checking motion physics...', 'Generating AI report...']
                : ['Scanning patterns…', 'Verifying authenticity…', 'Analyzing metadata…', 'Generating report…'];
            
            let msgIdx = 0;
            const msgTimer = setInterval(() => {
                const nextMsg = msgs[msgIdx++ % msgs.length];
                if (submitBtn.disabled) { 
                    btnText.textContent = nextMsg; 
                    if (isVideo && scannerTextDisplay) scannerTextDisplay.textContent = nextMsg;
                }
            }, 3000);

            try {
                let formData;

                if (isVideo) {
                    // ── CLIENT-SIDE FRAME EXTRACTION ──
                    // Snap frames in browser, then send them as images
                    btnText.textContent = 'Extracting frames in browser...';
                    if (scannerTextDisplay) scannerTextDisplay.textContent = 'Snapping keyframes locally...';
                    
                    let frames;
                    try {
                        frames = await extractVideoFrames(selectedFile, 8);
                    } catch (err) {
                        // Fallback: send raw video if frame extraction fails
                        console.warn('Frame extraction failed, falling back to raw upload:', err);
                        frames = null;
                    }

                    if (frames && frames.length > 0) {
                        formData = new FormData();
                        // Append original filename so server knows the source
                        formData.append('video_filename', selectedFile.name);
                        frames.forEach((blob, i) => {
                            formData.append('video_frames', blob, `frame_${i}.jpg`);
                        });
                    } else {
                        // Fallback to raw upload if extraction totally failed
                        formData = new FormData(form);
                    }
                } else {
                    formData = new FormData(form);
                }

                btnText.textContent = 'Sending to AI...';
                const data = await fetchWithRetry('/analyze', { method: 'POST', body: formData });
                displayResult(data);
            } catch (err) {
                showError(err.message);
            } finally {
                clearInterval(msgTimer);
                submitBtn.disabled = false;
                btnText.textContent = 'Start Analysis';
                loader.classList.add('hidden');
                if (videoScanner) videoScanner.classList.add('hidden');
                if (imageScanner) imageScanner.classList.add('hidden');
            }
        });
    }

    // ─── Display Result ───────────────────────────────────────
    function displayResult(data) {
        let prob = 0;
        if (typeof data.probability === 'string') {
            prob = parseInt(data.probability.replace('%', '')) || 0;
        } else if (typeof data.probability === 'number') {
            prob = data.probability;
        }

        resultEmpty.classList.add('hidden');
        resultSection.classList.remove('hidden');

        animateValue(probabilityValue, 0, prob, 1100);

        const circ = 264;
        progressCircle.style.strokeDasharray = circ;
        progressCircle.style.strokeDashoffset = circ - (prob / 100) * circ;

        if (prob < 30) {
            progressCircle.style.stroke = '#10B981';
            verdictBadge.textContent = 'Likely Human';
            verdictBadge.className = 'verdict-badge human';
        } else if (prob < 70) {
            progressCircle.style.stroke = '#F59E0B';
            verdictBadge.textContent = 'Mixed / Uncertain';
            verdictBadge.className = 'verdict-badge mixed';
        } else {
            progressCircle.style.stroke = '#EF4444';
            verdictBadge.textContent = 'Likely AI-Generated';
            verdictBadge.className = 'verdict-badge ai';
        }

        explanationText.textContent = data.explanation || 'No explanation provided.';
        document.getElementById('pattern-text').textContent = data.pattern_consistency || 'Data unavailable.';
        document.getElementById('structure-text').textContent = data.structural_integrity || 'Data unavailable.';
        document.getElementById('noise-text').textContent = data.noise_signature || 'Data unavailable.';
        document.getElementById('metadata-text').textContent = data.metadata_validation || 'Data unavailable.';
    }

    function hideResult() {
        resultSection.classList.add('hidden');
        resultEmpty.classList.remove('hidden');
    }

    function animateValue(el, start, end, duration) {
        let t0 = null;
        const step = (ts) => {
            if (!t0) t0 = ts;
            const prog = Math.min((ts - t0) / duration, 1);
            el.innerHTML = Math.floor(prog * (end - start) + start) + '%';
            if (prog < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }

    function showError(msg) {
        errorMessage.textContent = msg;
        errorMessage.classList.remove('hidden');
    }

    // ─── Sample Button ────────────────────────────────────────
    sampleBtn && sampleBtn.addEventListener('click', () => {
        document.getElementById('text-input').value =
            'As an AI language model, I can assist you with a wide range of tasks including writing, analysis, coding, and answering questions. My responses are generated based on patterns learned from large datasets of text, allowing me to produce fluent and coherent content on virtually any topic.';
    });
});
