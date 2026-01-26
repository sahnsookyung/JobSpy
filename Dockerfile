# Force AMD64 to allow official Chrome. chrome is needed to avoid getting served interstitials
FROM --platform=linux/amd64 python:3.11-slim

# 1. Install minimal tools for Playwright's installer script
# (It needs wget/curl/gpg to fetch Chrome repos)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy requirements
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn

# 3. Install Browsers AND System Deps automatically
# --with-deps detects the OS (Debian 12) and installs the correct libs
RUN playwright install chrome chromium --with-deps

# 4. Copy code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
