from flask import Flask, send_from_directory, jsonify
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
		static_url_path="/",
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

	# Root route – serve the frontend if it exists, otherwise fall back to JSON info
	@app.route("/")
	def index():
		index_path = os.path.join(app.static_folder, "index.html")
		if os.path.exists(index_path):
			return send_from_directory(app.static_folder, "index.html")

		# Fallback: keep a helpful JSON response if the frontend build is missing
		return jsonify(
			message="Welcome to PG Admit - AI AGENTS",
			version="1.0.0",
		)

	# Optional SPA fallback so client-side routes work in production.
	# This will serve index.html for non-API paths.
	# Note: This route must be registered AFTER register_routes() to avoid catching API endpoints
	# We'll register it at the end of the function

	register_routes(app)
	
	# SPA fallback - register AFTER API routes so API routes take precedence
	# This serves index.html for client-side routes (React Router)
	@app.route("/<path:path>")
	def spa_fallback(path: str):
		# List of API route prefixes that should NOT serve index.html
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
			"health",
		)
		
		# Check if this path starts with any API prefix
		if any(path.startswith(prefix) for prefix in api_prefixes):
			# This is an API route - return 404 (should have been handled by register_routes)
			return ("Not Found", 404)

		# This is a frontend route - serve index.html for React Router
		index_path = os.path.join(app.static_folder, "index.html")
		if os.path.exists(index_path):
			return send_from_directory(app.static_folder, "index.html")

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
