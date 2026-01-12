"""
Supabase JWT Authentication Middleware for Flask

This module provides authentication decorators and utilities for validating
Supabase JWT tokens in Flask routes.
"""

import os
from functools import wraps
from typing import Optional, Tuple
import jwt
import requests as http_requests
from flask import request, jsonify, g
from http import HTTPStatus
from dotenv import load_dotenv

load_dotenv()

# Supabase config
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_token_from_header() -> Optional[str]:
    """
    Extract JWT token from Authorization header.
    Expected format: "Bearer <token>"
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


def verify_supabase_token(token: str) -> Tuple[bool, Optional[dict], Optional[str]]:
    """
    Verify a Supabase JWT token by calling Supabase auth API.

    Returns:
        Tuple of (is_valid, payload, error_message)
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False, None, "Server configuration error: Supabase URL or key not configured"

    try:
        # Verify token by calling Supabase auth API
        response = http_requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_KEY
            },
            timeout=10
        )

        if response.status_code == 200:
            user_data = response.json()
            # Build payload similar to JWT decode
            payload = {
                "sub": user_data.get("id"),
                "email": user_data.get("email"),
                "user_metadata": user_data.get("user_metadata", {}),
                "app_metadata": user_data.get("app_metadata", {}),
                "role": user_data.get("role", "authenticated")
            }
            return True, payload, None

        elif response.status_code == 401:
            return False, None, "Token has expired or is invalid"

        else:
            return False, None, f"Authentication failed: {response.status_code}"

    except http_requests.exceptions.Timeout:
        return False, None, "Authentication service timeout"

    except Exception as e:
        return False, None, f"Authentication error: {str(e)}"


def require_auth(f):
    """
    Decorator to require authentication for a route.

    Usage:
        @app.get("/protected")
        @require_auth
        def protected_route():
            user_id = g.user_id  # Access authenticated user's ID
            return jsonify({"message": "Hello authenticated user!"})

    The decorator sets the following on Flask's g object:
        - g.user_id: The Supabase user's UUID
        - g.user_email: The user's email (if available)
        - g.token_payload: The full decoded JWT payload
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_header()

        if not token:
            return jsonify({
                "error": "Authentication required",
                "message": "Missing Authorization header. Expected: Bearer <token>"
            }), HTTPStatus.UNAUTHORIZED

        is_valid, payload, error = verify_supabase_token(token)

        if not is_valid:
            return jsonify({
                "error": "Authentication failed",
                "message": error
            }), HTTPStatus.UNAUTHORIZED

        # Set user info on Flask's g object for access in route handlers
        g.user_id = payload.get("sub")  # Supabase user UUID
        g.user_email = payload.get("email")
        g.token_payload = payload

        return f(*args, **kwargs)

    return decorated_function


def optional_auth(f):
    """
    Decorator for routes where authentication is optional.
    If a valid token is provided, user info is set on g.
    If no token or invalid token, the request proceeds without user info.

    Usage:
        @app.get("/public-or-private")
        @optional_auth
        def flexible_route():
            if hasattr(g, 'user_id') and g.user_id:
                return jsonify({"message": f"Hello {g.user_email}!"})
            return jsonify({"message": "Hello anonymous user!"})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_header()

        if token:
            is_valid, payload, _ = verify_supabase_token(token)
            if is_valid:
                g.user_id = payload.get("sub")
                g.user_email = payload.get("email")
                g.token_payload = payload

        return f(*args, **kwargs)

    return decorated_function
