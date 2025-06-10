#!/usr/bin/env python3

from flask import Flask, render_template

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.route('/test')
def test_template():
    """Test the improved resume preview template with dummy data"""
    test_data = {
        'latex_content': 'Test LaTeX content',
        'latex_filename': 'test.tex',
        'pdf_filename': 'test.pdf',
        'pdf_compiled': True,
        'pdf_available': True,
        'original_score': 75,
        'new_score': 85,
        'improvements': ['Test improvement 1', 'Test improvement 2'],
    }
    
    try:
        return render_template('improved_resume_preview.html', 
                             session_id='test-session',
                             **test_data)
    except Exception as e:
        return f"Template error: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5001) 