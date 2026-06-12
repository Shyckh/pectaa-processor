import os
import io
import zipfile
from threading import Semaphore
from flask import Flask, request, render_template, send_file
from PIL import Image
from rembg import remove, new_session

app = Flask(__name__)

# CRITICAL FIX: Limit the server to processing exactly ONE image at a time
# This stops the 512MB RAM from overflowing on Render's free tier
memory_guard = Semaphore(1)

# Pre-initialize a lightweight model session to save memory space
try:
    ai_session = new_session("u2net_slim")  # Using the ultra-lightweight AI model
except Exception:
    ai_session = None

def process_single_image(file_bytes, target_width, target_height, max_kb):
    """Processes a single image cleanly within strict memory boundaries."""
    with memory_guard:  # Forces images to wait in line politely
        # 1. Remove background using our lightweight session
        if ai_session:
            subject_only_data = remove(file_bytes, session=ai_session)
        else:
            subject_only_data = remove(file_bytes)
            
        img = Image.open(io.BytesIO(subject_only_data)).convert("RGBA")
        
        # 2. Resize maintaining proportion or matching requested grid
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # 3. Compress to match maximum KB size rules dynamically
        output_io = io.BytesIO()
        img_rgb = img.convert("RGB") # Remove alpha layer for JPEG compression if needed
        
        quality = 95
        while quality > 10:
            output_io.seek(0)
            output_io.truncate(0)
            img_rgb.save(output_io, format="JPEG", quality=quality)
            if output_io.tell() <= max_kb * 1024:
                break
            quality -= 5
            
        return output_io.getvalue()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_bulk', methods=['POST'])
def process_bulk():
    if 'photos' not in request.files:
        return "No files uploaded", 400
        
    files = request.files.getlist('photos')
    target_width = int(request.form.get('width', 600))
    target_height = int(request.form.get('height', 800))
    max_kb = int(request.form.get('max_kb', 20))
    
    zip_io = io.BytesIO()
    
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for idx, file in enumerate(files):
            if file.filename == '':
                continue
                
            file_bytes = file.read()
            try:
                processed_bytes = process_single_image(file_bytes, target_width, target_height, max_kb)
                
                # Create clean unique naming layout
                filename = f"student_photo_{idx+1}.jpg"
                zip_file.writestr(filename, processed_bytes)
            except Exception as e:
                print(f"Skipping broken photo entry {idx}: {str(e)}")
                continue
                
    zip_io.seek(0)
    return send_file(
        zip_io,
        mimetype='application/zip',
        as_attachment=True,
        download_name='processed_student_photos.zip'
    )

if __name__ == '__main__':
    # Ensure port matches cloud environment metrics
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
