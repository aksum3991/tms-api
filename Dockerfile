# Use an official Python runtime
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working directory inside container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    default-libmysqlclient-dev \
    pkg-config \
    python3-dev \
    gcc \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install pipenv (only if your project uses Pipenv)
# RUN pip install --upgrade pip
# RUN pip install pipenv
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy Pipfile and Pipfile.lock first
# COPY Pipfile Pipfile.lock ./

# Install python dependencies
# RUN pipenv install --deploy --system

# Copy the rest of the project
COPY . .

# Collect static files (optional if you use Django admin)
# RUN python manage.py collectstatic --noinput

# Expose port 8000
EXPOSE 8000

# Start Django server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
