import os
import re
import json
import requests
from flask import Flask, request, render_template, jsonify, send_file
from werkzeug.utils import secure_filename
import PyPDF2
from docx import Document
import openai
from dotenv import load_dotenv
import tempfile
import subprocess
import time
import traceback
import shutil
import uuid
from sheets_integration import save_cv_to_sheets
from flask_login import login_required, current_user
from auth import auth_bp, get_login_manager, users, User

load_dotenv()

GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv('GOOGLE_SHEETS_SPREADSHEET_ID')

if os.path.exists('/app/latex_env.sh'):
    try:
        with open('/app/latex_env.sh', 'r') as f:
            content = f.read()
        
        for line in content.split('\n'):
            if line.startswith('export '):
                var_line = line[7:]
                if '=' in var_line:
                    key, value = var_line.split('=', 1)
                    value = value.strip('"\'')
                    if key == 'PATH':
                        current_path = os.environ.get('PATH', '')
                        if value not in current_path:
                            os.environ['PATH'] = f"{value}:{current_path}"
                    else:
                        os.environ[key] = value
        print("✅ LaTeX environment variables loaded")
    except Exception as e:
        print(f"⚠️ Could not load LaTeX environment: {e}")

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev_secret_key')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'

login_manager = get_login_manager(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

CV_DATA_FOLDER = 'cv_data'
os.makedirs(CV_DATA_FOLDER, exist_ok=True)

LATEX_AVAILABLE = False

pdflatex_paths = [
    '/opt/texlive/bin/x86_64-linux/pdflatex',
    '/usr/local/bin/pdflatex',
    '/usr/bin/pdflatex',
    shutil.which('pdflatex')
]

for path in pdflatex_paths:
    if path and os.path.exists(path) and os.access(path, os.X_OK):
        LATEX_AVAILABLE = True
        print(f"✅ Found pdflatex at: {path}")
        break

if not LATEX_AVAILABLE:
    LATEX_AVAILABLE = shutil.which('pdflatex') is not None

if os.name == 'nt' and shutil.which('pdflatex'):
    LATEX_AVAILABLE = True
    print(f"🪟 Windows detected - LaTeX force-enabled for local development")

BUILD_STATUS = "unknown"
LATEX_BUILD_MESSAGE = "LaTeX status unknown"

try:
    if os.path.exists('/app/latex_status.txt'):
        with open('/app/latex_status.txt', 'r') as f:
            content = f.read().strip()
            lines = content.split('\n')
            BUILD_STATUS = lines[0] if lines else "unknown"
            LATEX_BUILD_MESSAGE = lines[1] if len(lines) > 1 else "No details available"
        print(f"📋 Build Status: {BUILD_STATUS}")
        print(f"📄 Details: {LATEX_BUILD_MESSAGE}")
    else:
        print("📋 No build status file found - running in development mode")
except Exception as e:
    print(f"⚠️ Could not read build status: {e}")

print(f"🌍 Environment: {os.getenv('FLASK_ENV', 'development')}")
print(f"🐍 Python: {os.sys.version.split()[0]}")
print(f"📁 Working Directory: {os.getcwd()}")
print(f"🔧 PATH (first 200 chars): {os.getenv('PATH', '')[:200]}...")

if LATEX_AVAILABLE:
    print("✅ LaTeX (pdflatex) is available - PDF generation enabled")
    try:
        import subprocess
        result = subprocess.run(['pdflatex', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout:
            version_line = result.stdout.split('\n')[0]
            print(f"📄 pdflatex version: {version_line}")
    except Exception as e:
        print(f"⚠️ Could not get pdflatex version: {e}")
    
    if BUILD_STATUS == "SUCCESS":
        print("🎉 Deployment build confirmed LaTeX installation successful")
    elif BUILD_STATUS == "FAILED":
        print("⚠️ Build reported LaTeX failure, but pdflatex found locally")
else:
    print("⚠️ LaTeX (pdflatex) not found - running in LaTeX-only mode")
    print("📄 Users can download LaTeX files and compile them elsewhere")
    if BUILD_STATUS == "FAILED":
        print("❌ Deployment build confirmed LaTeX installation failed")
    elif BUILD_STATUS == "SUCCESS":
        print("🤔 Build reported success, but pdflatex not found - possible PATH issue")

if os.path.exists('/app/latex_warning.txt'):
    print("⚠️ LaTeX warning file detected")
    try:
        with open('/app/latex_warning.txt', 'r') as f:
            warning_content = f.read()
        print("📄 Warning details available at /debug/latex-warning")
    except Exception as e:
        print(f"⚠️ Could not read warning file: {e}")

openai.api_key = os.getenv('OPENAI_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyC5rY2zgtv6x2JM8Ew0Ia-1oCUax2q1ubU')

ALLOWED_EXTENSIONS = {'pdf', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    """Extract text from PDF file"""
    text = ""
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
    return text

def extract_text_from_docx(file_path):
    """Extract text from DOCX file"""
    text = ""
    try:
        doc = Document(file_path)
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
    except Exception as e:
        print(f"Error extracting text from DOCX: {e}")
    return text

def enhance_parsing_with_gemini(text):
    """Use Gemini AI to parse CV text and extract structured information"""
    
    prompt = f"""
    Parse the following CV/Resume text and extract structured information in JSON format. 
    IMPORTANT: Only include information that actually exists in the CV text. Do not add placeholder or example data.
    If a field doesn't exist in the CV, either omit it entirely or set it to null/empty.
    
    Required JSON structure (only include fields that have actual data):
    {{
        "name": "Full name (only if found)",
        "email": "Email address (only if found)",
        "phone": "Phone number (only if found)",
        "linkedin": "LinkedIn URL (only if found)",
        "github": "GitHub URL (only if found)",
        "website": "Personal website (only if found)",
        "address": "Address/Location (only if found)",
        "education": [
            {{
                "degree": "Degree name",
                "institution": "Institution name",
                "date": "Date range",
                "location": "Location (if mentioned)",
                "gpa": "GPA (if mentioned)",
                "details": "Additional details (if any)"
            }}
        ],
        "experience": [
            {{
                "title": "Job title",
                "company": "Company name",
                "date": "Date range",
                "location": "Location (if mentioned)",
                "description": ["List of responsibilities and achievements"]
            }}
        ],
        "projects": [
            {{
                "title": "Project name",
                "description": "Project description",
                "technologies": "Technologies used",
                "date": "Date or duration (if mentioned)",
                "link": "Project link (if mentioned)"
            }}
        ],
        "skills": {{
            "languages": ["Programming languages (only if mentioned)"],
            "frameworks": ["Frameworks and libraries (only if mentioned)"],
            "tools": ["Tools and software (only if mentioned)"],
            "libraries": ["Additional libraries (only if mentioned)"],
            "databases": ["Databases (only if mentioned)"],
            "other": ["Other technical skills (only if mentioned)"]
        }},
        "certifications": [
            {{
                "name": "Certification name",
                "issuer": "Issuing organization",
                "date": "Date obtained (if mentioned)"
            }}
        ],
        "awards": ["Awards and honors (only if mentioned)"],
        "languages": ["Spoken languages (only if mentioned)"],
        "custom_sections": [
            {{
                "title": "Section title",
                "content": "Section content"
            }}
        ]
    }}
    
    CV Text:
    {text}
    
    Return only the JSON object with actual data from the CV, no additional text:
    """
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        data = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            generated_text = result['candidates'][0]['content']['parts'][0]['text']
            
            json_start = generated_text.find('{')
            json_end = generated_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = generated_text[json_start:json_end]
                parsed_data = json.loads(json_text)
                return parsed_data
            else:
                print("Failed to extract JSON from Gemini response")
                return None
        else:
            print(f"Gemini API error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"Error with Gemini API: {e}")
        return None

def parse_cv_text(text):
    """Parse CV text and extract structured information with fallback"""
    
    print("=== SCRAPED CV TEXT ===")
    print(text[:1000] + "..." if len(text) > 1000 else text)
    print("=== END SCRAPED TEXT ===")
    
    gemini_result = enhance_parsing_with_gemini(text)
    if gemini_result:
        print("=== GEMINI PARSED DATA ===")
        print(json.dumps(gemini_result, indent=2))
        print("=== END GEMINI DATA ===")
        return gemini_result
    
    print("Gemini failed, using fallback parsing...")
    
    parsed_data = {
        'name': '',
        'email': '',
        'phone': '',
        'linkedin': '',
        'github': '',
        'website': '',
        'address': '',
        'education': [],
        'experience': [],
        'projects': [],
        'skills': {
            'languages': [],
            'frameworks': [],
            'tools': [],
            'libraries': [],
            'databases': [],
            'other': []
        },
        'certifications': [],
        'awards': [],
        'languages': [],
        'custom_sections': []
    }
    
    lines = text.split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    
    for line in lines:
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', line)
        if email_match and not parsed_data['email']:
            parsed_data['email'] = email_match.group()
        
        phone_match = re.search(r'(\+?1?[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})', line)
        if phone_match and not parsed_data['phone']:
            parsed_data['phone'] = phone_match.group()
        
        if 'linkedin.com' in line.lower() and not parsed_data['linkedin']:
            parsed_data['linkedin'] = line.strip()
        
        if 'github.com' in line.lower() and not parsed_data['github']:
            parsed_data['github'] = line.strip()
        
        if ('http' in line.lower() or 'www.' in line.lower()) and 'linkedin' not in line.lower() and 'github' not in line.lower() and not parsed_data['website']:
            parsed_data['website'] = line.strip()
    
    if lines and not parsed_data['name']:
        for line in lines[:5]:
            if not re.search(r'[@()]', line) and len(line.split()) <= 4 and len(line) > 2:
                parsed_data['name'] = line
                break
    
    current_section = None
    current_item = {}
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        if any(keyword in line_lower for keyword in ['education', 'academic']):
            current_section = 'education'
            continue
        elif any(keyword in line_lower for keyword in ['experience', 'work', 'employment', 'professional']):
            current_section = 'experience'
            continue
        elif any(keyword in line_lower for keyword in ['project', 'portfolio']):
            current_section = 'projects'
            continue
        elif any(keyword in line_lower for keyword in ['skill', 'technical', 'programming', 'languages']):
            current_section = 'skills'
            continue
        
        if current_section == 'education' and line:
            if any(degree in line_lower for degree in ['bachelor', 'master', 'phd', 'associate', 'certificate']):
                if current_item:
                    parsed_data['education'].append(current_item)
                current_item = {'degree': line, 'institution': '', 'date': ''}
            elif current_item and not current_item['institution']:
                current_item['institution'] = line
            elif current_item and re.search(r'\d{4}', line):
                current_item['date'] = line
        
        elif current_section == 'experience' and line:
            if any(char in line for char in ['-', '|']) or re.search(r'\d{4}', line):
                if current_item:
                    parsed_data['experience'].append(current_item)
                current_item = {'title': line, 'company': '', 'date': '', 'description': []}
            elif current_item and not current_item.get('description'):
                current_item['description'] = [line]
            elif current_item:
                current_item['description'].append(line)
        
        elif current_section == 'projects' and line:
            if current_item and 'title' in current_item:
                parsed_data['projects'].append(current_item)
                current_item = {}
            current_item = {'title': line, 'description': '', 'technologies': ''}
        
        elif current_section == 'skills' and line:
            if any(keyword in line_lower for keyword in ['language', 'programming']):
                skills_text = line.split(':')[-1] if ':' in line else line
                parsed_data['skills']['languages'] = [s.strip() for s in skills_text.split(',') if s.strip()]
            elif any(keyword in line_lower for keyword in ['framework']):
                skills_text = line.split(':')[-1] if ':' in line else line
                parsed_data['skills']['frameworks'] = [s.strip() for s in skills_text.split(',') if s.strip()]
            elif any(keyword in line_lower for keyword in ['tool', 'software']):
                skills_text = line.split(':')[-1] if ':' in line else line
                parsed_data['skills']['tools'] = [s.strip() for s in skills_text.split(',') if s.strip()]
    
    if current_item:
        if current_section == 'education':
            parsed_data['education'].append(current_item)
        elif current_section == 'experience':
            parsed_data['experience'].append(current_item)
        elif current_section == 'projects':
            parsed_data['projects'].append(current_item)
    
    cleaned_data = {}
    for key, value in parsed_data.items():
        if key == 'skills':
            skills_cleaned = {k: v for k, v in value.items() if v}
            if skills_cleaned:
                cleaned_data[key] = skills_cleaned
        elif isinstance(value, list):
            if value:
                cleaned_data[key] = value
        elif isinstance(value, str):
            if value:
                cleaned_data[key] = value
        else:
            if value:
                cleaned_data[key] = value
    
    return cleaned_data

app.register_blueprint(auth_bp)

@app.route('/')
def index():
    return render_template('landing.html')

if __name__ == '__main__':
    app.run(debug=True)
