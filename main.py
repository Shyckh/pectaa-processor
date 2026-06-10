import os
import zipfile
from flask import Flask, render_template, request, send_file
from PIL import Image, ImageOps
from rembg import remove
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# We create a thread pool worker group (handles up to 4 photos at the exact same time)
executor = ThreadPoolExecutor(max_workers=4)

TARGET_SIZE = (600, 800)
MAX_FILE_SIZE_KB = 20

def process_single_image(file_data, filename, target_size, user_max_kb):
    """Processes a single image matrix out of the main thread loop."""
    try:
        # AI Background Removal
        subject_only_data = remove(file_data)
        subject_img = Image.open(BytesIO(subject_only_data)).convert("RGBA")
        
        # Auto Crop bounding boxes
        bbox = subject_img.getbbox()
        if bbox:
            subject_img = subject_img.crop(bbox)
            
        # Zoom and Fit
        filled_subject = ImageOps.fit(subject_img, target_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.3))
        
        # Canvas Creation
        white_bg = Image.new("RGBA", target_size, (255, 255, 255, 255))
        white_bg.paste(filled_subject, (0, 0), filled_subject)
        final_img = white_bg.convert("RGB")
        
        # Compression Loop
        quality = 95
        img_buffer = BytesIO()
        while quality > 5:
            img_buffer.seek(0)
            img_buffer.truncate(0)
            final_img.save(img_buffer, format="JPEG", quality=quality)
            if (len(img_buffer.getvalue()) / 1024) <= user_max_kb:
                break
            quality -= 5
        else:
            img_buffer.seek(0)
            img_buffer.truncate(0)
            final_img.save(img_buffer, format="JPEG", quality=5)

        img_buffer.seek(0)
        original_base = os.path.splitext(filename)[0]
        return f"{original_base}_custom.jpg", img_buffer.getvalue()
    except Exception as e:
        print(f"Error processing {filename}: {str(e)}")
        return None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/process_bulk', methods=['POST'])
def process_bulk_images():
    try:
        user_width = int(request.form.get('width', 600))
        user_height = int(request.form.get('height', 800))
        user_max_kb = int(request.form.get('max_kb', 20))
    except ValueError:
        return "Invalid numeric dimensions entered.", 400

    target_size = (user_width, user_height)

    if 'photos' not in request.files:
        return "No files uploaded", 400
        
    files = request.files.getlist('photos')
    if not files or files[0].filename == '':
        return "No files selected", 400

    # Read all files into memory quickly before processing
    uploaded_data = [(f.read(), f.filename) for f in files if f.filename != '']

    # Submit all image jobs to our ThreadPool parallel lanes
    futures = [
        executor.submit(process_single_image, data, name, target_size, user_max_kb)
        for data, name in uploaded_data
    ]

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for future in futures:
            result = future.result()  # Gathers the finished photo data
            if result:
                img_name, img_bytes = result
                zip_file.writestr(img_name, img_bytes)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name="custom_processed_photos.zip"
    )

if __name__ == "__main__":
    app.run(debug=True)