from flask import Flask
from flask_cors import CORS
from .routes import register_routes
from .event_listener import start_profile_listener, stop_profile_listener
import atexit
import os


def create_app() -> Flask:
	frontend_path = os.path.join(os.path.dirname(__file__), "static-frontend")
	app = Flask(__name__, static_folder=frontend_path, static_url_path="/static-frontend")
	CORS(app, resources={r"/*": {
		"origins": [
			"http://localhost:5173",
			"https://pgadmin-frontend-app.vercel.app",
			"https://dashboard.pgadmit.com"
		],
		"methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
		"allow_headers": ["Content-Type", "Authorization"]
	}})
	register_routes(app)
	
	# Start profile change listener (simple polling)
	if os.getenv("ENABLE_PROFILE_LISTENER", "true").lower() == "true":
		try:
			print("Starting Profile Change Listener...")
			start_profile_listener()
			atexit.register(stop_profile_listener)
		except Exception as e:
			print(f"Failed to start listener: {str(e)}")
	
	return app
