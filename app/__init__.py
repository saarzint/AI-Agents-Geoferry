from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
from .routes import register_routes
from .event_listener import start_profile_listener, stop_profile_listener
import atexit
import os


def create_app() -> Flask:
	# Serve built frontend from the Docker image (see Dockerfile `static-frontend` copy)
	app = Flask(
		__name__,
		static_folder="static-frontend",  # populated by Docker multi-stage build
		static_url_path="",  # Empty string means static files are served at root level
	)
	# CORS configuration - allow all origins since frontend/backend are in same container
	# This allows the app to work with any domain (Cloud Run URL, custom domain, localhost)
	CORS(app, 
		resources={
			r"/*": {
				"origins": "*",  # Allow all origins - safe because frontend/backend are in same container
				"methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
				"allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
				"expose_headers": ["Content-Type", "Authorization"],
				"supports_credentials": False,
				"max_age": 3600
			},
			r"/stripe/webhook": {"origins": "*"}  # Stripe webhooks need to bypass CORS
		},
		supports_credentials=False,
	)

	# Helper function to check if a path is an API route
	def is_api_route(path: str) -> bool:
		"""Check if the path is an API route that shouldn't serve index.html"""
		api_prefixes = (
			"api",
			"admissions",
			"results",
			"stripe",
			"visa_info",
			"visa_report",
			"visa_alerts",
			"search_universities",
			"search_scholarships",
			"fetch_application_requirements",
			"application_requirements",
			"tokens",  # token balance & history endpoints
			"health",
			"counselor_notifications",
		)
		# Remove leading slash for comparison
		clean_path = path.lstrip('/')
		return any(clean_path.startswith(prefix) for prefix in api_prefixes)

	# Helper function to serve index.html for SPA
	def serve_spa_index():
		"""Serve the SPA index.html file"""
		if app.static_folder:
			index_path = os.path.join(app.static_folder, "index.html")
			if os.path.exists(index_path):
				return send_from_directory(app.static_folder, "index.html")
		return None

	# Root route – serve the frontend if it exists, otherwise fall back to JSON info
	@app.route("/")
	def index():
		result = serve_spa_index()
		if result:
			return result

		# Fallback: keep a helpful JSON response if the frontend build is missing
		return jsonify(
			message="Welcome to PG Admit - AI AGENTS",
			version="1.0.0",
		)

	register_routes(app)
	
	# SPA fallback - catch-all route for client-side routes (React Router)
	# This handles paths like /dashboard, /profile, etc.
	@app.route("/<path:path>")
	def spa_fallback(path: str):
		# Check if this is an API route
		if is_api_route(path):
			# This is an API route - return 404 (should have been handled by register_routes)
			return jsonify({"error": "Not Found", "path": path}), 404

		# Check if this is a request for a static file (js, css, images, etc.)
		static_extensions = ('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map', '.json')
		if path.endswith(static_extensions):
			# Try to serve from static folder
			if app.static_folder:
				file_path = os.path.join(app.static_folder, path)
				if os.path.exists(file_path):
					return send_from_directory(app.static_folder, path)
			# Static file not found
			return ("Not Found", 404)

		# This is a frontend route - serve index.html for React Router
		result = serve_spa_index()
		if result:
			return result

		# Log for debugging if index.html is not found
		if app.static_folder:
			index_path = os.path.join(app.static_folder, "index.html")
			print(f"Warning: index.html not found at {index_path}")
			print(f"Static folder: {app.static_folder}")
			print(f"Static folder exists: {os.path.exists(app.static_folder) if app.static_folder else 'N/A'}")

		return ("Not Found", 404)
	
	# 404 Error Handler - Critical for SPA routing!
	# This catches any 404 errors and serves index.html for frontend routes
	# This is the key fix for page reload issues on client-side routes
	@app.errorhandler(404)
	def handle_404(e):
		# Get the requested path
		path = request.path
		
		# If it's an API route, return proper JSON 404
		if is_api_route(path):
			return jsonify({
				"error": "Not Found",
				"message": f"The requested endpoint '{path}' was not found",
				"path": path
			}), 404
		
		# For static file requests that weren't found, return 404
		static_extensions = ('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map')
		if any(path.endswith(ext) for ext in static_extensions):
			return ("Not Found", 404)
		
		# For all other routes (frontend routes), serve index.html
		# This enables React Router to handle the route on the client side
		result = serve_spa_index()
		if result:
			return result
		
		# If index.html doesn't exist, return 404
		return ("Not Found", 404)
	
	# Start profile change listener (simple polling)
	if os.getenv("ENABLE_PROFILE_LISTENER", "true").lower() == "true":
		try:
			print("Starting Profile Change Listener...")
			start_profile_listener()
			atexit.register(stop_profile_listener)
		except Exception as e:
			print(f"Failed to start listener: {str(e)}")
	
	return app
