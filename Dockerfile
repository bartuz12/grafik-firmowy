# Używamy oficjalnego, lekkiego obrazu Pythona
FROM python:3.11-slim

# --- KRYTYCZNA POPRAWKA DLA "Build failed" ---
# Instalujemy niezbędne narzędzia systemowe (np. do kompilacji pandas)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Ustawiamy katalog roboczy wewnątrz kontenera
WORKDIR /app

# Ustawiamy zmienną środowiskową wymaganą przez Cloud Run
ENV PORT=8080

# Kopiujemy plik z zależnościami i instalujemy paczki (cache warstw Dockera)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiujemy resztę projektu
COPY . .

# --- OSTATECZNA POPRAWKA DLA "Container import failed" ---
# Poprawna komenda startowa (bez błędnego '' przed $PORT)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 aplikacja:create_app