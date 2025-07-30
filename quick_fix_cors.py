# Quick fix for the CORS request import issue
# This creates a version that works around the import problem

import sys
import re

# Read the current app.py
with open('app.py', 'r') as f:
    content = f.read()

# Replace the problematic after_request function with a safer version
new_after_request = '''# Add CORS headers to all responses
@app.after_request
def after_request(response):
    try:
        from flask import request as flask_request
        origin = flask_request.headers.get('Origin')
    except:
        # Fallback for any import issues
        origin = '*'
    
    cors_origin = get_cors_origin(origin)
    
    if cors_origin:
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Max-Age', '3600')  # Cache preflight for 1 hour
    
    return response'''

# Replace the problematic OPTIONS handler
new_options_handler = '''# Handle preflight OPTIONS requests
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    try:
        from flask import request as flask_request
        origin = flask_request.headers.get('Origin')
    except:
        origin = '*'
    
    cors_origin = get_cors_origin(origin)
    
    response = Response()
    if cors_origin:
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Max-Age', '3600')
    else:
        response.status_code = 403
    
    return response'''

# Apply the fixes
old_after_pattern = r'# Add CORS headers to all responses\s*@app\.after_request\s*def after_request\(response\):.*?return response'
old_options_pattern = r'# Handle preflight OPTIONS requests\s*@app\.route\(.*?\)\s*def handle_options\(path\):.*?return response'

content = re.sub(old_after_pattern, new_after_request, content, flags=re.DOTALL)
content = re.sub(old_options_pattern, new_options_handler, content, flags=re.DOTALL)

# Write the fixed version
with open('app_quick_fix.py', 'w') as f:
    f.write(content)

print("✅ Quick fix created as app_quick_fix.py")
print("🔧 This version imports 'request' locally within functions to avoid the import error")
