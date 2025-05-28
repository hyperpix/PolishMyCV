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

# Load environment variables
load_dotenv()

# Source LaTeX environment if available (for Render deployment)
if os.path.exists('/app/latex_env.sh'):
    try:
        # Read the environment variables from the script
        with open('/app/latex_env.sh', 'r') as f:
            content = f.read()
        
        # Extract environment variables and apply them
        for line in content.split('\n'):
            if line.startswith('export '):
                var_line = line[7:]  # Remove 'export '
                if '=' in var_line:
                    key, value = var_line.split('=', 1)
                    # Remove quotes if present
                    value = value.strip('"\'')
                    # Handle PATH specially to append rather than replace
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
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'

# Create directories if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Enhanced LaTeX availability check with environment variables
LATEX_AVAILABLE = False

# Check multiple possible locations for pdflatex
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
    # Final check using which command
    LATEX_AVAILABLE = shutil.which('pdflatex') is not None

# Check for build status file
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

# Enhanced startup message with more detailed information
print(f"🌍 Environment: {os.getenv('FLASK_ENV', 'development')}")
print(f"🐍 Python: {os.sys.version.split()[0]}")
print(f"📁 Working Directory: {os.getcwd()}")
print(f"🔧 PATH (first 200 chars): {os.getenv('PATH', '')[:200]}...")

if LATEX_AVAILABLE:
    print("✅ LaTeX (pdflatex) is available - PDF generation enabled")
    
    # Get pdflatex version if possible
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

# Check for LaTeX warning file
if os.path.exists('/app/latex_warning.txt'):
    print("⚠️ LaTeX warning file detected")
    try:
        with open('/app/latex_warning.txt', 'r') as f:
            warning_content = f.read()
        print("📄 Warning details available at /debug/latex-warning")
    except Exception as e:
        print(f"⚠️ Could not read warning file: {e}")

# API keys
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
            # Extract the text from Gemini response
            generated_text = result['candidates'][0]['content']['parts'][0]['text']
            
            # Clean the response to extract JSON
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
    
    # First try with Gemini AI
    gemini_result = enhance_parsing_with_gemini(text)
    if gemini_result:
        print("=== GEMINI PARSED DATA ===")
        print(json.dumps(gemini_result, indent=2))
        print("=== END GEMINI DATA ===")
        return gemini_result
    
    # Fallback to regex-based parsing if Gemini fails
    print("Gemini failed, using fallback parsing...")
    
    # Initialize the parsed data structure with only empty containers
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
    
    # Extract basic contact information
    for line in lines:
        # Email pattern
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', line)
        if email_match and not parsed_data['email']:
            parsed_data['email'] = email_match.group()
        
        # Phone pattern
        phone_match = re.search(r'(\+?1?[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})', line)
        if phone_match and not parsed_data['phone']:
            parsed_data['phone'] = phone_match.group()
        
        # LinkedIn pattern
        if 'linkedin.com' in line.lower() and not parsed_data['linkedin']:
            parsed_data['linkedin'] = line.strip()
        
        # GitHub pattern
        if 'github.com' in line.lower() and not parsed_data['github']:
            parsed_data['github'] = line.strip()
        
        # Website pattern (basic)
        if ('http' in line.lower() or 'www.' in line.lower()) and 'linkedin' not in line.lower() and 'github' not in line.lower() and not parsed_data['website']:
            parsed_data['website'] = line.strip()
    
    # Extract name (usually the first significant line)
    if lines and not parsed_data['name']:
        # Look for a line that might be a name (usually at the top, not an email/phone)
        for line in lines[:5]:
            if not re.search(r'[@()]', line) and len(line.split()) <= 4 and len(line) > 2:
                parsed_data['name'] = line
                break
    
    # Extract education, experience, projects, and skills
    current_section = None
    current_item = {}
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # Identify sections
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
        
        # Process content based on current section
        if current_section == 'education' and line:
            # Look for degree patterns
            if any(degree in line_lower for degree in ['bachelor', 'master', 'phd', 'associate', 'certificate']):
                if current_item:
                    parsed_data['education'].append(current_item)
                current_item = {'degree': line, 'institution': '', 'date': ''}
            elif current_item and not current_item['institution']:
                current_item['institution'] = line
            elif current_item and re.search(r'\d{4}', line):
                current_item['date'] = line
        
        elif current_section == 'experience' and line:
            # Look for job titles or company names
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
            # Parse skills line by line
            if any(keyword in line_lower for keyword in ['language', 'programming']):
                skills_text = line.split(':')[-1] if ':' in line else line
                parsed_data['skills']['languages'] = [s.strip() for s in skills_text.split(',') if s.strip()]
            elif any(keyword in line_lower for keyword in ['framework']):
                skills_text = line.split(':')[-1] if ':' in line else line
                parsed_data['skills']['frameworks'] = [s.strip() for s in skills_text.split(',') if s.strip()]
            elif any(keyword in line_lower for keyword in ['tool', 'software']):
                skills_text = line.split(':')[-1] if ':' in line else line
                parsed_data['skills']['tools'] = [s.strip() for s in skills_text.split(',') if s.strip()]
    
    # Add the last item if it exists
    if current_item:
        if current_section == 'education':
            parsed_data['education'].append(current_item)
        elif current_section == 'experience':
            parsed_data['experience'].append(current_item)
        elif current_section == 'projects':
            parsed_data['projects'].append(current_item)
    
    # Clean up empty fields
    cleaned_data = {}
    for key, value in parsed_data.items():
        if key == 'skills':
            # Only include skill categories that have actual skills
            skills_cleaned = {k: v for k, v in value.items() if v}
            if skills_cleaned:
                cleaned_data[key] = skills_cleaned
        elif isinstance(value, list):
            # Only include lists that have items
            if value:
                cleaned_data[key] = value
        elif isinstance(value, str):
            # Only include strings that are not empty
            if value:
                cleaned_data[key] = value
        else:
            if value:
                cleaned_data[key] = value
    
    return cleaned_data

def clean_text_for_latex(text):
    """Clean text to be LaTeX-safe"""
    if not text:
        return ""
    
    # Handle case where text might be a list
    if isinstance(text, list):
        return [clean_text_for_latex(item) for item in text]
    
    # Convert to string if not already
    text = str(text)
    
    # First handle backslashes to avoid conflicts
    text = text.replace('\\', '\\textbackslash{}')
    
    # Replace problematic Unicode characters
    replacements = {
        '○': '\\textbullet',  # Unicode bullet
        '●': '\\textbullet',  # Black circle
        '•': '\\textbullet',  # Bullet
        '◦': '\\textbullet',  # White bullet
        '▪': '\\textbullet',  # Black small square
        '▫': '\\textbullet',  # White small square
        '–': '--',           # En dash
        '—': '---',          # Em dash
        ''': "'",            # Left single quotation mark
        ''': "'",            # Right single quotation mark
        '"': '"',            # Left double quotation mark
        '"': '"',            # Right double quotation mark
        '…': '...',          # Horizontal ellipsis
        '°': '\\textdegree', # Degree symbol
        '±': '\\textpm',     # Plus-minus
        '×': '\\texttimes',  # Multiplication sign
        '÷': '\\textdiv',    # Division sign
        '€': '\\texteuro',   # Euro sign
        '£': '\\textsterling', # Pound sign
        '¥': '\\textyen',    # Yen sign
        '©': '\\textcopyright', # Copyright
        '®': '\\textregistered', # Registered trademark
        '™': '\\texttrademark', # Trademark
    }
    
    # Apply replacements
    for unicode_char, latex_replacement in replacements.items():
        text = text.replace(unicode_char, latex_replacement)
    
    # Escape special LaTeX characters (excluding backslash which we handled first)
    latex_special_chars = {
        '&': '\\&',
        '%': '\\%',
        '$': '\\$',
        '#': '\\#',
        '^': '\\textasciicircum{}',
        '_': '\\_',
        '{': '\\{',
        '}': '\\}',
        '~': '\\textasciitilde{}',
    }
    
    for char, replacement in latex_special_chars.items():
        text = text.replace(char, replacement)
    
    return text

def generate_latex_resume(parsed_data):
    """Generate LaTeX resume using Jake's Resume template"""
    
    # Jake's Resume template with Unicode support
    latex_template = r"""
%-------------------------
% Resume in Latex
% Author : Jake Gutierrez
% Based off of: https://github.com/sb2nov/resume
% License : MIT
%------------------------

\documentclass[letterpaper,11pt]{article}

\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{textcomp}
\input{glyphtounicode}

%----------FONT OPTIONS----------
% sans-serif
% \usepackage[sfdefault]{FiraSans}
% \usepackage[sfdefault]{roboto}
% \usepackage[sfdefault]{noto-sans}
% \usepackage[default]{sourcesanspro}

% serif
% \usepackage{CormorantGaramond}
% \usepackage{charter}

\pagestyle{fancy}
\fancyhf{} % clear all header and footer fields
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

% Adjust margins
\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}

\urlstyle{same}

\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

% Sections formatting
\titleformat{\section}{
  \vspace{-4pt}\scshape\raggedright\large
}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]

% Ensure that generate pdf is machine readable/ATS parsable
\pdfgentounicode=1

%-------------------------
% Custom commands
\newcommand{\resumeItem}[1]{
  \item\small{
    {#1 \vspace{-2pt}}
  }
}

\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeSubSubheading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \textit{\small#1} & \textit{\small #2} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \small#1 & #2 \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}

\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}

\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}

%-------------------------------------------
%%%%%%  RESUME STARTS HERE  %%%%%%%%%%%%%%%%%%%%%%%%%%%%

\begin{document}

%----------HEADING----------
\begin{center}
    \textbf{\Huge \scshape """ + clean_text_for_latex(parsed_data.get('name', 'Name Not Found')) + r"""} \\ \vspace{1pt}"""

    # Build contact information dynamically
    contact_parts = []
    
    if parsed_data.get('phone'):
        contact_parts.append(clean_text_for_latex(parsed_data['phone']))
    
    if parsed_data.get('email'):
        email = clean_text_for_latex(parsed_data['email'])
        contact_parts.append(f"\\href{{mailto:{email}}}{{\\underline{{{email}}}}}")
    
    if parsed_data.get('linkedin'):
        linkedin_url = parsed_data['linkedin']
        if not linkedin_url.startswith('http'):
            linkedin_url = 'https://' + linkedin_url
        contact_parts.append(f"\\href{{{linkedin_url}}}{{\\underline{{LinkedIn}}}}")
    
    if parsed_data.get('github'):
        github_url = parsed_data['github']
        if not github_url.startswith('http'):
            github_url = 'https://' + github_url
        contact_parts.append(f"\\href{{{github_url}}}{{\\underline{{GitHub}}}}")
    
    if parsed_data.get('website'):
        website_url = parsed_data['website']
        if not website_url.startswith('http'):
            website_url = 'https://' + website_url
        contact_parts.append(f"\\href{{{website_url}}}{{\\underline{{Website}}}}")
    
    if contact_parts:
        latex_template += f"""
    \\small {' $|$ '.join(contact_parts)}"""
    
    latex_template += r"""
\end{center}"""

    # Add Professional Summary section only if summary data exists
    if parsed_data.get('summary'):
        summary = clean_text_for_latex(parsed_data['summary'])
        latex_template += f"""

%-----------PROFESSIONAL SUMMARY-----------
\\section{{Professional Summary}}
 \\begin{{itemize}}[leftmargin=0.15in, label={{}}]
    \\small{{\\item{{
     {summary}
    }}}}
 \\end{{itemize}}"""

    # Add Education section only if education data exists
    if parsed_data.get('education'):
        latex_template += r"""

%-----------EDUCATION-----------
\section{Education}
  \resumeSubHeadingListStart"""
        
        for edu in parsed_data['education']:
            degree = clean_text_for_latex(edu.get('degree', ''))
            institution = clean_text_for_latex(edu.get('institution', ''))
            date = clean_text_for_latex(edu.get('date', ''))
            location = clean_text_for_latex(edu.get('location', ''))
            gpa = clean_text_for_latex(edu.get('gpa', ''))
            details = clean_text_for_latex(edu.get('details', ''))
            
            # Build the education entry
            latex_template += f"""
    \\resumeSubheading
      {{{degree}}}{{{date}}}
      {{{institution}}}{{{location}}}"""
            
            # Add GPA or details if they exist
            if gpa or details:
                latex_template += r"""
      \resumeItemListStart"""
                if gpa:
                    latex_template += f"""
        \\resumeItem{{GPA: {gpa}}}"""
                if details:
                    latex_template += f"""
        \\resumeItem{{{details}}}"""
                latex_template += r"""
      \resumeItemListEnd"""
        
        latex_template += r"""
  \resumeSubHeadingListEnd"""

    # Add Experience section only if experience data exists
    if parsed_data.get('experience'):
        latex_template += r"""

%-----------EXPERIENCE-----------
\section{Experience}
  \resumeSubHeadingListStart"""
        
        for exp in parsed_data['experience']:
            title = clean_text_for_latex(exp.get('title', ''))
            company = clean_text_for_latex(exp.get('company', ''))
            date = clean_text_for_latex(exp.get('date', ''))
            location = clean_text_for_latex(exp.get('location', ''))
            description = exp.get('description', [])
            
            latex_template += f"""
    \\resumeSubheading
      {{{title}}}{{{date}}}
      {{{company}}}{{{location}}}"""
            
            if description:
                latex_template += r"""
      \resumeItemListStart"""
                for desc in description[:4]:  # Limit to 4 bullet points
                    clean_desc = clean_text_for_latex(desc)
                    latex_template += f"""
        \\resumeItem{{{clean_desc}}}"""
                latex_template += r"""
      \resumeItemListEnd"""
        
        latex_template += r"""
  \resumeSubHeadingListEnd"""

    # Add Projects section only if projects data exists
    if parsed_data.get('projects'):
        latex_template += r"""

%-----------PROJECTS-----------
\section{Projects}
    \resumeSubHeadingListStart"""
        
        for project in parsed_data['projects']:
            title = clean_text_for_latex(project.get('title', ''))
            description = project.get('description', '')
            if isinstance(description, list):
                description = clean_text_for_latex(' '.join(description))
            else:
                description = clean_text_for_latex(description)
            technologies = clean_text_for_latex(project.get('technologies', ''))
            date = clean_text_for_latex(project.get('date', ''))
            link = project.get('link', '')
            
            # Build project title with technologies
            project_title = title
            if technologies:
                project_title += f" $|$ \\emph{{{technologies}}}"
            
            latex_template += f"""
      \\resumeProjectHeading
          {{\\textbf{{{project_title}}}}}{{{date}}}"""
            
            if description:
                latex_template += f"""
          \\resumeItemListStart
            \\resumeItem{{{description}}}"""
                if link:
                    latex_template += f"""
            \\resumeItem{{Link: \\href{{{link}}}{{\\underline{{{link}}}}}}}"""
                latex_template += r"""
          \resumeItemListEnd"""
        
        latex_template += r"""
    \resumeSubHeadingListEnd"""

    # Add Technical Skills section only if skills data exists
    if parsed_data.get('skills'):
        skills = parsed_data['skills']
        skill_lines = []
        
        if skills.get('languages'):
            clean_languages = [clean_text_for_latex(lang) for lang in skills['languages']]
            skill_lines.append(f"\\textbf{{Languages}}: {', '.join(clean_languages)}")
        
        if skills.get('frameworks'):
            clean_frameworks = [clean_text_for_latex(fw) for fw in skills['frameworks']]
            skill_lines.append(f"\\textbf{{Frameworks}}: {', '.join(clean_frameworks)}")
        
        if skills.get('tools'):
            clean_tools = [clean_text_for_latex(tool) for tool in skills['tools']]
            skill_lines.append(f"\\textbf{{Developer Tools}}: {', '.join(clean_tools)}")
        
        if skills.get('libraries'):
            clean_libraries = [clean_text_for_latex(lib) for lib in skills['libraries']]
            skill_lines.append(f"\\textbf{{Libraries}}: {', '.join(clean_libraries)}")
        
        if skills.get('databases'):
            clean_databases = [clean_text_for_latex(db) for db in skills['databases']]
            skill_lines.append(f"\\textbf{{Databases}}: {', '.join(clean_databases)}")
        
        if skills.get('other'):
            clean_other = [clean_text_for_latex(other) for other in skills['other']]
            skill_lines.append(f"\\textbf{{Other}}: {', '.join(clean_other)}")
        
        if skill_lines:
            latex_template += r"""

%-----------PROGRAMMING SKILLS-----------
\section{Technical Skills}
 \begin{itemize}[leftmargin=0.15in, label={}]
    \small{\item{
     """ + ' \\\\\n     '.join(skill_lines) + r"""
    }}
 \end{itemize}"""

    # Add Certifications section only if certifications data exists
    if parsed_data.get('certifications'):
        latex_template += r"""

%-----------CERTIFICATIONS-----------
\section{Certifications}
  \resumeSubHeadingListStart"""
        
        for cert in parsed_data['certifications']:
            name = clean_text_for_latex(cert.get('name', ''))
            issuer = clean_text_for_latex(cert.get('issuer', ''))
            date = clean_text_for_latex(cert.get('date', ''))
            
            latex_template += f"""
    \\resumeSubheading
      {{{name}}}{{{date}}}
      {{{issuer}}}{{}}"""
        
        latex_template += r"""
  \resumeSubHeadingListEnd"""

    # Add Awards section only if awards data exists
    if parsed_data.get('awards'):
        latex_template += r"""

%-----------AWARDS-----------
\section{Awards \& Honors}
  \resumeItemListStart"""
        
        for award in parsed_data['awards']:
            clean_award = clean_text_for_latex(award)
            latex_template += f"""
    \\resumeItem{{{clean_award}}}"""
        
        latex_template += r"""
  \resumeItemListEnd"""

    # Add Languages section only if language data exists
    if parsed_data.get('languages'):
        latex_template += r"""

%-----------LANGUAGES-----------
\section{Languages}
  \resumeItemListStart"""
        
        for lang in parsed_data['languages']:
            clean_lang = clean_text_for_latex(lang)
            latex_template += f"""
    \\resumeItem{{{clean_lang}}}"""
        
        latex_template += r"""
  \resumeItemListEnd"""

    # Add Custom Sections
    if parsed_data.get('custom_sections'):
        for section in parsed_data['custom_sections']:
            title = clean_text_for_latex(section.get('title', ''))
            content = clean_text_for_latex(section.get('content', ''))
            
            # Convert title to uppercase for section header
            title_upper = title.upper()
            
            latex_template += f"""

%-----------{title_upper}-----------
\\section{{{title}}}"""
            
            # Check if content contains bullet points or line breaks
            content_lines = [line.strip() for line in content.split('\n') if line.strip()]
            
            if len(content_lines) > 1:
                # Multiple lines - treat as list
                latex_template += r"""
  \resumeItemListStart"""
                
                for line in content_lines:
                    # Remove bullet points if they exist
                    clean_line = line.lstrip('•*-+ ').strip()
                    if clean_line:
                        latex_template += f"""
    \\resumeItem{{{clean_line}}}"""
                
                latex_template += r"""
  \resumeItemListEnd"""
            else:
                # Single line or paragraph - treat as simple text
                if content:
                    latex_template += f"""
 \\begin{{itemize}}[leftmargin=0.15in, label={{}}]
    \\small{{\\item{{
     {content}
    }}}}
 \\end{{itemize}}"""

    latex_template += r"""

%-------------------------------------------
\end{document}
"""

    return latex_template

def compile_latex_to_pdf(latex_content, output_filename):
    """Compile LaTeX content to PDF using pdflatex with enhanced error handling"""
    try:
        print(f"🔧 Starting PDF compilation for: {output_filename}")
        print(f"📅 Compilation started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Check if LaTeX is available globally
        if not LATEX_AVAILABLE:
            print("❌ LaTeX (pdflatex) is not installed on this system")
            print("🔧 PDF compilation skipped - LaTeX source file will be available for download")
            print("💡 Users can compile locally or use Overleaf")
            return False
        
        # Get compilation timeout from environment
        compile_timeout = int(os.getenv('LATEX_COMPILE_TIMEOUT', '120'))
        
        # Find the best pdflatex binary
        pdflatex_binary = None
        possible_paths = [
            '/opt/texlive/bin/x86_64-linux/pdflatex',
            '/usr/local/bin/pdflatex', 
            '/usr/bin/pdflatex',
            shutil.which('pdflatex')
        ]
        
        for path in possible_paths:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                pdflatex_binary = path
                print(f"✅ Using pdflatex at: {path}")
                break
        
        if not pdflatex_binary:
            print("❌ No executable pdflatex binary found")
            return False
        
        # Double-check pdflatex availability at runtime
        try:
            result_check = subprocess.run([pdflatex_binary, '--version'], 
                                        capture_output=True, text=True, timeout=10)
            if result_check.returncode != 0:
                print("❌ pdflatex command failed version check")
                print(f"   Return code: {result_check.returncode}")
                print(f"   stderr: {result_check.stderr}")
                return False
            else:
                print(f"✅ pdflatex version check successful")
                version_line = result_check.stdout.split('\n')[0] if result_check.stdout else "Unknown version"
                print(f"   Version: {version_line}")
        except subprocess.TimeoutExpired:
            print("❌ pdflatex version check timed out")
            return False
        except FileNotFoundError:
            print("❌ pdflatex binary not found")
            return False
        except Exception as e:
            print(f"❌ Error checking pdflatex: {str(e)}")
            return False
        
        # Prepare the LaTeX content with proper encoding handling
        try:
            # Ensure the LaTeX content is properly encoded
            if isinstance(latex_content, str):
                latex_content_bytes = latex_content.encode('utf-8', errors='replace')
            else:
                latex_content_bytes = latex_content
                
            latex_content_str = latex_content_bytes.decode('utf-8', errors='replace')
            print(f"📄 LaTeX content length: {len(latex_content_str)} characters")
        except Exception as e:
            print(f"❌ Error processing LaTeX content encoding: {str(e)}")
            return False
        
        # Create a temporary directory for compilation
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"📁 Created temporary directory: {temp_dir}")
            
            # Create the .tex file
            tex_file = os.path.join(temp_dir, 'resume.tex')
            try:
                with open(tex_file, 'w', encoding='utf-8') as f:
                    f.write(latex_content_str)
                print(f"✅ Created .tex file: {tex_file}")
                print(f"   File size: {os.path.getsize(tex_file)} bytes")
            except Exception as e:
                print(f"❌ Error writing .tex file: {str(e)}")
                return False
            
            # Change to temp directory for compilation
            original_dir = os.getcwd()
            try:
                os.chdir(temp_dir)
                print(f"📂 Changed to temp directory: {temp_dir}")
                
                # Compile with pdflatex
                compile_command = [
                    pdflatex_binary,
                    '-interaction=nonstopmode',
                    '-halt-on-error',
                    '-file-line-error',
                    'resume.tex'
                ]
                
                print(f"🚀 Running compilation command: {' '.join(compile_command)}")
                
                # Enhanced environment variables for LaTeX
                env = os.environ.copy()
                env.update({
                    'TEXMFCACHE': os.getenv('TEXMFCACHE', '/tmp/texmf-cache'),
                    'TEXMFVAR': os.getenv('TEXMFVAR', '/tmp/texmf-var'),
                    'TEXMFHOME': os.getenv('TEXMFHOME', '/tmp/texmf-home'),
                    'openout_any': 'a',
                    'openin_any': 'a',
                    'max_print_line': '10000',
                    'error_line': '254',
                    'half_error_line': '238'
                })
                
                result = subprocess.run(
                    compile_command,
                    capture_output=True,
                    text=True,
                    timeout=compile_timeout,
                    env=env
                )
                
                print(f"📊 Compilation completed with return code: {result.returncode}")
                
                if result.stdout:
                    print("📝 LaTeX stdout (first 500 chars):")
                    print(result.stdout[:500])
                    if len(result.stdout) > 500:
                        print("... (output truncated)")
                
                if result.stderr:
                    print("⚠️ LaTeX stderr:")
                    print(result.stderr)
                
                # Check if PDF was created
                pdf_path = os.path.join(temp_dir, 'resume.pdf')
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                    print(f"✅ PDF created successfully: {pdf_path}")
                    print(f"   PDF size: {os.path.getsize(pdf_path)} bytes")
                    
                    # Copy to output directory
                    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
                    try:
                        with open(pdf_path, 'rb') as src, open(output_path, 'wb') as dst:
                            dst.write(src.read())
                        
                        print(f"✅ PDF copied to: {output_path}")
                        print(f"   Final PDF size: {os.path.getsize(output_path)} bytes")
                        return True
                        
                    except Exception as e:
                        print(f"❌ Error copying PDF to output directory: {str(e)}")
                        return False
                else:
                    print("❌ PDF file was not created")
                    
                    # Check for .log file to get more details
                    log_path = os.path.join(temp_dir, 'resume.log')
                    if os.path.exists(log_path):
                        try:
                            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                                log_content = f.read()
                            print("📋 LaTeX log file (last 1000 chars):")
                            print(log_content[-1000:] if len(log_content) > 1000 else log_content)
                        except Exception as e:
                            print(f"⚠️ Could not read log file: {str(e)}")
                    
                    return False
                    
            except subprocess.TimeoutExpired:
                print(f"❌ LaTeX compilation timed out after {compile_timeout} seconds")
                return False
            except Exception as e:
                print(f"❌ Error during compilation: {str(e)}")
                import traceback
                print(f"   Traceback: {traceback.format_exc()}")
                return False
            finally:
                try:
                    os.chdir(original_dir)
                    print(f"📂 Returned to original directory: {original_dir}")
                except Exception as e:
                    print(f"⚠️ Could not return to original directory: {str(e)}")
                    
    except Exception as e:
        print(f"❌ Unexpected error in compile_latex_to_pdf: {str(e)}")
        import traceback
        print(f"   Full traceback: {traceback.format_exc()}")
        return False

@app.route('/')
def index():
    return render_template('landing.html')

@app.route('/upload')
def upload_page():
    return render_template('upload.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Extract text based on file type
        if filename.lower().endswith('.pdf'):
            extracted_text = extract_text_from_pdf(file_path)
        elif filename.lower().endswith('.docx'):
            extracted_text = extract_text_from_docx(file_path)
        else:
            return jsonify({'error': 'Unsupported file type'}), 400
        
        # Parse the extracted text using Gemini AI
        parsed_data = parse_cv_text(extracted_text)
        
        # Generate LaTeX
        latex_content = generate_latex_resume(parsed_data)
        
        # Save LaTeX file
        base_filename = filename.rsplit('.', 1)[0]
        latex_filename = f"{base_filename}_resume.tex"
        latex_path = os.path.join(app.config['OUTPUT_FOLDER'], latex_filename)
        
        with open(latex_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
        
        print(f"Generated LaTeX saved to: {latex_path}")
        print("=== GENERATED LATEX CONTENT (first 500 chars) ===")
        print(latex_content[:500] + "..." if len(latex_content) > 500 else latex_content)
        
        # Compile to PDF
        pdf_filename = f"{base_filename}_resume.pdf"
        pdf_compiled = compile_latex_to_pdf(latex_content, pdf_filename)
        
        # Clean up uploaded file
        os.remove(file_path)
        
        response_data = {
            'success': True,
            'parsed_data': parsed_data,
            'latex_content': latex_content,
            'latex_download_url': f'/download/{latex_filename}',
            'pdf_compiled': pdf_compiled,
            'latex_available': LATEX_AVAILABLE
        }
        
        if pdf_compiled:
            response_data.update({
                'pdf_download_url': f'/download/{pdf_filename}',
                'pdf_preview_url': f'/preview/{pdf_filename}'
            })
        else:
            if not LATEX_AVAILABLE:
                response_data['warning'] = 'LaTeX is not installed on this server. You can download the LaTeX source and compile it locally or using Overleaf.'
            else:
                response_data['warning'] = 'PDF compilation failed. LaTeX source is still available for download.'
        
        return jsonify(response_data)
    
    return jsonify({'error': 'Invalid file type. Please upload PDF or DOCX files only.'}), 400

@app.route('/download/<filename>')
def download_file(filename):
    file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

@app.route('/preview/<filename>')
def preview_pdf(filename):
    file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    if os.path.exists(file_path) and filename.endswith('.pdf'):
        return send_file(file_path, mimetype='application/pdf')
    return jsonify({'error': 'PDF file not found'}), 404

@app.route('/result')
def result_page():
    return render_template('result.html')

@app.route('/create-cv')
def create_cv_page():
    return render_template('create_cv.html')

@app.route('/api/create-cv', methods=['POST'])
def create_cv():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'})
        
        # Validate required fields
        if not data.get('name') or not data.get('email'):
            return jsonify({'success': False, 'error': 'Name and email are required fields'})
        
        # Process the data to match our existing structure
        parsed_data = {
            'name': data.get('name', ''),
            'email': data.get('email', ''),
            'phone': data.get('phone', ''),
            'linkedin': data.get('linkedin', ''),
            'github': data.get('github', ''),
            'website': data.get('website', ''),
            'address': data.get('address', ''),
            'summary': data.get('summary', ''),
            'education': [],
            'experience': [],
            'projects': [],
            'skills': {
                'languages': [],
                'frameworks': [],
                'tools': [],
                'databases': [],
                'other': []
            },
            'custom_sections': []
        }
        
        # Process education
        if data.get('education'):
            for edu in data['education']:
                if edu.get('degree') or edu.get('institution'):
                    parsed_data['education'].append({
                        'degree': edu.get('degree', ''),
                        'institution': edu.get('institution', ''),
                        'date': edu.get('date', ''),
                        'location': edu.get('location', ''),
                        'gpa': edu.get('gpa', ''),
                        'details': edu.get('details', '')
                    })
        
        # Process experience
        if data.get('experience'):
            for exp in data['experience']:
                if exp.get('title') or exp.get('company'):
                    # Split description by lines for bullet points
                    description_lines = []
                    if exp.get('description'):
                        description_lines = [line.strip() for line in exp['description'].split('\n') if line.strip()]
                    
                    parsed_data['experience'].append({
                        'title': exp.get('title', ''),
                        'company': exp.get('company', ''),
                        'date': exp.get('date', ''),
                        'location': exp.get('location', ''),
                        'description': description_lines
                    })
        
        # Process projects
        if data.get('projects'):
            for proj in data['projects']:
                if proj.get('title'):
                    parsed_data['projects'].append({
                        'title': proj.get('title', ''),
                        'description': proj.get('description', ''),
                        'technologies': proj.get('technologies', ''),
                        'date': proj.get('date', ''),
                        'link': proj.get('link', '')
                    })
        
        # Process skills
        if data.get('skills'):
            skills = data['skills']
            
            # Convert comma-separated strings to lists
            for skill_type in ['languages', 'frameworks', 'tools', 'databases', 'other']:
                if skills.get(skill_type):
                    parsed_data['skills'][skill_type] = [
                        item.strip() for item in skills[skill_type].split(',') if item.strip()
                    ]
        
        # Process custom sections
        if data.get('custom'):
            for custom in data['custom']:
                if custom.get('title') and custom.get('content'):
                    parsed_data['custom_sections'].append({
                        'title': custom['title'],
                        'content': custom['content']
                    })
        
        print("=== PROCESSED CV DATA ===")
        print(json.dumps(parsed_data, indent=2))
        print("=== END PROCESSED DATA ===")
        
        # Generate LaTeX content
        latex_content = generate_latex_resume(parsed_data)
        
        # Generate unique filename
        timestamp = str(int(time.time()))
        latex_filename = f"resume_{timestamp}.tex"
        pdf_filename = f"resume_{timestamp}.pdf"
        
        # Save LaTeX file
        latex_path = os.path.join(app.config['OUTPUT_FOLDER'], latex_filename)
        with open(latex_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
        
        # Compile to PDF
        success = compile_latex_to_pdf(latex_content, pdf_filename)
        
        response_data = {
            'success': True,
            'latex_file': latex_filename,
            'latex_available': LATEX_AVAILABLE
        }
        
        if success:
            response_data['pdf_file'] = pdf_filename
        else:
            response_data['pdf_file'] = None
            if not LATEX_AVAILABLE:
                response_data['warning'] = 'LaTeX is not installed on this server. You can download the LaTeX source and compile it locally using MiKTeX, TeX Live, or online using Overleaf.'
            else:
                response_data['warning'] = 'PDF compilation failed. LaTeX source is still available for download. You can compile it manually using a LaTeX editor.'
        
        return jsonify(response_data)
    
    except Exception as e:
        print(f"Error in create_cv: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/preview', methods=['POST'])
def preview_latex():
    """Generate a preview of the LaTeX content"""
    data = request.get_json()
    latex_content = data.get('latex_content', '')
    
    if not latex_content:
        return jsonify({'error': 'No LaTeX content provided'}), 400
    
    # Save to temporary file and compile (optional feature)
    # This requires LaTeX installation on the server
    return jsonify({'success': True, 'message': 'LaTeX content ready for download'})

@app.route('/static/<filename>')
def static_files(filename):
    """Serve static files like images"""
    return send_file(os.path.join('static', filename))

@app.route('/debug/system')
def debug_system():
    """Debug endpoint to check system configuration"""
    try:
        import platform
        import shutil
        
        debug_info = {
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'current_dir': os.getcwd(),
            'output_folder': app.config.get('OUTPUT_FOLDER', 'Not set'),
            'upload_folder': app.config.get('UPLOAD_FOLDER', 'Not set'),
            'latex_available_global': LATEX_AVAILABLE
        }
        
        # Check if directories exist
        debug_info['directories'] = {
            'output_exists': os.path.exists(app.config.get('OUTPUT_FOLDER', '')),
            'upload_exists': os.path.exists(app.config.get('UPLOAD_FOLDER', '')),
        }
        
        # Check LaTeX installation comprehensively
        pdflatex_path = shutil.which('pdflatex')
        latex_path = shutil.which('latex')
        debug_info['latex'] = {
            'pdflatex_found': pdflatex_path is not None,
            'pdflatex_path': pdflatex_path,
            'latex_found': latex_path is not None,
            'latex_path': latex_path,
            'startup_check': LATEX_AVAILABLE
        }
        
        # Test LaTeX packages availability
        if pdflatex_path:
            try:
                result = subprocess.run(['pdflatex', '--version'], 
                                      capture_output=True, text=True, timeout=10)
                debug_info['latex']['version_check'] = {
                    'returncode': result.returncode,
                    'stdout': result.stdout[:500] if result.stdout else None,
                    'stderr': result.stderr[:500] if result.stderr else None,
                }
                
                # Check for common LaTeX packages
                try:
                    test_latex = "\\documentclass{article}\\usepackage{geometry}\\usepackage{fontenc}\\begin{document}Test\\end{document}"
                    with tempfile.TemporaryDirectory() as temp_dir:
                        test_file = os.path.join(temp_dir, 'test.tex')
                        with open(test_file, 'w') as f:
                            f.write(test_latex)
                        
                        test_result = subprocess.run([
                            'pdflatex', '-interaction=nonstopmode', 
                            '-output-directory', temp_dir, test_file
                        ], capture_output=True, text=True, timeout=30)
                        
                        debug_info['latex']['package_test'] = {
                            'returncode': test_result.returncode,
                            'packages_available': test_result.returncode == 0
                        }
                except Exception as e:
                    debug_info['latex']['package_test'] = {'error': str(e)}
                    
            except Exception as e:
                debug_info['latex']['version_error'] = str(e)
        
        # List files in output directory
        try:
            output_dir = app.config.get('OUTPUT_FOLDER', '')
            if os.path.exists(output_dir):
                debug_info['output_files'] = os.listdir(output_dir)[:10]  # First 10 files
            else:
                debug_info['output_files'] = 'Directory does not exist'
        except Exception as e:
            debug_info['output_files_error'] = str(e)
        
        # Environment variables (non-sensitive)
        debug_info['environment'] = {
            'RENDER': os.getenv('RENDER', 'Not set'),
            'FLASK_ENV': os.getenv('FLASK_ENV', 'Not set'),
            'PATH_latex_locations': [p for p in os.getenv('PATH', '').split(':') if 'tex' in p.lower()][:5]
        }
        
        return jsonify(debug_info)
    
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()})

@app.route('/debug/test-latex')
def debug_test_latex():
    """Test LaTeX compilation with a simple document"""
    try:
        simple_latex = """
\\documentclass{article}
\\begin{document}
\\title{Test Document}
\\author{System Test}
\\maketitle
This is a test document to verify LaTeX compilation.
\\end{document}
"""
        
        test_filename = f"test_{int(time.time())}.pdf"
        success = compile_latex_to_pdf(simple_latex, test_filename)
        
        result = {
            'compilation_success': success,
            'test_filename': test_filename,
            'timestamp': int(time.time())
        }
        
        if success:
            test_path = os.path.join(app.config['OUTPUT_FOLDER'], test_filename)
            if os.path.exists(test_path):
                result['file_size'] = os.path.getsize(test_path)
                result['download_url'] = f'/download/{test_filename}'
            else:
                result['error'] = 'File compilation reported success but file not found'
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()})

@app.route('/debug/test-latex-comprehensive')
def debug_test_latex_comprehensive():
    """Comprehensive LaTeX testing endpoint for deployment debugging"""
    try:
        import platform
        import shutil
        import tempfile
        import glob
        
        debug_info = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'build_status': {
                'status': BUILD_STATUS,
                'message': LATEX_BUILD_MESSAGE,
                'latex_available_runtime': LATEX_AVAILABLE,
            },
            'system': {
                'platform': platform.platform(),
                'python_version': platform.python_version(),
                'current_dir': os.getcwd(),
                'user': os.getenv('USER', 'unknown'),
                'home': os.getenv('HOME', 'unknown'),
                'path': os.getenv('PATH', 'unknown')[:500] + '...' if len(os.getenv('PATH', '')) > 500 else os.getenv('PATH', ''),
            },
            'latex': {
                'available_global': LATEX_AVAILABLE,
                'pdflatex_path': shutil.which('pdflatex'),
                'latex_path': shutil.which('latex'),
                'tex_path': shutil.which('tex'),
            },
            'directories': {
                'output_exists': os.path.exists(app.config.get('OUTPUT_FOLDER', '')),
                'upload_exists': os.path.exists(app.config.get('UPLOAD_FOLDER', '')),
                'tmp_writable': os.access('/tmp', os.W_OK),
            },
            'files': {
                'latex_warning_exists': os.path.exists('/app/latex_warning.txt'),
                'latex_status_exists': os.path.exists('/app/latex_status.txt'),
                'build_files': []
            },
            'environment': {
                'render': os.getenv('RENDER'),
                'debian_frontend': os.getenv('DEBIAN_FRONTEND'),
                'texmfcache': os.getenv('TEXMFCACHE'),
            }
        }
        
        # Check for build-related files
        build_files = glob.glob('*.log') + glob.glob('*.txt') + glob.glob('build.*')
        debug_info['files']['build_files'] = build_files[:10]  # Limit to first 10
        
        # Try to find LaTeX binaries
        latex_binaries = []
        try:
            result = subprocess.run(['find', '/usr', '-name', '*latex*', '-type', 'f'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                latex_binaries = result.stdout.strip().split('\n')[:20]  # Limit to first 20
        except:
            pass
        debug_info['latex']['found_binaries'] = latex_binaries
        
        # Test LaTeX compilation if available
        if debug_info['latex']['pdflatex_path']:
            debug_info['latex']['compilation_test'] = test_latex_compilation()
        else:
            debug_info['latex']['compilation_test'] = {'status': 'skipped', 'reason': 'pdflatex not found'}
        
        # Check package installations
        package_check = {}
        packages_to_check = ['texlive-latex-base', 'texlive-fonts-recommended', 'lmodern']
        for package in packages_to_check:
            try:
                result = subprocess.run(['dpkg', '-l', package], 
                                      capture_output=True, text=True, timeout=5)
                package_check[package] = 'installed' if result.returncode == 0 else 'not_installed'
            except:
                package_check[package] = 'unknown'
        debug_info['packages'] = package_check
        
        # Disk space check
        try:
            result = subprocess.run(['df', '-h', '.'], capture_output=True, text=True, timeout=5)
            debug_info['disk_space'] = result.stdout.strip().split('\n')[-1] if result.returncode == 0 else 'unknown'
        except:
            debug_info['disk_space'] = 'unknown'
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

@app.route('/debug/latex-warning')
def debug_latex_warning():
    """Show LaTeX warning and build status information"""
    try:
        info = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'build_status': BUILD_STATUS,
            'build_message': LATEX_BUILD_MESSAGE,
            'latex_available': LATEX_AVAILABLE,
            'warnings': {}
        }
        
        # Read LaTeX warning file if it exists
        if os.path.exists('/app/latex_warning.txt'):
            try:
                with open('/app/latex_warning.txt', 'r') as f:
                    info['warnings']['latex_warning'] = f.read()
            except Exception as e:
                info['warnings']['latex_warning_error'] = str(e)
        else:
            info['warnings']['latex_warning'] = 'No LaTeX warning file found'
        
        # Read build status file if it exists
        if os.path.exists('/app/latex_status.txt'):
            try:
                with open('/app/latex_status.txt', 'r') as f:
                    info['warnings']['build_status_file'] = f.read()
            except Exception as e:
                info['warnings']['build_status_error'] = str(e)
        else:
            info['warnings']['build_status_file'] = 'No build status file found'
        
        # Check if we're running on Render
        if os.getenv('RENDER'):
            info['deployment'] = 'render'
            info['recommendations'] = [
                "LaTeX installation on Render is challenging due to environment limitations",
                "Consider using a VPS (DigitalOcean, Linode) for full LaTeX support",
                "Alternative: Use LaTeX download + Overleaf compilation workflow",
                "Self-hosting guide available in repository documentation"
            ]
        else:
            info['deployment'] = 'local_or_other'
            info['recommendations'] = [
                "Install LaTeX locally: apt install texlive-latex-base texlive-fonts-recommended",
                "For full installation: apt install texlive-full",
                "Restart the application after LaTeX installation"
            ]
        
        return jsonify(info)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

def test_latex_compilation():
    """Test LaTeX compilation with a simple document"""
    try:
        test_latex = r"""
\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\begin{document}
\title{Test Document}
\author{CVLatex Test}
\date{\today}
\maketitle

This is a test document to verify LaTeX compilation works correctly.

\section{Introduction}
If you can see this PDF, LaTeX compilation is working.

\end{document}
"""
        
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_file = os.path.join(temp_dir, 'test.tex')
            with open(tex_file, 'w', encoding='utf-8') as f:
                f.write(test_latex)
            
            # Set environment variables
            env = os.environ.copy()
            env['TEXMFCACHE'] = '/tmp/texmf-cache'
            env['openout_any'] = 'a'
            env['openin_any'] = 'a'
            
            # Change to temp directory
            original_dir = os.getcwd()
            os.chdir(temp_dir)
            
            try:
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'test.tex'],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env
                )
                
                pdf_path = os.path.join(temp_dir, 'test.pdf')
                
                compilation_result = {
                    'status': 'success' if result.returncode == 0 and os.path.exists(pdf_path) else 'failed',
                    'return_code': result.returncode,
                    'pdf_created': os.path.exists(pdf_path),
                    'pdf_size': os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0,
                    'stdout_length': len(result.stdout),
                    'stderr_length': len(result.stderr),
                    'stdout_preview': result.stdout[:200] + '...' if len(result.stdout) > 200 else result.stdout,
                    'stderr_preview': result.stderr[:200] + '...' if len(result.stderr) > 200 else result.stderr,
                }
                
                # Check for log file
                log_path = os.path.join(temp_dir, 'test.log')
                if os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                        log_content = f.read()
                    compilation_result['log_preview'] = log_content[-300:] if len(log_content) > 300 else log_content
                
                return compilation_result
                
            finally:
                os.chdir(original_dir)
            
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }

if __name__ == '__main__':
    app.run(debug=True) 