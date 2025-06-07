from flask import Blueprint, request, jsonify, render_template, current_app
import os
import uuid
import json
from werkzeug.utils import secure_filename
from cv_utils import allowed_file, extract_text_from_pdf, extract_text_from_docx, parse_cv_text

upload_bp = Blueprint('upload', __name__)

@upload_bp.route('/upload')
def upload_page():
    return render_template('upload.html')

@upload_bp.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    mode = request.form.get('mode', 'professional')
    job_description = request.form.get('job_description', '')
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        if filename.lower().endswith('.pdf'):
            extracted_text = extract_text_from_pdf(file_path)
        elif filename.lower().endswith('.docx'):
            extracted_text = extract_text_from_docx(file_path)
        else:
            return jsonify({'error': 'Unsupported file type'}), 400
        parsed_data = parse_cv_text(extracted_text, gemini_api_key=os.getenv('GEMINI_API_KEY'))
        # (Enhance for job, save to sheets, etc. can be added here)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as cleanup_error:
            print(f"⚠️ Could not clean up uploaded file: {cleanup_error}")
        session_id = str(uuid.uuid4())
        cv_data = {
            'parsed_data': parsed_data,
            'mode': mode,
            'job_description': job_description,
            'original_filename': filename
        }
        session_file = os.path.join('temp_sessions', f'{session_id}.json')
        os.makedirs('temp_sessions', exist_ok=True)
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(cv_data, f, ensure_ascii=False, indent=2)
        return jsonify({
            'success': True,
            'session_id': session_id,
            'redirect_url': f'/preview-cv/{session_id}'
        })
    return jsonify({'error': 'Invalid file type. Please upload PDF or DOCX files only.'}), 400
