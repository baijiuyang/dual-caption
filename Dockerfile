FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml app.py dual_caption.py fix_srt.py ./
RUN pip install --no-cache-dir .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
