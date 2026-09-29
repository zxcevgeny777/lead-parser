# Official Microsoft Playwright image with Python 3.10 and Chromium pre-installed
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0

# Install Python dependencies and Playwright browser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

# Copy application source code
COPY . .

# Expose port
EXPOSE 8080

# Run the web server
CMD ["python", "web_ui.py"]
