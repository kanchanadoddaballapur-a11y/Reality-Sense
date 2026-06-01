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
                // Assign dropped file to input
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

    // ─── Form Submission ──────────────────────────────────────
    if (form) {
        form.addEventListener('submit', async (e) => {
            console.log('Form submission started');
            e.preventDefault();

            hideResult();
            errorMessage.classList.add('hidden');

            const hasFile  = fileInput.files.length > 0;

            if (!hasFile) { showError('Please select a file to analyze.'); return; }

            // Loading state
            submitBtn.disabled = true;
            btnText.textContent = 'Analyzing...';
            loader.classList.remove('hidden');
            
            const videoScanner = document.getElementById('video-scanner');
            const imageScanner = document.getElementById('image-scanner');
            const scannerTextDisplay = document.getElementById('scanner-text-display');
            
            const isVideo = hasFile && fileInput.files[0].type.startsWith('video/');
            const isImage = hasFile && fileInput.files[0].type.startsWith('image/');
            
            if (isVideo && videoScanner) videoScanner.classList.remove('hidden');
            if (isImage && imageScanner) imageScanner.classList.remove('hidden');

            let msgs = ['Scanning patterns…', 'Verifying authenticity…', 'Analyzing metadata…', 'Generating report…'];
            if (isVideo) {
                msgs = [
                    'Uploading video...', 
                    'Processing video frames (this may take up to a minute)...', 
                    'Scanning for temporal AI artifacts...', 
                    'Verifying physics & consistency...',
                    'Still analyzing, please be patient...',
                    'Generating final AI report...'
                ];
            }
            
            let msgIdx = 0;
            const msgTimer = setInterval(() => {
                const nextMsg = msgs[msgIdx++ % msgs.length];
                if (submitBtn.disabled) { 
                    btnText.textContent = nextMsg; 
                    if (isVideo && scannerTextDisplay) scannerTextDisplay.textContent = nextMsg;
                }
            }, 4000);

            try {
                const response = await fetch('/analyze', { method: 'POST', body: new FormData(form) });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'An error occurred during analysis.');
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

        // Show result panel
        resultEmpty.classList.add('hidden');
        resultSection.classList.remove('hidden');

        // Animate percentage
        animateValue(probabilityValue, 0, prob, 1100);

        // Update progress ring (circumference for r=42: 2*PI*42 ≈ 264)
        const circ = 264;
        progressCircle.style.strokeDasharray = circ;
        progressCircle.style.strokeDashoffset = circ - (prob / 100) * circ;

        // Color & Verdict
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
        
        // Populate Advanced Breakdown
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
