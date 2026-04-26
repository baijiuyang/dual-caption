FROM python:3.11-slim

WORKDIR /app

# Install dependencies in a separate cached layer so code changes
# don't force a slow reinstall every rebuild.
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY app.py dual_caption.py fix_srt.py ./

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
