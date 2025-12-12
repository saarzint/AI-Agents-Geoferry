from flask import Flask
from flask_cors import CORS
from .routes import register_routes
from .event_listener import start_profile_listener, stop_profile_listener
import atexit
import os


def create_app() -> Flask:
	app = Flask(__name__)
	# CORS configuration - allow Stripe webhooks (no origin check for webhooks)
	# More permissive CORS for development
	CORS(app, 
		resources={
			r"/*": {
				"origins": ["http://localhost:5173", "http://localhost:3000", "https://pgadmin-frontend-app.vercel.app"],
				"methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
				"allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
				"expose_headers": ["Content-Type", "Authorization"],
				"supports_credentials": False,
				"max_age": 3600
			},
			r"/stripe/webhook": {"origins": "*"}  # Stripe webhooks need to bypass CORS
		},
		supports_credentials=False
	)
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
