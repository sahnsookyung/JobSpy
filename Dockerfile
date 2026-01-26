# Use a lightweight Python base image
FROM python:3.11-slim

# 1. Install system dependencies required for Playwright and general build tools
# Playwright needs these to run Chromium/WebKit headless
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libgconf-2-4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libnss3-dev \
    libxss-dev \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Install Playwright browsers (Chromium is usually sufficient for scraping)
# We install with --with-deps to ensure any missing OS-level libs are grabbed
RUN playwright install chromium --with-deps

# 4. Copy the rest of the application
COPY . .

# Expose the port
EXPOSE 8000

# Run the API server
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
