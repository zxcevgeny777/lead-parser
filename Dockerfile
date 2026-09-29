# Official Microsoft Playwright image with Python 3.10 and Chromium pre-installed
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=10000 \
    HOST=0.0.0.0

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose Render standard port
EXPOSE 10000

# Run the web server
CMD ["python", "web_ui.py"]
