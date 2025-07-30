from flask import Flask, Response, render_template, jsonify, request
import time

app = Flask(__name__)

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

# Add CORS headers to all responses
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
    
    return response

# Handle preflight OPTIONS requests
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
    
    return response

@app.route('/cors-test')
def cors_test():
    """Test endpoint to verify CORS configuration"""
    origin = request.headers.get('Origin', 'No origin header')
    return jsonify({
        "message": "CORS test successful!",
        "origin": origin,
        "allowed": is_allowed_origin(origin),
        "timestamp": time.time(),
        "allowed_origins": ALLOWED_ORIGINS,
        "lovable_domains_supported": [
            "https://lovable.dev",
            "*.lovable.dev",
            "*.lovable.app",
            "https://bookworm-scanner-vision.lovable.app"
        ]
    })

@app.route('/test')
def test():
    return jsonify({
        "message": "Enhanced CORS test successful!",
        "timestamp": time.time()
    })

@app.route('/video_feed')
def video_feed():
    """Test video feed endpoint"""
    def generate():
        for i in range(10):
            yield (b'--frame\r\n'
                   b'Content-Type: text/plain\r\n\r\n' + 
                   f'Frame {i} - Enhanced CORS\r\n'.encode() + b'\r\n')
            time.sleep(1)
    
    origin = request.headers.get('Origin')
    cors_origin = get_cors_origin(origin)
    
    response = Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')
    if cors_origin:
        response.headers['Access-Control-Allow-Origin'] = cors_origin
        response.headers['Access-Control-Allow-Methods'] = 'GET'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Cache-Control'] = 'no-cache'
    
    return response

if __name__ == '__main__':
    print("🚀 Starting Enhanced CORS test server...")
    print("📋 Supported domains:")
    for origin in ALLOWED_ORIGINS:
        print(f"  ✅ {origin}")
    print("  ✅ *.lovable.dev (any subdomain)")
    print("  ✅ *.lovable.app (any subdomain)")
    print("\n🔗 Test URLs:")
    print("  http://localhost:5000/cors-test")
    print("  http://localhost:5000/test")
    print("  http://localhost:5000/video_feed")
    app.run(host='0.0.0.0', port=5000, debug=True)
