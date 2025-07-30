#!/usr/bin/env python3

# Script to update app.py with enhanced CORS configuration

import re

# Read the original app.py
with open('app.py', 'r') as f:
    content = f.read()

# Add request import if not present
if 'from flask import' in content and 'request' not in content:
    content = content.replace(
        'from flask import Flask, Response, render_template, jsonify',
        'from flask import Flask, Response, render_template, jsonify, request'
    )

# Define the new CORS configuration
cors_config = '''
# Allowed CORS origins for external domains
ALLOWED_ORIGINS = [
    'https://bookworm-scanner-vision.lovable.app',
    'https://lovable.dev',
    'http://localhost:3000',  # For local development
    'http://127.0.0.1:3000',  # For local development
    'http://localhost:5173',  # Vite dev server
    'http://127.0.0.1:5173',  # Vite dev server
]

def is_allowed_origin(origin):
    """Check if the origin is allowed for CORS"""
    if not origin:
        return True  # Allow requests without origin (direct API calls)
    
    # Allow any subdomain of lovable.dev
    if origin.endswith('.lovable.dev') or origin == 'https://lovable.dev':
        return True
    
    # Allow any subdomain of lovable.app
    if origin.endswith('.lovable.app'):
        return True
    
    # Allow specific origins
    return origin in ALLOWED_ORIGINS

def get_cors_origin(request_origin):
    """Get the appropriate CORS origin header value"""
    if is_allowed_origin(request_origin):
        return request_origin if request_origin else '*'
    return None

'''

# Replace the old CORS configuration
old_cors_pattern = r'# Add CORS headers to all responses\s*@app\.after_request\s*def after_request\(response\):.*?return response'
new_cors_after_request = '''# Add CORS headers to all responses
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    cors_origin = get_cors_origin(origin)
    
    if cors_origin:
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Max-Age', '3600')  # Cache preflight for 1 hour
    
    return response'''

# Replace the old OPTIONS handler
old_options_pattern = r'# Handle preflight OPTIONS requests\s*@app\.route\(.*?\)\s*def handle_options\(path\):.*?return response'
new_options_handler = '''# Handle preflight OPTIONS requests
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    origin = request.headers.get('Origin')
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

# Add CORS test route
cors_test_route = '''
@app.route('/cors-test')
def cors_test():
    """Test endpoint to verify CORS configuration"""
    origin = request.headers.get('Origin', 'No origin header')
    return jsonify({
        "message": "CORS test successful!",
        "origin": origin,
        "allowed": is_allowed_origin(origin),
        "timestamp": time.time(),
        "allowed_origins": ALLOWED_ORIGINS
    })
'''

# Apply the changes
content = re.sub(old_cors_pattern, new_cors_after_request, content, flags=re.DOTALL)
content = re.sub(old_options_pattern, new_options_handler, content, flags=re.DOTALL)

# Insert CORS configuration after imports
app_creation_pattern = r'(app = Flask\(__name__\))'
content = re.sub(app_creation_pattern, f'app = Flask(__name__){cors_config}', content)

# Add CORS test route before the index route
index_route_pattern = r'(@app\.route\(\'/\'\))'
content = re.sub(index_route_pattern, f'{cors_test_route}\\1', content)

# Write the updated content
with open('app_updated.py', 'w') as f:
    f.write(content)

print("✅ Updated app.py created as app_updated.py")
print("📋 Changes made:")
print("  - Enhanced CORS configuration with specific domain support")
print("  - Added support for https://lovable.dev/projects/*")
print("  - Added support for *.lovable.dev and *.lovable.app subdomains")
print("  - Added /cors-test endpoint for verification")
print("  - Improved security with origin validation")
