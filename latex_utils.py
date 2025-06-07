import os
import shutil
import tempfile
import subprocess
import time
import traceback

def clean_text_for_latex(text):
    """Clean text to be LaTeX-safe"""
    if not text:
        return ""
    if isinstance(text, list):
        return [clean_text_for_latex(item) for item in text]
    text = str(text)
    text = text.replace('\\', '\\textbackslash{}')
    replacements = {
        '○': '\\textbullet', '●': '\\textbullet', '•': '\\textbullet', '◦': '\\textbullet',
        '▪': '\\textbullet', '▫': '\\textbullet', '–': '--', '—': '---',
        ''': "'", ''': "'", '"': '"', '"': '"', '…': '...', '°': '\\textdegree',
        '±': '\\textpm', '×': '\\texttimes', '÷': '\\textdiv', '€': '\\texteuro',
        '£': '\\textsterling', '¥': '\\textyen', '©': '\\textcopyright',
        '®': '\\textregistered', '™': '\\texttrademark',
    }
    for unicode_char, latex_replacement in replacements.items():
        text = text.replace(unicode_char, latex_replacement)
    latex_special_chars = {
        '&': '\\&', '%': '\\%', '$': '\\$', '#': '\\#', '^': '\\textasciicircum{}',
        '_': '\\_', '{': '\\{', '}': '\\}', '~': '\\textasciitilde{}',
    }
    for char, replacement in latex_special_chars.items():
        text = text.replace(char, replacement)
    return text

def generate_latex_resume(parsed_data):
    """Generate LaTeX resume using Jake's Resume template"""
    # (Shortened for brevity, copy the full function from app.py here)
    # You can move the full function body from app.py to here.
    pass

def compile_latex_to_pdf(latex_content, output_filename, output_folder, latex_available=True):
    """Compile LaTeX content to PDF using pdflatex"""
    print(f"🔍 compile_latex_to_pdf called with output_filename: {output_filename}")
    if not latex_available:
        print("❌ LaTeX not available - cannot compile to PDF")
        return False
    original_dir = os.getcwd()
    temp_dir = None
    try:
        pdflatex_path = shutil.which('pdflatex')
        if not pdflatex_path:
            for path in ['/opt/texlive/bin/x86_64-linux/pdflatex', '/usr/local/bin/pdflatex', '/usr/bin/pdflatex']:
                if os.path.exists(path):
                    pdflatex_path = path
                    break
        if not pdflatex_path:
            print("❌ pdflatex executable not found")
            return False
        temp_dir = tempfile.mkdtemp()
        tex_filename = 'resume.tex'
        tex_path = os.path.join(temp_dir, tex_filename)
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
        output_dir = os.path.abspath(output_folder)
        output_path = os.path.join(output_dir, output_filename)
        os.makedirs(output_dir, exist_ok=True)
        os.chdir(temp_dir)
        cmd = [pdflatex_path, '-interaction=nonstopmode', '-halt-on-error', '-file-line-error', tex_filename]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        pdf_path = os.path.join(temp_dir, 'resume.pdf')
        if os.path.exists(pdf_path):
            try:
                shutil.copy2(pdf_path, output_path)
                return True
            except Exception as copy_error:
                print(f"❌ Error copying PDF to output directory: {copy_error}")
                return False
        else:
            return False
    except subprocess.TimeoutExpired:
        print("❌ LaTeX compilation timed out")
        return False
    except Exception as e:
        print(f"❌ Error during LaTeX compilation: {e}")
        traceback.print_exc()
        return False
    finally:
        os.chdir(original_dir)
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"⚠️ Could not clean up temp directory: {e}")
