from flask import Flask, Response, jsonify
import time

app = Flask(__name__)

# Add CORS headers to all responses
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# Handle preflight OPTIONS requests
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/test')
def test():
    return jsonify({
        "message": "CORS test successful!",
        "timestamp": time.time(),
        "cors_enabled": True
    })

@app.route('/video_feed')
def video_feed():
    """Test video feed endpoint"""
    def generate():
        for i in range(10):
            yield (b'--frame\r\n'
                   b'Content-Type: text/plain\r\n\r\n' + 
                   f'Frame {i}\r\n'.encode() + b'\r\n')
            time.sleep(1)
    
    response = Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Cache-Control'] = 'no-cache'
    return response

if __name__ == '__main__':
    print("Starting CORS test server...")
    print("Test URLs:")
    print("  http://localhost:5000/test")
    print("  http://localhost:5000/video_feed")
    app.run(host='0.0.0.0', port=5000, debug=True)
