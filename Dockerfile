# Apify Python base image (includes Python 3.13 + apify runtime conventions)
FROM apify/actor-python:3.13

USER myuser

# Install dependencies first (cached layer)
COPY --chown=myuser:myuser requirements.txt ./
RUN echo "Python version:" && python --version \
 && pip install --no-cache-dir -r requirements.txt \
 && echo "Installed packages:" && pip freeze \
 # warm-up: import once so the ONNX layout model and fonts are resolved at build time
 && python -c "import pymupdf4llm, pymupdf.layout; print('pymupdf4llm', pymupdf4llm.__version__)"

COPY --chown=myuser:myuser . ./

# Compile to catch syntax errors at build time
RUN python -m compileall -q src/

ENV OMP_NUM_THREADS=1
CMD ["python3", "-m", "src"]
