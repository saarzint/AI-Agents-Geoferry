# Use latest Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application code
COPY . .

# Expose port 5000
EXPOSE 5000

# Run the Flask application
CMD ["python", "-m", "flask", "--app", "app.main:create_app()", "run", "--host=0.0.0.0", "--port=5000"]