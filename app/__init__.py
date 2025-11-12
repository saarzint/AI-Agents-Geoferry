from flask import Flask
from flask_cors import CORS
from .routes import register_routes
from .event_listener import start_profile_listener, stop_profile_listener
import atexit
import os


def create_app() -> Flask:
	app = Flask(__name__)
	CORS(app, resources={r"/*": {"origins": ["http://localhost:5173"]}})
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
